"""Módulo de telemetria automática do SGE.

Recebe leituras de gateways/PCs de aquisição por HTTPS/JSON, guarda-as no
SQLite central e disponibiliza painel, histórico e exportação. O módulo não
comunica com o F650 e não envia comandos para equipamentos de campo.
"""
from __future__ import annotations

import csv
import hashlib
import io
import math
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from functools import wraps
from typing import Any, Iterable

from flask import Blueprint, Response, jsonify, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash


DEVICE_CODE_F650 = "F650_ENTRADA_GERAL_33KV"
DEFAULT_ONLINE_SECONDS = 180
DEFAULT_DELAYED_SECONDS = 900
LOCAL_TIMEZONE = timezone(timedelta(hours=2))

# Os valores abaixo são limites de supervisão do SGE. Não alteram ajustes,
# protecções ou a programação do F650. Foram escolhidos para uma rede nominal
# de 33 kV e podem ser ajustados no futuro no servidor, sem tocar no PC de campo.
DEFAULT_ALERT_CONFIG = {
    "nominal_voltage_kv": 33.0,
    "outage_voltage_kv": 3.3,
    "voltage_warning_low_kv": 31.35,
    "voltage_critical_low_kv": 29.70,
    "voltage_warning_high_kv": 34.65,
    "voltage_critical_high_kv": 36.30,
    "pf_warning": 0.85,
    "pf_critical": 0.80,
    "frequency_warning_low_hz": 49.5,
    "frequency_critical_low_hz": 49.0,
    "frequency_warning_high_hz": 50.5,
    "frequency_critical_high_hz": 51.0,
    "voltage_unbalance_warning_pct": 2.0,
    "voltage_unbalance_critical_pct": 3.0,
    "current_unbalance_warning_pct": 10.0,
    "current_unbalance_critical_pct": 20.0,
    "current_limit_a": 0.0,
    "minimum_power_for_pf_mw": 0.10,
}

POWER_CHANNELS = {
    "potencia_activa_total_mw",
    "potencia_reactiva_total_mvar",
    "potencia_activa_fase_a_mw",
    "potencia_activa_fase_b_mw",
    "potencia_activa_fase_c_mw",
    "potencia_reactiva_fase_a_mvar",
    "potencia_reactiva_fase_b_mvar",
    "potencia_reactiva_fase_c_mvar",
}
PF_CHANNELS = {
    "factor_potencia_total",
    "factor_potencia_fase_a",
    "factor_potencia_fase_b",
    "factor_potencia_fase_c",
}
DISPLAY_ABSOLUTE_CHANNELS = POWER_CHANNELS | PF_CHANNELS
VOLTAGE_CHANNELS = ("tensao_ab_kv", "tensao_bc_kv", "tensao_ca_kv")
CURRENT_CHANNELS = ("corrente_fase_a_a", "corrente_fase_b_a", "corrente_fase_c_a")

# Canais preparados a partir do mapa de utilizador do F650 da Entrada Geral.
# Os limites são operacionais do SGE e não alteram as protecções do relé.
F650_CHANNELS = [
    ("tensao_ab_kv", "Tensão AB", "kV", 31.35, 34.65, 10, 1),
    ("tensao_bc_kv", "Tensão BC", "kV", 31.35, 34.65, 20, 1),
    ("tensao_ca_kv", "Tensão CA", "kV", 31.35, 34.65, 30, 1),
    ("tensao_an_kv", "Tensão AN", "kV", None, None, 40, 0),
    ("tensao_bn_kv", "Tensão BN", "kV", None, None, 50, 0),
    ("tensao_cn_kv", "Tensão CN", "kV", None, None, 60, 0),
    ("corrente_fase_a_a", "Corrente fase A", "A", 0.0, None, 70, 1),
    ("corrente_fase_b_a", "Corrente fase B", "A", 0.0, None, 80, 1),
    ("corrente_fase_c_a", "Corrente fase C", "A", 0.0, None, 90, 1),
    ("corrente_terra_ig_a", "Corrente de terra", "A", 0.0, None, 100, 0),
    ("potencia_activa_total_mw", "Potência activa total", "MW", None, None, 110, 1),
    ("potencia_reactiva_total_mvar", "Potência reactiva total", "MVAr", None, None, 120, 1),
    ("potencia_activa_fase_a_mw", "Potência activa fase A", "MW", None, None, 130, 0),
    ("potencia_activa_fase_b_mw", "Potência activa fase B", "MW", None, None, 140, 0),
    ("potencia_activa_fase_c_mw", "Potência activa fase C", "MW", None, None, 150, 0),
    ("potencia_reactiva_fase_a_mvar", "Potência reactiva fase A", "MVAr", None, None, 160, 0),
    ("potencia_reactiva_fase_b_mvar", "Potência reactiva fase B", "MVAr", None, None, 170, 0),
    ("potencia_reactiva_fase_c_mvar", "Potência reactiva fase C", "MVAr", None, None, 180, 0),
    ("factor_potencia_total", "Factor de potência total", "", 0.85, 1.0, 190, 1),
    ("factor_potencia_fase_a", "Factor de potência fase A", "", -1.0, 1.0, 200, 0),
    ("factor_potencia_fase_b", "Factor de potência fase B", "", -1.0, 1.0, 210, 0),
    ("factor_potencia_fase_c", "Factor de potência fase C", "", -1.0, 1.0, 220, 0),
    ("frequencia_hz", "Frequência", "Hz", 49.5, 50.5, 230, 1),
    ("relacao_tc", "Relação TC", "", 79.9, 80.1, 240, 0),
    ("relacao_tp", "Relação TP", "", 299.9, 300.1, 250, 0),
]


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=20)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=20000")
    return conn


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso_utc(value: datetime | None = None) -> str:
    dt = value or _utc_now()
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime:
    if value is None or str(value).strip() == "":
        return _utc_now()
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ValueError("timestamp inválido; use ISO 8601") from exc
    if dt.tzinfo is None:
        # Para o piloto da ETA Umbeluzi, timestamps sem zona são tratados como UTC+02.
        dt = dt.replace(tzinfo=timezone(timedelta(hours=2)))
    dt = dt.astimezone(timezone.utc)
    if dt > _utc_now() + timedelta(minutes=10):
        raise ValueError("timestamp está demasiado no futuro")
    return dt


def _safe_float(value: Any) -> float:
    if isinstance(value, bool):
        raise ValueError("valor booleano não é uma medição")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("valor não numérico") from exc
    if not math.isfinite(number):
        raise ValueError("valor não finito")
    if abs(number) > 1e12:
        raise ValueError("valor fora do limite de segurança")
    return number


def _device_state(last_seen: str | None) -> tuple[str, int | None]:
    if not last_seen:
        return "offline", None
    try:
        dt = _parse_timestamp(last_seen)
    except ValueError:
        return "offline", None
    age = max(0, int((_utc_now() - dt).total_seconds()))
    if age <= DEFAULT_ONLINE_SECONDS:
        return "online", age
    if age <= DEFAULT_DELAYED_SECONDS:
        return "atrasado", age
    return "offline", age


def _processed_value(code: str, value: float | None) -> float | None:
    """Valor operacional apresentado, mantendo o bruto disponível em separado."""
    if value is None:
        return None
    return abs(float(value)) if code in DISPLAY_ABSOLUTE_CHANNELS else float(value)


def _flow_direction(value: float | None) -> str | None:
    if value is None:
        return None
    if float(value) < 0:
        return "reverso"
    if float(value) > 0:
        return "directo"
    return "sem_fluxo"


def _phase_unbalance(values: Iterable[float]) -> float | None:
    clean = [abs(float(value)) for value in values if value is not None]
    if len(clean) < 3:
        return None
    average = sum(clean) / len(clean)
    if average <= 0:
        return 0.0
    return max(abs(value - average) for value in clean) / average * 100.0


def _duration_seconds(started_at: str | None, ended_at: str | None = None) -> int:
    if not started_at:
        return 0
    try:
        start = _parse_timestamp(started_at)
        end = _parse_timestamp(ended_at) if ended_at else _utc_now()
    except ValueError:
        return 0
    return max(0, int((end - start).total_seconds()))


def _format_local_datetime(value: str | None) -> str:
    if not value:
        return "—"
    try:
        return _parse_timestamp(value).astimezone(LOCAL_TIMEZONE).strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return str(value)


def _token_from_request() -> str:
    auth = (request.headers.get("Authorization") or "").strip()
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("X-SGE-Token") or "").strip()


def _token_matches(device: sqlite3.Row, token: str) -> bool:
    if not token:
        return False
    stored_hash = device["token_hash"]
    if stored_hash:
        try:
            return check_password_hash(stored_hash, token)
        except Exception:
            return False
    fallback = os.environ.get("SGE_F650_API_TOKEN") or os.environ.get("SGE_TELEMETRY_TOKEN")
    return bool(fallback and secrets.compare_digest(fallback, token))


