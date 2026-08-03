"""Domínio dashboard_executive extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""

# === Fase 7B: Dashboard auditado, financeiro e executivo ===
def _dashboard_get_cfg_map():
    """Devolve configurações dos locais usadas no dashboard sem quebrar bases antigas."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    cfg = {}
    try:
        rows = c.execute("""
            SELECT l.id, l.nome,
                   COALESCE(lc.fator_mult, l.fator_multiplicativo, 1.0) AS fator_mult,
                   COALESCE(lc.pot_contratada, l.potencia_contratada, l.potencia_contratada_kva, 0.0) AS pot_contratada,
                   COALESCE(lc.tarifa_ativa, 4.78) AS tarifa_ativa,
                   COALESCE(lc.tarifa_reativa, 0) AS tarifa_reativa,
                   COALESCE(lc.tarifa_ponta, 497.03) AS tarifa_ponta,
                   COALESCE(lc.taxa_fixa, 0) AS taxa_fixa,
                   COALESCE(lc.taxa_radio, 0) AS taxa_radio,
                   COALESCE(lc.taxa_lixo, 0) AS taxa_lixo,
                   COALESCE(lc.iva, 16) AS iva
            FROM locais l
            LEFT JOIN locais_cfg lc ON lc.local_id = l.id
        """).fetchall()
        for r in rows:
            d = dict(r)
            if not d.get('tarifa_reativa') and d.get('tarifa_ativa'):
                d['tarifa_reativa'] = float(d.get('tarifa_ativa') or 0) * 0.30
            cfg[d['nome']] = d
    except Exception:
        pass
    finally:
        conn.close()
    return cfg


def _dashboard_month_finance(local_nome, mes, ano, cfg):
    """Calcula valores do dashboard usando a mesma filosofia da fatura EDM mensal."""
    try:
        ctx = _montar_contexto_fatura_mensal(local_nome, str(mes).zfill(2), int(ano))
        q = ctx['qfat']
    except Exception:
        q = {'kwh_ativa':0.0,'kvarh_reativa':0.0,'kvarh_excedente':0.0,'kw_ponta_lida':0.0,'agua_total':0.0,'consumo_especifico':None,'avisos':[]}
        tariffs = normalise_tariffs(cfg)
        bill = calculate_invoice(active_kwh=0, tariffs=tariffs)
        ctx = {
            'demanda_ponta_kw': bill['billing_demand_kw'], 'valor_ativa': bill['active_cost_mzn'],
            'valor_reativa': bill['reactive_cost_mzn'], 'valor_ponta': bill['demand_cost_mzn'],
            'subtotal': bill['subtotal_mzn'], 'valor_iva': bill['vat_mzn'], 'total': bill['total_mzn'],
            'tarifa_ativa': tariffs['tarifa_ativa'], 'tarifa_reativa': tariffs['tarifa_reativa'],
            'tarifa_ponta': tariffs['tarifa_ponta'],
        }
    return {
        'qfat': q,
        'ponta_faturavel': ctx['demanda_ponta_kw'],
        'valor_ativa': ctx['valor_ativa'],
        'valor_reativa': ctx['valor_reativa'],
        'valor_ponta': ctx['valor_ponta'],
        'subtotal': ctx['subtotal'],
        'valor_iva': ctx['valor_iva'],
        'total': ctx['total'],
        'tarifa_ativa': ctx['tarifa_ativa'],
        'tarifa_reativa': ctx['tarifa_reativa'],
        'tarifa_ponta': ctx['tarifa_ponta'],
    }


