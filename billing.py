"""Motor único de faturação energética do SGE.

Todas as páginas, APIs, relatórios e a telemetria devem usar estas funções.
As duas regras fiscais/operacionais abaixo são deliberadamente centralizadas:

* IVA: 16% aplicado a 62% do subtotal (taxa efetiva de 9,92%).
* Ponta faturável: 20% da potência contratada + 80% da ponta medida.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping


VAT_RATE = 0.16
VAT_BASE_FACTOR = 0.62
REACTIVE_LIMIT_FACTOR = 0.75
CONTRACTED_DEMAND_SHARE = 0.20
MEASURED_DEMAND_SHARE = 0.80

DEFAULT_TARIFFS = {
    "tarifa_ativa": 4.780,
    "tarifa_reativa": 1.430,
    "tarifa_ponta": 497.03,
    "tarifa_perdas": 4.780,
    "taxa_fixa": 207.28,
    "taxa_radio": 297.00,
    "taxa_lixo": 150.00,
    "iva": VAT_RATE * 100.0,
    "iva_base_factor": VAT_BASE_FACTOR,
    "pot_contratada": 0.0,
}


def _number(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return float(default)
        number = float(str(value).strip().replace(",", "."))
        return number if number == number else float(default)
    except (TypeError, ValueError):
        return float(default)


def _non_negative(value: Any, default: float = 0.0) -> float:
    return max(0.0, _number(value, default))


def normalise_tariffs(values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Devolve um tarifário completo e força a regra fiscal aprovada."""
    source = dict(values or {})
    tariffs: dict[str, Any] = dict(DEFAULT_TARIFFS)
    for key in (
        "tarifa_ativa",
        "tarifa_reativa",
        "tarifa_ponta",
        "tarifa_perdas",
        "taxa_fixa",
        "taxa_radio",
        "taxa_lixo",
        "pot_contratada",
    ):
        if key in source and source[key] is not None:
            tariffs[key] = _non_negative(source[key], tariffs[key])
    if not tariffs["tarifa_reativa"] and tariffs["tarifa_ativa"]:
        tariffs["tarifa_reativa"] = tariffs["tarifa_ativa"] * 0.30

    # Estes valores não são configuráveis por rota: são a regra fiscal do SGE.
    tariffs["iva"] = VAT_RATE * 100.0
    tariffs["iva_base_factor"] = VAT_BASE_FACTOR
    for key in ("source", "configured", "valid_from", "valid_to", "history_id"):
        if key in source:
            tariffs[key] = source[key]
    return tariffs


def billing_demand(contracted_power_kw: Any, measured_peak_kw: Any) -> float:
    contracted = _non_negative(contracted_power_kw)
    measured = _non_negative(measured_peak_kw)
    return CONTRACTED_DEMAND_SHARE * contracted + MEASURED_DEMAND_SHARE * measured


