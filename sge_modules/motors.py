"""Domínio motors extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""

def _motor_intervalo_padrao():
    hoje = datetime.now().date()
    return (hoje - timedelta(days=30)).strftime('%Y-%m-%d'), hoje.strftime('%Y-%m-%d')


def _motor_float(v, default=0.0):
    try:
        if v is None or v == '':
            return default
        return float(str(v).replace(',', '.'))
    except Exception:
        return default


def _motor_dict_factory(cursor, row):
    return {col[0]: row[idx] for idx, col in enumerate(cursor.description)}


def _motor_load_equipamentos(local_id=None, equip_id=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = _motor_dict_factory
    c = conn.cursor()
    try:
        c.execute("PRAGMA table_info(equipamentos)")
        cols = {r['name'] for r in c.fetchall()}
    except Exception:
        cols = set()

    optional = []
    for col in ['tag', 'categoria', 'criticidade', 'fabricante', 'modelo', 'especificacao', 'potencia_kw', 'ativo']:
        if col in cols:
            optional.append(f"e.{col} AS {col}")
        else:
            optional.append(f"'' AS {col}")

    sql = f'''
        SELECT e.id, e.nome, e.local_id, l.nome AS local_nome,
               {', '.join(optional)},
               cfg.tensao_nominal, cfg.corrente_nominal, cfg.potencia_nominal_kw,
               cfg.fp_nominal, cfg.eficiencia_nominal, cfg.limite_corrente, cfg.limite_fp
        FROM equipamentos e
        LEFT JOIN locais l ON l.id=e.local_id
        LEFT JOIN equipamentos_cfg cfg ON cfg.equipamento_id=e.id
        WHERE 1=1
    '''
    params = []
    if local_id:
        local_ids_scope = get_descendant_local_ids(local_id, include_self=True)
        if not local_ids_scope:
            local_ids_scope = [int(local_id)]
        placeholders_local = ','.join('?' for _ in local_ids_scope)
        sql += f' AND e.local_id IN ({placeholders_local})'; params.extend(local_ids_scope)
    if equip_id:
        sql += ' AND e.id=?'; params.append(equip_id)
    sql += ' ORDER BY COALESCE(l.nome,\'\'), e.nome'
    c.execute(sql, params)
    rows = c.fetchall()
    conn.close()
    return rows


def _motor_collect_stats(local_id=None, equip_id=None, ini=None, fim=None):
    if not ini or not fim:
        ini, fim = _motor_intervalo_padrao()
    dt_ini = ini + ' 00:00:00'
    dt_fim = fim + ' 23:59:59'
    equipamentos = _motor_load_equipamentos(local_id, equip_id)
    by_id = {int(e['id']): e for e in equipamentos}
    by_name = {(e['nome'] or '').strip().lower(): int(e['id']) for e in equipamentos}

    stats = {}
    for e in equipamentos:
        stats[int(e['id'])] = {
            'equipamento': e,
            'n': 0, 'kwh': 0.0, 'fp_sum': 0.0, 'fp_n': 0,
            'corr_sum': 0.0, 'corr_n': 0, 'corr_max': 0.0,
            'kw_sum': 0.0, 'kw_n': 0, 'kw_max': 0.0,
            'ponta_max': 0.0, 'tensao_min': None, 'tensao_max': None,
            'agua': 0.0, 'horas': 0.0, 'arranques': 0, 'last_ts': '',
            'alertas': [], 'fontes': set()
        }

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = _motor_dict_factory
    c = conn.cursor()

    # Medições específicas do módulo Motores
    params = [dt_ini, dt_fim]
    sql = '''
        SELECT m.*, e.nome AS equipamento_nome, e.local_id
        FROM motor_medicoes m
        JOIN equipamentos e ON e.id=m.equipamento_id
        WHERE datetime(m.datahora) BETWEEN datetime(?) AND datetime(?)
    '''
    if local_id:
        local_ids_scope = get_descendant_local_ids(local_id, include_self=True)
        if not local_ids_scope:
            local_ids_scope = [int(local_id)]
        placeholders_local = ','.join('?' for _ in local_ids_scope)
        sql += f' AND e.local_id IN ({placeholders_local})'; params.extend(local_ids_scope)
    if equip_id:
        sql += ' AND e.id=?'; params.append(equip_id)
    sql += ' ORDER BY datetime(m.datahora)'
    try:
        c.execute(sql, params)
        rows = c.fetchall()
    except Exception:
        rows = []

    for r in rows:
        eid = int(r['equipamento_id'])
        if eid not in stats:
            continue
        st = stats[eid]
        st['fontes'].add('Motores')
        st['n'] += 1
        st['last_ts'] = max(st['last_ts'], r.get('datahora') or '')
        kwh = _motor_float(r.get('energia_kwh'))
        st['kwh'] += max(kwh, 0)
        fp = r.get('fator_potencia')
        if fp is not None:
            st['fp_sum'] += _motor_float(fp); st['fp_n'] += 1
        corr = r.get('corrente_a')
        if corr is not None:
            corr = _motor_float(corr); st['corr_sum'] += corr; st['corr_n'] += 1; st['corr_max'] = max(st['corr_max'], corr)
        kw = r.get('pot_ativa_kw')
        if kw is not None:
            kw = _motor_float(kw); st['kw_sum'] += kw; st['kw_n'] += 1; st['kw_max'] = max(st['kw_max'], kw)
        tensao = r.get('tensao_v')
        if tensao is not None:
            tensao = _motor_float(tensao)
            st['tensao_min'] = tensao if st['tensao_min'] is None else min(st['tensao_min'], tensao)
            st['tensao_max'] = tensao if st['tensao_max'] is None else max(st['tensao_max'], tensao)

    # Dados da Monitoria Operacional: tabela leituras, associada pelo nome do equipamento.
    params = [dt_ini, dt_fim]
    sql = '''
        SELECT datahora, local, equipamento, energia_ativa, pot_ativa, fp, ponta, caudal_elevada, corrente, tensao
        FROM leituras
        WHERE datetime(datahora) BETWEEN datetime(?) AND datetime(?)
          AND COALESCE(equipamento,'') <> ''
    '''
    if equip_id and equip_id in by_id:
        sql += ' AND lower(equipamento)=lower(?)'; params.append(by_id[equip_id]['nome'])
    sql += ' ORDER BY datetime(datahora)'
    try:
        c.execute(sql, params)
        leituras = c.fetchall()
    except Exception:
        leituras = []

    for r in leituras:
        name = (r.get('equipamento') or '').strip().lower()
        eid = by_name.get(name)
        if not eid or eid not in stats:
            continue
        # se filtrou local, confirma pelo equipamento cadastrado
        if local_id and int(stats[eid]['equipamento'].get('local_id') or 0) != int(local_id):
            continue
        st = stats[eid]
        st['fontes'].add('Monitoria')
        st['n'] += 1
        st['last_ts'] = max(st['last_ts'], r.get('datahora') or '')
        st['kwh'] += max(_motor_float(r.get('energia_ativa')), 0)
        fp = r.get('fp')
        if fp is not None:
            st['fp_sum'] += _motor_float(fp); st['fp_n'] += 1
        corr = r.get('corrente')
        if corr is not None:
            corr = _motor_float(corr); st['corr_sum'] += corr; st['corr_n'] += 1; st['corr_max'] = max(st['corr_max'], corr)
        kw = r.get('pot_ativa')
        if kw is not None:
            kw = _motor_float(kw); st['kw_sum'] += kw; st['kw_n'] += 1; st['kw_max'] = max(st['kw_max'], kw)
        st['ponta_max'] = max(st['ponta_max'], _motor_float(r.get('ponta')))
        st['agua'] += max(_motor_float(r.get('caudal_elevada')), 0)
        tensao = r.get('tensao')
        if tensao is not None:
            tensao = _motor_float(tensao)
            st['tensao_min'] = tensao if st['tensao_min'] is None else min(st['tensao_min'], tensao)
            st['tensao_max'] = tensao if st['tensao_max'] is None else max(st['tensao_max'], tensao)

    # Horas de funcionamento / arranques
    params = [dt_ini, dt_fim, dt_ini, dt_fim, dt_fim]
    sql = '''
        SELECT r.equipamento_id, r.start_time, r.stop_time, r.duracao_min
        FROM motor_runs r
        JOIN equipamentos e ON e.id=r.equipamento_id
        WHERE ((datetime(r.start_time) BETWEEN datetime(?) AND datetime(?))
            OR (r.stop_time IS NOT NULL AND datetime(r.stop_time) BETWEEN datetime(?) AND datetime(?))
            OR (r.stop_time IS NULL AND datetime(r.start_time) <= datetime(?)))
    '''
    if local_id:
        sql += ' AND e.local_id=?'; params.append(local_id)
    if equip_id:
        sql += ' AND e.id=?'; params.append(equip_id)
    try:
        c.execute(sql, params)
        runs = c.fetchall()
    except Exception:
        runs = []
    fim_dt = datetime.fromisoformat(dt_fim)
    for r in runs:
        eid = int(r['equipamento_id'])
        if eid not in stats:
            continue
        stats[eid]['arranques'] += 1
        stats[eid]['fontes'].add('Horas')
        dur = r.get('duracao_min')
        if dur is None:
            try:
                st_dt = datetime.fromisoformat((r.get('start_time') or '').replace(' ', 'T'))
                dur = max((fim_dt - st_dt).total_seconds()/60.0, 0)
            except Exception:
                dur = 0
        stats[eid]['horas'] += _motor_float(dur)/60.0

    conn.close()

    analyzed = []
    total_alertas = 0
    criticos = 0
    for eid, st in stats.items():
        e = st['equipamento']
        avg_fp = st['fp_sum']/st['fp_n'] if st['fp_n'] else None
        avg_corr = st['corr_sum']/st['corr_n'] if st['corr_n'] else None
        avg_kw = st['kw_sum']/st['kw_n'] if st['kw_n'] else None
        pot_nom = _motor_float(e.get('potencia_nominal_kw')) or _motor_float(e.get('potencia_kw'))
        corr_nom = _motor_float(e.get('corrente_nominal'))
        lim_corr = _motor_float(e.get('limite_corrente')) or (corr_nom * 1.10 if corr_nom else 0)
        lim_fp = _motor_float(e.get('limite_fp'), 0.80) or 0.80
        carga_pct = (avg_kw / pot_nom * 100.0) if avg_kw is not None and pot_nom else None
        ce = (st['kwh']/st['agua']) if st['agua'] else None
        alertas = []
        if st['n'] == 0:
            alertas.append(('Informativo', 'Sem medições no período', 'Lançar medições operacionais ou associar leituras da Monitoria.'))
        if avg_fp is not None and avg_fp < lim_fp:
            nivel = 'Crítico' if avg_fp < 0.75 else 'Atenção'
            alertas.append((nivel, f'FP médio baixo: {avg_fp:.3f}', 'Avaliar compensação reativa, regime de carga e banco de capacitores.'))
        if lim_corr and st['corr_max'] > lim_corr:
            alertas.append(('Crítico', f'Corrente máxima acima do limite: {st["corr_max"]:.1f} A > {lim_corr:.1f} A', 'Verificar sobrecarga, desalinhamento, rolamentos, bomba travada ou desequilíbrio.'))
        if st['tensao_min'] is not None and (st['tensao_min'] < 360 or st['tensao_max'] > 440):
            alertas.append(('Atenção', f'Tensão fora da faixa: {st["tensao_min"]:.1f}–{st["tensao_max"]:.1f} V', 'Confirmar tensão por fase, queda de tensão e estado do quadro/transformador.'))
        if carga_pct is not None and carga_pct < 35:
            alertas.append(('Atenção', f'Baixo carregamento estimado: {carga_pct:.1f}%', 'Motor pode estar sobredimensionado ou a operar fora do ponto ótimo.'))
        if carga_pct is not None and carga_pct > 105:
            alertas.append(('Crítico', f'Sobrecarga estimada: {carga_pct:.1f}%', 'Reduzir carga e verificar dimensionamento/proteções.'))
        if st['horas'] > 0 and st['arranques'] / max(st['horas'], 1) > 6:
            alertas.append(('Atenção', 'Frequência elevada de arranques', 'Avaliar lógica de comando, pressostatos/níveis e impacto na vida útil.'))
        status = 'Normal'
        if any(a[0] == 'Crítico' for a in alertas): status = 'Crítico'
        elif any(a[0] == 'Atenção' for a in alertas): status = 'Atenção'
        elif st['n'] == 0: status = 'Sem dados'
        total_alertas += len(alertas)
        if status == 'Crítico': criticos += 1
        analyzed.append({
            'id': eid, 'equipamento': e, 'status': status, 'alertas': alertas,
            'n': st['n'], 'kwh': st['kwh'], 'avg_fp': avg_fp, 'avg_corr': avg_corr,
            'corr_max': st['corr_max'], 'avg_kw': avg_kw, 'kw_max': st['kw_max'],
            'ponta_max': st['ponta_max'], 'horas': st['horas'], 'arranques': st['arranques'],
            'tensao_min': st['tensao_min'], 'tensao_max': st['tensao_max'],
            'agua': st['agua'], 'ce': ce, 'carga_pct': carga_pct, 'last_ts': st['last_ts'],
            'fontes': ', '.join(sorted(st['fontes'])) or '—',
        })
    order = {'Crítico':0, 'Atenção':1, 'Normal':2, 'Sem dados':3}
    analyzed.sort(key=lambda x: (order.get(x['status'], 9), -(x['kwh'] or 0), x['equipamento']['nome'] or ''))
    resumo = {
        'equipamentos': len(analyzed),
        'com_dados': sum(1 for x in analyzed if x['n'] > 0),
        'criticos': criticos,
        'alertas': total_alertas,
        'kwh': sum(x['kwh'] for x in analyzed),
        'horas': sum(x['horas'] for x in analyzed),
        'fp_medio': None,
        'corrente_max': max([x['corr_max'] for x in analyzed] or [0]),
    }
    fp_vals = [x['avg_fp'] for x in analyzed if x['avg_fp'] is not None]
    if fp_vals:
        resumo['fp_medio'] = sum(fp_vals)/len(fp_vals)
    return analyzed, resumo, ini, fim



def _motor_kvar_compensacao(avg_kw, fp_atual, fp_alvo=0.92):
    """Estimativa de kVAr para corrigir FP de um motor/carga.
    Retorna None quando os dados não permitem cálculo coerente.
    """
    try:
        p_kw = float(avg_kw or 0)
        fp1 = float(fp_atual or 0)
        fp2 = float(fp_alvo or 0.92)
        if p_kw <= 0 or fp1 <= 0 or fp1 >= fp2 or fp2 >= 1:
            return None
        import math
        phi1 = math.acos(max(min(fp1, 0.999999), 0.000001))
        phi2 = math.acos(max(min(fp2, 0.999999), 0.000001))
        kvar = p_kw * (math.tan(phi1) - math.tan(phi2))
        return max(kvar, 0)
    except Exception:
        return None


def _motor_recomendacoes_detalhadas(analise):
    recs = []
    avg_fp = analise.get('avg_fp')
    carga = analise.get('carga_pct')
    corr_max = analise.get('corr_max') or 0
    horas = analise.get('horas') or 0
    arr = analise.get('arranques') or 0
    if avg_fp is not None and avg_fp < 0.80:
        recs.append(('Compensação reativa', 'Prioritário', 'Verificar banco de capacitores, correção individual/coletiva e operação em baixo carregamento.'))
    if carga is not None and carga < 35:
        recs.append(('Baixo carregamento', 'Atenção', 'Avaliar se o motor está sobredimensionado, se existe estrangulamento hidráulico ou se o ponto de operação da bomba está fora do ideal.'))
    if carga is not None and carga > 100:
        recs.append(('Sobrecarga', 'Crítico', 'Confirmar corrente por fase, vibração, rolamentos, alinhamento, estado da bomba e proteções térmicas.'))
    if arr and horas and arr / max(horas, 1) > 6:
        recs.append(('Arranques frequentes', 'Atenção', 'Rever lógica de comando, níveis, pressostatos, VFD/soft-starter e proteção contra partidas excessivas.'))
    if corr_max:
        recs.append(('Inspeção eléctrica', 'Rotina', 'Comparar corrente medida com corrente nominal do motor e verificar desequilíbrio entre fases quando houver medição trifásica disponível.'))
    if not recs:
        recs.append(('Operação normal', 'Rotina', 'Manter monitoria periódica, limpeza, reaperto de terminais, verificação de ventilação e atualização do histórico operacional.'))
    return recs

@app.route('/motores')
def motores_menu():
    local_id = request.args.get('local_id', type=int)
    equip_id = request.args.get('equipamento_id', type=int)
    data_ini = request.args.get('ini')
    data_fim = request.args.get('fim')
    if not data_ini or not data_fim:
        data_ini, data_fim = _motor_intervalo_padrao()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT id, nome FROM locais ORDER BY nome')
    locais = c.fetchall()
    c.execute('SELECT id, nome FROM equipamentos ORDER BY nome')
    equipamentos_select = c.fetchall()
    conn.close()
    analises, resumo, data_ini, data_fim = _motor_collect_stats(local_id, equip_id, data_ini, data_fim)
    return render_template('motores.html', locais=locais, equipamentos_select=equipamentos_select,
                           analises=analises, resumo=resumo, local_id=local_id or '', equip_id=equip_id or '',
                           data_ini=data_ini, data_fim=data_fim)


@app.route('/motores/medir', methods=['GET', 'POST'])
@app.route('/motores/nova', methods=['GET', 'POST'])
def motor_medir():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('''
        SELECT e.id, e.nome, COALESCE(l.nome,'')
        FROM equipamentos e LEFT JOIN locais l ON l.id=e.local_id
        ORDER BY COALESCE(l.nome,''), e.nome
    ''')
    equipamentos = c.fetchall()
    conn.close()

    if request.method == 'POST':
        equipamento_id = int(request.form['equipamento_id'])
        datahora = request.form.get('datahora') or datetime.now().strftime('%Y-%m-%dT%H:%M')
        tensao_v = _motor_float(request.form.get('tensao_v'))
        corrente_a = _motor_float(request.form.get('corrente_a'))
        fp = _motor_float(request.form.get('fator_potencia'))
        freq = _motor_float(request.form.get('frequencia_hz'), 50)
        fases = int(_motor_float(request.form.get('fases'), 3) or 3)
        pot_ativa_kw = request.form.get('pot_ativa_kw')
        pot_reativa_kvar = request.form.get('pot_reativa_kvar')
        pot_aparente_kva = request.form.get('pot_aparente_kva')
        eficiencia = request.form.get('eficiencia')
        observacoes = request.form.get('observacoes', '').strip()

        pot_ativa_kw = _motor_float(pot_ativa_kw, None) if pot_ativa_kw not in (None, '',) else None
        pot_reativa_kvar = _motor_float(pot_reativa_kvar, None) if pot_reativa_kvar not in (None, '',) else None
        pot_aparente_kva = _motor_float(pot_aparente_kva, None) if pot_aparente_kva not in (None, '',) else None
        eficiencia = _motor_float(eficiencia, None) if eficiencia not in (None, '',) else None

        if not pot_aparente_kva and fases == 3 and tensao_v > 0 and corrente_a > 0:
            pot_aparente_kva = (math.sqrt(3) * tensao_v * corrente_a) / 1000.0
        elif not pot_aparente_kva and fases == 1 and tensao_v > 0 and corrente_a > 0:
            pot_aparente_kva = (tensao_v * corrente_a) / 1000.0
        if not pot_ativa_kw and pot_aparente_kva and fp > 0:
            pot_ativa_kw = pot_aparente_kva * fp
        if not pot_reativa_kvar and pot_aparente_kva and (pot_ativa_kw is not None):
            pot_reativa_kvar = math.sqrt(max(pot_aparente_kva**2 - pot_ativa_kw**2, 0))

        energia_kwh = None
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('SELECT datahora, pot_ativa_kw FROM motor_medicoes WHERE equipamento_id=? ORDER BY datetime(datahora) DESC LIMIT 1', (equipamento_id,))
        last = c.fetchone()
        if last and pot_ativa_kw is not None:
            try:
                dt_last = datetime.fromisoformat(last[0].replace(' ', 'T'))
                dt_now = datetime.fromisoformat(datahora)
                dh = max((dt_now - dt_last).total_seconds() / 3600.0, 0)
                pot_media = ((_motor_float(last[1])) + pot_ativa_kw) / 2.0
                energia_kwh = pot_media * dh
            except Exception:
                energia_kwh = None

        avisos = []
        if fp and fp < 0.80: avisos.append(f'FP baixo: {fp:.3f}')
        if tensao_v and (tensao_v < 360 or tensao_v > 440): avisos.append(f'Tensão fora da faixa: {tensao_v:.1f} V')
        if avisos:
            observacoes = (observacoes + ' | ' if observacoes else '') + 'ALERTA MOTOR: ' + '; '.join(avisos)

        c.execute('''
            INSERT INTO motor_medicoes
            (equipamento_id, datahora, tensao_v, corrente_a, fator_potencia, frequencia_hz, fases,
             pot_ativa_kw, pot_reativa_kvar, pot_aparente_kva, eficiencia, energia_kwh, observacoes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (equipamento_id, datahora.replace('T',' '), tensao_v, corrente_a, fp, freq, fases,
              pot_ativa_kw, pot_reativa_kvar, pot_aparente_kva, eficiencia, energia_kwh, observacoes))
        conn.commit(); conn.close()
        if request.form.get('continuar') == '1':
            return redirect(url_for('motor_medir'))
        return redirect(url_for('motores_menu'))

    now = datetime.now().strftime('%Y-%m-%dT%H:%M')
    return render_template('motor_medicao_form.html', equipamentos=equipamentos, now=now)


@app.route('/motores/runs', methods=['GET'])
def motor_runs_page():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT e.id, e.nome, l.nome FROM equipamentos e LEFT JOIN locais l ON e.local_id=l.id ORDER BY l.nome, e.nome')
    equipamentos = c.fetchall()
    c.execute('''
        SELECT r.id, e.nome, COALESCE(l.nome,''), r.start_time, r.stop_time, r.duracao_min
        FROM motor_runs r
        LEFT JOIN equipamentos e ON e.id=r.equipamento_id
        LEFT JOIN locais l ON l.id=e.local_id
        ORDER BY r.id DESC LIMIT 50
    ''')
    runs = c.fetchall()
    conn.close()
    return render_template('motor_runs.html', equipamentos=equipamentos, runs=runs)


@app.route('/motores/run/start', methods=['POST'])
def motor_run_start():
    equipamento_id = int(request.form['equipamento_id'])
    agora = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT id FROM motor_runs WHERE equipamento_id=? AND stop_time IS NULL', (equipamento_id,))
    aberto = c.fetchone()
    if not aberto:
        c.execute('INSERT INTO motor_runs (equipamento_id, start_time) VALUES (?, ?)', (equipamento_id, agora))
        conn.commit()
    conn.close()
    return redirect(url_for('motor_runs_page'))


@app.route('/motores/run/stop', methods=['POST'])
def motor_run_stop():
    equipamento_id = int(request.form['equipamento_id'])
    agora_dt = datetime.now()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT id, start_time FROM motor_runs WHERE equipamento_id=? AND stop_time IS NULL ORDER BY id DESC LIMIT 1', (equipamento_id,))
    row = c.fetchone()
    if row:
        run_id, start_str = row
        try:
            start_dt = datetime.fromisoformat(start_str)
            dur_min = max((agora_dt - start_dt).total_seconds() / 60.0, 0)
        except Exception:
            dur_min = 0
        c.execute('UPDATE motor_runs SET stop_time=?, duracao_min=? WHERE id=?',
                  (agora_dt.strftime('%Y-%m-%d %H:%M:%S'), dur_min, run_id))
        conn.commit()
    conn.close()
    return redirect(url_for('motor_runs_page'))


@app.route('/motores/graficos', methods=['GET'])
def motor_graficos():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT e.id, e.nome, l.nome FROM equipamentos e LEFT JOIN locais l ON e.local_id=l.id ORDER BY l.nome, e.nome')
    equipamentos = c.fetchall()
    conn.close()
    equip_id = request.args.get('equipamento_id', type=int)
    data_ini = request.args.get('ini')
    data_fim = request.args.get('fim')
    if not data_ini or not data_fim:
        data_ini, data_fim = _motor_intervalo_padrao()
    series = []
    if equip_id:
        rows, _, _, _ = _motor_collect_stats(None, equip_id, data_ini, data_fim)
        # gráfico detalhado usa medições reais do motor
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('''
            SELECT datahora, tensao_v, corrente_a, fator_potencia, frequencia_hz,
                   pot_ativa_kw, pot_reativa_kvar, pot_aparente_kva
            FROM motor_medicoes
            WHERE equipamento_id=? AND datetime(datahora) BETWEEN datetime(?) AND datetime(?)
            ORDER BY datetime(datahora)
        ''', (equip_id, data_ini+' 00:00:00', data_fim+' 23:59:59'))
        series = c.fetchall(); conn.close()
    datas = [s[0] for s in series]
    return render_template('motor_graficos.html', equipamentos=equipamentos, equip_id=equip_id or '', data_ini=data_ini, data_fim=data_fim,
                           datas=datas, tensao=[s[1] for s in series], corrente=[s[2] for s in series], fp=[s[3] for s in series],
                           freq=[s[4] for s in series], p_kw=[s[5] for s in series], q_kvar=[s[6] for s in series], s_kva=[s[7] for s in series])


@app.route('/motores/relatorio', methods=['GET'])
def motor_relatorio():
    local_id = request.args.get('local_id', type=int)
    equip_id = request.args.get('equipamento_id', type=int)
    data_ini = request.args.get('ini')
    data_fim = request.args.get('fim')
    if not data_ini or not data_fim:
        data_ini, data_fim = _motor_intervalo_padrao()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT id, nome FROM locais ORDER BY nome')
    locais = c.fetchall()
    c.execute('SELECT id, nome FROM equipamentos ORDER BY nome')
    equipamentos_select = c.fetchall()
    conn.close()
    analises, resumo, data_ini, data_fim = _motor_collect_stats(local_id, equip_id, data_ini, data_fim)
    return render_template('motor_relatorio.html', locais=locais, equipamentos_select=equipamentos_select,
                           analises=analises, resumo=resumo, local_id=local_id or '', equip_id=equip_id or '',
                           data_ini=data_ini, data_fim=data_fim)



@app.route('/motores/detalhe/<int:equipamento_id>', methods=['GET'])
def motor_detalhe(equipamento_id):
    data_ini = request.args.get('ini')
    data_fim = request.args.get('fim')
    if not data_ini or not data_fim:
        data_ini, data_fim = _motor_intervalo_padrao()

    analises, resumo, data_ini, data_fim = _motor_collect_stats(None, equipamento_id, data_ini, data_fim)
    analise = analises[0] if analises else None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = _motor_dict_factory
    c = conn.cursor()
    c.execute("""
        SELECT e.*, l.nome AS local_nome,
               cfg.tensao_nominal, cfg.corrente_nominal, cfg.potencia_nominal_kw,
               cfg.fp_nominal, cfg.eficiencia_nominal, cfg.limite_corrente, cfg.limite_fp
        FROM equipamentos e
        LEFT JOIN locais l ON l.id=e.local_id
        LEFT JOIN equipamentos_cfg cfg ON cfg.equipamento_id=e.id
        WHERE e.id=?
    """, (equipamento_id,))
    equipamento = c.fetchone()
    if not equipamento:
        conn.close()
        flash('Equipamento não encontrado.', 'warning')
        return redirect(url_for('motores_menu'))

    c.execute("""
        SELECT datahora, tensao_v, corrente_a, fator_potencia, frequencia_hz,
               pot_ativa_kw, pot_reativa_kvar, pot_aparente_kva, energia_kwh, observacoes
        FROM motor_medicoes
        WHERE equipamento_id=? AND datetime(datahora) BETWEEN datetime(?) AND datetime(?)
        ORDER BY datetime(datahora) DESC LIMIT 25
    """, (equipamento_id, data_ini+' 00:00:00', data_fim+' 23:59:59'))
    medicoes = c.fetchall()

    c.execute("""
        SELECT id, start_time, stop_time, duracao_min
        FROM motor_runs
        WHERE equipamento_id=? AND datetime(start_time) BETWEEN datetime(?) AND datetime(?)
        ORDER BY datetime(start_time) DESC LIMIT 20
    """, (equipamento_id, data_ini+' 00:00:00', data_fim+' 23:59:59'))
    runs = c.fetchall()

    c.execute("""
        SELECT datahora, local, equipamento, energia_ativa, pot_ativa, fp, ponta, corrente, tensao, observacoes
        FROM leituras
        WHERE lower(COALESCE(equipamento,''))=lower(?)
          AND datetime(datahora) BETWEEN datetime(?) AND datetime(?)
        ORDER BY datetime(datahora) DESC LIMIT 25
    """, ((equipamento.get('nome') or ''), data_ini+' 00:00:00', data_fim+' 23:59:59'))
    leituras_monitoria = c.fetchall()
    conn.close()

    if not analise:
        analise = {
            'id': equipamento_id, 'equipamento': equipamento, 'status': 'Sem dados', 'alertas': [],
            'n': 0, 'kwh': 0, 'avg_fp': None, 'avg_corr': None, 'corr_max': 0, 'avg_kw': None,
            'kw_max': 0, 'ponta_max': 0, 'horas': 0, 'arranques': 0, 'tensao_min': None,
            'tensao_max': None, 'agua': 0, 'ce': None, 'carga_pct': None, 'last_ts': '', 'fontes': '—'
        }

    kvar_sugerido = _motor_kvar_compensacao(analise.get('avg_kw'), analise.get('avg_fp'), 0.92)
    recomendacoes = _motor_recomendacoes_detalhadas(analise)
    return render_template('motor_detalhe.html', equipamento=equipamento, analise=analise,
                           medicoes=medicoes, runs=runs, leituras_monitoria=leituras_monitoria,
                           data_ini=data_ini, data_fim=data_fim, kvar_sugerido=kvar_sugerido,
                           recomendacoes=recomendacoes)

@app.route('/motores/export/medicoes_csv')
def export_medicoes_csv():
    equip_id = request.args.get('equipamento_id', type=int)
    data_ini = request.args.get('ini')
    data_fim = request.args.get('fim')
    if not equip_id:
        return Response('equipamento_id é obrigatório', status=400)
    if not data_ini or not data_fim:
        data_ini, data_fim = _motor_intervalo_padrao()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('''SELECT datahora,tensao_v,corrente_a,fator_potencia,frequencia_hz,pot_ativa_kw,pot_reativa_kvar,pot_aparente_kva,energia_kwh,observacoes
                 FROM motor_medicoes WHERE equipamento_id=? AND datetime(datahora) BETWEEN datetime(?) AND datetime(?) ORDER BY datetime(datahora)''',
              (equip_id, data_ini+' 00:00:00', data_fim+' 23:59:59'))
    rows = c.fetchall(); conn.close()
    si = StringIO(); w = csv.writer(si, delimiter=';')
    w.writerow(['datahora','tensao_v','corrente_a','fator_potencia','frequencia_hz','pot_ativa_kw','pot_reativa_kvar','pot_aparente_kva','energia_kwh','observacoes'])
    for r in rows: w.writerow(r)
    return Response(si.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment;filename=medicoes_motor_{equip_id}_{data_ini}_a_{data_fim}.csv'})


@app.route('/motores/export/runs_csv')
def export_runs_csv():
    equip_id = request.args.get('equipamento_id', type=int)
    data_ini = request.args.get('ini')
    data_fim = request.args.get('fim')
    if not equip_id:
        return Response('equipamento_id é obrigatório', status=400)
    if not data_ini or not data_fim:
        data_ini, data_fim = _motor_intervalo_padrao()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('''SELECT id,start_time,stop_time,duracao_min FROM motor_runs WHERE equipamento_id=? AND datetime(start_time) BETWEEN datetime(?) AND datetime(?) ORDER BY datetime(start_time)''',
              (equip_id, data_ini+' 00:00:00', data_fim+' 23:59:59'))
    rows = c.fetchall(); conn.close()
    si = StringIO(); w = csv.writer(si, delimiter=';')
    w.writerow(['id','start_time','stop_time','duracao_min'])
    for r in rows: w.writerow(r)
    return Response(si.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment;filename=horas_motor_{equip_id}_{data_ini}_a_{data_fim}.csv'})




# === MOTORES - FECHO DO MÓDULO: MANUTENÇÃO, EXPORTAÇÃO E IMPRESSÃO ===

def _motor_contexto_detalhe(equipamento_id, data_ini=None, data_fim=None):
    if not data_ini or not data_fim:
        data_ini, data_fim = _motor_intervalo_padrao()
    analises, resumo, data_ini, data_fim = _motor_collect_stats(None, equipamento_id, data_ini, data_fim)
    analise = analises[0] if analises else None

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = _motor_dict_factory
    c = conn.cursor()
    c.execute("""
        SELECT e.*, l.nome AS local_nome,
               cfg.tensao_nominal, cfg.corrente_nominal, cfg.potencia_nominal_kw,
               cfg.fp_nominal, cfg.eficiencia_nominal, cfg.limite_corrente, cfg.limite_fp
        FROM equipamentos e
        LEFT JOIN locais l ON l.id=e.local_id
        LEFT JOIN equipamentos_cfg cfg ON cfg.equipamento_id=e.id
        WHERE e.id=?
    """, (equipamento_id,))
    equipamento = c.fetchone()
    if not equipamento:
        conn.close()
        return None

    c.execute("""
        SELECT datahora, tensao_v, corrente_a, fator_potencia, frequencia_hz,
               pot_ativa_kw, pot_reativa_kvar, pot_aparente_kva, energia_kwh, observacoes
        FROM motor_medicoes
        WHERE equipamento_id=? AND datetime(datahora) BETWEEN datetime(?) AND datetime(?)
        ORDER BY datetime(datahora) DESC LIMIT 25
    """, (equipamento_id, data_ini+' 00:00:00', data_fim+' 23:59:59'))
    medicoes = c.fetchall()

    c.execute("""
        SELECT id, start_time, stop_time, duracao_min
        FROM motor_runs
        WHERE equipamento_id=? AND datetime(start_time) BETWEEN datetime(?) AND datetime(?)
        ORDER BY datetime(start_time) DESC LIMIT 20
    """, (equipamento_id, data_ini+' 00:00:00', data_fim+' 23:59:59'))
    runs = c.fetchall()

    c.execute("""
        SELECT datahora, local, equipamento, energia_ativa, pot_ativa, fp, ponta, corrente, tensao, observacoes
        FROM leituras
        WHERE lower(COALESCE(equipamento,''))=lower(?)
          AND datetime(datahora) BETWEEN datetime(?) AND datetime(?)
        ORDER BY datetime(datahora) DESC LIMIT 25
    """, ((equipamento.get('nome') or ''), data_ini+' 00:00:00', data_fim+' 23:59:59'))
    leituras_monitoria = c.fetchall()
    conn.close()

    if not analise:
        analise = {
            'id': equipamento_id, 'equipamento': equipamento, 'status': 'Sem dados', 'alertas': [],
            'n': 0, 'kwh': 0, 'avg_fp': None, 'avg_corr': None, 'corr_max': 0, 'avg_kw': None,
            'kw_max': 0, 'ponta_max': 0, 'horas': 0, 'arranques': 0, 'tensao_min': None,
            'tensao_max': None, 'agua': 0, 'ce': None, 'carga_pct': None, 'last_ts': '', 'fontes': '—'
        }
    kvar_sugerido = _motor_kvar_compensacao(analise.get('avg_kw'), analise.get('avg_fp'), 0.92)
    recomendacoes = _motor_recomendacoes_detalhadas(analise)
    return dict(equipamento=equipamento, analise=analise, medicoes=medicoes, runs=runs,
                leituras_monitoria=leituras_monitoria, data_ini=data_ini, data_fim=data_fim,
                kvar_sugerido=kvar_sugerido, recomendacoes=recomendacoes,
                gerado_em=datetime.now().strftime('%d/%m/%Y %H:%M'))


@app.route('/motores/manutencao', methods=['GET'])
def motor_manutencao():
    local_id = request.args.get('local_id', type=int)
    equip_id = request.args.get('equipamento_id', type=int)
    data_ini = request.args.get('ini')
    data_fim = request.args.get('fim')
    if not data_ini or not data_fim:
        data_ini, data_fim = _motor_intervalo_padrao()

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT id, nome FROM locais ORDER BY nome')
    locais = c.fetchall()
    c.execute('SELECT id, nome FROM equipamentos ORDER BY nome')
    equipamentos_select = c.fetchall()
    conn.close()

    analises, resumo, data_ini, data_fim = _motor_collect_stats(local_id, equip_id, data_ini, data_fim)

    planos = []
    for a in analises:
        score = 0
        if a.get('status') == 'Crítico': score += 70
        elif a.get('status') == 'Atenção': score += 40
        elif a.get('status') == 'Sem dados': score += 15
        score += min(len(a.get('alertas') or []) * 8, 30)
        if a.get('avg_fp') is not None and a.get('avg_fp') < 0.80: score += 12
        if a.get('corr_max') and a.get('avg_corr') and a.get('corr_max') > max(a.get('avg_corr')*1.35, 1): score += 8
        if a.get('carga_pct') is not None and (a.get('carga_pct') < 35 or a.get('carga_pct') > 105): score += 10
        score = min(score, 100)
        if score >= 75:
            prioridade = 'Alta'
            prazo = '0–7 dias'
        elif score >= 45:
            prioridade = 'Média'
            prazo = '7–30 dias'
        else:
            prioridade = 'Baixa'
            prazo = 'Próxima ronda'
        planos.append(dict(a=a, score=score, prioridade=prioridade, prazo=prazo,
                           recomendacoes=_motor_recomendacoes_detalhadas(a)))
    planos.sort(key=lambda x: x['score'], reverse=True)
    return render_template('motor_manutencao.html', locais=locais, equipamentos_select=equipamentos_select,
                           analises=analises, planos=planos, resumo=resumo, local_id=local_id or '',
                           equip_id=equip_id or '', data_ini=data_ini, data_fim=data_fim,
                           gerado_em=datetime.now().strftime('%d/%m/%Y %H:%M'))


@app.route('/motores/detalhe/<int:equipamento_id>/imprimir', methods=['GET'])
def motor_detalhe_imprimir(equipamento_id):
    ctx = _motor_contexto_detalhe(equipamento_id, request.args.get('ini'), request.args.get('fim'))
    if not ctx:
        flash('Equipamento não encontrado.', 'warning')
        return redirect(url_for('motores_menu'))
    return render_template('motor_detalhe_print.html', **ctx)


@app.route('/motores/export/diagnostico_csv', methods=['GET'])
def export_diagnostico_motores_csv():
    local_id = request.args.get('local_id', type=int)
    equip_id = request.args.get('equipamento_id', type=int)
    data_ini = request.args.get('ini')
    data_fim = request.args.get('fim')
    if not data_ini or not data_fim:
        data_ini, data_fim = _motor_intervalo_padrao()
    analises, resumo, data_ini, data_fim = _motor_collect_stats(local_id, equip_id, data_ini, data_fim)
    si = StringIO(); w = csv.writer(si, delimiter=';')
    w.writerow(['periodo_inicial','periodo_final','estado','equipamento','local','fontes','medicoes','energia_kwh','pot_media_kw','carga_pct','corrente_media_a','corrente_max_a','fp_medio','horas','arranques','tensao_min_v','tensao_max_v','alertas'])
    for a in analises:
        alertas = ' | '.join([f'{al[0]}: {al[1]}' for al in (a.get('alertas') or [])])
        eq = a.get('equipamento') or {}
        w.writerow([data_ini, data_fim, a.get('status'), eq.get('nome'), eq.get('local_nome'), a.get('fontes'), a.get('n'),
                    f"{a.get('kwh') or 0:.3f}", f"{a.get('avg_kw') or 0:.3f}" if a.get('avg_kw') is not None else '',
                    f"{a.get('carga_pct') or 0:.2f}" if a.get('carga_pct') is not None else '',
                    f"{a.get('avg_corr') or 0:.3f}" if a.get('avg_corr') is not None else '',
                    f"{a.get('corr_max') or 0:.3f}", f"{a.get('avg_fp') or 0:.4f}" if a.get('avg_fp') is not None else '',
                    f"{a.get('horas') or 0:.2f}", a.get('arranques') or 0,
                    f"{a.get('tensao_min') or 0:.2f}" if a.get('tensao_min') is not None else '',
                    f"{a.get('tensao_max') or 0:.2f}" if a.get('tensao_max') is not None else '', alertas])
    return Response(si.getvalue(), mimetype='text/csv', headers={'Content-Disposition': f'attachment;filename=diagnostico_motores_{data_ini}_a_{data_fim}.csv'})


# === ALERTAS ===


