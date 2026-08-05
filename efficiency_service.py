"""Serviços de eficiência energética do SGE.

O módulo mantém cálculos e critérios de qualidade fora das rotas Flask. Assim,
dashboard, API, PDF, Excel e testes usam exatamente a mesma interpretação de
energia, água, custo, linha de base e poupança.
"""
from __future__ import annotations

import calendar
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from billing import VAT_BASE_FACTOR, VAT_RATE, calculate_invoice, resolve_tariffs


LOCAL_TIMEZONE = timezone(timedelta(hours=2))
MIN_BASELINE_MONTHS = 3
DEFAULT_MIN_COVERAGE_PCT = 80.0
VALID_15MIN_COVERAGE_PCT = 80.0
MAX_TELEMETRY_GAP_SECONDS = 600


class EfficiencyValidationError(ValueError):
    """Erro de validação que pode ser mostrado ao utilizador."""


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return float(default)
        parsed = float(str(value).strip().replace(",", "."))
        return parsed if math.isfinite(parsed) else float(default)
    except (TypeError, ValueError):
        return float(default)


def _period_key(year: int, month: int) -> str:
    return f"{int(year):04d}-{int(month):02d}"


def parse_period(value: str) -> tuple[int, int]:
    text = str(value or "").strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m")
    except ValueError as exc:
        raise EfficiencyValidationError("O período deve usar o formato AAAA-MM.") from exc
    return parsed.year, parsed.month


def previous_month(year: int, month: int) -> tuple[int, int]:
    return (int(year) - 1, 12) if int(month) == 1 else (int(year), int(month) - 1)


def add_month(year: int, month: int, offset: int = 1) -> tuple[int, int]:
    absolute = int(year) * 12 + int(month) - 1 + int(offset)
    return absolute // 12, absolute % 12 + 1


def iter_months(start: str, end: str, *, limit: int = 60) -> list[tuple[int, int]]:
    sy, sm = parse_period(start)
    ey, em = parse_period(end)
    if (ey, em) < (sy, sm):
        raise EfficiencyValidationError("O fim da linha de base não pode anteceder o início.")
    months: list[tuple[int, int]] = []
    year, month = sy, sm
    while (year, month) <= (ey, em):
        months.append((year, month))
        if len(months) > limit:
            raise EfficiencyValidationError(f"O período não pode exceder {limit} meses.")
        year, month = add_month(year, month)
    return months


def _connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def _last_reading_before(conn: sqlite3.Connection, local_name: str, year: int, month: int, column: str) -> float | None:
    py, pm = previous_month(year, month)
    row = conn.execute(
        f"""
        SELECT {column} FROM leituras_mensais
        WHERE local=? AND ano=? AND printf('%02d', CAST(mes AS INTEGER))=?
          AND {column} IS NOT NULL AND {column}>0
        ORDER BY data DESC, rowid DESC LIMIT 1
        """,
        (local_name, py, f"{pm:02d}"),
    ).fetchone()
    return _number(row[0], 0.0) if row else None


def _operational_month(conn: sqlite3.Connection, local_id: int, year: int, month: int) -> dict[str, Any]:
    """Seleciona uma fonte por grandeza, sem somar PIGI, EDM e outras fontes."""
    try:
        rows = conn.execute(
            """SELECT data,fonte,energia_kwh,
                      COALESCE(volume_distribuido_m3,volume_produzido_m3,volume_captado_m3) AS volume_m3,
                      horas_operacao,tipo_dado,cobertura_pct
               FROM operacional_dados
               WHERE local_id=? AND estado='validado' AND substr(data,1,7)=?
               ORDER BY data,id""",
            (int(local_id), f"{int(year):04d}-{int(month):02d}"),
        ).fetchall()
    except sqlite3.Error:
        return {}
    if not rows:
        return {}
    energy_priority = {"TELEMETRIA": 5, "EDM_PLANILHA": 4, "PIGI": 3, "SCADA": 2, "MANUAL": 1}
    water_priority = {"SCADA": 5, "PIGI": 4, "EDM_PLANILHA": 2, "MANUAL": 1}
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(str(row["fonte"] or "MANUAL").upper(), []).append(row)
    def choose(field: str):
        priority = water_priority if field == "volume_m3" else energy_priority
        choices = []
        for source, items in grouped.items():
            valid = [item for item in items if _number(item[field]) is not None and _number(item[field]) >= 0]
            if valid:
                choices.append((priority.get(source, 0), len({x["data"] for x in valid}), source, valid))
        return max(choices, default=None, key=lambda x: (x[0], x[1]))
    energy_pick, water_pick = choose("energia_kwh"), choose("volume_m3")
    days_energy = len({x["data"] for x in energy_pick[3]}) if energy_pick else 0
    days_water = len({x["data"] for x in water_pick[3]}) if water_pick else 0
    days = min(x for x in (days_energy, days_water) if x > 0) if days_energy and days_water else max(days_energy, days_water)
    return {
        "energia_kwh": sum(max(0.0, _number(x["energia_kwh"])) for x in energy_pick[3]) if energy_pick else None,
        "agua_m3": sum(max(0.0, _number(x["volume_m3"])) for x in water_pick[3]) if water_pick else None,
        "fonte_energia": energy_pick[2] if energy_pick else None,
        "fonte_agua": water_pick[2] if water_pick else None,
        "dias_energia": days_energy, "dias_agua": days_water, "dias_com_dados": days,
    }


