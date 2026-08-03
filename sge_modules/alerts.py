"""Domínio alerts extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""

def _ensure_alertas_perf_indexes():
    """Índices leves para acelerar o Centro de Alertas. Idempotente."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('CREATE INDEX IF NOT EXISTS idx_leituras_datahora_local ON leituras(datahora, local)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_leituras_local_equip ON leituras(local, equipamento)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_lm_data_local ON leituras_mensais(data, local)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_motor_medicoes_data_equip ON motor_medicoes(datahora, equipamento_id)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_motor_runs_equip_start ON motor_runs(equipamento_id, start_time)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_equipamentos_local ON equipamentos(local_id)')
        conn.commit(); conn.close()
    except Exception:
        try:
            if conn: conn.close()
        except Exception:
            pass

def _alertas_hash(*parts):
    import hashlib
    raw = '|'.join(str(p or '') for p in parts)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]


def _ensure_alertas_acoes_schema():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS alertas_acoes (
            alerta_id TEXT PRIMARY KEY,
            estado TEXT DEFAULT 'Novo',
            responsavel TEXT,
            observacao TEXT,
            atualizado_em TEXT DEFAULT (datetime('now','localtime'))
        )
    """)
    existentes = {r[1] for r in c.execute('PRAGMA table_info(alertas_acoes)').fetchall()}
    extras = {
        'prazo': 'TEXT',
        'acao_tomada': 'TEXT',
        'fechado_em': 'TEXT',
        'prioridade_manual': 'TEXT',
        'evidencia': 'TEXT',
        'custo_estimado': 'REAL DEFAULT 0',
        'snapshot_nivel': 'TEXT',
        'snapshot_origem': 'TEXT',
        'snapshot_categoria': 'TEXT',
        'snapshot_local': 'TEXT',
        'snapshot_equipamento': 'TEXT',
        'snapshot_tipo': 'TEXT',
        'snapshot_causa': 'TEXT',
        'snapshot_impacto': 'TEXT',
        'snapshot_acao': 'TEXT',
        'snapshot_ultima': 'TEXT',
        'snapshot_link': 'TEXT',
        'manual': 'INTEGER DEFAULT 0'
    }
    for col, typ in extras.items():
        if col not in existentes:
            try:
                c.execute(f'ALTER TABLE alertas_acoes ADD COLUMN {col} {typ}')
            except Exception:
                pass
    try:
        c.execute('CREATE INDEX IF NOT EXISTS idx_alertas_acoes_estado ON alertas_acoes(estado)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_alertas_acoes_manual ON alertas_acoes(manual)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_alertas_acoes_atualizado ON alertas_acoes(atualizado_em)')
    except Exception:
        pass
    conn.commit(); conn.close()


def _load_alertas_acoes():
    _ensure_alertas_acoes_schema()
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    rows = conn.execute('SELECT * FROM alertas_acoes').fetchall()
    conn.close()
    return {r['alerta_id']: dict(r) for r in rows}




def _snapshot_to_event(row):
    """Converte alertas manuais/arquivados em eventos exibíveis, mesmo que a origem dinâmica já não gere o alerta."""
    return {
        'id': row.get('alerta_id') or '',
        'nivel': row.get('snapshot_nivel') or 'Informativo',
        'origem': row.get('snapshot_origem') or ('Manual / Operador' if row.get('manual') else 'Arquivo'),
        'local': row.get('snapshot_local') or '—',
        'equipamento': row.get('snapshot_equipamento') or '—',
        'tipo': row.get('snapshot_tipo') or 'Alerta registado',
        'causa': row.get('snapshot_causa') or 'Registo manual ou histórico preservado.',
        'impacto': row.get('snapshot_impacto') or 'Acompanhar impacto técnico/operacional.',
        'acao': row.get('snapshot_acao') or 'Definir e executar acção correctiva.',
        'ultima': row.get('snapshot_ultima') or row.get('atualizado_em') or '—',
        'impacto_mt': float(row.get('custo_estimado') or 0),
        'link': row.get('snapshot_link') or '',
        'estado': row.get('estado') or 'Novo',
        'responsavel': row.get('responsavel') or '',
        'observacao': row.get('observacao') or '',
        'acao_tomada': row.get('acao_tomada') or '',
        'prazo': row.get('prazo') or '',
        'fechado_em': row.get('fechado_em') or '',
        'atualizado_em': row.get('atualizado_em') or '',
        'evidencia': row.get('evidencia') or '',
        'categoria': row.get('snapshot_categoria') or _categoria_alerta(row.get('snapshot_tipo'), row.get('snapshot_origem')),
        'score': 0,
        'sla': 'Sem prazo',
        'prazo_sugerido': '',
        'manual': int(row.get('manual') or 0),
    }


def _alertas_saved_snapshot_rows(only_manual=False):
    _ensure_alertas_acoes_schema()
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    sql = 'SELECT * FROM alertas_acoes'
    params = []
    if only_manual:
        sql += ' WHERE COALESCE(manual,0)=1'
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def _fmt_mt(v):
    try:
        return f"{float(v):,.2f}".replace(',', 'X').replace('.', ',').replace('X', '.') + ' MT'
    except Exception:
        return '0,00 MT'


def _nivel_peso(nivel):
    return {'Crítico': 0, 'Atenção': 1, 'Informativo': 2}.get(nivel, 9)


def _categoria_alerta(tipo, origem=''):
    t = (tipo or '').lower(); o = (origem or '').lower()
    if 'fp' in t or 'fator' in t or 'reativa' in t:
        return 'Energia reativa / FP'
    if 'tensão' in t or 'tensao' in t:
        return 'Qualidade de energia'
    if 'corrente' in t or 'sobrecarga' in t or 'arranque' in t or 'motor' in o:
        return 'Motores e cargas'
    if 'ponta' in t or 'demanda' in t:
        return 'Ponta / demanda'
    if 'específico' in t or 'agua' in t or 'água' in t:
        return 'Eficiência hidráulica'
    if 'fatura' in t or 'factura' in t:
        return 'Faturação'
    if 'leitura' in t:
        return 'Dados / leituras'
    return 'Operacional'


def _prazo_sugerido(nivel, tipo):
    hoje = datetime.now().date()
    t = (tipo or '').lower()
    if nivel == 'Crítico':
        dias = 2
    elif nivel == 'Atenção':
        dias = 7
    else:
        dias = 15
    if 'tensão' in t or 'corrente' in t or 'sobrecarga' in t:
        dias = min(dias, 3 if nivel == 'Crítico' else 5)
    return (hoje + timedelta(days=dias)).isoformat()


def _score_alerta(e):
    base = {'Crítico': 90, 'Atenção': 60, 'Informativo': 25}.get(e.get('nivel'), 10)
    tipo = (e.get('tipo') or '').lower()
    if any(x in tipo for x in ['reativa', 'ponta', 'fatura', 'factura']): base += 8
    if any(x in tipo for x in ['sobrecarga', 'tensão', 'corrente']): base += 10
    if e.get('estado') == 'Resolvido': base -= 60
    if e.get('estado') == 'Ignorado': base -= 50
    if e.get('estado') == 'Em análise': base -= 10
    return max(0, min(100, base))


def _classificar_sla(e):
    estado = e.get('estado') or 'Novo'
    if estado in ('Resolvido', 'Ignorado'):
        return 'Fechado'
    prazo = e.get('prazo') or e.get('prazo_sugerido') or ''
    try:
        d = datetime.strptime(prazo[:10], '%Y-%m-%d').date()
        hoje = datetime.now().date()
        if d < hoje:
            return 'Vencido'
        if (d - hoje).days <= 2:
            return 'A vencer'
        return 'No prazo'
    except Exception:
        return 'Sem prazo'


def _add_alerta_evento(eventos, nivel, origem, local, equipamento, tipo, causa, impacto, acao, ultima='—', impacto_mt=0, link=None, chave_extra=''):
    alerta_id = _alertas_hash(nivel, origem, local, equipamento, tipo, ultima, chave_extra)
    eventos.append({
        'id': alerta_id,
        'nivel': nivel,
        'origem': origem,
        'local': local or '—',
        'equipamento': equipamento or '—',
        'tipo': tipo,
        'causa': causa,
        'impacto': impacto,
        'acao': acao,
        'ultima': ultima or '—',
        'impacto_mt': float(impacto_mt or 0),
        'link': link or '',
        'estado': 'Novo',
        'responsavel': '',
        'observacao': '',
        'acao_tomada': '',
        'prazo': '',
        'fechado_em': '',
        'atualizado_em': '',
        'categoria': _categoria_alerta(tipo, origem),
        'score': 0,
        'sla': 'Sem prazo',
        'prazo_sugerido': '',
    })


def _collect_alertas_monitoria(local_nome=None, data_ini=None, data_fim=None):
    eventos = []
    try:
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
        c = conn.cursor()
        sql = """SELECT id, datahora, local, equipamento, energia_ativa, energia_reativa, pot_ativa, fp, ponta, caudal_elevada, corrente, tensao
                 FROM leituras WHERE date(substr(datahora,1,10)) BETWEEN date(?) AND date(?)"""
        params = [data_ini, data_fim]
        if local_nome:
            if isinstance(local_nome, (list, tuple, set)):
                nomes = [x for x in local_nome if str(x).strip()]
                if nomes:
                    sql += ' AND local IN (' + ','.join('?' for _ in nomes) + ')'; params.extend(nomes)
            else:
                sql += ' AND local=?'; params.append(local_nome)
        sql += ' ORDER BY datetime(datahora) DESC LIMIT 1500'
        rows = c.execute(sql, params).fetchall()
        conn.close()
        correntes = [float(r['corrente'] or 0) for r in rows if float(r['corrente'] or 0) > 0]
        pontas = [float(r['ponta'] or 0) for r in rows if float(r['ponta'] or 0) > 0]
        corrente_ref = (sum(correntes) / len(correntes) * 1.35) if correntes else 0
        ponta_ref = (sum(pontas) / len(pontas) * 1.40) if pontas else 0
        for r in rows:
            fp = float(r['fp'] or 0)
            tensao = float(r['tensao'] or 0)
            corrente = float(r['corrente'] or 0)
            ponta = float(r['ponta'] or 0)
            kwh = float(r['energia_ativa'] or 0)
            agua = float(r['caudal_elevada'] or 0)
            ult = r['datahora'] or '—'
            local = r['local'] or '—'; eq = r['equipamento'] or '—'
            if fp and fp < 0.80:
                _add_alerta_evento(eventos, 'Crítico', 'Monitoria Operacional', local, eq, 'Fator de potência muito baixo', 'FP medido abaixo de 0,80.', 'Aumenta perdas, aquecimento e risco de reativa excedente na instalação.', 'Verificar banco de capacitores, cargas em vazio e regime de operação.', ult, 0, '/monitoria', r['id'])
            elif fp and fp < 0.85:
                _add_alerta_evento(eventos, 'Atenção', 'Monitoria Operacional', local, eq, 'Fator de potência baixo', 'FP medido abaixo do limite operacional recomendado.', 'Pode contribuir para penalizações e baixa eficiência.', 'Acompanhar recorrência e avaliar necessidade de correção do FP.', ult, 0, '/monitoria', r['id'])
            if tensao and (tensao < 360 or tensao > 440):
                nivel = 'Crítico' if tensao < 340 or tensao > 460 else 'Atenção'
                _add_alerta_evento(eventos, nivel, 'Monitoria Operacional', local, eq, 'Tensão fora da faixa', f'Tensão registada: {tensao:.1f} V.', 'Pode provocar falhas, aquecimento ou disparos de proteção.', 'Confirmar medição por fase, queda de tensão, ligações e estado do transformador/quadro.', ult, 0, '/monitoria', r['id'])
            if corrente_ref and corrente > corrente_ref:
                _add_alerta_evento(eventos, 'Atenção', 'Monitoria Operacional', local, eq, 'Corrente acima do padrão', f'Corrente registada: {corrente:.1f} A.', 'Possível sobrecarga, desequilíbrio ou alteração mecânica na carga.', 'Comparar com corrente nominal do equipamento e inspecionar a carga.', ult, 0, '/monitoria', r['id'])
            if ponta_ref and ponta > ponta_ref:
                _add_alerta_evento(eventos, 'Atenção', 'Monitoria Operacional', local, eq, 'Ponta operacional elevada', f'Ponta registada: {ponta:.2f} kW.', 'Pode elevar a procura máxima mensal.', 'Avaliar arranques simultâneos e escalonamento de cargas.', ult, 0, '/monitoria', r['id'])
            if kwh > 0 and agua > 0 and (kwh/agua) > 5:
                _add_alerta_evento(eventos, 'Atenção', 'Monitoria Operacional', local, eq, 'Consumo específico elevado', f'{(kwh/agua):.3f} kWh/m³.', 'Indica possível queda de eficiência no sistema de bombagem.', 'Verificar caudal, pressão, filtros, válvulas e ponto de operação da bomba.', ult, 0, '/monitoria', r['id'])
    except Exception:
        pass
    return eventos


def _collect_alertas_mensais(local_nome=None, data_ini=None, data_fim=None):
    eventos = []
    try:
        ensure_faturas_mensais_archive_schema()
        conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
        c = conn.cursor()
        sql = """SELECT local, data, mes, ano, ativa, reativa, ponta, fp, diferenca, agua, esp, valor
                 FROM leituras_mensais WHERE date(data) BETWEEN date(?) AND date(?)"""
        params = [data_ini, data_fim]
        if local_nome:
            if isinstance(local_nome, (list, tuple, set)):
                nomes = [x for x in local_nome if str(x).strip()]
                if nomes:
                    sql += ' AND local IN (' + ','.join('?' for _ in nomes) + ')'; params.extend(nomes)
            else:
                sql += ' AND local=?'; params.append(local_nome)
        sql += ' ORDER BY date(data) DESC LIMIT 1500'
        rows = c.execute(sql, params).fetchall()
        fatur_sql = """SELECT local, mes, ano, total, kvarh_excedente, demanda_ponta_kw, consumo_especifico, atualizado_em
                             FROM faturas_mensais_arquivo"""
        fatur_params = []
        if local_nome:
            if isinstance(local_nome, (list, tuple, set)):
                nomes = [x for x in local_nome if str(x).strip()]
                if nomes:
                    fatur_sql += ' WHERE local IN (' + ','.join('?' for _ in nomes) + ')'; fatur_params.extend(nomes)
            else:
                fatur_sql += ' WHERE local=?'; fatur_params.append(local_nome)
        fatur_sql += ' ORDER BY atualizado_em DESC LIMIT 300'
        fatur = c.execute(fatur_sql, fatur_params).fetchall()
        conn.close()
        for r in rows:
            ult = r['data'] or '—'; local = r['local'] or '—'
            fp = float(r['fp'] or 0); dif = float(r['diferenca'] or 0); esp = float(r['esp'] or 0); agua = float(r['agua'] or 0)
            if dif < 0:
                _add_alerta_evento(eventos, 'Crítico', 'Leituras Mensais', local, 'Instalação', 'Leitura ativa decrescente', 'A leitura atual ficou inferior à leitura anterior.', 'Pode gerar fatura incorreta e distorcer energia ativa.', 'Conferir leitura do contador, fator multiplicativo e leitura do mês anterior.', ult, 0, '/leituras_mensal', f"{local}-{ult}-dif")
            if fp and fp < 0.80:
                _add_alerta_evento(eventos, 'Crítico', 'Leituras Mensais', local, 'Instalação', 'FP mensal diário muito baixo', f'FP = {fp:.3f}.', 'Risco direto de reativa excedente e perdas internas.', 'Avaliar compensação reativa e operação das cargas indutivas.', ult, 0, '/leituras_mensal', f"{local}-{ult}-fp")
            elif fp and fp < 0.85:
                _add_alerta_evento(eventos, 'Atenção', 'Leituras Mensais', local, 'Instalação', 'FP mensal diário baixo', f'FP = {fp:.3f}.', 'Pode aumentar reativa excedente no fecho do mês.', 'Monitorar e acionar plano de correção caso se repita.', ult, 0, '/leituras_mensal', f"{local}-{ult}-fp")
            if dif > 0 and agua <= 0:
                _add_alerta_evento(eventos, 'Informativo', 'Leituras Mensais', local, 'Instalação', 'Água não registada', 'Existe consumo de energia sem volume de água informado.', 'Impede cálculo confiável do consumo específico.', 'Preencher água elevada/produzida para análise energética.', ult, 0, '/leituras_mensal', f"{local}-{ult}-agua")
            if esp and esp > 5:
                _add_alerta_evento(eventos, 'Atenção', 'Leituras Mensais', local, 'Instalação', 'Consumo específico mensal elevado', f'{esp:.3f} kWh/m³.', 'Pode indicar operação fora do ponto eficiente ou perda hidráulica.', 'Comparar com histórico, verificar caudal, pressão, válvulas e bombas.', ult, 0, '/leituras_mensal', f"{local}-{ult}-esp")
        for f in fatur:
            if local_nome and f['local'] != local_nome:
                continue
            total = float(f['total'] or 0); kvar = float(f['kvarh_excedente'] or 0); ce = float(f['consumo_especifico'] or 0)
            ult = f"{str(f['mes']).zfill(2)}/{f['ano']}"
            if kvar > 0:
                _add_alerta_evento(eventos, 'Atenção', 'Fatura EDM', f['local'], 'Instalação', 'Reativa excedente faturada', f'Reativa excedente: {kvar:,.2f} kVArh.'.replace(',', 'X').replace('.', ',').replace('X','.'), 'Aumenta o valor da fatura e indica baixo fator de potência.', 'Verificar banco de capacitores e perfis de carga do período.', ult, 0, '/leituras_mensal/faturas', f"{f['local']}-{ult}-kvar")
            if total > 0:
                _add_alerta_evento(eventos, 'Informativo', 'Fatura EDM', f['local'], 'Instalação', 'Fatura arquivada', f'Total: {_fmt_mt(total)}.', 'Fatura disponível no arquivo para consulta e descarga.', 'Conferir valores e manter o mês fechado após validação.', ult, total, '/leituras_mensal/faturas', f"{f['local']}-{ult}-fat")
            if ce and ce > 5:
                _add_alerta_evento(eventos, 'Atenção', 'Fatura EDM', f['local'], 'Instalação', 'Consumo específico mensal elevado', f'{ce:.3f} kWh/m³.', 'Pode representar custo excessivo de bombagem.', 'Priorizar auditoria hidráulica e elétrica da instalação.', ult, 0, '/leituras_mensal/faturas', f"{f['local']}-{ult}-ce")
    except Exception:
        pass
    return eventos


def _collect_alertas_motores(local_id=None, data_ini=None, data_fim=None):
    eventos = []
    try:
        analises, resumo, _, _ = _motor_collect_stats(local_id, None, data_ini, data_fim)
        max_motor_alertas = 220
        for a in analises:
            if len(eventos) >= max_motor_alertas:
                break
            for nivel, titulo, acao in a.get('alertas') or []:
                titulo_norm = (titulo or '').lower()
                # Evita gerar centenas de alertas informativos "Sem medições", que deixavam a página lenta.
                if 'sem medi' in titulo_norm or 'sem dados' in titulo_norm:
                    continue
                eq = a.get('equipamento') or {}
                _add_alerta_evento(
                    eventos, nivel, 'Motores', eq.get('local_nome') or '—', eq.get('nome') or '—', titulo,
                    'Diagnóstico automático do desempenho electromecânico.',
                    'Pode afetar rendimento, disponibilidade, consumo energético ou manutenção.',
                    acao, a.get('last_ts') or '—', 0, f"/motores/detalhe/{a.get('id')}", a.get('id')
                )
                if len(eventos) >= max_motor_alertas:
                    break
        return eventos, resumo
    except Exception:
        return eventos, {'equipamentos': 0}


def _preparar_eventos_alertas(local_id=None, data_ini=None, data_fim=None, origem_filtro='', nivel_filtro='', estado_filtro='', categoria_filtro='', sla_filtro=''):
    _ensure_alertas_perf_indexes()
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    locais_rows = conn.execute('SELECT id, nome FROM locais ORDER BY nome').fetchall()
    conn.close()
    local_nome = ''
    local_ids_scope = []
    local_names_scope = []
    if local_id:
        local_ids_scope = get_descendant_local_ids(local_id, include_self=True)
        local_names_scope = get_local_names_for_ids(local_ids_scope)
        for l in locais_rows:
            if int(l['id']) == int(local_id):
                local_nome = l['nome']; break

    eventos = []
    motor_resumo = {'equipamentos': 0}
    # Coleta selectiva por origem: evita processar todos os módulos quando o utilizador filtra uma origem.
    if not origem_filtro or origem_filtro == 'Motores':
        motor_eventos, motor_resumo = _collect_alertas_motores(local_id, data_ini, data_fim)
        eventos.extend(motor_eventos)
    if not origem_filtro or origem_filtro == 'Monitoria Operacional':
        eventos.extend(_collect_alertas_monitoria((local_names_scope or None) if local_id else None, data_ini, data_fim))
    if not origem_filtro or origem_filtro in ('Leituras Mensais', 'Fatura EDM'):
        eventos.extend(_collect_alertas_mensais((local_names_scope or None) if local_id else None, data_ini, data_fim))

    acoes = _load_alertas_acoes()
    dyn_ids = {e.get('id') for e in eventos}
    # Acrescenta alertas manuais e alertas arquivados que já não aparecem nas origens dinâmicas,
    # preservando histórico e rastreabilidade operacional.
    for aid, row in acoes.items():
        if aid not in dyn_ids and (row.get('manual') or row.get('snapshot_tipo')):
            eventos.append(_snapshot_to_event(row))

    for e in eventos:
        st = acoes.get(e['id'], {})
        if st:
            e['estado'] = st.get('estado') or e.get('estado') or 'Novo'
            e['responsavel'] = st.get('responsavel') or ''
            e['observacao'] = st.get('observacao') or ''
            e['acao_tomada'] = st.get('acao_tomada') or ''
            e['prazo'] = st.get('prazo') or e.get('prazo') or ''
            e['fechado_em'] = st.get('fechado_em') or ''
            e['atualizado_em'] = st.get('atualizado_em') or ''
            e['evidencia'] = st.get('evidencia') or ''
            if st.get('custo_estimado') not in (None, ''):
                try: e['impacto_mt'] = float(st.get('custo_estimado') or e.get('impacto_mt') or 0)
                except Exception: pass
        e['categoria'] = e.get('categoria') or _categoria_alerta(e.get('tipo'), e.get('origem'))
        e['prazo_sugerido'] = _prazo_sugerido(e.get('nivel'), e.get('tipo'))
        if not e.get('prazo'):
            e['prazo'] = e['prazo_sugerido']
        e['sla'] = _classificar_sla(e)
        e['score'] = _score_alerta(e)

    if origem_filtro:
        eventos = [e for e in eventos if e['origem'] == origem_filtro]
    if nivel_filtro:
        eventos = [e for e in eventos if e['nivel'] == nivel_filtro]
    if estado_filtro:
        eventos = [e for e in eventos if e['estado'] == estado_filtro]
    if categoria_filtro:
        eventos = [e for e in eventos if e['categoria'] == categoria_filtro]
    if sla_filtro:
        eventos = [e for e in eventos if e['sla'] == sla_filtro]

    eventos.sort(key=lambda x: (_nivel_peso(x['nivel']), {'Vencido':0,'A vencer':1,'No prazo':2,'Sem prazo':3,'Fechado':4}.get(x.get('sla','Sem prazo'),9), -x.get('score',0), {'Novo':0,'Em análise':1,'Resolvido':2,'Ignorado':3}.get(x.get('estado','Novo'),9)))
    # Protecção de desempenho: a tela principal mostra alertas prioritários em vez de renderizar milhares de linhas.
    if len(eventos) > 650:
        eventos = eventos[:650]
    resumo = {
        'total': len(eventos),
        'criticos': sum(1 for e in eventos if e['nivel'] == 'Crítico'),
        'atencao': sum(1 for e in eventos if e['nivel'] == 'Atenção'),
        'informativos': sum(1 for e in eventos if e['nivel'] == 'Informativo'),
        'novos': sum(1 for e in eventos if e['estado'] == 'Novo'),
        'analise': sum(1 for e in eventos if e['estado'] == 'Em análise'),
        'resolvidos': sum(1 for e in eventos if e['estado'] == 'Resolvido'),
        'ignorados': sum(1 for e in eventos if e['estado'] == 'Ignorado'),
        'pendentes': sum(1 for e in eventos if e['estado'] not in ('Resolvido','Ignorado')),
        'vencidos': sum(1 for e in eventos if e['sla'] == 'Vencido'),
        'a_vencer': sum(1 for e in eventos if e['sla'] == 'A vencer'),
        'impacto_mt': sum(float(e.get('impacto_mt') or 0) for e in eventos),
        'equipamentos': motor_resumo.get('equipamentos', 0) if isinstance(motor_resumo, dict) else 0,
    }
    resumo['taxa_resolucao'] = round((resumo['resolvidos'] / resumo['total'] * 100), 1) if resumo['total'] else 0
    if resumo['criticos'] > 0 or resumo['vencidos'] > 0:
        estado_geral = 'Crítico'
    elif resumo['atencao'] > 0 or resumo['a_vencer'] > 0:
        estado_geral = 'Atenção'
    elif resumo['total'] > 0:
        estado_geral = 'Informativo'
    else:
        estado_geral = 'Normal'

    origem_counts, categoria_counts, sla_counts, local_counts = {}, {}, {}, {}
    for e in eventos:
        origem_counts[e['origem']] = origem_counts.get(e['origem'], 0) + 1
        categoria_counts[e['categoria']] = categoria_counts.get(e['categoria'], 0) + 1
        sla_counts[e['sla']] = sla_counts.get(e['sla'], 0) + 1
        local_counts[e['local']] = local_counts.get(e['local'], 0) + 1
    ranking_locais = sorted(local_counts.items(), key=lambda x: x[1], reverse=True)[:8]
    return eventos, resumo, locais_rows, estado_geral, origem_counts, categoria_counts, sla_counts, ranking_locais




def _alertas_request_filters():
    local_id = request.args.get('local_id', type=int)
    origem_filtro = request.args.get('origem', '').strip()
    nivel_filtro = request.args.get('nivel', '').strip()
    estado_filtro = request.args.get('estado', '').strip()
    categoria_filtro = request.args.get('categoria', '').strip()
    sla_filtro = request.args.get('sla', '').strip()
    data_ini = request.args.get('ini')
    data_fim = request.args.get('fim')
    if not data_ini or not data_fim:
        data_ini, data_fim = _motor_intervalo_padrao()
    return local_id, origem_filtro, nivel_filtro, estado_filtro, categoria_filtro, sla_filtro, data_ini, data_fim


@app.route('/alertas/kanban')
def alertas_kanban():
    local_id, origem_filtro, nivel_filtro, estado_filtro, categoria_filtro, sla_filtro, data_ini, data_fim = _alertas_request_filters()
    eventos, resumo, locais_rows, estado_geral, origem_counts, categoria_counts, sla_counts, ranking_locais = _preparar_eventos_alertas(local_id, data_ini, data_fim, origem_filtro, nivel_filtro, '', categoria_filtro, sla_filtro)
    colunas = {k: [] for k in ['Novo','Em análise','Resolvido','Ignorado']}
    for e in eventos:
        colunas.setdefault(e.get('estado') or 'Novo', []).append(e)
    return render_template('alertas_kanban.html', colunas=colunas, eventos=eventos, resumo=resumo,
                           data_ini=data_ini, data_fim=data_fim, estado_geral=estado_geral,
                           local_id=local_id or '', origem_filtro=origem_filtro, nivel_filtro=nivel_filtro,
                           categoria_filtro=categoria_filtro, sla_filtro=sla_filtro)


@app.route('/alertas/historico')
def alertas_historico():
    _ensure_alertas_acoes_schema()
    estado = request.args.get('estado','').strip()
    conn = sqlite3.connect(DB_PATH); conn.row_factory = sqlite3.Row
    sql = 'SELECT * FROM alertas_acoes'
    params = []
    if estado:
        sql += ' WHERE estado=?'; params.append(estado)
    sql += ' ORDER BY COALESCE(atualizado_em, fechado_em, prazo) DESC'
    rows = [dict(r) for r in conn.execute(sql, params).fetchall()]
    conn.close()
    eventos = [_snapshot_to_event(r) for r in rows]
    for e in eventos:
        e['categoria'] = e.get('categoria') or _categoria_alerta(e.get('tipo'), e.get('origem'))
        e['prazo_sugerido'] = _prazo_sugerido(e.get('nivel'), e.get('tipo'))
        if not e.get('prazo'): e['prazo'] = e['prazo_sugerido']
        e['sla'] = _classificar_sla(e)
        e['score'] = _score_alerta(e)
    return render_template('alertas_historico.html', eventos=eventos, estado=estado)


@app.route('/alertas/manual', methods=['POST'])
def alertas_manual():
    _ensure_alertas_acoes_schema()
    nivel = request.form.get('nivel','Atenção').strip() or 'Atenção'
    local = request.form.get('local','').strip() or '—'
    equipamento = request.form.get('equipamento','').strip() or '—'
    tipo = request.form.get('tipo','Alerta manual').strip() or 'Alerta manual'
    causa = request.form.get('causa','Registo manual do operador.').strip() or 'Registo manual do operador.'
    impacto = request.form.get('impacto','Impacto operacional a acompanhar.').strip() or 'Impacto operacional a acompanhar.'
    acao = request.form.get('acao','Avaliar e executar acção correctiva.').strip() or 'Avaliar e executar acção correctiva.'
    responsavel = request.form.get('responsavel','').strip()
    prazo = request.form.get('prazo','').strip() or _prazo_sugerido(nivel, tipo)
    custo = request.form.get('custo_estimado','0').replace(',','.')
    try: custo = float(custo or 0)
    except Exception: custo = 0.0
    aid = 'manual_' + _alertas_hash(datetime.now().isoformat(), nivel, local, equipamento, tipo)
    categoria = _categoria_alerta(tipo, 'Manual / Operador')
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""INSERT INTO alertas_acoes(alerta_id, estado, responsavel, observacao, acao_tomada, prazo, atualizado_em,
                 evidencia, custo_estimado, snapshot_nivel, snapshot_origem, snapshot_categoria, snapshot_local,
                 snapshot_equipamento, snapshot_tipo, snapshot_causa, snapshot_impacto, snapshot_acao, snapshot_ultima,
                 snapshot_link, manual)
                 VALUES(?,?,?,?,?,?,datetime('now','localtime'),?,?,?,?,?,?,?,?,?,?,?,?,?,1)""",
              (aid, 'Novo', responsavel, '', '', prazo, '', custo, nivel, 'Manual / Operador', categoria, local,
               equipamento, tipo, causa, impacto, acao, datetime.now().strftime('%Y-%m-%d %H:%M'), '',))
    conn.commit(); conn.close()
    return redirect(request.form.get('next') or url_for('alertas'))