def calculate_invoice(
    *,
    active_kwh: Any,
    reactive_kvarh: Any = 0.0,
    measured_peak_kw: Any = 0.0,
    contracted_power_kw: Any | None = None,
    losses_kwh: Any = 0.0,
    tariffs: Mapping[str, Any] | None = None,
    previous_balance_mzn: Any = 0.0,
    bill_losses: bool = False,
) -> dict[str, Any]:
    """Calcula uma fatura completa com uma estrutura estável e testável."""
    t = normalise_tariffs(tariffs)
    active = _non_negative(active_kwh)
    reactive = _non_negative(reactive_kvarh)
    losses = _non_negative(losses_kwh)
    contracted = _non_negative(
        t.get("pot_contratada") if contracted_power_kw is None else contracted_power_kw
    )
    measured_peak = _non_negative(measured_peak_kw)
    reactive_limit = REACTIVE_LIMIT_FACTOR * active
    reactive_excess = max(0.0, reactive - reactive_limit)
    demand = billing_demand(contracted, measured_peak)

    active_cost = active * t["tarifa_ativa"]
    reactive_cost = reactive_excess * t["tarifa_reativa"]
    demand_cost = demand * t["tarifa_ponta"]
    losses_cost = losses * t["tarifa_perdas"] if bill_losses else 0.0
    energy_subtotal = active_cost + reactive_cost + demand_cost + losses_cost
    fees_subtotal = t["taxa_fixa"] + t["taxa_radio"] + t["taxa_lixo"]
    subtotal = energy_subtotal + fees_subtotal
    vat_base = subtotal * VAT_BASE_FACTOR
    vat_value = vat_base * VAT_RATE
    previous_balance = _number(previous_balance_mzn, 0.0)
    total_before_balance = subtotal + vat_value
    total = total_before_balance + previous_balance

    return {
        "tariffs": t,
        "active_energy_kwh": active,
        "reactive_energy_kvarh": reactive,
        "reactive_limit_kvarh": reactive_limit,
        "reactive_excess_kvarh": reactive_excess,
        "losses_kwh": losses if bill_losses else 0.0,
        "measured_peak_kw": measured_peak,
        "contracted_power_kw": contracted,
        "billing_demand_kw": demand,
        "active_cost_mzn": active_cost,
        "reactive_cost_mzn": reactive_cost,
        "demand_cost_mzn": demand_cost,
        "losses_cost_mzn": losses_cost,
        "energy_subtotal_mzn": energy_subtotal,
        "fixed_fee_mzn": t["taxa_fixa"],
        "radio_fee_mzn": t["taxa_radio"],
        "waste_fee_mzn": t["taxa_lixo"],
        "fees_subtotal_mzn": fees_subtotal,
        "subtotal_mzn": subtotal,
        "vat_rate": VAT_RATE,
        "vat_rate_percent": VAT_RATE * 100.0,
        "vat_base_factor": VAT_BASE_FACTOR,
        "vat_base_percent": VAT_BASE_FACTOR * 100.0,
        "vat_base_mzn": vat_base,
        "vat_mzn": vat_value,
        "previous_balance_mzn": previous_balance,
        "total_before_balance_mzn": total_before_balance,
        "total_mzn": total,
    }


def _date_text(value: date | datetime | str | None) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    if not text:
        return date.today().isoformat()
    if len(text) >= 10:
        text = text[:10]
    datetime.strptime(text, "%Y-%m-%d")
    return text


def resolve_tariffs(conn, local_id: int | None, effective_date: date | datetime | str | None = None) -> dict[str, Any]:
    """Resolve o tarifário válido na data, com fallback compatível com bases antigas."""
    when = _date_text(effective_date)
    if local_id is not None:
        try:
            row = conn.execute(
                """
                SELECT id, valid_from, valid_to, tarifa_ativa, tarifa_reativa,
                       tarifa_ponta, tarifa_perdas, taxa_fixa, taxa_radio, taxa_lixo,
                       pot_contratada
                FROM tarifas_historico
                WHERE local_id=? AND valid_from<=?
                  AND (valid_to IS NULL OR valid_to='' OR valid_to>=?)
                ORDER BY valid_from DESC, id DESC LIMIT 1
                """,
                (int(local_id), when, when),
            ).fetchone()
        except Exception:
            row = None
        if row:
            keys = (
                "history_id", "valid_from", "valid_to", "tarifa_ativa",
                "tarifa_reativa", "tarifa_ponta", "tarifa_perdas", "taxa_fixa",
                "taxa_radio", "taxa_lixo", "pot_contratada",
            )
            values = dict(zip(keys, tuple(row)))
            values.update(configured=True, source="Tarifário histórico válido no período")
            return normalise_tariffs(values)

        try:
            row = conn.execute(
                """
                SELECT tarifa_ativa, tarifa_reativa, tarifa_ponta, tarifa_perdas,
                       taxa_fixa, taxa_radio, taxa_lixo, pot_contratada
                FROM locais_cfg WHERE local_id=? LIMIT 1
                """,
                (int(local_id),),
            ).fetchone()
        except Exception:
            row = None
        if row:
            keys = (
                "tarifa_ativa", "tarifa_reativa", "tarifa_ponta", "tarifa_perdas",
                "taxa_fixa", "taxa_radio", "taxa_lixo", "pot_contratada",
            )
            values = dict(zip(keys, tuple(row)))
            values.update(configured=True, source="Configuração atual do local")
            return normalise_tariffs(values)

    return normalise_tariffs({"configured": False, "source": "Valores-padrão do SGE"})

