"""Domínio dashboard_core extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""

@app.route('/')
def index():
    return render_template('index.html')



# === MÓDULO UNIFICADO: GESTÃO DE LEITURAS, CONSUMO E FATURAÇÃO ===
@app.route('/energia')
@app.route('/gestao_leituras')
def gestao_leituras():
    """Centro único para leitura diária, consulta, planilha mensal e fatura."""
    from datetime import datetime
    mes = request.args.get('mes', default=datetime.now().month, type=int)
    ano = request.args.get('ano', default=datetime.now().year, type=int)
    local_id = request.args.get('local_id', type=int)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    locais = c.execute("""
        SELECT id, nome
        FROM locais
        ORDER BY nome
    """).fetchall()

    selected_local = None
    if locais:
        if local_id is None:
            local_id = locais[0]['id']
        selected_local = c.execute("SELECT * FROM locais WHERE id=?", (local_id,)).fetchone()
        if selected_local is None:
            selected_local = locais[0]
            local_id = selected_local['id']

    cfg = {}
    if selected_local:
        cfg_row = c.execute("SELECT * FROM locais_cfg WHERE local_id=?", (local_id,)).fetchone()
        if cfg_row:
            cfg = dict(cfg_row)

    fator_mult = float(cfg.get('fator_mult') or selected_local['fator_multiplicativo'] if selected_local and 'fator_multiplicativo' in selected_local.keys() else 1) if selected_local else 1.0
    tarifas = resolve_tariffs(conn, local_id, f"{int(ano):04d}-{int(mes):02d}-01") if selected_local else normalise_tariffs()

    totais = dict(dias=0, ativa=0, reativa=0, ponta=0, agua=0, fp_medio=0, diferenca=0)
    if selected_local:
        r = c.execute("""
            SELECT COUNT(*) dias,
                   COALESCE(SUM(ativa),0) ativa,
                   COALESCE(SUM(reativa),0) reativa,
                   COALESCE(MAX(ponta),0) ponta,
                   COALESCE(SUM(agua),0) agua,
                   COALESCE(AVG(NULLIF(fp,0)),0) fp_medio,
                   COALESCE(SUM(CASE WHEN diferenca IS NOT NULL AND diferenca != '' THEN diferenca ELSE ativa END),0) diferenca
            FROM leituras_mensais
            WHERE local=? AND mes=? AND ano=?
        """, (selected_local['nome'], str(mes), int(ano))).fetchone()
        if r:
            totais.update(dict(r))

    ativa_faturavel = float(totais.get('diferenca') or totais.get('ativa') or 0) * fator_mult
    reativa_faturavel = float(totais.get('reativa') or 0) * fator_mult
    ponta_faturavel = _ponta_faturavel_edm(float(cfg.get('pot_contratada') or (selected_local['potencia_contratada'] if selected_local and 'potencia_contratada' in selected_local.keys() else 0) or 0), float(totais.get('ponta') or 0) * fator_mult)
    agua = float(totais.get('agua') or 0)
    consumo_especifico = (ativa_faturavel / agua) if agua > 0 else 0
    fatura = calculate_invoice(
        active_kwh=ativa_faturavel,
        reactive_kvarh=reativa_faturavel,
        measured_peak_kw=float(totais.get('ponta') or 0) * fator_mult,
        contracted_power_kw=tarifas.get('pot_contratada'),
        tariffs=tarifas,
    )
    ponta_faturavel = fatura['billing_demand_kw']
    total_estimado = fatura['total_mzn']

    resumo = {
        'fator_mult': fator_mult,
        'pot_contratada': fatura['contracted_power_kw'],
        'pot_instalada': float(cfg.get('pot_instalada') or 0),
        'tarifa_ativa': tarifas['tarifa_ativa'],
        'tarifa_reativa': tarifas['tarifa_reativa'],
        'tarifa_ponta': tarifas['tarifa_ponta'],
        'ativa_faturavel': ativa_faturavel,
        'reativa_faturavel': reativa_faturavel,
        'ponta_faturavel': ponta_faturavel,
        'consumo_especifico': consumo_especifico,
        'fp_medio': float(totais.get('fp_medio') or 0),
        'total_estimado': total_estimado,
    }
    conn.close()
    return render_template('gestao_leituras.html', locais=locais, selected_local=selected_local, mes=mes, ano=ano, resumo=resumo)

# === DASHBOARD ===
# === DASHBOARD (versão excelência v2) ===
from collections import defaultdict

def _ensure_idx_dashboard():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_leituras_mensais_local_mes_ano ON leituras_mensais(local, mes, ano)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_leituras_mensais_data ON leituras_mensais(data)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_motor_runs_start ON motor_runs(start_time)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_equip_local ON equipamentos(local_id)")
        conn.commit()
    finally:
        conn.close()

def _detect_tariff_column(c):
    # tenta descobrir a coluna de tarifa em locais_cfg
    try:
        cols = [r[1] for r in c.execute("PRAGMA table_info(locais_cfg)").fetchall()]
    except Exception:
        return None
    for name in ("tarifa_kwh","tarifa_ativa","tarifa"):
        if name in cols:
            return name
    return None

def _prev_month(mes, ano):
    m = int(mes)
    if m == 1:
        return "12", ano - 1
    return f"{m-1:02d}", ano

def _dias_no_mes(mes, ano):
    import calendar
    return calendar.monthrange(int(ano), int(mes))[1]

def _agg_dashboard(mes, ano, local_id=None):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        # detetar coluna de tarifa (se existir)
        tarifa_col = _detect_tariff_column(c)
        where_local = ""
        where_local_runs = ""
        params_main = [mes, ano]
        params_runs = [mes, str(ano)]
        params_daily = [mes, ano]
        if local_id:
            where_local = " AND l.id = ? "
            params_main.append(int(local_id))
            where_local_runs = " AND e.local_id = ? "
            params_runs.append(int(local_id))
            params_daily.append(int(local_id))

        # agregados por local no mês
        rows = c.execute(f"""
            SELECT l.id AS local_id, l.nome AS local,
                   ROUND(COALESCE(SUM(m.diferenca),0),2) AS energia_mes,
                   SUM(CASE WHEN m.fp IS NOT NULL AND m.fp < 0.80 THEN 1 ELSE 0 END) AS fp_baixo,
                   MAX(m.ponta) AS ponta_max,
                   COUNT(DISTINCT m.data) AS dias_com_dados
            FROM locais l
            LEFT JOIN leituras_mensais m
                   ON m.local = l.nome AND m.mes = ? AND m.ano = ?
            WHERE 1=1 {where_local}
            GROUP BY l.id, l.nome
            ORDER BY energia_mes DESC, l.nome ASC
        """, params_main).fetchall()

        # horas de motor por local no mês
        hrs = dict(c.execute(f"""
            SELECT e.local_id, ROUND(COALESCE(SUM(r.duracao_min),0)/60.0, 2) as horas
            FROM motor_runs r
            JOIN equipamentos e ON e.id = r.equipamento_id
            WHERE strftime('%m', r.start_time)=? AND strftime('%Y', r.start_time)=? {where_local_runs}
            GROUP BY e.local_id
        """, params_runs).fetchall())

        # tarifas por local (se houver)
        tarifas = {}
        if tarifa_col:
            try:
                tarifas = dict(c.execute(f"""
                    SELECT lc.local_id, ROUND(COALESCE(lc.{tarifa_col},0),4) as tarifa
                    FROM locais_cfg lc
                """).fetchall())
            except Exception:
                tarifas = {}

        # KPI globais e cartões
        cards, energia_total, ponta_max_global, locais_fp_baixo = [], 0.0, 0.0, 0
        dias_mes = _dias_no_mes(mes, ano)
        locais_cobertura_baixa = 0
        custo_total = 0.0
        custos_habilitados = bool(tarifa_col)

        for lid, lname, energia_mes, fp_baixo, ponta_max, dias_com_dados in rows:
            energia_mes = float(energia_mes or 0)
            fp_baixo = int(fp_baixo or 0)
            ponta_max = float(ponta_max or 0)
            dias_com_dados = int(dias_com_dados or 0)
            horas_motores = float(hrs.get(lid, 0.0))

            cobertura_pct = round( (dias_com_dados * 100.0 / dias_mes) if dias_mes else 0.0 , 1)
            if cobertura_pct < 80.0:
                locais_cobertura_baixa += 1

            tarifa_kwh = tarifas.get(lid) if custos_habilitados else None
            custo_estimado = round(energia_mes * float(tarifa_kwh), 2) if (custos_habilitados and tarifa_kwh is not None) else None
            if custo_estimado is not None:
                custo_total += custo_estimado

            cards.append({
                "local_id": lid,
                "local": lname,
                "energia_mes": energia_mes,
                "fp_baixo": fp_baixo,
                "ponta_max": ponta_max,
                "horas_motores": horas_motores,
                "dias_com_dados": dias_com_dados,
                "dias_mes": dias_mes,
                "cobertura_pct": cobertura_pct,
                "tarifa_kwh": tarifa_kwh if tarifa_kwh is not None else None,
                "custo_estimado": custo_estimado if custo_estimado is not None else None
            })

            energia_total += energia_mes
            ponta_max_global = max(ponta_max_global, ponta_max)
            if fp_baixo > 0:
                locais_fp_baixo += 1

        # Ranking (Top 8)
        top = sorted(cards, key=lambda x: x["energia_mes"], reverse=True)[:8]
        rank = {"labels": [x["local"] for x in top], "data": [x["energia_mes"] for x in top]}

        # Tendência diária (todas as leituras do mês, somadas por dia)
        daily = c.execute(f"""
            SELECT m.data, ROUND(COALESCE(SUM(m.diferenca),0),2) as kwh
            FROM leituras_mensais m
            JOIN locais l ON l.nome = m.local
            WHERE m.mes = ? AND m.ano = ? {(" AND l.id = ?" if local_id else "")}
            GROUP BY m.data
            ORDER BY m.data ASC
        """, params_daily).fetchall()
        trend = {"labels": [r[0] for r in daily], "data": [float(r[1] or 0) for r in daily]}

        # M-1 comparação
        mes_prev, ano_prev = _prev_month(mes, ano)
        energia_prev = c.execute("""
            SELECT ROUND(COALESCE(SUM(m.diferenca),0),2)
            FROM leituras_mensais m
            JOIN locais l ON l.nome = m.local
            WHERE m.mes = ? AND m.ano = ?
            """ + ( " AND l.id = ?" if local_id else "" ),
            ([mes_prev, ano_prev] + ([int(local_id)] if local_id else []))
        ).fetchone()[0] or 0.0
        energia_prev = float(energia_prev)

        # custo M-1
        custo_prev = None
        if custos_habilitados:
            # aproximação: custo_prev = sum(energia_prev_por_local * tarifa_local)
            # para simplificar, usa a mesma tarifa atual por local
            if local_id:
                lid = int(local_id)
                t = tarifas.get(lid, 0.0)
                # energia_prev por local selecionado
                eprev_local = c.execute("""
                    SELECT ROUND(COALESCE(SUM(m.diferenca),0),2)
                    FROM leituras_mensais m
                    JOIN locais l ON l.nome = m.local
                    WHERE m.mes = ? AND m.ano = ? AND l.id = ?
                """, [mes_prev, ano_prev, lid]).fetchone()[0] or 0.0
                custo_prev = round(float(eprev_local) * float(t), 2)
            else:
                # calcula energia_prev por local
                eprev_rows = c.execute("""
                    SELECT l.id, ROUND(COALESCE(SUM(m.diferenca),0),2)
                    FROM leituras_mensais m
                    JOIN locais l ON l.nome = m.local
                    WHERE m.mes = ? AND m.ano = ?
                    GROUP BY l.id
                """, [mes_prev, ano_prev]).fetchall()
                cprev = 0.0
                for lid, eprev in eprev_rows:
                    cprev += float(eprev or 0) * float(tarifas.get(lid, 0.0))
                custo_prev = round(cprev, 2)

        # deltas
        def _pct_delta(cur, prev):
            try:
                if prev == 0:
                    return None if cur == 0 else 100.0
                return (float(cur) - float(prev)) * 100.0 / float(prev)
            except Exception:
                return None

        delta_energia_pct = _pct_delta(energia_total, energia_prev)
        delta_custo_pct = _pct_delta(custo_total if custos_habilitados else None, custo_prev) if custos_habilitados else None

        kpis = {
            "energia_total": round(energia_total, 2),
            "ponta_max_global": round(ponta_max_global, 2),
            "locais_fp_baixo": locais_fp_baixo,
            "horas_motores_total": round(sum(x["horas_motores"] for x in cards), 2),
            "locais_cobertura_baixa": int(locais_cobertura_baixa),
            "custo_total": round(custo_total, 2) if custos_habilitados else 0,
            "custos_habilitados": custos_habilitados,
            "delta_energia_pct": delta_energia_pct,
            "delta_custo_pct": delta_custo_pct
        }

        return cards, kpis, rank, trend
    finally:
        conn.close()

@app.route('/dashboard')
def dashboard():
    _ensure_idx_dashboard()
    hoje = datetime.now()
    mes = (request.args.get('mes') or hoje.strftime('%m')).zfill(2)
    ano = int(request.args.get('ano') or hoje.year)
    local_id = request.args.get('local_id')

    cards, kpis, rank, trend = _agg_dashboard(mes, ano, local_id=local_id)
    locais = get_locais()
    return render_template('dashboard.html', cards=cards, kpis=kpis, rank=rank, trend=trend, locais=locais, mes=mes, ano=ano, local_id=local_id)

@app.route('/dashboard/export')
def dashboard_export():
    # export CSV com os agregados mostrados na tela
    hoje = datetime.now()
    mes = (request.args.get('mes') or hoje.strftime('%m')).zfill(2)
    ano = int(request.args.get('ano') or hoje.year)
    local_id = request.args.get('local_id')

    cards, kpis, rank, trend = _agg_dashboard(mes, ano, local_id=local_id)

    import csv
    from io import StringIO
    si = StringIO()
    w = csv.writer(si, delimiter=';')
    header = ["local_id","local","energia_kwh","fp_baixo_dias","ponta_max_kw","horas_motores_h","dias_com_dados","dias_mes","cobertura_pct","tarifa_kwh","custo_estimado_mzn"]
    w.writerow(header)
    for c in cards:
        w.writerow([
            c["local_id"], c["local"], c["energia_mes"], c["fp_baixo"], c["ponta_max"],
            c["horas_motores"], c["dias_com_dados"], c["dias_mes"], c["cobertura_pct"],
            ("" if c["tarifa_kwh"] is None else c["tarifa_kwh"]),
            ("" if c["custo_estimado"] is None else c["custo_estimado"]),
        ])
    output = si.getvalue().encode("utf-8-sig")
    return Response(output, mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=dashboard_{ano}-{mes}.csv"})# === LOCAIS ===