@app.route('/alertas', methods=['GET'])
def alertas():
    local_id = request.args.get('local_id', type=int)
    origem_filtro = request.args.get('origem', '').strip()
    nivel_filtro = request.args.get('nivel', '').strip()
    estado_filtro = request.args.get('estado', '').strip()
    categoria_filtro = request.args.get('categoria', '').strip()
    sla_filtro = request.args.get('sla', '').strip()
    data_ini = request.args.get('ini')
    data_fim = request.args.get('fim')
    if not data_ini or not data_fim:
        data_ini, data_fim = _motor_intervalo_padrao()
    eventos, resumo, locais_rows, estado_geral, origem_counts, categoria_counts, sla_counts, ranking_locais = _preparar_eventos_alertas(local_id, data_ini, data_fim, origem_filtro, nivel_filtro, estado_filtro, categoria_filtro, sla_filtro)
    return render_template('alertas.html', eventos=eventos, resumo=resumo, locais=locais_rows,
                           local_id=local_id or '', data_ini=data_ini, data_fim=data_fim,
                           estado_geral=estado_geral, origem_counts=origem_counts,
                           categoria_counts=categoria_counts, sla_counts=sla_counts,
                           ranking_locais=ranking_locais,
                           origem_filtro=origem_filtro, nivel_filtro=nivel_filtro,
                           estado_filtro=estado_filtro, categoria_filtro=categoria_filtro, sla_filtro=sla_filtro)