def month_metrics(conn: sqlite3.Connection, local_id: int, year: int, month: int) -> dict[str, Any]:
    """Calcula os indicadores físicos e financeiros de um local/mês.

    A energia segue a mesma regra da faturação mensal: última leitura acumulada
    menos a leitura final do mês anterior; sem base anterior, a primeira leitura
    válida do próprio mês é apenas referência.
    """
    local = conn.execute(
        "SELECT id, nome, COALESCE(tipo_local,''), COALESCE(categoria_operacional,'') FROM locais WHERE id=?",
        (int(local_id),),
    ).fetchone()
    if not local:
        raise EfficiencyValidationError("Local não encontrado.")
    month_text = f"{int(month):02d}"
    rows = conn.execute(
        """
        SELECT data, ativa, reativa, ponta, fp, agua, anterior, diferenca
        FROM leituras_mensais
        WHERE local=? AND ano=? AND printf('%02d', CAST(mes AS INTEGER))=?
          AND (ativa IS NOT NULL OR reativa IS NOT NULL OR ponta IS NOT NULL OR agua IS NOT NULL)
        ORDER BY data, rowid
        """,
        (local["nome"], int(year), month_text),
    ).fetchall()

    active = [(row["data"], _number(row["ativa"])) for row in rows if _number(row["ativa"]) > 0]
    reactive = [(row["data"], _number(row["reativa"])) for row in rows if _number(row["reativa"]) > 0]
    previous_active = _last_reading_before(conn, local["nome"], year, month, "ativa")
    previous_reactive = _last_reading_before(conn, local["nome"], year, month, "reativa")
    active_base = previous_active if previous_active and previous_active > 0 else (active[0][1] if active else 0.0)
    reactive_base = previous_reactive if previous_reactive and previous_reactive > 0 else (reactive[0][1] if reactive else 0.0)
    active_final = active[-1][1] if active else active_base
    reactive_final = reactive[-1][1] if reactive else reactive_base
    energy_kwh = max(0.0, active_final - active_base)
    reactive_kvarh = max(0.0, reactive_final - reactive_base)
    water_m3 = sum(max(0.0, _number(row["agua"])) for row in rows)
    peak_kw = max([max(0.0, _number(row["ponta"])) for row in rows] or [0.0])
    fp_values = [abs(_number(row["fp"])) for row in rows if 0 < abs(_number(row["fp"])) <= 1.2]
    fp_avg = sum(fp_values) / len(fp_values) if fp_values else None

    days_in_month = calendar.monthrange(int(year), int(month))[1]
    days_with_data = len({row["data"] for row in rows if row["data"]})
    energy_source = "LEITURA_MENSAL"
    water_source = "LEITURA_MENSAL"
    operational = _operational_month(conn, local_id, year, month)
    if operational.get("energia_kwh") is not None:
        energy_kwh = operational["energia_kwh"]
        energy_source = operational["fonte_energia"]
        # PIGI/EDM diário representa consumo já calculado, não leitura acumulada.
        reactive_kvarh = 0.0
    if operational.get("agua_m3") is not None:
        water_m3 = operational["agua_m3"]
        water_source = operational["fonte_agua"]
    if operational:
        relevant = [operational.get("dias_energia") if operational.get("energia_kwh") is not None else None,
                    operational.get("dias_agua") if operational.get("agua_m3") is not None else None]
        relevant = [value for value in relevant if value is not None]
        if relevant:
            days_with_data = min(relevant)
    coverage_pct = min(100.0, days_with_data * 100.0 / days_in_month) if days_in_month else 0.0
    tariffs = resolve_tariffs(conn, int(local_id), f"{int(year):04d}-{int(month):02d}-01")
    invoice = calculate_invoice(
        active_kwh=energy_kwh,
        reactive_kvarh=reactive_kvarh,
        measured_peak_kw=peak_kw,
        contracted_power_kw=tariffs.get("pot_contratada"),
        tariffs=tariffs,
        bill_losses=False,
    )
    specific = energy_kwh / water_m3 if energy_kwh > 0 and water_m3 > 0 else None
    cost_specific = invoice["total_mzn"] / water_m3 if water_m3 > 0 else None
    warnings: list[str] = []
    if not rows and not operational:
        warnings.append("Sem leituras no período.")
    if energy_kwh <= 0:
        warnings.append("Sem energia ativa faturável validada.")
    if water_m3 <= 0:
        warnings.append("Sem volume de água; kWh/m³ e MZN/m³ indisponíveis.")
    if coverage_pct < DEFAULT_MIN_COVERAGE_PCT:
        warnings.append("Cobertura de leituras inferior a 80%.")
    if active and previous_active is None:
        warnings.append("Sem leitura-base do mês anterior; a primeira leitura do mês foi usada como referência.")
    if operational:
        warnings.append(f"Energia: {energy_source}; água: {water_source}. As fontes não foram somadas.")
        if energy_source in ("PIGI", "EDM_PLANILHA"):
            warnings.append("O custo é estimado com as tarifas disponíveis; a fatura oficial continua separada.")

    return {
        "local_id": int(local["id"]),
        "local": local["nome"],
        "tipo_local": local[2] or local[3] or "Não classificado",
        "periodo": _period_key(year, month),
        "ano": int(year),
        "mes": int(month),
        "energia_kwh": round(energy_kwh, 6),
        "reativa_kvarh": round(reactive_kvarh, 6),
        "reativa_excedente_kvarh": round(invoice["reactive_excess_kvarh"], 6),
        "ponta_medida_kw": round(peak_kw, 6),
        "ponta_faturavel_kw": round(invoice["billing_demand_kw"], 6),
        "agua_m3": round(water_m3, 6),
        "consumo_especifico_kwh_m3": round(specific, 8) if specific is not None else None,
        "custo_total_mzn": round(invoice["total_mzn"], 6),
        "custo_especifico_mzn_m3": round(cost_specific, 8) if cost_specific is not None else None,
        "fp_medio": round(fp_avg, 6) if fp_avg is not None else None,
        "dias_com_dados": days_with_data,
        "dias_mes": days_in_month,
        "cobertura_pct": round(coverage_pct, 2),
        "tem_base_anterior": previous_active is not None,
        "leitura_base_ativa": active_base,
        "leitura_final_ativa": active_final,
        "tarifa_ativa": tariffs["tarifa_ativa"],
        "tarifa_fonte": tariffs.get("source"),
        "fonte_energia": energy_source,
        "fonte_agua": water_source,
        "avisos": warnings,
    }