def _migrate(db_path: str) -> None:
    conn = _connect(db_path)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS telemetry_devices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                local_id INTEGER,
                code TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                manufacturer TEXT,
                model TEXT,
                firmware TEXT,
                protocol TEXT,
                local_ip TEXT,
                token_hash TEXT,
                active INTEGER NOT NULL DEFAULT 1,
                last_seen TEXT,
                last_measurement_at TEXT,
                last_status TEXT DEFAULT 'offline',
                last_remote_ip TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TEXT,
                FOREIGN KEY(local_id) REFERENCES locais(id)
            );

            CREATE TABLE IF NOT EXISTS telemetry_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                unit TEXT,
                min_value REAL,
                max_value REAL,
                active INTEGER NOT NULL DEFAULT 1,
                show_dashboard INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                updated_at TEXT,
                UNIQUE(device_id, code),
                FOREIGN KEY(device_id) REFERENCES telemetry_devices(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS telemetry_readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                measured_at TEXT NOT NULL,
                received_at TEXT NOT NULL,
                value REAL NOT NULL,
                quality TEXT NOT NULL DEFAULT 'good',
                delayed INTEGER NOT NULL DEFAULT 0,
                batch_id TEXT,
                source TEXT NOT NULL DEFAULT 'automatico',
                UNIQUE(device_id, channel_id, measured_at),
                FOREIGN KEY(device_id) REFERENCES telemetry_devices(id) ON DELETE CASCADE,
                FOREIGN KEY(channel_id) REFERENCES telemetry_channels(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS telemetry_ingest_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER,
                batch_id TEXT,
                received_at TEXT NOT NULL,
                remote_ip TEXT,
                accepted INTEGER NOT NULL DEFAULT 0,
                duplicates INTEGER NOT NULL DEFAULT 0,
                rejected INTEGER NOT NULL DEFAULT 0,
                status TEXT,
                detail TEXT,
                FOREIGN KEY(device_id) REFERENCES telemetry_devices(id) ON DELETE SET NULL
            );

            CREATE TABLE IF NOT EXISTS telemetry_alert_config (
                device_id INTEGER PRIMARY KEY,
                nominal_voltage_kv REAL NOT NULL DEFAULT 33.0,
                outage_voltage_kv REAL NOT NULL DEFAULT 3.3,
                voltage_warning_low_kv REAL NOT NULL DEFAULT 31.35,
                voltage_critical_low_kv REAL NOT NULL DEFAULT 29.70,
                voltage_warning_high_kv REAL NOT NULL DEFAULT 34.65,
                voltage_critical_high_kv REAL NOT NULL DEFAULT 36.30,
                pf_warning REAL NOT NULL DEFAULT 0.85,
                pf_critical REAL NOT NULL DEFAULT 0.80,
                frequency_warning_low_hz REAL NOT NULL DEFAULT 49.5,
                frequency_critical_low_hz REAL NOT NULL DEFAULT 49.0,
                frequency_warning_high_hz REAL NOT NULL DEFAULT 50.5,
                frequency_critical_high_hz REAL NOT NULL DEFAULT 51.0,
                voltage_unbalance_warning_pct REAL NOT NULL DEFAULT 2.0,
                voltage_unbalance_critical_pct REAL NOT NULL DEFAULT 3.0,
                current_unbalance_warning_pct REAL NOT NULL DEFAULT 10.0,
                current_unbalance_critical_pct REAL NOT NULL DEFAULT 20.0,
                current_limit_a REAL NOT NULL DEFAULT 0.0,
                minimum_power_for_pf_mw REAL NOT NULL DEFAULT 0.10,
                updated_at TEXT,
                FOREIGN KEY(device_id) REFERENCES telemetry_devices(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS telemetry_alerts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                device_id INTEGER NOT NULL,
                alert_type TEXT NOT NULL,
                severity TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                title TEXT NOT NULL,
                message TEXT NOT NULL,
                started_at TEXT NOT NULL,
                last_detected_at TEXT NOT NULL,
                resolved_at TEXT,
                duration_seconds INTEGER,
                value REAL,
                unit TEXT,
                threshold TEXT,
                occurrences INTEGER NOT NULL DEFAULT 1,
                acknowledged_at TEXT,
                acknowledged_by TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(device_id) REFERENCES telemetry_devices(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_telemetry_readings_device_time
                ON telemetry_readings(device_id, measured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_telemetry_readings_channel_time
                ON telemetry_readings(channel_id, measured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_telemetry_devices_local
                ON telemetry_devices(local_id);
            CREATE INDEX IF NOT EXISTS idx_telemetry_ingest_received
                ON telemetry_ingest_log(received_at DESC);
            CREATE INDEX IF NOT EXISTS idx_telemetry_alerts_device_status
                ON telemetry_alerts(device_id, status, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_telemetry_alerts_type
                ON telemetry_alerts(device_id, alert_type, id DESC);
            """
        )
        conn.commit()
    finally:
        conn.close()


def _seed_f650(db_path: str) -> None:
    conn = _connect(db_path)
    try:
        local = conn.execute(
            "SELECT id FROM locais WHERE UPPER(nome)=? LIMIT 1", ("ETA DE UMBELUZI",)
        ).fetchone()
        if not local:
            local = conn.execute(
                "SELECT id FROM locais WHERE UPPER(nome) LIKE '%UMBELUZI%' ORDER BY id LIMIT 1"
            ).fetchone()
        local_id = local["id"] if local else None

        conn.execute(
            """
            INSERT INTO telemetry_devices(
                local_id, code, name, manufacturer, model, firmware, protocol,
                local_ip, active, updated_at
            ) VALUES(?,?,?,?,?,?,?,?,1,?)
            ON CONFLICT(code) DO UPDATE SET
                local_id=COALESCE(excluded.local_id, telemetry_devices.local_id),
                name=excluded.name,
                manufacturer=excluded.manufacturer,
                model=excluded.model,
                firmware=excluded.firmware,
                protocol=excluded.protocol,
                local_ip=excluded.local_ip,
                active=1,
                updated_at=excluded.updated_at
            """,
            (
                local_id,
                DEVICE_CODE_F650,
                "F650 – Entrada Geral 33 kV",
                "GE Multilin",
                "F650",
                "5.40",
                "Modbus TCP",
                "192.168.0.1",
                _iso_utc(),
            ),
        )
        device = conn.execute(
            "SELECT id, token_hash FROM telemetry_devices WHERE code=?", (DEVICE_CODE_F650,)
        ).fetchone()
        if not device:
            raise RuntimeError("não foi possível criar o dispositivo F650")

        configured_token = os.environ.get("SGE_F650_API_TOKEN") or os.environ.get("SGE_TELEMETRY_TOKEN")
        if configured_token:
            current_hash = device["token_hash"]
            valid = False
            if current_hash:
                try:
                    valid = check_password_hash(current_hash, configured_token)
                except Exception:
                    valid = False
            if not valid:
                conn.execute(
                    "UPDATE telemetry_devices SET token_hash=?, updated_at=? WHERE id=?",
                    (generate_password_hash(configured_token), _iso_utc(), device["id"]),
                )

        for code, name, unit, min_value, max_value, sort_order, show_dashboard in F650_CHANNELS:
            conn.execute(
                """
                INSERT INTO telemetry_channels(
                    device_id, code, name, unit, min_value, max_value,
                    active, show_dashboard, sort_order, updated_at
                ) VALUES(?,?,?,?,?,?,1,?,?,?)
                ON CONFLICT(device_id, code) DO UPDATE SET
                    name=excluded.name,
                    unit=excluded.unit,
                    min_value=excluded.min_value,
                    max_value=excluded.max_value,
                    active=1,
                    show_dashboard=excluded.show_dashboard,
                    sort_order=excluded.sort_order,
                    updated_at=excluded.updated_at
                """,
                (
                    device["id"],
                    code,
                    name,
                    unit,
                    min_value,
                    max_value,
                    show_dashboard,
                    sort_order,
                    _iso_utc(),
                ),
            )
        cfg_columns = ", ".join(["device_id"] + list(DEFAULT_ALERT_CONFIG.keys()))
        cfg_placeholders = ", ".join("?" for _ in range(len(DEFAULT_ALERT_CONFIG) + 1))
        conn.execute(
            f"INSERT OR IGNORE INTO telemetry_alert_config({cfg_columns}) VALUES({cfg_placeholders})",
            [device["id"], *DEFAULT_ALERT_CONFIG.values()],
        )
        conn.commit()
    finally:
        conn.close()


def _load_device(conn: sqlite3.Connection, code: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM telemetry_devices WHERE code=? AND active=1", (code,)
    ).fetchone()


def _load_channels(conn: sqlite3.Connection, device_id: int) -> dict[str, sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM telemetry_channels WHERE device_id=? AND active=1", (device_id,)
    ).fetchall()
    return {row["code"]: row for row in rows}


def _alert_config(conn: sqlite3.Connection, device_id: int) -> dict[str, float]:
    row = conn.execute(
        "SELECT * FROM telemetry_alert_config WHERE device_id=?", (device_id,)
    ).fetchone()
    config = dict(DEFAULT_ALERT_CONFIG)
    if row:
        for key in DEFAULT_ALERT_CONFIG:
            if key in row.keys() and row[key] is not None:
                config[key] = float(row[key])
    return config


def _latest_values(conn: sqlite3.Connection, device_id: int) -> dict[str, float]:
    rows = conn.execute(
        """
        SELECT c.code, r.value
        FROM telemetry_channels c
        JOIN telemetry_readings r ON r.id=(
            SELECT rr.id FROM telemetry_readings rr
            WHERE rr.channel_id=c.id
            ORDER BY rr.measured_at DESC, rr.id DESC LIMIT 1
        )
        WHERE c.device_id=? AND c.active=1
        """,
        (device_id,),
    ).fetchall()
    return {row["code"]: float(row["value"]) for row in rows}


def _set_alert(
    conn: sqlite3.Connection,
    device_id: int,
    alert_type: str,
    active: bool,
    event_at: str,
    *,
    severity: str = "warning",
    title: str = "",
    message: str = "",
    value: float | None = None,
    unit: str = "",
    threshold: str = "",
) -> None:
    """Abre, actualiza ou encerra um evento sem gerar duplicados por leitura."""
    current = conn.execute(
        """
        SELECT * FROM telemetry_alerts
        WHERE device_id=? AND alert_type=? AND status IN ('open','acknowledged')
        ORDER BY id DESC LIMIT 1
        """,
        (device_id, alert_type),
    ).fetchone()
    if active:
        if current:
            last_detected = max(str(current["last_detected_at"] or event_at), event_at)
            event_severity = (
                "critical"
                if current["severity"] == "critical" or severity == "critical"
                else severity
            )
            conn.execute(
                """
                UPDATE telemetry_alerts
                SET severity=?, title=?, message=?, last_detected_at=?, value=?,
                    unit=?, threshold=?, occurrences=occurrences+1
                WHERE id=?
                """,
                (
                    event_severity,
                    title,
                    message,
                    last_detected,
                    value,
                    unit,
                    threshold,
                    current["id"],
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO telemetry_alerts(
                    device_id, alert_type, severity, status, title, message,
                    started_at, last_detected_at, value, unit, threshold,
                    occurrences, created_at
                ) VALUES(?,?,?,'open',?,?,?,?,?,?,?,1,?)
                """,
                (
                    device_id,
                    alert_type,
                    severity,
                    title,
                    message,
                    event_at,
                    event_at,
                    value,
                    unit,
                    threshold,
                    _iso_utc(),
                ),
            )
    elif current:
        resolved_at = max(str(current["last_detected_at"] or event_at), event_at)
        duration = _duration_seconds(current["started_at"], resolved_at)
        conn.execute(
            """
            UPDATE telemetry_alerts
            SET status='resolved', resolved_at=?, duration_seconds=?
            WHERE id=?
            """,
            (resolved_at, duration, current["id"]),
        )


def _reconcile_communication_alert(conn: sqlite3.Connection, device: sqlite3.Row) -> None:
    """Mantém alertas de comunicação separados de um corte confirmado por tensão."""
    state, age = _device_state(device["last_seen"])
    now = _iso_utc()
    if not device["last_seen"]:
        return
    if state == "offline":
        started_at = _iso_utc(
            _parse_timestamp(device["last_seen"]) + timedelta(seconds=DEFAULT_DELAYED_SECONDS)
        )
        _set_alert(
            conn,
            device["id"],
            "sem_comunicacao",
            True,
            started_at,
            severity="critical",
            title="Perda de comunicação com o F650",
            message=(
                "O servidor deixou de receber dados. Isto não confirma corte de energia; "
                "verifique o PC de aquisição, Internet e serviço de envio."
            ),
            value=float(age or 0),
            unit="s",
            threshold=f"> {DEFAULT_DELAYED_SECONDS} s",
        )
        _set_alert(conn, device["id"], "dados_atrasados", False, started_at)
    elif state == "atrasado":
        started_at = _iso_utc(
            _parse_timestamp(device["last_seen"]) + timedelta(seconds=DEFAULT_ONLINE_SECONDS)
        )
        _set_alert(
            conn,
            device["id"],
            "dados_atrasados",
            True,
            started_at,
            severity="warning",
            title="Dados de telemetria atrasados",
            message="Não chegam novas leituras dentro do intervalo normal de supervisão.",
            value=float(age or 0),
            unit="s",
            threshold=f"> {DEFAULT_ONLINE_SECONDS} s",
        )
        _set_alert(conn, device["id"], "sem_comunicacao", False, now)
    else:
        _set_alert(conn, device["id"], "dados_atrasados", False, now)
        _set_alert(conn, device["id"], "sem_comunicacao", False, now)


def _evaluate_measurement_alerts(
    conn: sqlite3.Connection,
    device_id: int,
    measured_at: str,
    block_values: dict[str, float],
) -> None:
    """Avalia somente grandezas úteis à operação e evita alarmes redundantes."""
    values = _latest_values(conn, device_id)
    values.update(block_values)
    config = _alert_config(conn, device_id)
    now = measured_at

    voltages = {code: values.get(code) for code in VOLTAGE_CHANNELS}
    has_voltages = all(value is not None for value in voltages.values())
    outage = False
    if has_voltages:
        voltage_values = [abs(float(value)) for value in voltages.values() if value is not None]
        outage = max(voltage_values) <= config["outage_voltage_kv"]
        _set_alert(
            conn,
            device_id,
            "corte_energia",
            outage,
            now,
            severity="critical",
            title="Corte de energia confirmado",
            message=(
                "As três tensões entre fases encontram-se próximas de zero. "
                "O evento foi confirmado pelas medições do F650."
            ),
            value=max(voltage_values),
            unit="kV",
            threshold=f"3 fases ≤ {config['outage_voltage_kv']:.2f} kV",
        )

        phase_names = {
            "tensao_ab_kv": "AB",
            "tensao_bc_kv": "BC",
            "tensao_ca_kv": "CA",
        }
        low = {code: abs(float(value)) for code, value in voltages.items() if abs(float(value)) < config["voltage_warning_low_kv"]}
        high = {code: abs(float(value)) for code, value in voltages.items() if abs(float(value)) > config["voltage_warning_high_kv"]}
        if outage:
            low = {}
            high = {}
        low_critical = any(value < config["voltage_critical_low_kv"] for value in low.values())
        high_critical = any(value > config["voltage_critical_high_kv"] for value in high.values())
        _set_alert(
            conn,
            device_id,
            "subtensao",
            bool(low),
            now,
            severity="critical" if low_critical else "warning",
            title="Subtensão na entrada geral",
            message="Fase(s) abaixo do limite: " + ", ".join(
                f"{phase_names[code]} {value:.2f} kV" for code, value in low.items()
            ),
            value=min(low.values()) if low else None,
            unit="kV",
            threshold=f"atenção < {config['voltage_warning_low_kv']:.2f}; crítico < {config['voltage_critical_low_kv']:.2f}",
        )
        _set_alert(
            conn,
            device_id,
            "sobretensao",
            bool(high),
            now,
            severity="critical" if high_critical else "warning",
            title="Sobretensão na entrada geral",
            message="Fase(s) acima do limite: " + ", ".join(
                f"{phase_names[code]} {value:.2f} kV" for code, value in high.items()
            ),
            value=max(high.values()) if high else None,
            unit="kV",
            threshold=f"atenção > {config['voltage_warning_high_kv']:.2f}; crítico > {config['voltage_critical_high_kv']:.2f}",
        )
        voltage_unbalance = _phase_unbalance(voltage_values)
        voltage_unbalance_active = bool(
            not outage
            and voltage_unbalance is not None
            and voltage_unbalance > config["voltage_unbalance_warning_pct"]
        )
        _set_alert(
            conn,
            device_id,
            "desequilibrio_tensao",
            voltage_unbalance_active,
            now,
            severity=(
                "critical"
                if voltage_unbalance is not None
                and voltage_unbalance > config["voltage_unbalance_critical_pct"]
                else "warning"
            ),
            title="Desequilíbrio de tensão",
            message="A diferença entre as tensões das fases ultrapassou o limite operacional.",
            value=voltage_unbalance,
            unit="%",
            threshold=f"> {config['voltage_unbalance_warning_pct']:.1f}%",
        )

    currents = [values.get(code) for code in CURRENT_CHANNELS]
    if all(value is not None for value in currents):
        current_values = [abs(float(value)) for value in currents if value is not None]
        current_average = sum(current_values) / 3.0
        current_unbalance = _phase_unbalance(current_values)
        unbalance_active = bool(
            current_average >= 5.0
            and current_unbalance is not None
            and current_unbalance > config["current_unbalance_warning_pct"]
        )
        _set_alert(
            conn,
            device_id,
            "desequilibrio_corrente",
            unbalance_active,
            now,
            severity=(
                "critical"
                if current_unbalance is not None
                and current_unbalance > config["current_unbalance_critical_pct"]
                else "warning"
            ),
            title="Desequilíbrio de corrente",
            message="As correntes das três fases apresentam diferença acima do limite operacional.",
            value=current_unbalance,
            unit="%",
            threshold=f"> {config['current_unbalance_warning_pct']:.1f}%",
        )
        current_limit = config["current_limit_a"]
        _set_alert(
            conn,
            device_id,
            "sobrecorrente",
            bool(current_limit > 0 and max(current_values) > current_limit),
            now,
            severity="critical",
            title="Corrente acima do limite configurado",
            message="Uma ou mais fases ultrapassaram a corrente operacional definida no SGE.",
            value=max(current_values),
            unit="A",
            threshold=f"> {current_limit:.1f} A" if current_limit > 0 else "desactivado",
        )

    active_power = values.get("potencia_activa_total_mw")
    power_factor = values.get("factor_potencia_total")
    pf_value = abs(float(power_factor)) if power_factor is not None else None
    enough_load = active_power is None or abs(float(active_power)) >= config["minimum_power_for_pf_mw"]
    pf_active = bool(not outage and enough_load and pf_value is not None and pf_value < config["pf_warning"])
    _set_alert(
        conn,
        device_id,
        "factor_potencia_baixo",
        pf_active,
        now,
        severity="critical" if pf_value is not None and pf_value < config["pf_critical"] else "warning",
        title="Factor de potência baixo",
        message="O módulo do factor de potência está abaixo do nível recomendado.",
        value=pf_value,
        unit="",
        threshold=f"atenção < {config['pf_warning']:.2f}; crítico < {config['pf_critical']:.2f}",
    )

    frequency = values.get("frequencia_hz")
    if frequency is not None:
        frequency = float(frequency)
        frequency_active = bool(
            not outage
            and (
                frequency < config["frequency_warning_low_hz"]
                or frequency > config["frequency_warning_high_hz"]
            )
        )
        frequency_critical = bool(
            frequency < config["frequency_critical_low_hz"]
            or frequency > config["frequency_critical_high_hz"]
        )
        _set_alert(
            conn,
            device_id,
            "frequencia_fora_faixa",
            frequency_active,
            now,
            severity="critical" if frequency_critical else "warning",
            title="Frequência fora da faixa",
            message="A frequência medida na entrada geral ultrapassou o limite operacional.",
            value=frequency,
            unit="Hz",
            threshold=(
                f"{config['frequency_warning_low_hz']:.1f}–"
                f"{config['frequency_warning_high_hz']:.1f} Hz"
            ),
        )


def _public_alert(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    end = item.get("resolved_at") if item.get("status") == "resolved" else None
    item["duration_seconds"] = int(
        item.get("duration_seconds") or _duration_seconds(item.get("started_at"), end)
    )
    return item


def _query_alerts(
    conn: sqlite3.Connection,
    device_id: int,
    cutoff: str,
    limit: int = 100,
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT * FROM telemetry_alerts
        WHERE device_id=?
          AND (started_at>=? OR resolved_at>=? OR status IN ('open','acknowledged'))
        ORDER BY CASE severity WHEN 'critical' THEN 0 ELSE 1 END,
                 CASE status WHEN 'open' THEN 0 WHEN 'acknowledged' THEN 1 ELSE 2 END,
                 started_at DESC
        LIMIT ?
        """,
        (device_id, cutoff, cutoff, limit),
    ).fetchall()
    return [_public_alert(row) for row in rows]


def _build_analysis(
    conn: sqlite3.Connection,
    device: sqlite3.Row,
    hours: int,
) -> dict[str, Any]:
    cutoff_dt = _utc_now() - timedelta(hours=hours)
    cutoff = _iso_utc(cutoff_dt)
    period_seconds = max(1, int((_utc_now() - cutoff_dt).total_seconds()))
    key_channels = [
        *VOLTAGE_CHANNELS,
        *CURRENT_CHANNELS,
        "potencia_activa_total_mw",
        "potencia_reactiva_total_mvar",
        "factor_potencia_total",
        "frequencia_hz",
    ]
    placeholders = ",".join("?" for _ in key_channels)
    stats_rows = conn.execute(
        f"""
        SELECT c.code, c.name, c.unit, COUNT(*) AS samples,
               MIN(ABS(r.value)) AS minimum,
               AVG(ABS(r.value)) AS average,
               MAX(ABS(r.value)) AS maximum
        FROM telemetry_readings r
        JOIN telemetry_channels c ON c.id=r.channel_id
        WHERE r.device_id=? AND r.measured_at>=? AND c.code IN ({placeholders})
        GROUP BY c.id
        ORDER BY c.sort_order
        """,
        [device["id"], cutoff, *key_channels],
    ).fetchall()
    stats = [dict(row) for row in stats_rows]
    stats_by_code = {row["code"]: row for row in stats}

    power_rows = conn.execute(
        """
        SELECT r.measured_at, ABS(r.value) AS value
        FROM telemetry_readings r
        JOIN telemetry_channels c ON c.id=r.channel_id
        WHERE r.device_id=? AND c.code='potencia_activa_total_mw'
          AND r.measured_at>=? AND r.quality!='bad'
        ORDER BY r.measured_at, r.id
        """,
        (device["id"], cutoff),
    ).fetchall()
    energy_kwh = 0.0
    covered_seconds = 0.0
    ignored_gaps = 0
    peak_mw = 0.0
    peak_at = None
    previous = None
    for row in power_rows:
        try:
            current_dt = _parse_timestamp(row["measured_at"])
        except ValueError:
            continue
        value = abs(float(row["value"] or 0))
        if value >= peak_mw:
            peak_mw = value
            peak_at = row["measured_at"]
        if previous:
            delta_seconds = (current_dt - previous[0]).total_seconds()
            if 0 < delta_seconds <= 600:
                energy_kwh += ((previous[1] + value) / 2.0) * 1000.0 * delta_seconds / 3600.0
                covered_seconds += delta_seconds
            elif delta_seconds > 600:
                ignored_gaps += 1
        previous = (current_dt, value)

    phase_rows = conn.execute(
        """
        SELECT r.measured_at,
               MAX(CASE WHEN c.code='tensao_ab_kv' THEN ABS(r.value) END) AS vab,
               MAX(CASE WHEN c.code='tensao_bc_kv' THEN ABS(r.value) END) AS vbc,
               MAX(CASE WHEN c.code='tensao_ca_kv' THEN ABS(r.value) END) AS vca,
               MAX(CASE WHEN c.code='corrente_fase_a_a' THEN ABS(r.value) END) AS ia,
               MAX(CASE WHEN c.code='corrente_fase_b_a' THEN ABS(r.value) END) AS ib,
               MAX(CASE WHEN c.code='corrente_fase_c_a' THEN ABS(r.value) END) AS ic
        FROM telemetry_readings r
        JOIN telemetry_channels c ON c.id=r.channel_id
        WHERE r.device_id=? AND r.measured_at>=?
          AND c.code IN ('tensao_ab_kv','tensao_bc_kv','tensao_ca_kv',
                         'corrente_fase_a_a','corrente_fase_b_a','corrente_fase_c_a')
        GROUP BY r.measured_at
        ORDER BY r.measured_at
        """,
        (device["id"], cutoff),
    ).fetchall()
    voltage_unbalances = []
    current_unbalances = []
    for row in phase_rows:
        if all(row[key] is not None for key in ("vab", "vbc", "vca")):
            voltage_unbalances.append(_phase_unbalance([row["vab"], row["vbc"], row["vca"]]) or 0.0)
        if all(row[key] is not None for key in ("ia", "ib", "ic")):
            current_unbalances.append(_phase_unbalance([row["ia"], row["ib"], row["ic"]]) or 0.0)

    alerts = _query_alerts(conn, device["id"], cutoff, 100)
    open_alerts = [item for item in alerts if item["status"] in ("open", "acknowledged")]
    outage_seconds = 0
    comm_seconds = 0
    for item in alerts:
        try:
            started = max(_parse_timestamp(item["started_at"]), cutoff_dt)
            ended = min(
                _parse_timestamp(item["resolved_at"]) if item.get("resolved_at") else _utc_now(),
                _utc_now(),
            )
        except ValueError:
            continue
        overlap = max(0, int((ended - started).total_seconds()))
        if item["alert_type"] == "corte_energia":
            outage_seconds += overlap
        if item["alert_type"] in ("sem_comunicacao", "dados_atrasados"):
            comm_seconds += overlap

    latest = _latest_values(conn, device["id"])
    latest_p = latest.get("potencia_activa_total_mw")
    latest_q = latest.get("potencia_reactiva_total_mvar")
    latest_s = (
        math.sqrt(float(latest_p) ** 2 + float(latest_q) ** 2)
        if latest_p is not None and latest_q is not None
        else None
    )
    pf_stats = stats_by_code.get("factor_potencia_total") or {}
    frequency_stats = stats_by_code.get("frequencia_hz") or {}
    voltage_stats = [stats_by_code.get(code) for code in VOLTAGE_CHANNELS if stats_by_code.get(code)]
    current_stats = [stats_by_code.get(code) for code in CURRENT_CHANNELS if stats_by_code.get(code)]
    voltage_min = min((float(row["minimum"]) for row in voltage_stats), default=None)
    voltage_max = max((float(row["maximum"]) for row in voltage_stats), default=None)
    current_max = max((float(row["maximum"]) for row in current_stats), default=None)
    data_coverage_pct = min(100.0, covered_seconds / period_seconds * 100.0)
    energy_availability_pct = max(0.0, 100.0 - outage_seconds / period_seconds * 100.0)
    communication_availability_pct = max(0.0, 100.0 - comm_seconds / period_seconds * 100.0)

    recommendations = []
    active_types = {item["alert_type"] for item in open_alerts}
    if "corte_energia" in active_types:
        recommendations.append("Confirmar a alimentação de 33 kV e seguir o procedimento operacional para restabelecimento seguro.")
    if active_types & {"sem_comunicacao", "dados_atrasados"}:
        recommendations.append("Verificar o serviço de aquisição no PC, a ligação à Internet e o último envio; não alterar o F650.")
    if active_types & {"subtensao", "sobretensao"}:
        recommendations.append("Comparar as três fases, confirmar o nível da rede e acompanhar a duração antes de intervir nos equipamentos.")
    if float(pf_stats.get("average") or 1.0) < DEFAULT_ALERT_CONFIG["pf_warning"]:
        recommendations.append("Avaliar a compensação de energia reactiva e o regime de funcionamento das cargas.")
    if max(voltage_unbalances or [0.0]) > DEFAULT_ALERT_CONFIG["voltage_unbalance_warning_pct"]:
        recommendations.append("Investigar assimetria da alimentação e distribuição das cargas entre fases.")
    if data_coverage_pct < 90.0:
        recommendations.append("A cobertura de dados do período está incompleta; interpretar energia estimada e médias com cautela.")
    if not recommendations:
        recommendations.append("Manter a monitoria e comparar este período com os próximos relatórios para identificar tendências.")

    critical_open = sum(1 for item in open_alerts if item["severity"] == "critical")
    if critical_open:
        operational_state = "Crítico"
    elif open_alerts:
        operational_state = "Atenção"
    elif data_coverage_pct < 50:
        operational_state = "Dados insuficientes"
    else:
        operational_state = "Normal"

    return {
        "generated_at": _iso_utc(),
        "hours": hours,
        "device": {
            "code": device["code"],
            "name": device["name"],
            "local_name": device["local_name"] if "local_name" in device.keys() else None,
        },
        "summary": {
            "operational_state": operational_state,
            "energy_kwh": round(energy_kwh, 2),
            "peak_mw": round(peak_mw, 3),
            "peak_at": peak_at,
            "power_factor_avg": round(float(pf_stats.get("average") or 0), 3),
            "frequency_avg_hz": round(float(frequency_stats.get("average") or 0), 3),
            "voltage_min_kv": round(voltage_min, 3) if voltage_min is not None else None,
            "voltage_max_kv": round(voltage_max, 3) if voltage_max is not None else None,
            "current_max_a": round(current_max, 2) if current_max is not None else None,
            "voltage_unbalance_max_pct": round(max(voltage_unbalances or [0.0]), 3),
            "current_unbalance_max_pct": round(max(current_unbalances or [0.0]), 3),
            "data_coverage_pct": round(data_coverage_pct, 1),
            "energy_availability_pct": round(energy_availability_pct, 2),
            "communication_availability_pct": round(communication_availability_pct, 2),
            "outage_duration_seconds": outage_seconds,
            "communication_gap_seconds": comm_seconds,
            "active_alerts": len(open_alerts),
            "critical_alerts": critical_open,
            "ignored_data_gaps": ignored_gaps,
            "latest_active_power_mw": round(abs(float(latest_p)), 3) if latest_p is not None else None,
            "latest_reactive_power_mvar": round(abs(float(latest_q)), 3) if latest_q is not None else None,
            "latest_apparent_power_mva": round(latest_s, 3) if latest_s is not None else None,
            "measured_flow_direction": _flow_direction(latest_p),
        },
        "stats": stats,
        "alerts": alerts,
        "recommendations": recommendations,
    }


def _human_duration(seconds: int | float | None) -> str:
    total = max(0, int(seconds or 0))
    days, remainder = divmod(total, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days} d")
    if hours:
        parts.append(f"{hours} h")
    if minutes:
        parts.append(f"{minutes} min")
    if not parts:
        parts.append(f"{secs} s")
    return " ".join(parts[:2])


def _format_pt_number(value: int | float | None, digits: int = 2) -> str:
    if value is None:
        return "—"
    return f"{float(value):,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _build_pdf_report(analysis: dict[str, Any]) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER, TA_LEFT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    buffer = io.BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=14 * mm,
        leftMargin=14 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title="Relatório de Telemetria e Qualidade de Energia",
        author="SGE · Águas e Saneamento de Maputo",
    )
    styles = getSampleStyleSheet()
    styles.add(
        ParagraphStyle(
            name="SGETitle",
            parent=styles["Title"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=21,
            textColor=colors.HexColor("#123B69"),
            alignment=TA_LEFT,
            spaceAfter=5,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SGESubtitle",
            parent=styles["Normal"],
            fontSize=9,
            leading=12,
            textColor=colors.HexColor("#5D6B7A"),
            spaceAfter=10,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SGESection",
            parent=styles["Heading2"],
            fontSize=11,
            leading=14,
            textColor=colors.HexColor("#123B69"),
            spaceBefore=10,
            spaceAfter=6,
        )
    )
    styles.add(
        ParagraphStyle(
            name="SGESmall",
            parent=styles["Normal"],
            fontSize=7.4,
            leading=9.5,
            textColor=colors.HexColor("#263442"),
        )
    )
    styles.add(
        ParagraphStyle(
            name="SGENote",
            parent=styles["Normal"],
            fontSize=8,
            leading=11,
            textColor=colors.HexColor("#5D6B7A"),
        )
    )

    device = analysis["device"]
    summary = analysis["summary"]
    state_color = {
        "Crítico": colors.HexColor("#B42318"),
        "Atenção": colors.HexColor("#B54708"),
        "Normal": colors.HexColor("#027A48"),
    }.get(summary["operational_state"], colors.HexColor("#475467"))
    story = [
        Paragraph("ÁGUAS E SANEAMENTO DE MAPUTO", styles["SGESubtitle"]),
        Paragraph("Relatório de Telemetria e Qualidade de Energia", styles["SGETitle"]),
        Paragraph(
            f"{device.get('name') or device.get('code')} · {device.get('local_name') or 'Local não associado'}<br/>"
            f"Período analisado: últimas {analysis['hours']} horas · Emitido em {_format_local_datetime(analysis['generated_at'])}",
            styles["SGESubtitle"],
        ),
    ]
    state_table = Table(
        [
            [
                Paragraph("ESTADO OPERACIONAL", styles["SGESmall"]),
                Paragraph(f"<b>{summary['operational_state']}</b>", styles["SGESmall"]),
                Paragraph("ALERTAS ACTIVOS", styles["SGESmall"]),
                Paragraph(f"<b>{summary['active_alerts']}</b> ({summary['critical_alerts']} críticos)", styles["SGESmall"]),
            ]
        ],
        colWidths=[38 * mm, 46 * mm, 38 * mm, 54 * mm],
    )
    state_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F2F6FA")),
                ("TEXTCOLOR", (1, 0), (1, 0), state_color),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CAD5E0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DCE4EC")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 7),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
            ]
        )
    )
    story.extend([state_table, Paragraph("Indicadores principais", styles["SGESection"])])

    indicator_data = [
        ["Energia estimada", "Pico de potência", "Factor de potência médio"],
        [
            f"{_format_pt_number(summary['energy_kwh'], 1)} kWh",
            f"{_format_pt_number(summary['peak_mw'], 3)} MW",
            _format_pt_number(summary["power_factor_avg"], 3),
        ],
        ["Faixa de tensão", "Desequilíbrio máx. tensão", "Cobertura de dados"],
        [
            (
                f"{_format_pt_number(summary['voltage_min_kv'], 2)}–{_format_pt_number(summary['voltage_max_kv'], 2)} kV"
                if summary["voltage_min_kv"] is not None and summary["voltage_max_kv"] is not None
                else "—"
            ),
            f"{_format_pt_number(summary['voltage_unbalance_max_pct'], 2)}%",
            f"{_format_pt_number(summary['data_coverage_pct'], 1)}%",
        ],
        ["Disponibilidade de energia", "Disponibilidade de comunicação", "Duração dos cortes"],
        [
            f"{_format_pt_number(summary['energy_availability_pct'], 2)}%",
            f"{_format_pt_number(summary['communication_availability_pct'], 2)}%",
            _human_duration(summary["outage_duration_seconds"]),
        ],
    ]
    indicators = Table(indicator_data, colWidths=[58.7 * mm] * 3)
    indicators.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#EAF2F8")),
                ("BACKGROUND", (0, 2), (-1, 2), colors.HexColor("#EAF2F8")),
                ("BACKGROUND", (0, 4), (-1, 4), colors.HexColor("#EAF2F8")),
                ("FONTNAME", (0, 0), (-1, -1), "Helvetica"),
                ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
                ("FONTNAME", (0, 3), (-1, 3), "Helvetica-Bold"),
                ("FONTNAME", (0, 5), (-1, 5), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#475467")),
                ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#475467")),
                ("TEXTCOLOR", (0, 4), (-1, 4), colors.HexColor("#475467")),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#CAD5E0")),
                ("INNERGRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#DCE4EC")),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.append(indicators)

    story.append(Paragraph("Mínimo, média e máximo por grandeza", styles["SGESection"]))
    stats_data = [["Grandeza", "Mínimo", "Média", "Máximo", "Amostras"]]
    for row in analysis["stats"]:
        unit = f" {row['unit']}" if row.get("unit") else ""
        stats_data.append(
            [
                Paragraph(str(row["name"]), styles["SGESmall"]),
                f"{_format_pt_number(row['minimum'] or 0, 3)}{unit}",
                f"{_format_pt_number(row['average'] or 0, 3)}{unit}",
                f"{_format_pt_number(row['maximum'] or 0, 3)}{unit}",
                str(row["samples"]),
            ]
        )
    stats_table = Table(stats_data, colWidths=[58 * mm, 31 * mm, 31 * mm, 31 * mm, 25 * mm], repeatRows=1)
    stats_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123B69")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 7.2),
                ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D5DDE5")),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(stats_table)

    story.append(Paragraph("Ocorrências e alertas", styles["SGESection"]))
    if analysis["alerts"]:
        alert_data = [["Nível", "Estado", "Ocorrência", "Início", "Duração"]]
        for item in analysis["alerts"][:35]:
            alert_data.append(
                [
                    "Crítico" if item["severity"] == "critical" else "Atenção",
                    {"open": "Activo", "acknowledged": "Reconhecido", "resolved": "Resolvido"}.get(item["status"], item["status"]),
                    Paragraph(
                        f"<b>{item['title']}</b><br/>{item['message']}", styles["SGESmall"]
                    ),
                    _format_local_datetime(item["started_at"]),
                    _human_duration(item["duration_seconds"]),
                ]
            )
        alerts_table = Table(
            alert_data,
            colWidths=[19 * mm, 23 * mm, 82 * mm, 35 * mm, 22 * mm],
            repeatRows=1,
        )
        alerts_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#123B69")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 7),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
                    ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D5DDE5")),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        story.append(alerts_table)
    else:
        story.append(Paragraph("Não foram registadas ocorrências no período analisado.", styles["SGENote"]))

    story.append(Paragraph("Recomendações operacionais", styles["SGESection"]))
    for recommendation in analysis["recommendations"]:
        story.append(Paragraph(f"• {recommendation}", styles["SGENote"]))
        story.append(Spacer(1, 2 * mm))
    story.extend(
        [
            Spacer(1, 3 * mm),
            Paragraph(
                "Nota: potências e factor de potência são apresentados em módulo para representar o consumo. "
                "O sinal bruto e o sentido medido pelo relé continuam preservados nos dados exportados. "
                "Os limites deste relatório são de supervisão e não modificam as protecções do F650.",
                styles["SGENote"],
            ),
        ]
    )

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#D5DDE5"))
        canvas.line(14 * mm, 11 * mm, 196 * mm, 11 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(colors.HexColor("#667085"))
        canvas.drawString(14 * mm, 7 * mm, "SGE · Águas e Saneamento de Maputo")
        canvas.drawRightString(196 * mm, 7 * mm, f"Página {doc.page}")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def _normalise_payloads(body: Any) -> list[dict[str, Any]]:
    if not isinstance(body, dict):
        raise ValueError("corpo JSON deve ser um objecto")
    if "readings" in body:
        readings = body.get("readings")
        if not isinstance(readings, list) or not readings:
            raise ValueError("readings deve ser uma lista não vazia")
        if len(readings) > 500:
            raise ValueError("máximo de 500 blocos por pedido")
        return readings
    return [body]


def _value_state(channel: sqlite3.Row, value: float, quality: str) -> str:
    if quality == "bad":
        return "bad"
    compared_value = abs(value) if channel["code"] in DISPLAY_ABSOLUTE_CHANNELS else value
    min_value = channel["min_value"]
    max_value = channel["max_value"]
    if min_value is not None and compared_value < float(min_value):
        return "warning"
    if max_value is not None and compared_value > float(max_value):
        return "warning"
    if quality == "suspect":
        return "warning"
    return "normal"


def _admin_or_manager_required(current_user_getter):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            user = current_user_getter() if current_user_getter else None
            # Quando o login está desactivado, a aplicação mantém o comportamento existente.
            if user and user.get("role") not in ("admin", "gestor"):
                return jsonify(success=False, error="forbidden"), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


def register_telemetry(app, db_path: str) -> None:
    """Cria tabelas, regista o F650 piloto e liga as rotas ao Flask."""
    if app.extensions.get("sge_telemetry_registered"):
        return

    _migrate(db_path)
    _seed_f650(db_path)

    bp = Blueprint("telemetria", __name__)

    @bp.get("/api/v1/telemetria/ping")
    def api_ping():
        """Confirma URL, token e cadastro do dispositivo sem guardar medições."""
        device_code = str(
            request.args.get("device") or request.headers.get("X-Device-Code") or DEVICE_CODE_F650
        ).strip()
        token = _token_from_request()
        conn = _connect(db_path)
        try:
            device = _load_device(conn, device_code)
            if not device:
                return jsonify(success=False, error="not_found", message="Dispositivo desconhecido"), 404
            if not _token_matches(device, token):
                return jsonify(success=False, error="invalid_token", message="Token de telemetria inválido"), 401
            channel_count = conn.execute(
                "SELECT COUNT(*) AS total FROM telemetry_channels WHERE device_id=? AND active=1",
                (device["id"],),
            ).fetchone()["total"]
            state, age_seconds = _device_state(device["last_seen"])
            return jsonify(
                success=True,
                service="sge-telemetria",
                device=device_code,
                registered=True,
                channels=int(channel_count),
                state=state,
                age_seconds=age_seconds,
                server_time=_iso_utc(),
                message="API e token válidos; nenhuma medição foi guardada.",
            )
        finally:
            conn.close()

    @bp.post("/api/v1/telemetria")
    def ingest():
        if not request.is_json:
            return jsonify(success=False, error="content_type", message="Use application/json"), 415
        try:
            payloads = _normalise_payloads(request.get_json(silent=False))
        except Exception as exc:
            return jsonify(success=False, error="invalid_json", message=str(exc)), 400

        token = _token_from_request()
        remote_ip = request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()
        batch_id = (request.headers.get("X-Batch-ID") or str(uuid.uuid4())).strip()[:100]
        received_dt = _utc_now()
        received_at = _iso_utc(received_dt)
        accepted = duplicates = rejected = 0
        errors: list[dict[str, Any]] = []
        seen_devices: set[int] = set()

        conn = _connect(db_path)
        try:
            # Autenticação é feita por dispositivo. Para o lote piloto, todos os
            # blocos devem usar um token válido para o dispositivo indicado.
            for index, payload in enumerate(payloads):
                if not isinstance(payload, dict):
                    rejected += 1
                    errors.append({"index": index, "error": "bloco não é um objecto"})
                    continue
                device_code = str(payload.get("device") or payload.get("device_code") or "").strip()
                if not device_code:
                    rejected += 1
                    errors.append({"index": index, "error": "device é obrigatório"})
                    continue
                device = _load_device(conn, device_code)
                if not device:
                    rejected += 1
                    errors.append({"index": index, "error": "dispositivo desconhecido"})
                    continue
                if not _token_matches(device, token):
                    conn.rollback()
                    return jsonify(success=False, error="invalid_token", message="Token de telemetria inválido"), 401

                try:
                    measured_dt = _parse_timestamp(payload.get("timestamp") or payload.get("measured_at"))
                except ValueError as exc:
                    rejected += 1
                    errors.append({"index": index, "error": str(exc)})
                    continue
                measured_at = _iso_utc(measured_dt)
                delayed = 1 if (received_dt - measured_dt) > timedelta(minutes=5) else 0
                quality = str(payload.get("quality") or "good").strip().lower()
                if quality not in {"good", "suspect", "bad"}:
                    quality = "suspect"
                values = payload.get("values")
                if not isinstance(values, dict) or not values:
                    rejected += 1
                    errors.append({"index": index, "error": "values deve ser um objecto não vazio"})
                    continue
                if len(values) > 100:
                    rejected += 1
                    errors.append({"index": index, "error": "máximo de 100 grandezas por bloco"})
                    continue

                channels = _load_channels(conn, device["id"])
                accepted_this_block = 0
                duplicates_this_block = 0
                block_values: dict[str, float] = {}
                for channel_code, raw_value in values.items():
                    channel = channels.get(str(channel_code))
                    if not channel:
                        rejected += 1
                        errors.append(
                            {"index": index, "channel": str(channel_code), "error": "canal desconhecido"}
                        )
                        continue
                    try:
                        value = _safe_float(raw_value)
                    except ValueError as exc:
                        rejected += 1
                        errors.append({"index": index, "channel": channel_code, "error": str(exc)})
                        continue
                    block_values[str(channel_code)] = value
                    cursor = conn.execute(
                        """
                        INSERT OR IGNORE INTO telemetry_readings(
                            device_id, channel_id, measured_at, received_at, value,
                            quality, delayed, batch_id, source
                        ) VALUES(?,?,?,?,?,?,?,?, 'automatico')
                        """,
                        (
                            device["id"],
                            channel["id"],
                            measured_at,
                            received_at,
                            value,
                            quality,
                            delayed,
                            batch_id,
                        ),
                    )
                    if cursor.rowcount == 1:
                        accepted += 1
                        accepted_this_block += 1
                    else:
                        duplicates += 1
                        duplicates_this_block += 1

                if accepted_this_block or duplicates_this_block:
                    seen_devices.add(int(device["id"]))
                    conn.execute(
                        """
                        UPDATE telemetry_devices
                        SET last_seen=?,
                            last_measurement_at=CASE
                                WHEN last_measurement_at IS NULL OR last_measurement_at<? THEN ?
                                ELSE last_measurement_at
                            END,
                            last_status='online',
                            last_remote_ip=?, updated_at=?
                        WHERE id=?
                        """,
                        (
                            received_at,
                            measured_at,
                            measured_at,
                            remote_ip,
                            received_at,
                            device["id"],
                        ),
                    )
                    _set_alert(conn, device["id"], "dados_atrasados", False, received_at)
                    _set_alert(conn, device["id"], "sem_comunicacao", False, received_at)
                    if delayed == 0 and block_values:
                        _evaluate_measurement_alerts(
                            conn, device["id"], measured_at, block_values
                        )

            for device_id in seen_devices or {None}:
                conn.execute(
                    """
                    INSERT INTO telemetry_ingest_log(
                        device_id, batch_id, received_at, remote_ip, accepted,
                        duplicates, rejected, status, detail
                    ) VALUES(?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        device_id,
                        batch_id,
                        received_at,
                        remote_ip,
                        accepted,
                        duplicates,
                        rejected,
                        "ok" if accepted or duplicates else "rejected",
                        "; ".join(str(item) for item in errors[:10]),
                    ),
                )
            conn.commit()
        except sqlite3.Error as exc:
            conn.rollback()
            return jsonify(success=False, error="database", message="Falha temporária ao guardar telemetria"), 503
        finally:
            conn.close()

        status_code = 200 if accepted or duplicates else 422
        return (
            jsonify(
                success=status_code == 200,
                batch_id=batch_id,
                accepted=accepted,
                duplicates=duplicates,
                rejected=rejected,
                errors=errors[:25],
                received_at=received_at,
            ),
            status_code,
        )

    @bp.get("/telemetria")
    def dashboard():
        selected = (request.args.get("device") or DEVICE_CODE_F650).strip()
        conn = _connect(db_path)
        try:
            devices = conn.execute(
                """
                SELECT d.*, l.nome AS local_name
                FROM telemetry_devices d
                LEFT JOIN locais l ON l.id=d.local_id
                WHERE d.active=1
                ORDER BY l.nome, d.name
                """
            ).fetchall()
        finally:
            conn.close()
        device_rows = []
        for row in devices:
            item = dict(row)
            item["state"], item["age_seconds"] = _device_state(item.get("last_seen"))
            device_rows.append(item)
        return render_template(
            "telemetria.html",
            devices=device_rows,
            selected_device=selected,
            online_seconds=DEFAULT_ONLINE_SECONDS,
        )

    @bp.get("/telemetria/api/overview")
    def overview():
        code = (request.args.get("device") or DEVICE_CODE_F650).strip()
        conn = _connect(db_path)
        try:
            device = conn.execute(
                """
                SELECT d.*, l.nome AS local_name
                FROM telemetry_devices d
                LEFT JOIN locais l ON l.id=d.local_id
                WHERE d.code=? AND d.active=1
                """,
                (code,),
            ).fetchone()
            if not device:
                return jsonify(success=False, error="not_found"), 404
            _reconcile_communication_alert(conn, device)
            conn.commit()
            state, age_seconds = _device_state(device["last_seen"])
            rows = conn.execute(
                """
                SELECT c.code, c.name, c.unit, c.min_value, c.max_value,
                       c.show_dashboard, c.sort_order,
                       r.value, r.quality, r.measured_at, r.received_at, r.delayed
                FROM telemetry_channels c
                LEFT JOIN telemetry_readings r ON r.id=(
                    SELECT rr.id FROM telemetry_readings rr
                    WHERE rr.channel_id=c.id
                    ORDER BY rr.measured_at DESC, rr.id DESC LIMIT 1
                )
                WHERE c.device_id=? AND c.active=1
                ORDER BY c.sort_order, c.name
                """,
                (device["id"],),
            ).fetchall()
            channels = []
            warning_count = 0
            for row in rows:
                item = dict(row)
                raw_value = float(row["value"]) if row["value"] is not None else None
                item["raw_value"] = raw_value
                item["value"] = _processed_value(row["code"], raw_value)
                item["direction"] = (
                    _flow_direction(raw_value)
                    if row["code"] in POWER_CHANNELS
                    else None
                )
                item["state"] = (
                    _value_state(row, raw_value, row["quality"])
                    if row["value"] is not None
                    else "missing"
                )
                if item["state"] in ("warning", "bad"):
                    warning_count += 1
                channels.append(item)
            active_alert_count = conn.execute(
                """
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN severity='critical' THEN 1 ELSE 0 END) AS critical
                FROM telemetry_alerts
                WHERE device_id=? AND status IN ('open','acknowledged')
                """,
                (device["id"],),
            ).fetchone()
            public_device = {
                "id": device["id"],
                "local_id": device["local_id"],
                "local_name": device["local_name"],
                "code": device["code"],
                "name": device["name"],
                "manufacturer": device["manufacturer"],
                "model": device["model"],
                "firmware": device["firmware"],
                "protocol": device["protocol"],
                "local_ip": device["local_ip"],
                "last_seen": device["last_seen"],
                "last_measurement_at": device["last_measurement_at"],
                "last_remote_ip": device["last_remote_ip"],
                "state": state,
                "age_seconds": age_seconds,
                "warning_count": warning_count,
                "active_alert_count": int(active_alert_count["total"] or 0),
                "critical_alert_count": int(active_alert_count["critical"] or 0),
                "token_configured": bool(device["token_hash"]),
            }
            return jsonify(
                success=True,
                server_time=_iso_utc(),
                device=public_device,
                channels=channels,
            )
        finally:
            conn.close()

    @bp.get("/telemetria/api/history")
    def history():
        code = (request.args.get("device") or DEVICE_CODE_F650).strip()
        requested_channels = [
            part.strip() for part in (request.args.get("channels") or "").split(",") if part.strip()
        ]
        try:
            hours = max(1, min(24 * 31, int(request.args.get("hours") or 24)))
            limit = max(10, min(10000, int(request.args.get("limit") or 6000)))
        except ValueError:
            return jsonify(success=False, error="invalid_parameters"), 400
        cutoff = _iso_utc(_utc_now() - timedelta(hours=hours))
        # Reduz automaticamente a quantidade de pontos para manter o painel rápido.
        bucket_seconds = 60 if hours <= 24 else (300 if hours <= 168 else 1800)

        conn = _connect(db_path)
        try:
            device = _load_device(conn, code)
            if not device:
                return jsonify(success=False, error="not_found"), 404
            params: list[Any] = [bucket_seconds, bucket_seconds, device["id"], cutoff]
            channel_clause = ""
            if requested_channels:
                placeholders = ",".join("?" for _ in requested_channels)
                channel_clause = f" AND c.code IN ({placeholders})"
                params.extend(requested_channels)
            params.append(limit)
            rows = conn.execute(
                f"""
                SELECT c.code, c.name, c.unit,
                       strftime('%Y-%m-%dT%H:%M:%SZ',
                           (CAST(strftime('%s', r.measured_at) AS INTEGER) / ?) * ?,
                           'unixepoch') AS measured_at,
                       AVG(r.value) AS value,
                       CASE
                           WHEN SUM(CASE WHEN r.quality='bad' THEN 1 ELSE 0 END)>0 THEN 'bad'
                           WHEN SUM(CASE WHEN r.quality='suspect' THEN 1 ELSE 0 END)>0 THEN 'suspect'
                           ELSE 'good'
                       END AS quality
                FROM telemetry_readings r
                JOIN telemetry_channels c ON c.id=r.channel_id
                WHERE r.device_id=? AND r.measured_at>=? {channel_clause}
                GROUP BY c.id, (CAST(strftime('%s', r.measured_at) AS INTEGER) / ?)
                ORDER BY measured_at ASC, c.sort_order ASC
                LIMIT ?
                """,
                params[:-1] + [bucket_seconds, params[-1]],
            ).fetchall()
            series: dict[str, dict[str, Any]] = {}
            for row in rows:
                raw_value = float(row["value"]) if row["value"] is not None else None
                value = _processed_value(row["code"], raw_value)
                series.setdefault(
                    row["code"],
                    {"code": row["code"], "name": row["name"], "unit": row["unit"], "points": []},
                )["points"].append([row["measured_at"], value, row["quality"], raw_value])
            return jsonify(success=True, device=code, hours=hours, series=list(series.values()))
        finally:
            conn.close()

    @bp.get("/telemetria/export.csv")
    def export_csv():
        code = (request.args.get("device") or DEVICE_CODE_F650).strip()
        try:
            hours = max(1, min(24 * 366, int(request.args.get("hours") or 24)))
        except ValueError:
            hours = 24
        cutoff = _iso_utc(_utc_now() - timedelta(hours=hours))
        conn = _connect(db_path)
        try:
            rows = conn.execute(
                """
                SELECT d.code AS device, l.nome AS local, c.code AS channel,
                       c.name, c.unit, r.measured_at, r.received_at,
                       r.value, r.quality, r.delayed
                FROM telemetry_readings r
                JOIN telemetry_devices d ON d.id=r.device_id
                LEFT JOIN locais l ON l.id=d.local_id
                JOIN telemetry_channels c ON c.id=r.channel_id
                WHERE d.code=? AND r.measured_at>=?
                ORDER BY r.measured_at, c.sort_order
                """,
                (code, cutoff),
            ).fetchall()
        finally:
            conn.close()
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(
            [
                "dispositivo",
                "local",
                "canal",
                "grandeza",
                "unidade",
                "data_hora_medicao_utc",
                "data_hora_recepcao_utc",
                "valor",
                "valor_operacional",
                "sentido_medido",
                "qualidade",
                "enviado_em_atraso",
            ]
        )
        for row in rows:
            raw_value = float(row["value"])
            writer.writerow(
                [
                    row["device"],
                    row["local"],
                    row["channel"],
                    row["name"],
                    row["unit"],
                    row["measured_at"],
                    row["received_at"],
                    raw_value,
                    _processed_value(row["channel"], raw_value),
                    _flow_direction(raw_value) if row["channel"] in POWER_CHANNELS else "",
                    row["quality"],
                    row["delayed"],
                ]
            )
        filename = f"telemetria_{code}_{hours}h.csv"
        return Response(
            "\ufeff" + stream.getvalue(),
            mimetype="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @bp.get("/telemetria/api/ingest-status")
    def ingest_status():
        code = (request.args.get("device") or DEVICE_CODE_F650).strip()
        conn = _connect(db_path)
        try:
            device = _load_device(conn, code)
            if not device:
                return jsonify(success=False, error="not_found"), 404
            logs = conn.execute(
                """
                SELECT received_at, remote_ip, accepted, duplicates, rejected, status
                FROM telemetry_ingest_log
                WHERE device_id=?
                ORDER BY id DESC LIMIT 20
                """,
                (device["id"],),
            ).fetchall()
            return jsonify(success=True, logs=[dict(row) for row in logs])
        finally:
            conn.close()

    @bp.get("/telemetria/api/analysis")
    def analysis_api():
        code = (request.args.get("device") or DEVICE_CODE_F650).strip()
        try:
            hours = max(1, min(24 * 366, int(request.args.get("hours") or 24)))
        except ValueError:
            return jsonify(success=False, error="invalid_parameters"), 400
        conn = _connect(db_path)
        try:
            device = conn.execute(
                """
                SELECT d.*, l.nome AS local_name
                FROM telemetry_devices d
                LEFT JOIN locais l ON l.id=d.local_id
                WHERE d.code=? AND d.active=1
                """,
                (code,),
            ).fetchone()
            if not device:
                return jsonify(success=False, error="not_found"), 404
            _reconcile_communication_alert(conn, device)
            conn.commit()
            return jsonify(success=True, analysis=_build_analysis(conn, device, hours))
        finally:
            conn.close()

    @bp.get("/telemetria/api/alerts")
    def alerts_api():
        code = (request.args.get("device") or DEVICE_CODE_F650).strip()
        try:
            hours = max(1, min(24 * 366, int(request.args.get("hours") or 168)))
        except ValueError:
            return jsonify(success=False, error="invalid_parameters"), 400
        cutoff = _iso_utc(_utc_now() - timedelta(hours=hours))
        conn = _connect(db_path)
        try:
            device = _load_device(conn, code)
            if not device:
                return jsonify(success=False, error="not_found"), 404
            _reconcile_communication_alert(conn, device)
            conn.commit()
            alerts = _query_alerts(conn, device["id"], cutoff, 100)
            active = [item for item in alerts if item["status"] in ("open", "acknowledged")]
            return jsonify(
                success=True,
                alerts=alerts,
                counts={
                    "active": len(active),
                    "critical": sum(1 for item in active if item["severity"] == "critical"),
                    "resolved": sum(1 for item in alerts if item["status"] == "resolved"),
                },
            )
        finally:
            conn.close()

    @bp.post("/telemetria/api/alerts/<int:alert_id>/acknowledge")
    def acknowledge_alert(alert_id: int):
        conn = _connect(db_path)
        try:
            row = conn.execute(
                "SELECT * FROM telemetry_alerts WHERE id=?", (alert_id,)
            ).fetchone()
            if not row:
                return jsonify(success=False, error="not_found"), 404
            if row["status"] == "resolved":
                return jsonify(success=False, error="already_resolved"), 409
            actor = str(session.get("username") or "utilizador").strip()[:100]
            acknowledged_at = _iso_utc()
            conn.execute(
                """
                UPDATE telemetry_alerts
                SET status='acknowledged', acknowledged_at=?, acknowledged_by=?
                WHERE id=?
                """,
                (acknowledged_at, actor, alert_id),
            )
            conn.commit()
            return jsonify(success=True, acknowledged_at=acknowledged_at, acknowledged_by=actor)
        finally:
            conn.close()

    @bp.get("/telemetria/relatorio.pdf")
    def telemetry_report_pdf():
        code = (request.args.get("device") or DEVICE_CODE_F650).strip()
        try:
            hours = max(1, min(24 * 366, int(request.args.get("hours") or 24)))
        except ValueError:
            hours = 24
        conn = _connect(db_path)
        try:
            device = conn.execute(
                """
                SELECT d.*, l.nome AS local_name
                FROM telemetry_devices d
                LEFT JOIN locais l ON l.id=d.local_id
                WHERE d.code=? AND d.active=1
                """,
                (code,),
            ).fetchone()
            if not device:
                return jsonify(success=False, error="not_found"), 404
            _reconcile_communication_alert(conn, device)
            conn.commit()
            report = _build_pdf_report(_build_analysis(conn, device, hours))
        finally:
            conn.close()
        filename = f"relatorio_telemetria_{code}_{hours}h.pdf"
        return Response(
            report,
            mimetype="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    app.register_blueprint(bp)
    app.extensions["sge_telemetry_registered"] = True