@app.route('/alertas/acao', methods=['POST'])
def alertas_acao():
    _ensure_alertas_acoes_schema()
    alerta_id = request.form.get('alerta_id', '').strip()
    estado = request.form.get('estado', 'Em análise').strip()
    responsavel = request.form.get('responsavel', '').strip()
    observacao = request.form.get('observacao', '').strip()
    acao_tomada = request.form.get('acao_tomada', '').strip()
    evidencia = request.form.get('evidencia', '').strip()
    prazo = request.form.get('prazo', '').strip()
    custo_raw = request.form.get('custo_estimado', '').strip().replace(',','.')
    try: custo_estimado = float(custo_raw) if custo_raw != '' else 0.0
    except Exception: custo_estimado = 0.0
    snap = {k: request.form.get(k, '').strip() for k in ['snapshot_nivel','snapshot_origem','snapshot_categoria','snapshot_local','snapshot_equipamento','snapshot_tipo','snapshot_causa','snapshot_impacto','snapshot_acao','snapshot_ultima','snapshot_link']}
    next_url = request.form.get('next') or url_for('alertas')
    if not alerta_id:
        return redirect(next_url)
    if estado not in ('Novo', 'Em análise', 'Resolvido', 'Ignorado'):
        estado = 'Em análise'
    fechado_em = "datetime('now','localtime')" if estado in ('Resolvido','Ignorado') else 'NULL'
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute(f"""INSERT INTO alertas_acoes(alerta_id, estado, responsavel, observacao, acao_tomada, prazo, fechado_em, atualizado_em,
                    evidencia, custo_estimado, snapshot_nivel, snapshot_origem, snapshot_categoria, snapshot_local, snapshot_equipamento,
                    snapshot_tipo, snapshot_causa, snapshot_impacto, snapshot_acao, snapshot_ultima, snapshot_link)
                 VALUES(?,?,?,?,?,?,{fechado_em},datetime('now','localtime'),?,?,?,?,?,?,?,?,?,?,?,?,?)
                 ON CONFLICT(alerta_id) DO UPDATE SET
                    estado=excluded.estado,
                    responsavel=excluded.responsavel,
                    observacao=excluded.observacao,
                    acao_tomada=excluded.acao_tomada,
                    prazo=excluded.prazo,
                    fechado_em={fechado_em},
                    evidencia=excluded.evidencia,
                    custo_estimado=excluded.custo_estimado,
                    snapshot_nivel=CASE WHEN excluded.snapshot_nivel!='' THEN excluded.snapshot_nivel ELSE alertas_acoes.snapshot_nivel END,
                    snapshot_origem=CASE WHEN excluded.snapshot_origem!='' THEN excluded.snapshot_origem ELSE alertas_acoes.snapshot_origem END,
                    snapshot_categoria=CASE WHEN excluded.snapshot_categoria!='' THEN excluded.snapshot_categoria ELSE alertas_acoes.snapshot_categoria END,
                    snapshot_local=CASE WHEN excluded.snapshot_local!='' THEN excluded.snapshot_local ELSE alertas_acoes.snapshot_local END,
                    snapshot_equipamento=CASE WHEN excluded.snapshot_equipamento!='' THEN excluded.snapshot_equipamento ELSE alertas_acoes.snapshot_equipamento END,
                    snapshot_tipo=CASE WHEN excluded.snapshot_tipo!='' THEN excluded.snapshot_tipo ELSE alertas_acoes.snapshot_tipo END,
                    snapshot_causa=CASE WHEN excluded.snapshot_causa!='' THEN excluded.snapshot_causa ELSE alertas_acoes.snapshot_causa END,
                    snapshot_impacto=CASE WHEN excluded.snapshot_impacto!='' THEN excluded.snapshot_impacto ELSE alertas_acoes.snapshot_impacto END,
                    snapshot_acao=CASE WHEN excluded.snapshot_acao!='' THEN excluded.snapshot_acao ELSE alertas_acoes.snapshot_acao END,
                    snapshot_ultima=CASE WHEN excluded.snapshot_ultima!='' THEN excluded.snapshot_ultima ELSE alertas_acoes.snapshot_ultima END,
                    snapshot_link=CASE WHEN excluded.snapshot_link!='' THEN excluded.snapshot_link ELSE alertas_acoes.snapshot_link END,
                    atualizado_em=datetime('now','localtime')""",
              (alerta_id, estado, responsavel, observacao, acao_tomada, prazo, evidencia, custo_estimado,
               snap['snapshot_nivel'], snap['snapshot_origem'], snap['snapshot_categoria'], snap['snapshot_local'], snap['snapshot_equipamento'],
               snap['snapshot_tipo'], snap['snapshot_causa'], snap['snapshot_impacto'], snap['snapshot_acao'], snap['snapshot_ultima'], snap['snapshot_link']))
    conn.commit(); conn.close()
    return redirect(next_url)