def build_baseline_snapshot(
    conn: sqlite3.Connection,
    local_id: int,
    period_start: str,
    period_end: str,
    *,
    minimum_coverage_pct: float = DEFAULT_MIN_COVERAGE_PCT,
    minimum_months: int = MIN_BASELINE_MONTHS,
) -> dict[str, Any]:
    minimum_coverage_pct = max(0.0, min(100.0, _number(minimum_coverage_pct, DEFAULT_MIN_COVERAGE_PCT)))
    considered = [month_metrics(conn, local_id, year, month) for year, month in iter_months(period_start, period_end)]
    eligible = [
        item for item in considered
        if item["energia_kwh"] > 0
        and item["agua_m3"] > 0
        and item["cobertura_pct"] >= minimum_coverage_pct
        and item["consumo_especifico_kwh_m3"] is not None
    ]
    if len(eligible) < int(minimum_months):
        raise EfficiencyValidationError(
            f"A linha de base exige pelo menos {minimum_months} meses com energia, água e cobertura mínima. "
            f"Foram encontrados {len(eligible)} mês(es) elegível(eis)."
        )
    energy = sum(item["energia_kwh"] for item in eligible)
    water = sum(item["agua_m3"] for item in eligible)
    cost = sum(item["custo_total_mzn"] for item in eligible)
    count = len(eligible)
    return {
        "local_id": int(local_id),
        "periodo_inicio": period_start,
        "periodo_fim": period_end,
        "cobertura_minima_pct": minimum_coverage_pct,
        "meses_elegiveis": count,
        "energia_total_kwh": energy,
        "agua_total_m3": water,
        "custo_total_mzn": cost,
        "energia_media_mensal_kwh": energy / count,
        "agua_media_mensal_m3": water / count,
        "custo_medio_mensal_mzn": cost / count,
        "consumo_especifico_kwh_m3": energy / water,
        "custo_especifico_mzn_m3": cost / water,
        "meses": eligible,
        "meses_excluidos": [item for item in considered if item not in eligible],
    }