def _agg_dashboard(mes, ano, local_id=None):
    """
    Dashboard 7B: consolida leituras com a lógica da fatura mensal.
    Mantém a mesma assinatura usada pela rota /dashboard.
    """
    _ensure_idx_dashboard()
    cfg_map = _dashboard_get_cfg_map()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        params = []
        where = "WHERE COALESCE(l.ativo,1)=1"
        if local_id:
            where += " AND l.id=?"
            params.append(int(local_id))
        locais_rows = c.execute(f"SELECT id, nome FROM locais l {where} ORDER BY nome", params).fetchall()
        dias_mes = _dias_no_mes(mes, int(ano))
        cards = []
        energia_total = reativa_exc_total = fatura_total = ponta_faturavel_global = agua_total = 0.0
        locais_fp_baixo = locais_cobertura_baixa = locais_sem_base = 0
        fp_vals = []
        for lr in locais_rows:
            lid, lname = lr['id'], lr['nome']
            cfg = cfg_map.get(lname, {})
            fin = _dashboard_month_finance(lname, mes, ano, cfg)
            q = fin['qfat']
            kwh = float(q.get('kwh_ativa') or 0)
            rexc = float(q.get('kvarh_excedente') or 0)
            agua = float(q.get('agua_total') or 0)
            stat = c.execute("""
                SELECT COUNT(DISTINCT data) AS dias,
                       SUM(CASE WHEN fp IS NOT NULL AND fp>0 AND fp<0.80 THEN 1 ELSE 0 END) AS fp_baixo,
                       AVG(CASE WHEN fp IS NOT NULL AND fp>0 THEN fp ELSE NULL END) AS fp_medio,
                       MAX(CASE WHEN ponta IS NOT NULL THEN ponta ELSE 0 END) AS ponta_max
                FROM leituras_mensais
                WHERE local=? AND mes=? AND ano=?
            """, (lname, str(mes).zfill(2), int(ano))).fetchone()
            dias_com_dados = int((stat['dias'] if stat else 0) or 0)
            fp_baixo = int((stat['fp_baixo'] if stat else 0) or 0)
            fp_medio = float((stat['fp_medio'] if stat else 0) or 0)
            ponta_max = float(q.get('kw_ponta_lida') or (stat['ponta_max'] if stat else 0) or 0)
            if fp_medio:
                fp_vals.append(fp_medio)
            try:
                horas = c.execute("""
                    SELECT ROUND(COALESCE(SUM(r.duracao_min),0)/60.0,2)
                    FROM motor_runs r JOIN equipamentos e ON e.id=r.equipamento_id
                    WHERE e.local_id=? AND strftime('%m', r.start_time)=? AND strftime('%Y', r.start_time)=?
                """, (lid, str(mes).zfill(2), str(ano))).fetchone()[0] or 0
            except Exception:
                horas = 0
            cobertura_pct = round((dias_com_dados * 100.0 / dias_mes) if dias_mes else 0, 1)
            if cobertura_pct < 80:
                locais_cobertura_baixa += 1
            if fp_baixo > 0:
                locais_fp_baixo += 1
            if not q.get('tem_base_mes_anterior_ativa') and kwh > 0:
                locais_sem_base += 1
            status = 'Normal'
            if fp_baixo > 0 or rexc > 0 or cobertura_pct < 50:
                status = 'Crítico' if (fp_baixo > 3 or cobertura_pct < 40) else 'Atenção'
            cards.append({
                'local_id': lid,
                'local': lname,
                'energia_mes': round(kwh,2),
                'reativa_excedente': round(rexc,2),
                'ponta_max': round(ponta_max,2),
                'ponta_faturavel': round(fin['ponta_faturavel'],2),
                'fatura_estimativa': round(fin['total'],2),
                'valor_ativa': round(fin['valor_ativa'],2),
                'valor_reativa': round(fin['valor_reativa'],2),
                'valor_ponta': round(fin['valor_ponta'],2),
                'agua_total': round(agua,2),
                'consumo_especifico': q.get('consumo_especifico'),
                'fp_baixo': fp_baixo,
                'fp_medio': round(fp_medio,3) if fp_medio else None,
                'horas_motores': float(horas or 0),
                'dias_com_dados': dias_com_dados,
                'dias_mes': dias_mes,
                'cobertura_pct': cobertura_pct,
                'tarifa_kwh': fin['tarifa_ativa'],
                'custo_estimado': round(fin['total'],2),
                'status': status,
                'avisos': q.get('avisos', []),
            })
            energia_total += kwh
            reativa_exc_total += rexc
            fatura_total += fin['total']
            ponta_faturavel_global = max(ponta_faturavel_global, fin['ponta_faturavel'])
            agua_total += agua
        cards = sorted(cards, key=lambda x: x['energia_mes'], reverse=True)
        top = cards[:8]
        rank = {'labels':[x['local'] for x in top], 'data':[x['energia_mes'] for x in top]}
        params_daily = [str(mes).zfill(2), int(ano)]
        where_daily = ''
        if local_id:
            where_daily = ' AND l.id=?'
            params_daily.append(int(local_id))
        daily = c.execute(f"""
            SELECT m.data, ROUND(COALESCE(SUM(CASE WHEN m.diferenca>0 THEN m.diferenca ELSE 0 END),0),2) AS kwh
            FROM leituras_mensais m JOIN locais l ON l.nome=m.local
            WHERE m.mes=? AND m.ano=? {where_daily}
            GROUP BY m.data ORDER BY m.data
        """, params_daily).fetchall()
        trend = {'labels':[r['data'] for r in daily], 'data':[float(r['kwh'] or 0) for r in daily]}
        pm, py = _prev_month(str(mes).zfill(2), int(ano))
        prev_total = 0.0
        for lr in locais_rows:
            cfg = cfg_map.get(lr['nome'], {})
            try:
                prev_total += _dashboard_month_finance(lr['nome'], pm, py, cfg)['qfat'].get('kwh_ativa',0) or 0
            except Exception:
                pass
        def _pct_delta(curr, prev):
            try:
                curr=float(curr or 0); prev=float(prev or 0)
                if prev == 0:
                    return None
                return round(((curr-prev)/prev)*100, 1)
            except Exception:
                return None
        fp_medio_global = round(sum(fp_vals)/len(fp_vals),3) if fp_vals else None
        kpis = {
            'energia_total': round(energia_total,2),
            'reativa_excedente_total': round(reativa_exc_total,2),
            'ponta_max_global': round(ponta_faturavel_global,2),
            'ponta_faturavel_global': round(ponta_faturavel_global,2),
            'locais_fp_baixo': locais_fp_baixo,
            'horas_motores_total': round(sum(x['horas_motores'] for x in cards),2),
            'locais_cobertura_baixa': int(locais_cobertura_baixa),
            'custo_total': round(fatura_total,2),
            'fatura_total': round(fatura_total,2),
            'custos_habilitados': True,
            'delta_energia_pct': _pct_delta(energia_total, prev_total),
            'delta_custo_pct': None,
            'fp_medio_global': fp_medio_global,
            'agua_total': round(agua_total,2),
            'consumo_especifico_global': round(energia_total/agua_total,4) if agua_total else None,
            'locais_sem_base': locais_sem_base,
            'estado_geral': 'Crítico' if (locais_fp_baixo>0 or reativa_exc_total>0) else ('Atenção' if locais_cobertura_baixa>0 else 'Normal'),
        }
        return cards, kpis, rank, trend
    finally:
        conn.close()