@app.route('/alertas/acao_lote', methods=['POST'])
def alertas_acao_lote():
    _ensure_alertas_acoes_schema()
    ids = request.form.getlist('alerta_ids')
    estado = request.form.get('estado_lote', 'Em análise')
    responsavel = request.form.get('responsavel_lote', '').strip()
    observacao = request.form.get('observacao_lote', '').strip()
    next_url = request.form.get('next') or url_for('alertas')
    if estado not in ('Novo','Em análise','Resolvido','Ignorado'):
        estado = 'Em análise'
    if ids:
        fechado_expr = "datetime('now','localtime')" if estado in ('Resolvido','Ignorado') else 'NULL'
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        for alerta_id in ids:
            c.execute(f"""INSERT INTO alertas_acoes(alerta_id, estado, responsavel, observacao, atualizado_em, fechado_em)
                         VALUES(?,?,?,?,datetime('now','localtime'),{fechado_expr})
                         ON CONFLICT(alerta_id) DO UPDATE SET
                            estado=excluded.estado,
                            responsavel=COALESCE(NULLIF(excluded.responsavel,''), alertas_acoes.responsavel),
                            observacao=CASE WHEN excluded.observacao!='' THEN excluded.observacao ELSE alertas_acoes.observacao END,
                            atualizado_em=datetime('now','localtime'),
                            fechado_em={fechado_expr}""",
                      (alerta_id, estado, responsavel, observacao))
        conn.commit(); conn.close()
    return redirect(next_url)


