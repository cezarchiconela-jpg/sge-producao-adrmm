"""Domínio daily_readings_core extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""

@app.route('/leituras/local/<int:local_id>')
def leituras_por_local(local_id):
    local = get_local_by_id(local_id)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('''
        SELECT * FROM leituras WHERE local=?
        ORDER BY datahora
    ''', (local[1],))
    leituras = c.fetchall()
    conn.close()
    return render_template('leituras_local.html', local=local, leituras=leituras)

# === LEITURA DIÁRIA ===

@app.route('/add', methods=['GET', 'POST'])
@app.route('/monitoria/nova', methods=['GET', 'POST'])
def add():
    """Nova leitura operacional diária.
    Este registo é técnico/pontual e não substitui a planilha mensal de faturação.
    """
    def _calc_aparente(a, b):
        try:
            a = float(a or 0); b = float(b or 0)
            return math.sqrt(a*a + b*b) if (a or b) else 0.0
        except Exception:
            return 0.0

    def _calc_fp(ativa, reativa, pot_ativa, pot_reativa, aparente, pot_aparente):
        try:
            if aparente and float(aparente) > 0 and ativa:
                return max(0.0, min(1.0, float(ativa) / float(aparente)))
            if pot_aparente and float(pot_aparente) > 0 and pot_ativa:
                return max(0.0, min(1.0, float(pot_ativa) / float(pot_aparente)))
            base = _calc_aparente(ativa, reativa)
            if base > 0 and ativa:
                return max(0.0, min(1.0, float(ativa or 0) / base))
            basep = _calc_aparente(pot_ativa, pot_reativa)
            if basep > 0 and pot_ativa:
                return max(0.0, min(1.0, float(pot_ativa or 0) / basep))
        except Exception:
            pass
        return 0.0

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute('''SELECT l.id, l.nome, COALESCE(cfg.fator_mult,1.0), COALESCE(cfg.pot_contratada,0.0), COALESCE(cfg.pot_instalada,0.0)
                     FROM locais l LEFT JOIN locais_cfg cfg ON cfg.local_id=l.id
                     WHERE COALESCE(l.ativo,1)=1
                     ORDER BY l.nome COLLATE NOCASE''')
        locais = [{'id': r[0], 'nome': r[1], 'fator_mult': float(r[2] or 1), 'pot_contratada': float(r[3] or 0), 'pot_instalada': float(r[4] or 0)} for r in c.fetchall()]
        c.execute('''SELECT e.id, e.nome, COALESCE(e.tag,''), COALESCE(e.local_id,0), COALESCE(l.nome,'')
                     FROM equipamentos e LEFT JOIN locais l ON l.id=e.local_id
                     ORDER BY e.nome COLLATE NOCASE''')
        equipamentos = [{'id': r[0], 'nome': r[1], 'tag': r[2], 'local_id': int(r[3] or 0), 'local_nome': r[4]} for r in c.fetchall()]
    finally:
        conn.close()

    if request.method == 'POST':
        datahora = request.form.get('datahora') or datetime.now().strftime('%Y-%m-%dT%H:%M')
        local = (request.form.get('local') or '').strip()
        equipamento = (request.form.get('equipamento') or '').strip()
        energia_ativa = _to_float(request.form.get('energia_ativa'))
        energia_reativa = _to_float(request.form.get('energia_reativa'))
        energia_aparente = _to_float(request.form.get('energia_aparente'))
        pot_ativa = _to_float(request.form.get('pot_ativa'))
        pot_reativa = _to_float(request.form.get('pot_reativa'))
        pot_aparente = _to_float(request.form.get('pot_aparente'))
        fp = _to_float(request.form.get('fp'))
        ponta = _to_float(request.form.get('ponta'))
        caudal_elevada = _to_float(request.form.get('caudal_elevada'))
        corrente = _to_float(request.form.get('corrente'))
        tensao = _to_float(request.form.get('tensao'))
        observacoes = (request.form.get('observacoes') or '').strip()

        if energia_aparente <= 0 and (energia_ativa > 0 or energia_reativa > 0):
            energia_aparente = _calc_aparente(energia_ativa, energia_reativa)
        if pot_aparente <= 0 and (pot_ativa > 0 or pot_reativa > 0):
            pot_aparente = _calc_aparente(pot_ativa, pot_reativa)
        if fp <= 0:
            fp = _calc_fp(energia_ativa, energia_reativa, pot_ativa, pot_reativa, energia_aparente, pot_aparente)

        avisos = []
        if fp and fp < 0.85:
            avisos.append(f'FP baixo: {fp:.3f}')
        if tensao and (tensao < 360 or tensao > 440):
            avisos.append(f'Tensão fora da faixa 360–440 V: {tensao:.1f} V')
        if corrente <= 0 and pot_ativa <= 0 and energia_ativa <= 0:
            avisos.append('Registo sem corrente, potência ou energia ativa informada')
        if avisos:
            observacoes = (observacoes + ' | ' if observacoes else '') + 'ALERTA OPERACIONAL: ' + '; '.join(avisos)

        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('''
            INSERT INTO leituras (datahora, local, equipamento, energia_ativa, energia_reativa, energia_aparente,
                                  pot_ativa, pot_reativa, pot_aparente, fp, ponta, caudal_elevada,
                                  corrente, tensao, observacoes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (datahora, local, equipamento, energia_ativa, energia_reativa, energia_aparente,
              pot_ativa, pot_reativa, pot_aparente, fp, ponta, caudal_elevada,
              corrente, tensao, observacoes))
        conn.commit(); conn.close()

        if request.form.get('continuar') == '1':
            return redirect(url_for('add', local=local, equipamento=equipamento))
        return redirect(url_for('leituras_list', local=local, inicio=datahora[:10], fim=datahora[:10]))

    now = datetime.now().strftime('%Y-%m-%dT%H:%M')
    selected_local = request.args.get('local','')
    selected_equipamento = request.args.get('equipamento','')
    return render_template('add.html', locais=locais, equipamentos=equipamentos, now=now, selected_local=selected_local, selected_equipamento=selected_equipamento)



# === LEITURAS DIÁRIAS — LISTAGEM/FILTER/CRUD/EXPORT/IMPORT/GRÁFICO ===



@app.route('/leituras', methods=['GET'])
@app.route('/monitoria', methods=['GET'])
def leituras_list():
    """Monitoria operacional diária: leituras pontuais por local/equipamento, KPIs, alertas e gráficos."""
    end = request.args.get('fim') or datetime.now().strftime('%Y-%m-%d')
    start = request.args.get('inicio') or (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d')
    local = request.args.get('local','').strip()
    equipamento = request.args.get('equipamento','').strip()
    q = request.args.get('q','').strip()

    try:
        page = int(request.args.get('page', 1))
        if page < 1: page = 1
    except Exception:
        page = 1
    try:
        per = int(request.args.get('per', 50))
        if per < 10: per = 10
        if per > 200: per = 200
    except Exception:
        per = 50
    offset = (page - 1) * per

    base_sql = " FROM leituras WHERE date(datahora) BETWEEN ? AND ?"
    params = [start, end]
    if local:
        base_sql += " AND local = ?"
        params.append(local)
    if equipamento:
        base_sql += " AND equipamento = ?"
        params.append(equipamento)
    if q:
        base_sql += " AND (equipamento LIKE ? OR observacoes LIKE ? OR local LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()

    total_rows = c.execute("SELECT COUNT(*)" + base_sql, params).fetchone()[0]
    tot = c.execute("""SELECT COALESCE(SUM(energia_ativa),0), COALESCE(AVG(pot_ativa),0),
                            COALESCE(MAX(ponta),0), COALESCE(AVG(fp),0), COALESCE(SUM(caudal_elevada),0),
                            COALESCE(AVG(tensao),0), COALESCE(MAX(corrente),0)
                     """ + base_sql, params).fetchone()
    total_ativa = float(tot[0] or 0)
    media_pot_ativa = float(tot[1] or 0)
    max_ponta = float(tot[2] or 0)
    fp_medio = float(tot[3] or 0)
    agua_total = float(tot[4] or 0)
    tensao_media = float(tot[5] or 0)
    corrente_max = float(tot[6] or 0)
    consumo_especifico = (total_ativa / agua_total) if agua_total > 0 else 0.0

    resumo = c.execute("""SELECT local, COALESCE(SUM(energia_ativa),0) kwh, COALESCE(AVG(pot_ativa),0) avgkw,
                               COALESCE(MAX(ponta),0) maxp, COALESCE(AVG(fp),0) avgfp, COALESCE(SUM(caudal_elevada),0) agua
                        """ + base_sql + " GROUP BY local ORDER BY kwh DESC", params).fetchall()

    resumo_equip = c.execute("""SELECT equipamento, local, COUNT(*) n, COALESCE(SUM(energia_ativa),0) kwh,
                                      COALESCE(AVG(pot_ativa),0) avgkw, COALESCE(AVG(fp),0) avgfp,
                                      COALESCE(MAX(corrente),0) imax
                               """ + base_sql + " GROUP BY equipamento, local ORDER BY kwh DESC LIMIT 15", params).fetchall()

    rows = c.execute("SELECT *" + base_sql + " ORDER BY datahora DESC LIMIT ? OFFSET ?", params + [per, offset]).fetchall()
    chart_rows = c.execute("""SELECT datahora, COALESCE(energia_ativa,0), COALESCE(pot_ativa,0), COALESCE(fp,0),
                                   COALESCE(ponta,0), COALESCE(caudal_elevada,0), COALESCE(corrente,0), COALESCE(tensao,0)
                            """ + base_sql + " ORDER BY datahora ASC LIMIT 500", params).fetchall()
    locais_opts = [r[0] for r in c.execute("SELECT DISTINCT nome FROM locais WHERE nome IS NOT NULL AND TRIM(nome)<>'' ORDER BY nome").fetchall()]
    # inclui locais que existam apenas nas leituras antigas
    for r in c.execute("SELECT DISTINCT local FROM leituras WHERE local IS NOT NULL AND TRIM(local)<>'' ORDER BY local").fetchall():
        if r[0] not in locais_opts:
            locais_opts.append(r[0])
    equipamentos_opts = [r[0] for r in c.execute("SELECT DISTINCT equipamento FROM leituras WHERE equipamento IS NOT NULL AND TRIM(equipamento)<>'' ORDER BY equipamento").fetchall()]
    local_config = None
    if local:
        hierarchy_lookup = {r['full_name']: r['nome'] for r in get_locais_hierarchy(include_inactive=True)}
        local_db_name = hierarchy_lookup.get(local, local)
        local_config = c.execute("""SELECT nome, COALESCE(potencia_contratada_kva,potencia_contratada,0),
                                         COALESCE(fator_multiplicativo,1), COALESCE(potencia_instalada_kw,0),
                                         COALESCE(estado_tecnico,''), COALESCE(prioridade,'')
                                  FROM locais WHERE nome=? LIMIT 1""", (local_db_name,)).fetchone()
    conn.close()

    # Anomalias simples e operacionais
    vals = [float(r[4] or 0) for r in rows]
    deltas = [abs(vals[i]-vals[i+1]) for i in range(len(vals)-1)] if len(vals)>1 else []
    med = sorted(deltas)[len(deltas)//2] if deltas else 0.0
    thr = max(3*(med or 0), 0)
    anomalias = set()
    for i in range(len(rows)-1):
        if deltas and deltas[i] > thr and thr>0:
            anomalias.add(rows[i][0]); anomalias.add(rows[i+1][0])
    low_fp_count = sum(1 for r in rows if (r[10] is not None and float(r[10] or 0) < 0.85 and float(r[10] or 0) > 0))
    tensao_alert_count = sum(1 for r in rows if (r[14] is not None and (float(r[14] or 0) < 360 or float(r[14] or 0) > 440)))
    corrente_alert_count = sum(1 for r in rows if (r[13] is not None and float(r[13] or 0) > 0 and float(r[13] or 0) == corrente_max and corrente_max > 0))

    grafico = {
        'horas': [r[0] for r in chart_rows],
        'ativa': [float(r[1] or 0) for r in chart_rows],
        'pot_ativa': [float(r[2] or 0) for r in chart_rows],
        'fp': [float(r[3] or 0) for r in chart_rows],
        'ponta': [float(r[4] or 0) for r in chart_rows],
        'agua': [float(r[5] or 0) for r in chart_rows],
        'corrente': [float(r[6] or 0) for r in chart_rows],
        'tensao': [float(r[7] or 0) for r in chart_rows],
    }

    total_pages = max(1, (total_rows + per - 1) // per)

    return render_template('leituras_list.html',
                           leituras=rows,
                           inicio=start, fim=end, local=local, equipamento=equipamento, q=q,
                           grafico=grafico, grafico_horas=grafico['horas'], grafico_ativa=grafico['ativa'],
                           page=page, total_pages=total_pages, per=per,
                           total_ativa=total_ativa, media_pot_ativa=media_pot_ativa, max_ponta=max_ponta,
                           fp_medio=fp_medio, agua_total=agua_total, consumo_especifico=consumo_especifico,
                           tensao_media=tensao_media, corrente_max=corrente_max,
                           low_fp_count=low_fp_count, tensao_alert_count=tensao_alert_count,
                           corrente_alert_count=corrente_alert_count,
                           anomalias=list(anomalias), resumo=resumo, resumo_equip=resumo_equip,
                           locais_opts=locais_opts, equipamentos_opts=equipamentos_opts,
                           local_config=local_config)



@app.route('/monitoria/controlo', methods=['GET'])
def monitoria_controlo():
    """Painel de controlo da monitoria operacional: criticidade, anomalias priorizadas e plano de ação."""
    end = request.args.get('fim') or datetime.now().strftime('%Y-%m-%d')
    start = request.args.get('inicio') or (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d')
    local = request.args.get('local','').strip()
    equipamento = request.args.get('equipamento','').strip()
    q = request.args.get('q','').strip()

    base_sql = " FROM leituras WHERE date(datahora) BETWEEN ? AND ?"
    params = [start, end]
    if local:
        base_sql += " AND local = ?"
        params.append(local)
    if equipamento:
        base_sql += " AND equipamento = ?"
        params.append(equipamento)
    if q:
        base_sql += " AND (equipamento LIKE ? OR observacoes LIKE ? OR local LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    rows = c.execute("""SELECT id, datahora, local, equipamento, COALESCE(energia_ativa,0), COALESCE(energia_reativa,0),
                             COALESCE(energia_aparente,0), COALESCE(pot_ativa,0), COALESCE(pot_reativa,0),
                             COALESCE(pot_aparente,0), COALESCE(fp,0), COALESCE(ponta,0), COALESCE(caudal_elevada,0),
                             COALESCE(corrente,0), COALESCE(tensao,0), COALESCE(observacoes,'')
                      """ + base_sql + " ORDER BY datahora DESC LIMIT 2000", params).fetchall()
    locais_opts = [r[0] for r in c.execute("SELECT DISTINCT nome FROM locais WHERE nome IS NOT NULL AND TRIM(nome)<>'' ORDER BY nome").fetchall()]
    for r in c.execute("SELECT DISTINCT local FROM leituras WHERE local IS NOT NULL AND TRIM(local)<>'' ORDER BY local").fetchall():
        if r[0] not in locais_opts:
            locais_opts.append(r[0])
    equipamentos_opts = [r[0] for r in c.execute("SELECT DISTINCT equipamento FROM leituras WHERE equipamento IS NOT NULL AND TRIM(equipamento)<>'' ORDER BY equipamento").fetchall()]
    conn.close()

    total_registos = len(rows)
    total_kwh = sum(float(r[4] or 0) for r in rows)
    agua_total = sum(float(r[12] or 0) for r in rows)
    fp_vals = [float(r[10] or 0) for r in rows if float(r[10] or 0) > 0]
    tensao_vals = [float(r[14] or 0) for r in rows if float(r[14] or 0) > 0]
    corrente_vals = [float(r[13] or 0) for r in rows if float(r[13] or 0) > 0]
    fp_medio = sum(fp_vals)/len(fp_vals) if fp_vals else 0.0
    tensao_media = sum(tensao_vals)/len(tensao_vals) if tensao_vals else 0.0
    corrente_media = sum(corrente_vals)/len(corrente_vals) if corrente_vals else 0.0
    corrente_max = max(corrente_vals) if corrente_vals else 0.0
    max_ponta = max([float(r[11] or 0) for r in rows] or [0])
    consumo_especifico = (total_kwh / agua_total) if agua_total > 0 else 0.0

    # médias por equipamento para detectar desvios relativos
    eq_stats = {}
    for r in rows:
        key = (r[3] or 'Sem equipamento', r[2] or 'Sem local')
        st = eq_stats.setdefault(key, {'n':0,'kwh':0.0,'kw':0.0,'fp_sum':0.0,'fp_n':0,'corr_sum':0.0,'corr_n':0,'corr_max':0.0,'ponta':0.0,'agua':0.0,'alertas':0,'criticos':0})
        st['n'] += 1
        st['kwh'] += float(r[4] or 0)
        st['kw'] += float(r[7] or 0)
        fp = float(r[10] or 0); corr = float(r[13] or 0)
        if fp > 0: st['fp_sum'] += fp; st['fp_n'] += 1
        if corr > 0: st['corr_sum'] += corr; st['corr_n'] += 1; st['corr_max'] = max(st['corr_max'], corr)
        st['ponta'] = max(st['ponta'], float(r[11] or 0))
        st['agua'] += float(r[12] or 0)

    alertas = []
    def add_alerta(nivel, tipo, r, valor, impacto, acao):
        peso = 3 if nivel == 'Crítico' else 2 if nivel == 'Atenção' else 1
        alertas.append({'nivel':nivel, 'tipo':tipo, 'datahora':r[1], 'local':r[2] or '—', 'equipamento':r[3] or '—', 'valor':valor, 'impacto':impacto, 'acao':acao, 'peso':peso})
        key = (r[3] or 'Sem equipamento', r[2] or 'Sem local')
        if key in eq_stats:
            eq_stats[key]['alertas'] += 1
            if nivel == 'Crítico': eq_stats[key]['criticos'] += 1

    # Consumo específico por linha e referência do período
    ce_vals = []
    for r in rows:
        agua = float(r[12] or 0); kwh = float(r[4] or 0)
        if agua > 0 and kwh > 0:
            ce_vals.append(kwh/agua)
    ce_ref = (sum(ce_vals)/len(ce_vals)) if ce_vals else 0.0
    ponta_vals = [float(r[11] or 0) for r in rows if float(r[11] or 0)>0]
    ponta_ref = (sum(ponta_vals)/len(ponta_vals)) if ponta_vals else 0.0

    for r in rows:
        fp = float(r[10] or 0); tensao = float(r[14] or 0); corrente = float(r[13] or 0)
        ponta = float(r[11] or 0); kwh = float(r[4] or 0); agua = float(r[12] or 0)
        if 0 < fp < 0.75:
            add_alerta('Crítico','Fator de potência muito baixo',r,f'{fp:.3f}','Maior probabilidade de energia reativa excedente e perdas.','Inspecionar cargas, banco de capacitores, regime de operação e compensação reativa.')
        elif 0.75 <= fp < 0.85:
            add_alerta('Atenção','Fator de potência baixo',r,f'{fp:.3f}','Risco operacional e potencial penalização por reativa.','Acompanhar repetição do evento e avaliar necessidade de correção do FP.')
        if tensao > 0 and (tensao < 360 or tensao > 440):
            nivel = 'Crítico' if tensao < 340 or tensao > 460 else 'Atenção'
            add_alerta(nivel,'Tensão fora da faixa',r,f'{tensao:.1f} V','Pode causar aquecimento, disparos, baixo rendimento ou falha de equipamento.','Confirmar medição por fase, quedas de tensão, ligações e estado do transformador/quadro.')
        if corrente_media > 0 and corrente > 1.35 * corrente_media:
            add_alerta('Atenção','Corrente acima do padrão do período',r,f'{corrente:.1f} A','Possível sobrecarga, desequilíbrio ou alteração de regime.','Comparar com corrente nominal do equipamento e verificar carga mecânica/elétrica.')
        if ponta_ref > 0 and ponta > 1.25 * ponta_ref:
            add_alerta('Atenção','Ponta acima do padrão',r,f'{ponta:.2f} kW','Pode aumentar a procura máxima operacional e afetar custo mensal.','Verificar arranque simultâneo de cargas e possibilidade de escalonamento operacional.')
        if agua > 0 and ce_ref > 0 and (kwh/agua) > 1.30 * ce_ref:
            add_alerta('Atenção','Consumo específico acima do padrão',r,f'{(kwh/agua):.3f} kWh/m³','Indica possível perda de eficiência, queda de caudal ou operação fora do ponto ótimo.','Comparar caudal, pressão, válvulas, filtros e rendimento do conjunto motor-bomba.')
        if not (r[2] or '').strip() or not (r[3] or '').strip():
            add_alerta('Informativo','Registo incompleto',r,'Local/equipamento em falta','Reduz a qualidade da análise histórica.','Completar local e equipamento para melhorar rastreabilidade.')

    alertas.sort(key=lambda a: (-a['peso'], a['datahora'] or ''))
    criticos = sum(1 for a in alertas if a['nivel'] == 'Crítico')
    atencao = sum(1 for a in alertas if a['nivel'] == 'Atenção')
    informativos = sum(1 for a in alertas if a['nivel'] == 'Informativo')
    if criticos:
        estado = 'Crítico'; estado_classe = 'danger'; resumo_estado = 'Existem ocorrências críticas que exigem validação técnica antes de concluir o período.'
    elif atencao:
        estado = 'Atenção'; estado_classe = 'warn'; resumo_estado = 'Existem desvios operacionais que devem ser acompanhados e corrigidos.'
    elif total_registos:
        estado = 'Normal'; estado_classe = 'ok'; resumo_estado = 'Sem anomalias relevantes detectadas no intervalo filtrado.'
    else:
        estado = 'Sem dados'; estado_classe = 'info'; resumo_estado = 'Não existem leituras para o intervalo selecionado.'

    ranking = []
    for (eq, loc), st in eq_stats.items():
        avg_fp = st['fp_sum']/st['fp_n'] if st['fp_n'] else 0.0
        avg_kw = st['kw']/st['n'] if st['n'] else 0.0
        ce = st['kwh']/st['agua'] if st['agua'] > 0 else 0.0
        score = st['criticos']*3 + (st['alertas']-st['criticos'])*1
        ranking.append({'equipamento':eq, 'local':loc, 'n':st['n'], 'kwh':st['kwh'], 'avg_kw':avg_kw, 'avg_fp':avg_fp, 'imax':st['corr_max'], 'ponta':st['ponta'], 'agua':st['agua'], 'ce':ce, 'alertas':st['alertas'], 'criticos':st['criticos'], 'score':score})
    ranking.sort(key=lambda x: (-x['score'], -x['kwh']))

    plano = []
    if criticos:
        plano.append('Validar imediatamente as leituras críticas antes de usar estes dados em relatórios de desempenho.')
    if any(a['tipo'].startswith('Fator') for a in alertas):
        plano.append('Criar rotina de verificação do fator de potência por equipamento/local e cruzar com a fatura mensal de reativa excedente.')
    if any(a['tipo'].startswith('Tensão') for a in alertas):
        plano.append('Confirmar tensões por fase e avaliar quedas de tensão, transformador, cabos, barramentos e ligações.')
    if any(a['tipo'].startswith('Corrente') for a in alertas):
        plano.append('Comparar correntes medidas com corrente nominal e histórico do equipamento para identificar sobrecarga ou desequilíbrio.')
    if any('Consumo específico' in a['tipo'] for a in alertas):
        plano.append('Investigar causas hidráulicas/operacionais para consumo específico elevado, incluindo caudal, pressão, válvulas e ponto de operação da bomba.')
    if not plano:
        plano.append('Manter a monitoria diária e comparar tendências por local/equipamento semanalmente.')

    return render_template('monitoria_controle.html',
                           inicio=start, fim=end, local=local, equipamento=equipamento, q=q,
                           locais_opts=locais_opts, equipamentos_opts=equipamentos_opts,
                           total_registos=total_registos, total_kwh=total_kwh, agua_total=agua_total,
                           fp_medio=fp_medio, tensao_media=tensao_media, corrente_media=corrente_media,
                           corrente_max=corrente_max, max_ponta=max_ponta, consumo_especifico=consumo_especifico,
                           estado=estado, estado_classe=estado_classe, resumo_estado=resumo_estado,
                           criticos=criticos, atencao=atencao, informativos=informativos,
                           alertas=alertas[:80], alertas_total=len(alertas), ranking=ranking[:25], plano=plano)

@app.route('/monitoria/relatorio', methods=['GET'])
def monitoria_relatorio():
    """Relatório técnico-operacional da monitoria diária para impressão/análise."""
    end = request.args.get('fim') or datetime.now().strftime('%Y-%m-%d')
    start = request.args.get('inicio') or (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d')
    local = request.args.get('local','').strip()
    equipamento = request.args.get('equipamento','').strip()
    q = request.args.get('q','').strip()

    base_sql = " FROM leituras WHERE date(datahora) BETWEEN ? AND ?"
    params = [start, end]
    if local:
        base_sql += " AND local = ?"
        params.append(local)
    if equipamento:
        base_sql += " AND equipamento = ?"
        params.append(equipamento)
    if q:
        base_sql += " AND (equipamento LIKE ? OR observacoes LIKE ? OR local LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    rows = c.execute("""SELECT id, datahora, local, equipamento, COALESCE(energia_ativa,0), COALESCE(energia_reativa,0),
                             COALESCE(pot_ativa,0), COALESCE(pot_reativa,0), COALESCE(fp,0), COALESCE(ponta,0),
                             COALESCE(caudal_elevada,0), COALESCE(corrente,0), COALESCE(tensao,0), COALESCE(observacoes,'')
                      """ + base_sql + " ORDER BY datahora ASC", params).fetchall()
    resumo_equip = c.execute("""SELECT COALESCE(equipamento,'Sem equipamento') equipamento, COALESCE(local,'Sem local') local, COUNT(*) n,
                                      COALESCE(SUM(energia_ativa),0) kwh, COALESCE(AVG(pot_ativa),0) avgkw,
                                      COALESCE(MAX(ponta),0) maxponta, COALESCE(AVG(fp),0) avgfp,
                                      COALESCE(MAX(corrente),0) imax, COALESCE(AVG(tensao),0) vmed,
                                      COALESCE(SUM(caudal_elevada),0) agua
                               """ + base_sql + " GROUP BY equipamento, local ORDER BY kwh DESC LIMIT 20", params).fetchall()
    resumo_local = c.execute("""SELECT COALESCE(local,'Sem local') local, COUNT(*) n, COALESCE(SUM(energia_ativa),0) kwh,
                                     COALESCE(AVG(pot_ativa),0) avgkw, COALESCE(MAX(ponta),0) maxponta,
                                     COALESCE(AVG(fp),0) avgfp, COALESCE(SUM(caudal_elevada),0) agua
                              """ + base_sql + " GROUP BY local ORDER BY kwh DESC", params).fetchall()
    local_config = None
    if local:
        local_config = c.execute("""SELECT nome, COALESCE(potencia_contratada_kva,potencia_contratada,0),
                                         COALESCE(fator_multiplicativo,1), COALESCE(potencia_instalada_kw,0)
                                  FROM locais WHERE nome=? LIMIT 1""", (local,)).fetchone()
    conn.close()

    total_registos = len(rows)
    total_kwh = sum(float(r[4] or 0) for r in rows)
    total_kvarh = sum(float(r[5] or 0) for r in rows)
    agua_total = sum(float(r[10] or 0) for r in rows)
    avg_kw = (sum(float(r[6] or 0) for r in rows) / total_registos) if total_registos else 0.0
    avg_fp = (sum(float(r[8] or 0) for r in rows if float(r[8] or 0) > 0) / max(1, sum(1 for r in rows if float(r[8] or 0) > 0))) if rows else 0.0
    max_ponta = max([float(r[9] or 0) for r in rows] or [0])
    tensao_media = (sum(float(r[12] or 0) for r in rows if float(r[12] or 0) > 0) / max(1, sum(1 for r in rows if float(r[12] or 0) > 0))) if rows else 0.0
    consumo_especifico = (total_kwh / agua_total) if agua_total > 0 else 0.0

    alertas = []
    for r in rows:
        fp = float(r[8] or 0); tensao = float(r[12] or 0); corrente = float(r[11] or 0)
        if 0 < fp < 0.85:
            alertas.append({'nivel':'Crítico', 'tipo':'FP baixo', 'datahora':r[1], 'local':r[2], 'equipamento':r[3], 'valor':f'{fp:.3f}', 'acao':'Verificar compensação reativa, carga parcial ou banco de capacitores.'})
        if tensao > 0 and (tensao < 360 or tensao > 440):
            alertas.append({'nivel':'Atenção', 'tipo':'Tensão fora da faixa', 'datahora':r[1], 'local':r[2], 'equipamento':r[3], 'valor':f'{tensao:.1f} V', 'acao':'Confirmar tensão por fase, estado das ligações e quedas de tensão.'})
        if corrente > 0 and avg_kw > 0 and corrente > 1.35 * max(1, sum(float(x[11] or 0) for x in rows)/max(1,total_registos)):
            alertas.append({'nivel':'Atenção', 'tipo':'Corrente elevada', 'datahora':r[1], 'local':r[2], 'equipamento':r[3], 'valor':f'{corrente:.1f} A', 'acao':'Comparar com corrente nominal e avaliar sobrecarga ou desequilíbrio.'})

    recomenda = []
    if avg_fp and avg_fp < 0.85:
        recomenda.append('Priorizar análise de fator de potência e compensação reativa nos equipamentos/períodos com FP baixo.')
    if tensao_media and (tensao_media < 380 or tensao_media > 420):
        recomenda.append('Validar tensão média operacional e investigar queda/elevação de tensão na alimentação.')
    if consumo_especifico > 0:
        recomenda.append('Acompanhar consumo específico kWh/m³ por equipamento e comparar contra o melhor dia/período operacional.')
    if not recomenda:
        recomenda.append('Manter a monitoria diária e comparar tendências por equipamento para detectar desvios antecipadamente.')

    return render_template('monitoria_relatorio.html',
                           inicio=start, fim=end, local=local, equipamento=equipamento, q=q,
                           rows=rows, resumo_equip=resumo_equip, resumo_local=resumo_local, local_config=local_config,
                           total_registos=total_registos, total_kwh=total_kwh, total_kvarh=total_kvarh,
                           agua_total=agua_total, avg_kw=avg_kw, avg_fp=avg_fp, max_ponta=max_ponta,
                           tensao_media=tensao_media, consumo_especifico=consumo_especifico,
                           alertas=alertas[:50], alertas_total=len(alertas), recomenda=recomenda)

@app.route('/leituras/<int:lid>/duplicate', methods=['POST'])
def leituras_duplicate(lid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    row = c.execute("SELECT datahora, local, equipamento, energia_ativa, energia_reativa, energia_aparente, pot_ativa, pot_reativa, pot_aparente, fp, ponta, caudal_elevada, corrente, tensao, observacoes FROM leituras WHERE id=?", (lid,)).fetchone()
    if not row:
        conn.close()
        flash("Registo não encontrado.", "warning")
        return redirect(url_for('leituras_list'))
    c.execute("""
        INSERT INTO leituras
        (datahora, local, equipamento, energia_ativa, energia_reativa, energia_aparente,
         pot_ativa, pot_reativa, pot_aparente, fp, ponta, caudal_elevada, corrente, tensao, observacoes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, row)
    conn.commit(); conn.close()
    flash("Leitura duplicada.", "success")
    return redirect(url_for('leituras_list'))