@app.route('/dashboard/api')
def dashboard_api():
    hoje = datetime.now()
    mes = (request.args.get('mes') or hoje.strftime('%m')).zfill(2)
    ano = int(request.args.get('ano') or hoje.year)
    local_id = request.args.get('local_id')
    cards, kpis, rank, trend = _agg_dashboard(mes, ano, local_id=local_id)
    return jsonify({'mes': mes, 'ano': ano, 'local_id': local_id, 'kpis': kpis, 'cards': cards, 'rank': rank, 'trend': trend})


@app.route('/dashboard/relatorio')
def dashboard_relatorio():
    hoje = datetime.now()
    mes = (request.args.get('mes') or hoje.strftime('%m')).zfill(2)
    ano = int(request.args.get('ano') or hoje.year)
    local_id = request.args.get('local_id')
    cards, kpis, rank, trend = _agg_dashboard(mes, ano, local_id=local_id)
    locais = get_locais()
    return render_template('dashboard_relatorio.html', cards=cards, kpis=kpis, rank=rank, trend=trend, locais=locais, mes=mes, ano=ano, local_id=local_id)


# === Fase 7C: Dashboard final - score executivo, ações prioritárias e exportação estruturada ===
def _dashboard_score_e_acoes(cards, kpis):
    """Cria score executivo e plano de ações a partir dos dados já agregados do dashboard."""
    score = 100
    acoes = []
    def add(nivel, titulo, origem, impacto, acao, link, local=None, score_penalty=0):
        nonlocal score
        score -= score_penalty
        acoes.append({
            'nivel': nivel,
            'titulo': titulo,
            'origem': origem,
            'local': local or 'Geral',
            'impacto': impacto,
            'acao': acao,
            'link': link,
            'prioridade': {'Crítico': 100, 'Atenção': 70, 'Informativo': 35}.get(nivel, 50) + score_penalty
        })
    if (kpis.get('locais_sem_base') or 0) > 0:
        add('Atenção','Validar base do mês anterior','Leituras Mensais','Pode distorcer energia faturável e comparação mensal.','Confirmar última leitura válida do mês anterior e recalcular o período.','/leituras_mensal/arquivo', score_penalty=10)
    if (kpis.get('locais_cobertura_baixa') or 0) > 0:
        add('Atenção','Completar leituras em falta','Qualidade de Dados','A baixa cobertura reduz a confiança dos indicadores executivos.','Preencher dias em falta ou justificar ausência de dados.','/leituras_mensal/arquivo', score_penalty=12)
    if (kpis.get('reativa_excedente_total') or 0) > 0:
        add('Crítico','Reativa excedente no período','Faturação / FP','Aumenta o custo da fatura e indica baixo fator de potência.','Avaliar compensação reativa e regime de operação dos motores.','/alertas', score_penalty=15)
    if (kpis.get('locais_fp_baixo') or 0) > 0:
        add('Crítico','Locais com fator de potência baixo','Qualidade de Energia','Pode gerar penalização por reativa e perda de eficiência.','Abrir ação correctiva e analisar banco de capacitores/motores.','/alertas', score_penalty=15)
    delta = kpis.get('delta_energia_pct')
    if delta is not None and abs(float(delta or 0)) >= 20:
        add('Atenção','Variação anormal de consumo','Consumo Mensal','A energia mudou mais de 20% face ao mês anterior.','Comparar operação, bombas em serviço, caudais e leituras base.','/dashboard/relatorio', score_penalty=8)
    # ações por local
    for c in cards[:12]:
        loc = c.get('local')
        if (c.get('reativa_excedente') or 0) > 0 or (c.get('fp_baixo') or 0) > 0:
            add('Crítico','Corrigir FP / reativa excedente','Local crítico','Há impacto técnico e financeiro por baixo FP ou reativa excedente.','Inspecionar cargas indutivas, motores e compensação reativa.', c.get('link') or '/alertas', local=loc, score_penalty=5)
        if (c.get('cobertura_pct') or 0) < 80:
            add('Atenção','Melhorar cobertura de leituras','Dados do local','Dados incompletos reduzem a precisão da fatura e dos KPIs.', 'Completar planilha mensal e validar dados do operador.', c.get('link') or '/leituras_mensal', local=loc, score_penalty=4)
        if (c.get('status') or '').lower().startswith('cr'):
            add('Crítico','Local em estado crítico','Dashboard', 'O local concentra anomalias relevantes no período.', 'Abrir investigação técnica e definir responsável.', '/alertas', local=loc, score_penalty=5)
    if not acoes:
        add('Informativo','Manter rotina de acompanhamento','Gestão','Não foram detectados desvios críticos no período.','Manter preenchimento diário, validar faturas e monitorar tendências.','/monitoria', score_penalty=0)
    score = max(0, min(100, int(round(score))))
    acoes = sorted(acoes, key=lambda x: x.get('prioridade',0), reverse=True)
    return score, acoes[:30]