def approved_baseline(conn: sqlite3.Connection, local_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT b.*, l.nome AS local
        FROM eficiencia_baselines b JOIN locais l ON l.id=b.local_id
        WHERE b.local_id=? AND b.estado='aprovada'
        ORDER BY COALESCE(b.aprovado_em,b.criado_em) DESC, b.id DESC LIMIT 1
        """,
        (int(local_id),),
    ).fetchone()
    return dict(row) if row else None


def target_for_year(conn: sqlite3.Connection, local_id: int, year: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM eficiencia_metas WHERE local_id=? AND ano=? LIMIT 1",
        (int(local_id), int(year)),
    ).fetchone()
    return dict(row) if row else None


def evaluate_month(conn: sqlite3.Connection, local_id: int, year: int, month: int) -> dict[str, Any]:
    current = month_metrics(conn, local_id, year, month)
    baseline = approved_baseline(conn, local_id)
    target = target_for_year(conn, local_id, year)
    result = dict(current)
    result.update({
        "baseline": baseline,
        "meta": target,
        "estado_eficiencia": "Sem linha de base",
        "desvio_baseline_pct": None,
        "energia_esperada_kwh": None,
        "poupanca_energia_kwh": None,
        "poupanca_energia_pct": None,
        "poupanca_financeira_mzn": None,
        "qualidade_poupanca": "indisponível",
        "meta_kwh_m3": target.get("meta_kwh_m3") if target else None,
        "desvio_meta_pct": None,
    })
    specific = current.get("consumo_especifico_kwh_m3")
    if baseline and _number(baseline.get("consumo_especifico_kwh_m3")) > 0 and specific is not None and current["agua_m3"] > 0:
        baseline_specific = _number(baseline["consumo_especifico_kwh_m3"])
        expected = baseline_specific * current["agua_m3"]
        savings = expected - current["energia_kwh"]
        savings_pct = savings * 100.0 / expected if expected > 0 else None
        deviation = (specific - baseline_specific) * 100.0 / baseline_specific
        effective_active_rate = current["tarifa_ativa"] * (1.0 + VAT_RATE * VAT_BASE_FACTOR)
        financial = savings * effective_active_rate
        quality = "verificada" if current["cobertura_pct"] >= DEFAULT_MIN_COVERAGE_PCT and int(baseline["meses_elegiveis"] or 0) >= MIN_BASELINE_MONTHS else "indicativa"
        state = "Eficiente" if deviation <= -5 else ("Dentro da base" if deviation < 10 else ("Atenção" if deviation < 20 else "Crítico"))
        result.update({
            "estado_eficiencia": state,
            "desvio_baseline_pct": round(deviation, 2),
            "energia_esperada_kwh": round(expected, 6),
            "poupanca_energia_kwh": round(savings, 6),
            "poupanca_energia_pct": round(savings_pct, 2) if savings_pct is not None else None,
            "poupanca_financeira_mzn": round(financial, 6),
            "qualidade_poupanca": quality,
        })
    if target and specific is not None and _number(target.get("meta_kwh_m3")) > 0:
        target_specific = _number(target["meta_kwh_m3"])
        result["desvio_meta_pct"] = round((specific - target_specific) * 100.0 / target_specific, 2)
    return result


def efficiency_history(conn: sqlite3.Connection, local_id: int, year: int, month: int, months: int = 12) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    start_year, start_month = add_month(year, month, -(max(1, int(months)) - 1))
    for offset in range(max(1, int(months))):
        item_year, item_month = add_month(start_year, start_month, offset)
        result.append(evaluate_month(conn, local_id, item_year, item_month))
    return result


def _parse_timestamp(value: str) -> datetime:
    text = str(value or "").strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=LOCAL_TIMEZONE)
    return parsed.astimezone(timezone.utc)


def _quarter_floor(value: datetime) -> datetime:
    local = value.astimezone(LOCAL_TIMEZONE)
    local = local.replace(minute=(local.minute // 15) * 15, second=0, microsecond=0)
    return local.astimezone(timezone.utc)


def demand_15min(conn: sqlite3.Connection, local_id: int, year: int, month: int) -> dict[str, Any]:
    """Calcula a potência média observada em janelas civis de 15 minutos."""
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    if not {"telemetry_devices", "telemetry_channels", "telemetry_readings"}.issubset(tables):
        return {"available": False, "reason": "Sem telemetria configurada", "intervals": [], "peak_kw": None}
    start_local = datetime(int(year), int(month), 1, tzinfo=LOCAL_TIMEZONE)
    ny, nm = add_month(year, month)
    end_local = datetime(ny, nm, 1, tzinfo=LOCAL_TIMEZONE)
    start = start_local.astimezone(timezone.utc)
    end = end_local.astimezone(timezone.utc)
    device = conn.execute(
        "SELECT id, code, name FROM telemetry_devices WHERE local_id=? AND active=1 ORDER BY id LIMIT 1",
        (int(local_id),),
    ).fetchone()
    if not device:
        return {"available": False, "reason": "O local não possui dispositivo de telemetria ativo", "intervals": [], "peak_kw": None}
    rows = conn.execute(
        """
        SELECT r.measured_at, ABS(r.value) AS mw
        FROM telemetry_readings r JOIN telemetry_channels c ON c.id=r.channel_id
        WHERE r.device_id=? AND c.code='potencia_activa_total_mw' AND r.quality!='bad'
          AND r.measured_at>=? AND r.measured_at<?
        ORDER BY r.measured_at, r.id
        """,
        (device["id"], start.isoformat(), end.isoformat()),
    ).fetchall()
    points: list[tuple[datetime, float]] = []
    for row in rows:
        try:
            points.append((_parse_timestamp(row["measured_at"]), abs(_number(row["mw"])) * 1000.0))
        except (TypeError, ValueError):
            continue
    buckets: dict[datetime, dict[str, float]] = {}
    for (t0, p0), (t1, p1) in zip(points, points[1:]):
        gap = (t1 - t0).total_seconds()
        if gap <= 0 or gap > MAX_TELEMETRY_GAP_SECONDS:
            continue
        cursor = max(t0, start)
        segment_end = min(t1, end)
        if cursor >= segment_end:
            continue
        while cursor < segment_end:
            bucket = _quarter_floor(cursor)
            boundary = min(bucket + timedelta(minutes=15), segment_end)
            ratio0 = (cursor - t0).total_seconds() / gap
            ratio1 = (boundary - t0).total_seconds() / gap
            cp = p0 + (p1 - p0) * ratio0
            bp = p0 + (p1 - p0) * ratio1
            seconds = (boundary - cursor).total_seconds()
            energy_kwh = (cp + bp) / 2.0 * seconds / 3600.0
            entry = buckets.setdefault(bucket, {"energy_kwh": 0.0, "covered_seconds": 0.0})
            entry["energy_kwh"] += energy_kwh
            entry["covered_seconds"] += seconds
            cursor = boundary
    intervals: list[dict[str, Any]] = []
    for bucket, values in sorted(buckets.items()):
        coverage = min(100.0, values["covered_seconds"] * 100.0 / 900.0)
        valid = coverage >= VALID_15MIN_COVERAGE_PCT
        observed_hours = values["covered_seconds"] / 3600.0
        avg_kw = values["energy_kwh"] / observed_hours if observed_hours > 0 else None
        intervals.append({
            "inicio": bucket.astimezone(LOCAL_TIMEZONE).isoformat(),
            "media_kw": round(avg_kw, 3) if avg_kw is not None else None,
            "cobertura_pct": round(coverage, 1),
            "valido": valid,
            "estimado": valid and coverage < 95.0,
        })
    valid_rows = [item for item in intervals if item["valido"] and item["media_kw"] is not None]
    peak = max(valid_rows, key=lambda item: item["media_kw"]) if valid_rows else None
    return {
        "available": bool(valid_rows),
        "reason": None if valid_rows else "Sem intervalos de 15 minutos com cobertura mínima de 80%",
        "device_code": device["code"],
        "device_name": device["name"],
        "intervals": intervals,
        "valid_intervals": len(valid_rows),
        "peak_kw": peak["media_kw"] if peak else None,
        "peak_at": peak["inicio"] if peak else None,
        "peak_estimated": peak["estimado"] if peak else False,
    }


def build_dashboard(db_path: str, year: int, month: int, local_id: int | None = None) -> dict[str, Any]:
    conn = _connect(db_path)
    try:
        params: list[Any] = []
        where = "WHERE COALESCE(ativo,1)=1"
        if local_id:
            where += " AND id=?"
            params.append(int(local_id))
        local_rows = conn.execute(
            f"SELECT id, nome, COALESCE(tipo_local,''), COALESCE(categoria_operacional,'') FROM locais {where} ORDER BY nome",
            params,
        ).fetchall()
        evaluations = [evaluate_month(conn, row["id"], year, month) for row in local_rows]
        comparable = [item for item in evaluations if item["consumo_especifico_kwh_m3"] is not None]
        ranking = sorted(comparable, key=lambda item: item["consumo_especifico_kwh_m3"])
        total_energy = sum(item["energia_kwh"] for item in evaluations)
        total_water = sum(item["agua_m3"] for item in evaluations)
        total_cost = sum(item["custo_total_mzn"] for item in evaluations)
        verified = [item for item in evaluations if item["qualidade_poupanca"] == "verificada"]
        selected = evaluations[0] if local_id and evaluations else None
        history = efficiency_history(conn, int(local_id), year, month) if selected else []
        demand = demand_15min(conn, int(local_id), year, month) if selected else {
            "available": False, "reason": "Selecione um local para analisar a demanda de 15 minutos", "intervals": [], "peak_kw": None
        }
        measures_query = "SELECT m.*, l.nome AS local FROM eficiencia_medidas m JOIN locais l ON l.id=m.local_id"
        measures_params: list[Any] = []
        if local_id:
            measures_query += " WHERE m.local_id=?"
            measures_params.append(int(local_id))
        measures_query += " ORDER BY CASE m.prioridade WHEN 'Alta' THEN 1 WHEN 'Média' THEN 2 ELSE 3 END, m.id DESC"
        measures = [dict(row) for row in conn.execute(measures_query, measures_params).fetchall()]
        return {
            "periodo": _period_key(year, month),
            "ano": int(year),
            "mes": int(month),
            "local_id": int(local_id) if local_id else None,
            "selected": selected,
            "evaluations": evaluations,
            "ranking": ranking,
            "history": history,
            "demand_15min": demand,
            "measures": measures,
            "summary": {
                "energia_kwh": round(total_energy, 2),
                "agua_m3": round(total_water, 2),
                "custo_mzn": round(total_cost, 2),
                "consumo_especifico_kwh_m3": round(total_energy / total_water, 6) if total_water > 0 else None,
                "custo_especifico_mzn_m3": round(total_cost / total_water, 6) if total_water > 0 else None,
                "locais_com_indicador": len(comparable),
                "locais_com_baseline": sum(1 for item in evaluations if item["baseline"]),
                "locais_criticos": sum(1 for item in evaluations if item["estado_eficiencia"] == "Crítico"),
                "poupanca_verificada_kwh": round(sum(_number(item["poupanca_energia_kwh"]) for item in verified), 2),
                "poupanca_verificada_mzn": round(sum(_number(item["poupanca_financeira_mzn"]) for item in verified), 2),
                "medidas_abertas": sum(1 for item in measures if item["estado"] not in ("Verificada", "Cancelada")),
            },
        }
    finally:
        conn.close()


def audit(conn: sqlite3.Connection, entity: str, entity_id: int | None, action: str, detail: str, actor: str) -> None:
    conn.execute(
        "INSERT INTO eficiencia_audit(entidade, entidade_id, acao, detalhe, actor) VALUES(?,?,?,?,?)",
        (str(entity)[:60], entity_id, str(action)[:80], str(detail)[:1000], str(actor)[:100]),
    )
