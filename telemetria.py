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

from flask import Blueprint, Response, jsonify, render_template, request
from werkzeug.security import check_password_hash, generate_password_hash


DEVICE_CODE_F650 = "F650_ENTRADA_GERAL_33KV"
DEFAULT_ONLINE_SECONDS = 180
DEFAULT_DELAYED_SECONDS = 900

# Canais preparados a partir do mapa de utilizador do F650 da Entrada Geral.
# Os limites são operacionais do SGE e não alteram as protecções do relé.
F650_CHANNELS = [
    ("tensao_ab_kv", "Tensão AB", "kV", 31.0, 35.5, 10, 1),
    ("tensao_bc_kv", "Tensão BC", "kV", 31.0, 35.5, 20, 1),
    ("tensao_ca_kv", "Tensão CA", "kV", 31.0, 35.5, 30, 1),
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

            CREATE INDEX IF NOT EXISTS idx_telemetry_readings_device_time
                ON telemetry_readings(device_id, measured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_telemetry_readings_channel_time
                ON telemetry_readings(channel_id, measured_at DESC);
            CREATE INDEX IF NOT EXISTS idx_telemetry_devices_local
                ON telemetry_devices(local_id);
            CREATE INDEX IF NOT EXISTS idx_telemetry_ingest_received
                ON telemetry_ingest_log(received_at DESC);
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
    min_value = channel["min_value"]
    max_value = channel["max_value"]
    if min_value is not None and value < float(min_value):
        return "warning"
    if max_value is not None and value > float(max_value):
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
                        SET last_seen=?, last_measurement_at=?, last_status='online',
                            last_remote_ip=?, updated_at=?
                        WHERE id=?
                        """,
                        (received_at, measured_at, remote_ip, received_at, device["id"]),
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
                item["state"] = (
                    _value_state(row, float(row["value"]), row["quality"])
                    if row["value"] is not None
                    else "missing"
                )
                if item["state"] in ("warning", "bad"):
                    warning_count += 1
                channels.append(item)
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
                series.setdefault(
                    row["code"],
                    {"code": row["code"], "name": row["name"], "unit": row["unit"], "points": []},
                )["points"].append([row["measured_at"], row["value"], row["quality"]])
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
                "qualidade",
                "enviado_em_atraso",
            ]
        )
        for row in rows:
            writer.writerow(list(row))
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

    app.register_blueprint(bp)
    app.extensions["sge_telemetry_registered"] = True