# Reforça a função de agregação existente sem alterar a assinatura usada pelas rotas anteriores.
_dashboard_agg_base_7c = _agg_dashboard
def _agg_dashboard(mes, ano, local_id=None):
    cards, kpis, rank, trend = _dashboard_agg_base_7c(mes, ano, local_id=local_id)
    score, acoes = _dashboard_score_e_acoes(cards, kpis)
    kpis['score_executivo'] = score
    kpis['acoes_prioritarias'] = acoes
    kpis['total_acoes_prioritarias'] = len(acoes)
    kpis['estado_geral'] = 'Crítico' if score < 60 else ('Atenção' if score < 82 else (kpis.get('estado_geral') or 'Normal'))
    return cards, kpis, rank, trend

@app.route('/dashboard/acoes')
def dashboard_acoes():
    hoje = datetime.now()
    mes = (request.args.get('mes') or hoje.strftime('%m')).zfill(2)
    ano = int(request.args.get('ano') or hoje.year)
    local_id = request.args.get('local_id')
    cards, kpis, rank, trend = _agg_dashboard(mes, ano, local_id=local_id)
    locais = get_locais()
    return render_template('dashboard_acoes.html', cards=cards, kpis=kpis, rank=rank, trend=trend, locais=locais, mes=mes, ano=ano, local_id=local_id, acoes=kpis.get('acoes_prioritarias', []))

@app.route('/dashboard/export.json')
def dashboard_export_json():
    hoje = datetime.now()
    mes = (request.args.get('mes') or hoje.strftime('%m')).zfill(2)
    ano = int(request.args.get('ano') or hoje.year)
    local_id = request.args.get('local_id')
    cards, kpis, rank, trend = _agg_dashboard(mes, ano, local_id=local_id)
    payload = {'periodo': {'mes': mes, 'ano': ano, 'local_id': local_id}, 'kpis': kpis, 'locais': cards, 'ranking': rank, 'tendencia': trend}
    return Response(json.dumps(payload, ensure_ascii=False, indent=2), mimetype='application/json', headers={'Content-Disposition': f'attachment; filename=dashboard_{ano}_{mes}.json'})