@app.route('/leituras/delete_batch', methods=['POST'])
def leituras_delete_batch():
    ids = request.form.getlist('ids')
    if not ids:
        flash("Nenhuma linha selecionada.", "warning")
        return redirect(url_for('leituras_list'))
    # filtra apenas dígitos
    ids_clean = [i for i in ids if str(i).isdigit()]
    if not ids_clean:
        flash("Seleção inválida.", "warning")
        return redirect(url_for('leituras_list'))
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    qmarks = ",".join(["?"]*len(ids_clean))
    c.execute(f"DELETE FROM leituras WHERE id IN ({qmarks})", ids_clean)
    conn.commit(); conn.close()
    flash(f"{len(ids_clean)} leitura(s) eliminada(s).", "success")
    return redirect(url_for('leituras_list'))
@app.route('/leituras/export', methods=['GET'])
def leituras_export_csv():
    """Exporta CSV de leituras filtradas."""
    end = request.args.get('fim') or datetime.now().strftime('%Y-%m-%d')
    start = request.args.get('inicio') or (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d')
    local = request.args.get('local','')
    q = request.args.get('q','').strip()

    sql = "SELECT * FROM leituras WHERE date(datahora) BETWEEN ? AND ?"
    params = [start, end]
    if local:
        sql += " AND local = ?"
        params.append(local)
    if q:
        sql += " AND (equipamento LIKE ? OR observacoes LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])
    sql += " ORDER BY datahora"

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    rows = c.execute(sql, params).fetchall()
    conn.close()

    from io import StringIO
    si = StringIO()
    w = csv.writer(si, delimiter=';')
    header = [
        "id","datahora","local","equipamento","energia_ativa","energia_reativa","energia_aparente",
        "pot_ativa","pot_reativa","pot_aparente","fp","ponta","caudal_elevada","corrente","tensao","observacoes"
    ]
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return Response(si.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=leituras_{start}_a_{end}.csv'})

@app.route('/leituras/import', methods=['GET','POST'])
def leituras_import():
    locais = [l[1] for l in get_locais()]
    if request.method == 'POST':
        f = request.files.get('arquivo')
        if not f or f.filename == '':
            flash('Selecione um ficheiro CSV.','warning')
            return redirect(url_for('leituras_import'))
        # parse CSV (cabecalhos como no export)
        import csv
        from io import TextIOWrapper
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        inseridos = 0
        with TextIOWrapper(f.stream, encoding='utf-8', errors='ignore') as fh:
            reader = csv.DictReader(fh, delimiter=';')
            for row in reader:
                try:
                    c.execute('''INSERT INTO leituras
                         (datahora, local, equipamento, energia_ativa, energia_reativa, energia_aparente,
                          pot_ativa, pot_reativa, pot_aparente, fp, ponta, caudal_elevada, corrente, tensao, observacoes)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                         (row.get('datahora'), row.get('local'), row.get('equipamento'),
                          _to_float(row.get('energia_ativa')), _to_float(row.get('energia_reativa')), _to_float(row.get('energia_aparente')),
                          _to_float(row.get('pot_ativa')), _to_float(row.get('pot_reativa')), _to_float(row.get('pot_aparente')),
                          _to_float(row.get('fp')), _to_float(row.get('ponta')), _to_float(row.get('caudal_elevada')),
                          _to_float(row.get('corrente')), _to_float(row.get('tensao')), row.get('observacoes')))
                    inseridos += 1
                except Exception:
                    pass
        conn.commit(); conn.close()
        flash(f'Importação concluída: {inseridos} registos inseridos.','success')
        return redirect(url_for('leituras_list'))
    return render_template('leituras_import.html', locais=locais)

@app.route('/leituras/<int:lid>/edit', methods=['GET','POST'])
def leituras_edit(lid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    if request.method == 'POST':
        datahora = request.form.get('datahora')
        local = request.form.get('local')
        equipamento = request.form.get('equipamento')
        energia_ativa = _to_float(request.form.get('energia_ativa'))
        energia_reativa = _to_float(request.form.get('energia_reativa'))
        energia_aparente = _to_float(request.form.get('energia_aparente'))
        pot_ativa = _to_float(request.form.get('pot_ativa'))
        pot_reativa = _to_float(request.form.get('pot_reativa'))
        pot_aparente = _to_float(request.form.get('pot_aparente'))
        fp = _to_float(request.form.get('fp'))
        ponta = _to_float(request.form.get('ponta'))
        caudal_elevada = _to_float(request.form.get('caudal_elevada'))
        corrente = _to_float(request.form.get('corrente'))
        tensao = _to_float(request.form.get('tensao'))
        obs = request.form.get('observacoes','')
        c.execute('''UPDATE leituras SET datahora=?, local=?, equipamento=?, energia_ativa=?, energia_reativa=?, energia_aparente=?,
                     pot_ativa=?, pot_reativa=?, pot_aparente=?, fp=?, ponta=?, caudal_elevada=?, corrente=?, tensao=?, observacoes=?
                     WHERE id=?''',
                  (datahora, local, equipamento, energia_ativa, energia_reativa, energia_aparente,
                   pot_ativa, pot_reativa, pot_aparente, fp, ponta, caudal_elevada, corrente, tensao, obs, lid))
        conn.commit(); conn.close()
        flash('Leitura atualizada.','success')
        return redirect(url_for('leituras_list'))
    row = c.execute('SELECT * FROM leituras WHERE id=?', (lid,)).fetchone()
    conn.close()
    if not row:
        flash('Registo não encontrado.','warning')
        return redirect(url_for('leituras_list'))
    locais = [l[1] for l in get_locais()]
    return render_template('leituras_edit.html', row=row, locais=locais)

@app.route('/leituras/<int:lid>/delete', methods=['POST'])
def leituras_delete(lid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('DELETE FROM leituras WHERE id=?', (lid,))
    conn.commit(); conn.close()
    flash('Leitura eliminada.','success')
    return redirect(url_for('leituras_list'))

@app.route('/leituras/visualizar', methods=['GET'])
def visualizar_diario_view():
    """Visualiza um dia (ou intervalo curto) com gráfico."""
    locais = [l[1] for l in get_locais()]
    data = request.args.get('data') or datetime.now().strftime('%Y-%m-%d')
    local = request.args.get('local','')
    sql = "SELECT * FROM leituras WHERE date(datahora)=?"; params=[data]
    if local:
        sql += " AND local=?"; params.append(local)
    sql += " ORDER BY datahora"
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    leit = c.execute(sql, params).fetchall()
    conn.close()
    horas = [r[1] for r in leit]
    ativa = [float(r[4] or 0) for r in leit]
    return render_template('visualizar_diario.html', data=data, locais=locais, local=local,
                           leituras=leit, grafico_horas=horas, grafico_ativa=ativa)

# === Export de Leituras Mensais (referenciado no template) ===
@app.route('/leituras_mensal/export')
def leituras_mensal_export():
    local = request.args.get('local','')
    mes = request.args.get('mes') or datetime.now().strftime('%m')
    ano = int(request.args.get('ano') or datetime.now().year)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    rows = c.execute('''SELECT local,data,hora,ativa,reativa,ponta,fp,potc,anterior,atual,diferenca,agua,esp,acum,valor
                        FROM leituras_mensais WHERE local=? AND mes=? AND ano=? ORDER BY data''',
                     (local, mes, ano)).fetchall()
    conn.close()
    si = io.StringIO(); w = csv.writer(si, delimiter=';')
    w.writerow(['local','data','hora','ativa','reativa','ponta','fp','potc','anterior','atual','diferenca','agua','esp','acum','valor'])
    for r in rows:
        w.writerow(r)
    return Response(si.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=leituras_mensais_{local}_{mes}-{ano}.csv'})

# === LEITURA MENSAL ===


# === LEITURAS MENSAIS · FASE 2 OPERAÇÃO REAL ===

