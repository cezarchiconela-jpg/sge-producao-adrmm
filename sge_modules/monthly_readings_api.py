"""Domínio monthly_readings_api extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""

@app.get('/api/local_cfg', endpoint='api_local_cfg_v2')
def api_local_cfg_v2():
    try:
        local_any = request.args.get('local', '').strip()
    except Exception:
        local_any = ''
    conn = sqlite3.connect(DB_PATH if 'DB_PATH' in globals() else 'sge.db')
    try:
        local_id, _ = _get_local_id_by_any(conn, local_any)
        if not local_id:
            return jsonify({"error":"local não encontrado"}), 404
        cfg = _get_local_cfg_full(conn, local_id)
        return jsonify(cfg), 200
    finally:
        conn.close()


# --- Alias para compatibilidade com o frontend: /api/local_cfg/<id_ou_nome> ---
@app.get('/api/local_cfg/<path:local_any>', endpoint='api_local_cfg_alias')
def api_local_cfg_alias(local_any):
    try:
        any_val = (local_any or '').strip()
    except Exception:
        any_val = ''
    conn = sqlite3.connect(DB_PATH if 'DB_PATH' in globals() else 'sge.db')
    try:
        local_id, _ = _get_local_id_by_any(conn, any_val)
        if not local_id:
            return jsonify({"error": "local não encontrado"}), 404
        cfg = _get_local_cfg_full(conn, local_id)
        return jsonify(cfg), 200
    finally:
        conn.close()

@app.post('/api/leituras_mensal/calc_fatura', endpoint='api_calc_fatura_mensal_v2')
def api_calc_fatura_mensal_v2():
    data = request.get_json(silent=True) or {}

    fator_mult  = _to_float(data.get('fator_mult'), 1.0)
    kwh_ativa   = _to_float(data.get('kwh_ativa'))   * fator_mult
    kwh_reativa = _to_float(data.get('kwh_reativa')) * fator_mult
    kwh_ponta   = _to_float(data.get('kwh_ponta'))   * fator_mult
    kwh_perdas  = _to_float(data.get('kwh_perdas'))  * fator_mult  # mantido só para referência

    t_ativa   = _to_float(data.get('tarifa_ativa'))
    t_reativa = _to_float(data.get('tarifa_reativa'))
    t_ponta   = _to_float(data.get('tarifa_ponta'))
    t_perdas  = _to_float(data.get('tarifa_perdas'))

    taxa_fixa  = _to_float(data.get('taxa_fixa'))
    taxa_radio = _to_float(data.get('taxa_radio'))
    taxa_lixo  = _to_float(data.get('taxa_lixo'))
    pot_contratada = _to_float(data.get('pot_contratada'))
    fatura = calculate_invoice(
        active_kwh=kwh_ativa,
        reactive_kvarh=kwh_reativa,
        measured_peak_kw=kwh_ponta,
        contracted_power_kw=pot_contratada,
        losses_kwh=kwh_perdas,
        tariffs={
            'tarifa_ativa': t_ativa, 'tarifa_reativa': t_reativa,
            'tarifa_ponta': t_ponta, 'tarifa_perdas': t_perdas,
            'taxa_fixa': taxa_fixa, 'taxa_radio': taxa_radio, 'taxa_lixo': taxa_lixo,
        },
        bill_losses=False,
    )

    result = {
        "kwh": {
            "ativa":   round(kwh_ativa,       3),
            "reativa": round(fatura['reactive_excess_kvarh'], 3),
            "ponta":   round(fatura['billing_demand_kw'], 3),
            "perdas":  0.0
        },
        "custos": {
            "ativa":   round(fatura['active_cost_mzn'], 2),
            "reativa": round(fatura['reactive_cost_mzn'], 2),
            "ponta":   round(fatura['demand_cost_mzn'], 2),
            "perdas":  round(fatura['losses_cost_mzn'], 2)
        },
        "energia_subtotal": round(fatura['energy_subtotal_mzn'], 2),
        "taxas": {
            "fixa":  round(taxa_fixa,  2),
            "radio": round(taxa_radio, 2),
            "lixo":  round(taxa_lixo,  2)
        },
        "taxas_subtotal": round(fatura['fees_subtotal_mzn'], 2),
        "subtotal":       round(fatura['subtotal_mzn'], 2),
        "base_iva":       round(fatura['vat_base_mzn'], 2),
        "iva_percent":    16.0,
        "base_iva_percent": 62.0,
        "iva":            round(fatura['vat_mzn'], 2),
        "total":          round(fatura['total_mzn'], 2)
    }
    return jsonify(result), 200