@app.route('/alertas/relatorio')
def alertas_relatorio():
    local_id = request.args.get('local_id', type=int)
    origem_filtro = request.args.get('origem', '').strip()
    nivel_filtro = request.args.get('nivel', '').strip()
    estado_filtro = request.args.get('estado', '').strip()
    categoria_filtro = request.args.get('categoria', '').strip()
    sla_filtro = request.args.get('sla', '').strip()
    data_ini = request.args.get('ini')
    data_fim = request.args.get('fim')
    if not data_ini or not data_fim:
        data_ini, data_fim = _motor_intervalo_padrao()
    eventos, resumo, locais_rows, estado_geral, origem_counts, categoria_counts, sla_counts, ranking_locais = _preparar_eventos_alertas(local_id, data_ini, data_fim, origem_filtro, nivel_filtro, estado_filtro, categoria_filtro, sla_filtro)
    return render_template('alertas_relatorio.html', eventos=eventos[:80], resumo=resumo, locais=locais_rows,
                           data_ini=data_ini, data_fim=data_fim, estado_geral=estado_geral,
                           origem_counts=origem_counts, categoria_counts=categoria_counts,
                           sla_counts=sla_counts, ranking_locais=ranking_locais, gerado_em=datetime.now().strftime('%d/%m/%Y %H:%M'))


