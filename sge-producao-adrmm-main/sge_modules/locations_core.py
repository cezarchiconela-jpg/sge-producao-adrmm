"""Domínio locations_core extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""


def _safe_text(value, default=''):
    """Normaliza valores antigos/importados sem deixar a interface falhar."""
    if value is None:
        return default
    try:
        return str(value).strip()
    except Exception:
        return default


def _safe_float(value, default=0.0):
    """Aceita números SQLite e formatos locais como ``1.234,56``."""
    if value is None or isinstance(value, bool):
        return float(default)
    if isinstance(value, (int, float)):
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return float(default)

    text = _safe_text(value).replace('\u00a0', '').replace(' ', '')
    if not text or text.lower() in {'-', '--', '—', 'n/a', 'na', 'none', 'null'}:
        return float(default)
    try:
        if ',' in text and '.' in text:
            if text.rfind(',') > text.rfind('.'):
                text = text.replace('.', '').replace(',', '.')
            else:
                text = text.replace(',', '')
        elif ',' in text:
            text = text.replace(',', '.')
        return float(text)
    except (TypeError, ValueError, OverflowError):
        return float(default)


def _safe_int(value, default=0):
    try:
        return int(_safe_float(value, default))
    except (TypeError, ValueError, OverflowError):
        return int(default)


def ensure_locais_parent_id_column():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    c = conn.cursor()
    try:
        c.execute("PRAGMA busy_timeout=30000")
        cols = {row[1] for row in c.execute("PRAGMA table_info(locais)").fetchall()}
        changed = False
        if 'parent_id' not in cols:
            c.execute("ALTER TABLE locais ADD COLUMN parent_id INTEGER")
            changed = True
        indexes = {row[1] for row in c.execute("PRAGMA index_list(locais)").fetchall()}
        if 'idx_locais_parent_id' not in indexes:
            c.execute("CREATE INDEX idx_locais_parent_id ON locais(parent_id)")
            changed = True
        if changed:
            conn.commit()
    finally:
        conn.close()

def _get_locais_rows(include_inactive=True):
    ensure_locais_parent_id_column()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    sql = "SELECT id, nome, COALESCE(parent_id, NULL) AS parent_id, COALESCE(ativo,1) AS ativo FROM locais"
    params = []
    if not include_inactive:
        sql += " WHERE COALESCE(ativo,1)=1"
    sql += " ORDER BY nome COLLATE NOCASE"
    rows = c.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_locais_hierarchy(include_inactive=True, exclude_id=None):
    rows = _get_locais_rows(include_inactive=include_inactive)
    if exclude_id is not None:
        rows = [r for r in rows if int(r['id']) != int(exclude_id)]
    by_id = {int(r['id']): r for r in rows}
    children = {}
    roots = []
    for r in rows:
        rid = int(r['id'])
        pid = r.get('parent_id')
        if pid is not None:
            try:
                pid = int(pid)
            except Exception:
                pid = None
        r['parent_id'] = pid
        if pid and pid in by_id and pid != rid:
            children.setdefault(pid, []).append(rid)
        else:
            roots.append(rid)

    for key in children:
        children[key].sort(key=lambda cid: (by_id[cid].get('nome') or '').lower())
    roots = sorted(set(roots), key=lambda rid: (by_id[rid].get('nome') or '').lower())

    ordered = []
    visited = set()

    def walk(rid, depth=0, trail=None):
        if rid in visited:
            return
        visited.add(rid)
        row = dict(by_id[rid])
        trail = list(trail or [])
        trail.append(row.get('nome') or '')
        row['depth'] = depth
        row['display_name'] = (('— ' * depth) + (row.get('nome') or '')).strip()
        row['full_name'] = ' › '.join([p for p in trail if p])
        ordered.append(row)
        for child_id in children.get(rid, []):
            walk(child_id, depth + 1, trail)

    for rid in roots:
        walk(rid, 0, [])
    for rid in sorted(by_id.keys()):
        if rid not in visited:
            walk(rid, 0, [])
    return ordered


def get_local_choices(include_inactive=True, exclude_id=None):
    return [(r['id'], r['display_name']) for r in get_locais_hierarchy(include_inactive=include_inactive, exclude_id=exclude_id)]


def get_local_children(parent_id, include_inactive=True):
    parent_id = int(parent_id)
    rows = [r for r in get_locais_hierarchy(include_inactive=include_inactive) if (r.get('parent_id') is not None and int(r.get('parent_id')) == parent_id)]
    if not rows:
        return []
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    for row in rows:
        cnt = c.execute("SELECT COUNT(*) FROM equipamentos WHERE local_id=? AND COALESCE(deleted_at,'')=''", (row['id'],)).fetchone()[0]
        row['equipamentos_count'] = int(cnt or 0)
    conn.close()
    return rows


def get_descendant_local_ids(local_id, include_self=True):
    """Devolve o local e todos os sublocais abaixo dele. Usado para filtros hierárquicos."""
    try:
        root = int(local_id)
    except Exception:
        return []
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        rows = c.execute("SELECT id, parent_id FROM locais").fetchall()
    except Exception:
        conn.close()
        return [root] if include_self else []
    conn.close()
    children = {}
    for rid, pid in rows:
        try:
            rid = int(rid)
            pid = int(pid) if pid is not None else None
        except Exception:
            continue
        if pid:
            children.setdefault(pid, []).append(rid)
    found = []
    def walk(pid):
        for cid in children.get(pid, []):
            if cid not in found:
                found.append(cid)
                walk(cid)
    if include_self:
        found.append(root)
    walk(root)
    return found


def get_local_names_for_ids(local_ids):
    ids = [int(x) for x in (local_ids or []) if str(x).isdigit()]
    if not ids:
        return []
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    placeholders = ','.join('?' for _ in ids)
    rows = c.execute(f"SELECT nome FROM locais WHERE id IN ({placeholders})", ids).fetchall()
    conn.close()
    return [r[0] for r in rows if r and (r[0] or '').strip()]

def get_locais():
    return get_local_choices(include_inactive=True)

def get_local_by_id(local_id):
    """Compatibilidade: devolve o local no formato antigo (id, nome).
    Algumas rotas antigas ainda chamam esta função; sem ela o módulo de leituras mensais gera erro 500.
    """
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute('SELECT id, nome FROM locais WHERE id=?', (int(local_id),))
        row = c.fetchone()
        conn.close()
        return row
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return None

def get_local_full(local_id: int):
    """Dados completos do local (inclui colunas operacional e hierarquia)."""
    ensure_locais_parent_id_column()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('''
        SELECT l.id, l.nome, l.codigo, l.endereco, l.contato_nome, l.contato_tel, l.notas, COALESCE(l.ativo,1),
               COALESCE(l.tipo_local,''), COALESCE(l.categoria_operacional,''), COALESCE(l.email,''),
               COALESCE(l.responsavel_alt,''), COALESCE(l.estado_tecnico,'Normal'), COALESCE(l.prioridade,'Média'),
               l.parent_id, COALESCE(p.nome,'')
        FROM locais l
        LEFT JOIN locais p ON p.id = l.parent_id
        WHERE l.id=?
    ''', (local_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {
        "id": row[0], "nome": row[1], "codigo": row[2], "endereco": row[3],
        "contato_nome": row[4], "contato_tel": row[5], "notas": row[6],
        "ativo": _safe_int(row[7], 1),
        "tipo_local": row[8], "categoria_operacional": row[9], "email": row[10],
        "responsavel_alt": row[11], "estado_tecnico": row[12], "prioridade": row[13],
        "parent_id": (_safe_int(row[14]) if row[14] is not None else None), "parent_nome": row[15]
    }

def infer_local_tipo(nome: str, endereco: str = '') -> str:
    txt = f"{nome or ''} {endereco or ''}".lower()
    checks = [
        ('ETA', ['eta', 'estacao de tratamento', 'estação de tratamento']),
        ('CD', ['cd ', 'centro distrib', 'centro distribuidor']),
        ('Furo', ['furo', 'furos', 'poco', 'poço']),
        ('Reservatório', ['reservatorio', 'reservatório', 'tanque']),
        ('Estação', ['estacao', 'estação', 'psaa', 'elevatoria', 'elevatória']),
        ('Escritório', ['escritorio', 'escritório', 'administracao', 'administração']),
    ]
    for tipo, keys in checks:
        if any(k in txt for k in keys):
            return tipo
    return 'Outro'


def calcular_maturidade_local(local: dict) -> int:
    score = 0
    if _safe_text(local.get('codigo')):
        score += 10
    if _safe_text(local.get('endereco')):
        score += 10
    if _safe_text(local.get('contato_nome')):
        score += 10
    if _safe_text(local.get('contato_tel')):
        score += 10
    if _safe_text(local.get('email')):
        score += 8
    if _safe_text(local.get('responsavel_alt')):
        score += 7
    if _safe_text(local.get('tipo_local')):
        score += 10
    if _safe_text(local.get('categoria_operacional')):
        score += 5
    if _safe_float(local.get('pot_contratada'), 0) > 0:
        score += 12
    if _safe_float(local.get('pot_instalada'), 0) > 0:
        score += 12
    if _safe_float(local.get('fator_mult'), 1) != 1:
        score += 6
    if _safe_text(local.get('notas')):
        score += 5
    estado_tecnico = _safe_text(local.get('estado_tecnico'))
    if estado_tecnico and estado_tecnico.lower() != 'normal':
        score += 3
    if _safe_text(local.get('prioridade')):
        score += 2
    return min(score, 100)


def get_locais_with_cfg(search=None, incluir_inativos=False, sort='nome', order='asc', tipo=None, qualidade=None, estado_tecnico=None, prioridade=None):
    """Locais + config com filtros operacional."""
    ensure_locais_parent_id_column()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    where = []
    params = []
    if not incluir_inativos:
        where.append("COALESCE(l.ativo,1)=1")
    if search:
        where.append("(l.nome LIKE ? OR COALESCE(l.codigo,'') LIKE ? OR COALESCE(l.endereco,'') LIKE ? OR COALESCE(l.contato_nome,'') LIKE ? OR COALESCE(l.email,'') LIKE ?)")
        like = f"%{search}%"
        params += [like, like, like, like, like]
    where_sql = ("WHERE " + " AND ".join(where)) if where else ""

    sort_map = {
        "nome": "l.nome COLLATE NOCASE",
        "codigo": "COALESCE(l.codigo,'') COLLATE NOCASE",
        "fator": "COALESCE(cfg.fator_mult,1.0)",
        "pot_contratada": "COALESCE(cfg.pot_contratada,0.0)",
        "pot_instalada": "COALESCE(cfg.pot_instalada,0.0)",
        "maturidade": "l.nome COLLATE NOCASE",
    }
    order_by = sort_map.get(sort, "l.nome COLLATE NOCASE")
    direction = "DESC" if str(order).lower() == "desc" else "ASC"

    c.execute(f"""
        SELECT l.id, l.nome, l.codigo, l.endereco, l.contato_nome, l.contato_tel,
               COALESCE(l.ativo,1),
               COALESCE(cfg.fator_mult,1.0),
               COALESCE(cfg.pot_contratada,0.0),
               COALESCE(cfg.pot_instalada,0.0),
               COALESCE(l.notas,''), COALESCE(l.tipo_local,''), COALESCE(l.categoria_operacional,''),
               COALESCE(l.email,''), COALESCE(l.responsavel_alt,''), COALESCE(l.estado_tecnico,'Normal'),
               COALESCE(l.prioridade,'Média'), l.parent_id
        FROM locais l
        LEFT JOIN locais_cfg cfg ON cfg.local_id = l.id
        {where_sql}
        ORDER BY {order_by} {direction}
    """, tuple(params))
    rows = c.fetchall()
    conn.close()
    data = []
    for r in rows:
        item = {
            "id": r[0], "nome": r[1], "codigo": r[2], "endereco": r[3],
            "contato_nome": r[4], "contato_tel": r[5], "ativo": _safe_int(r[6], 1),
            "fator_mult": _safe_float(r[7], 1.0), "pot_contratada": _safe_float(r[8], 0.0),
            "pot_instalada": _safe_float(r[9], 0.0), "notas": r[10],
            "tipo_local": _safe_text(r[11]), "categoria_operacional": _safe_text(r[12]), "email": _safe_text(r[13]),
            "responsavel_alt": _safe_text(r[14]), "estado_tecnico": _safe_text(r[15], 'Normal') or 'Normal',
            "prioridade": _safe_text(r[16], 'Média') or 'Média',
            "parent_id": (_safe_int(r[17]) if r[17] is not None else None)
        }
        item['tipo'] = item['tipo_local'] or infer_local_tipo(item['nome'], item['endereco'])
        item['maturidade'] = calcular_maturidade_local(item)
        item['config_ok'] = (item['pot_contratada'] > 0 or item['pot_instalada'] > 0)
        data.append(item)

    hierarchy_map = {}
    for hierarchy_item in get_locais_hierarchy(include_inactive=True):
        hierarchy_id = _safe_int(hierarchy_item.get('id'))
        if hierarchy_id:
            hierarchy_map[hierarchy_id] = hierarchy_item
    for item in data:
        href = hierarchy_map.get(_safe_int(item['id']))
        item['display_name'] = (href.get('full_name') if href else item['nome']) or item['nome']
        item['depth'] = int(href.get('depth', 0)) if href else 0

    if tipo and tipo != 'todos':
        data = [r for r in data if _safe_text(r.get('tipo')).lower() == _safe_text(tipo).lower()]
    if estado_tecnico and estado_tecnico != 'todos':
        data = [r for r in data if _safe_text(r.get('estado_tecnico'), 'Normal').lower() == _safe_text(estado_tecnico).lower()]
    if prioridade and prioridade != 'todas':
        data = [r for r in data if _safe_text(r.get('prioridade'), 'Média').lower() == _safe_text(prioridade).lower()]
    if qualidade == 'completo':
        data = [r for r in data if r['maturidade'] >= 70]
    elif qualidade == 'incompleto':
        data = [r for r in data if r['maturidade'] < 70]
    elif qualidade == 'sem_contato':
        data = [r for r in data if not (r.get('contato_nome') or '').strip() and not (r.get('contato_tel') or '').strip()]
    elif qualidade == 'alta_prontidao':
        data = [r for r in data if r['config_ok'] and r['maturidade'] >= 70]

    if sort == 'maturidade':
        data = sorted(data, key=lambda x: x.get('maturidade', 0), reverse=(direction=='DESC'))
    return data

def get_local_overview(local_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    out = {
        'equipamentos_count': 0,
        'equipamentos_qtd_total': 0,
        'leituras_mensais_count': 0,
        'ultima_leitura': None,
        'primeira_leitura': None,
        'leituras_dias_com_dados': 0,
        'equipamentos_principais': [],
        'prontidao': 'Base',
        'prontidao_score': 0,
    }
    try:
        local_ids_scope = get_descendant_local_ids(local_id, include_self=True)
        placeholders_scope = ','.join('?' for _ in local_ids_scope) if local_ids_scope else '?'
        params_scope = local_ids_scope if local_ids_scope else [local_id]
        c.execute(f'''SELECT COUNT(*), COALESCE(SUM(COALESCE(quantidade,1)),0)
                     FROM equipamentos WHERE local_id IN ({placeholders_scope})''', params_scope)
        row = c.fetchone() or (0, 0)
        out['equipamentos_count'] = int(row[0] or 0)
        out['equipamentos_qtd_total'] = int(row[1] or 0)

        c.execute('SELECT nome FROM locais WHERE id=?', (local_id,))
        row = c.fetchone()
        local_nome = row[0] if row else ''
        local_names_scope = get_local_names_for_ids(local_ids_scope)
        if local_names_scope:
            placeholders_names = ','.join('?' for _ in local_names_scope)
            c.execute(f'''SELECT COUNT(*), MIN(data), MAX(data),
                                SUM(CASE WHEN COALESCE(ativa,0)<>0 OR COALESCE(reativa,0)<>0 OR COALESCE(ponta,0)<>0 OR COALESCE(agua,0)<>0 THEN 1 ELSE 0 END)
                         FROM leituras_mensais
                         WHERE local IN ({placeholders_names})''', local_names_scope)
            row = c.fetchone() or (0, None, None, 0)
            out['leituras_mensais_count'] = int(row[0] or 0)
            out['primeira_leitura'] = row[1]
            out['ultima_leitura'] = row[2]
            out['leituras_dias_com_dados'] = int(row[3] or 0)

        c.execute(f'''SELECT nome, COALESCE(quantidade,1)
                     FROM equipamentos WHERE local_id IN ({placeholders_scope})
                     ORDER BY nome LIMIT 5''', params_scope)
        out['equipamentos_principais'] = c.fetchall()
        score = 0
        if out['equipamentos_count'] > 0:
            score += 25
        if out['leituras_mensais_count'] > 0:
            score += 25
        if out['leituras_dias_com_dados'] > 0:
            score += 25
        if out['ultima_leitura']:
            score += 25
        out['prontidao_score'] = score
        out['prontidao'] = 'Alta' if score >= 75 else ('Média' if score >= 40 else 'Base')
    finally:
        conn.close()
    return out

def get_locais_module_summary(locais):
    resumo = {
        'total': len(locais),
        'ativos': 0,
        'arquivados': 0,
        'pot_contratada_total': 0.0,
        'pot_instalada_total': 0.0,
        'com_config': 0,
        'sem_config': 0,
        'fator_medio': 0.0,
        'maturidade_media': 0.0,
        'sem_contato': 0,
        'tipos': {},
        'tipo_dominante': '—',
        'alta_prioridade': 0,
        'criticos': 0,
    }
    if not locais:
        return resumo
    soma_fator = 0.0
    soma_maturidade = 0.0
    for r in locais:
        ativo = _safe_int(r.get('ativo'), 1)
        resumo['ativos' if ativo == 1 else 'arquivados'] += 1
        pot_c = _safe_float(r.get('pot_contratada'), 0)
        pot_i = _safe_float(r.get('pot_instalada'), 0)
        resumo['pot_contratada_total'] += pot_c
        resumo['pot_instalada_total'] += pot_i
        if pot_c > 0 or pot_i > 0:
            resumo['com_config'] += 1
        else:
            resumo['sem_config'] += 1
        soma_fator += _safe_float(r.get('fator_mult'), 1)
        soma_maturidade += _safe_float(r.get('maturidade'), 0)
        if not _safe_text(r.get('contato_nome')) and not _safe_text(r.get('contato_tel')):
            resumo['sem_contato'] += 1
        if _safe_text(r.get('prioridade')).lower() == 'alta':
            resumo['alta_prioridade'] += 1
        if _safe_text(r.get('estado_tecnico')).lower() in ('crítico', 'critico'):
            resumo['criticos'] += 1
        tipo = _safe_text(r.get('tipo')) or infer_local_tipo(r.get('nome'), r.get('endereco'))
        resumo['tipos'][tipo] = resumo['tipos'].get(tipo, 0) + 1
    resumo['fator_medio'] = soma_fator / max(len(locais), 1)
    resumo['maturidade_media'] = soma_maturidade / max(len(locais), 1)
    if resumo['tipos']:
        resumo['tipo_dominante'] = max(resumo['tipos'].items(), key=lambda kv: kv[1])[0]
    return resumo

def get_equipamentos():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('SELECT id, nome FROM equipamentos')
    equipamentos = c.fetchall()
    conn.close()
    return equipamentos

def get_equipamentos_por_local(local_id):
    local_ids_scope = get_descendant_local_ids(local_id, include_self=True)
    if not local_ids_scope:
        local_ids_scope = [local_id]
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    placeholders = ','.join('?' for _ in local_ids_scope)
    c.execute(f'''
        SELECT e.id, e.nome, e.tag, e.especificacao, e.ano_instalacao, e.quantidade
        FROM equipamentos e
        WHERE e.local_id IN ({placeholders})
        ORDER BY e.nome
    ''', local_ids_scope)
    equipamentos = c.fetchall()
    conn.close()
    return equipamentos

# Config por local (dict completo, inclui pot_instalada)
def get_local_cfg_full(local_id: int):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('''
        SELECT fator_mult, pot_contratada, tarifa_ativa, tarifa_reativa, tarifa_ponta,
               tarifa_perdas, taxa_fixa, taxa_radio, taxa_lixo, iva,
               COALESCE(pot_instalada, 0.0)
          FROM locais_cfg WHERE local_id=?
    ''', (local_id,))
    row = c.fetchone()
    if not row:
        c.execute('INSERT OR IGNORE INTO locais_cfg (local_id) VALUES (?)', (local_id,))
        conn.commit()
        row = (1.0, 0.0, 4.780, 1.430, 497.03, 4.780, 207.28, 297.00, 150.00, 16.0, 0.0)
    conn.close()
    return {
        "fator_mult": _safe_float(row[0], 1.0),
        "pot_contratada": _safe_float(row[1], 0.0),
        "tarifa_ativa": _safe_float(row[2], 4.780),
        "tarifa_reativa": _safe_float(row[3], 1.430),
        "tarifa_ponta": _safe_float(row[4], 497.03),
        "tarifa_perdas": _safe_float(row[5], 4.780),
        "taxa_fixa": _safe_float(row[6], 207.28),
        "taxa_radio": _safe_float(row[7], 297.00),
        "taxa_lixo": _safe_float(row[8], 150.00),
        "iva": _safe_float(row[9], 16.0),
        "pot_instalada": _safe_float(row[10], 0.0),
    }

def get_local_cfg(local_id: int):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT fator_mult, pot_contratada, tarifa_ativa, tarifa_reativa, tarifa_ponta,
               tarifa_perdas, taxa_fixa, taxa_radio, taxa_lixo, iva
        FROM locais_cfg WHERE local_id=?
    ''', (local_id,))
    row = c.fetchone()
    if not row:
        c.execute('INSERT OR IGNORE INTO locais_cfg (local_id) VALUES (?)', (local_id,))
        conn.commit()
        row = (1.0, 0.0, 4.780, 1.430, 497.03, 4.780, 207.28, 297.00, 150.00, 16.0)
    conn.close()
    return row


def _tarifas_local_periodo(local_id, mes=None, ano=None, effective_date=None):
    if effective_date is None:
        if mes is not None and ano is not None:
            effective_date = f"{int(ano):04d}-{int(mes):02d}-01"
        else:
            effective_date = datetime.now().strftime('%Y-%m-%d')
    conn = sqlite3.connect(DB_PATH)
    try:
        return resolve_tariffs(conn, local_id, effective_date)
    finally:
        conn.close()


def _guardar_tarifa_historica(local_id, valid_from, values, actor=None, notes=''):
    """Guarda uma vigência, fecha a anterior e impede sobreposição de períodos."""
    inicio = datetime.strptime(str(valid_from), '%Y-%m-%d').date()
    tarifas = normalise_tariffs(values)
    conn = sqlite3.connect(DB_PATH)
    try:
        c = conn.cursor()
        next_row = c.execute(
            "SELECT valid_from FROM tarifas_historico WHERE local_id=? AND valid_from>? ORDER BY valid_from LIMIT 1",
            (int(local_id), inicio.isoformat()),
        ).fetchone()
        fim = None
        if next_row:
            fim = (datetime.strptime(next_row[0], '%Y-%m-%d').date() - timedelta(days=1)).isoformat()
        previous = c.execute(
            "SELECT id FROM tarifas_historico WHERE local_id=? AND valid_from<? ORDER BY valid_from DESC LIMIT 1",
            (int(local_id), inicio.isoformat()),
        ).fetchone()
        if previous:
            c.execute(
                "UPDATE tarifas_historico SET valid_to=? WHERE id=?",
                ((inicio - timedelta(days=1)).isoformat(), previous[0]),
            )
        c.execute(
            """
            INSERT INTO tarifas_historico(
                local_id, valid_from, valid_to, tarifa_ativa, tarifa_reativa,
                tarifa_ponta, tarifa_perdas, taxa_fixa, taxa_radio, taxa_lixo,
                pot_contratada, iva_rate, iva_base_factor, created_by, notes
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(local_id, valid_from) DO UPDATE SET
                valid_to=excluded.valid_to, tarifa_ativa=excluded.tarifa_ativa,
                tarifa_reativa=excluded.tarifa_reativa, tarifa_ponta=excluded.tarifa_ponta,
                tarifa_perdas=excluded.tarifa_perdas, taxa_fixa=excluded.taxa_fixa,
                taxa_radio=excluded.taxa_radio, taxa_lixo=excluded.taxa_lixo,
                pot_contratada=excluded.pot_contratada, iva_rate=16.0,
                iva_base_factor=0.62, created_by=excluded.created_by, notes=excluded.notes
            """,
            (
                int(local_id), inicio.isoformat(), fim, tarifas['tarifa_ativa'],
                tarifas['tarifa_reativa'], tarifas['tarifa_ponta'], tarifas['tarifa_perdas'],
                tarifas['taxa_fixa'], tarifas['taxa_radio'], tarifas['taxa_lixo'],
                tarifas['pot_contratada'], 16.0, 0.62, actor or _actor_name(), notes,
            ),
        )
        if inicio <= datetime.now().date():
            current = resolve_tariffs(conn, int(local_id), datetime.now().strftime('%Y-%m-%d'))
            c.execute('INSERT OR IGNORE INTO locais_cfg(local_id) VALUES(?)', (int(local_id),))
            c.execute(
                """UPDATE locais_cfg SET pot_contratada=?, tarifa_ativa=?, tarifa_reativa=?,
                       tarifa_ponta=?, tarifa_perdas=?, taxa_fixa=?, taxa_radio=?, taxa_lixo=?, iva=16.0
                   WHERE local_id=?""",
                (
                    current['pot_contratada'], current['tarifa_ativa'], current['tarifa_reativa'],
                    current['tarifa_ponta'], current['tarifa_perdas'], current['taxa_fixa'],
                    current['taxa_radio'], current['taxa_lixo'], int(local_id),
                ),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

# Consumo mensal (kWh) a partir de leituras_mensais
def consumo_mensal_kwh(local_nome, mes, ano, fator_mult):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        SELECT diferenca, ativa FROM leituras_mensais
        WHERE local=? AND mes=? AND ano=?
    ''', (local_nome, mes, ano))
    rows = c.fetchall()
    conn.close()

    total = 0.0
    dias = 0
    for dif, ativa in rows:
        if dif is not None and dif != '':
            try:
                total += float(dif) * float(fator_mult)
                dias += 1
                continue
            except:
                pass
        if ativa is not None and ativa != '':
            try:
                total += float(ativa)
                dias += 1
            except:
                pass
    return (total, dias)

# === ROTAS PRINCIPAIS ===