@app.route('/alertas/export/csv')
def alertas_export_csv():
    local_id = request.args.get('local_id', type=int)
    origem_filtro = request.args.get('origem', '').strip()
    nivel_filtro = request.args.get('nivel', '').strip()
    estado_filtro = request.args.get('estado', '').strip()
    categoria_filtro = request.args.get('categoria', '').strip()
    sla_filtro = request.args.get('sla', '').strip()
    data_ini = request.args.get('ini')
    data_fim = request.args.get('fim')
    if not data_ini or not data_fim:
        data_ini, data_fim = _motor_intervalo_padrao()
    eventos, resumo, *_ = _preparar_eventos_alertas(local_id, data_ini, data_fim, origem_filtro, nivel_filtro, estado_filtro, categoria_filtro, sla_filtro)
    si = StringIO(); w = csv.writer(si, delimiter=';')
    w.writerow(['id','nivel','score','sla','prazo','estado','origem','categoria','local','equipamento','tipo','causa','impacto','acao_recomendada','acao_tomada','evidencia','ultima','responsavel','observacao','impacto_mt'])
    for e in eventos:
        w.writerow([e['id'], e['nivel'], e.get('score'), e.get('sla'), e.get('prazo'), e['estado'], e['origem'], e.get('categoria',''), e['local'], e['equipamento'], e['tipo'], e['causa'], e['impacto'], e['acao'], e.get('acao_tomada',''), e.get('evidencia',''), e['ultima'], e.get('responsavel',''), e.get('observacao',''), f"{float(e.get('impacto_mt') or 0):.2f}"])
    return Response(si.getvalue(), mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment;filename=alertas_sge_{data_ini}_a_{data_fim}.csv'})


# ==============================
# === DIMENSIONAMENTO SOLAR ===
# ==============================
# (coloca este bloco só uma vez no ficheiro)

