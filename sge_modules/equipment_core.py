"""Domínio equipment_core extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""

def _form_str(name):
    return (request.form.get(name) or '').strip()

def _form_int(name):
    v = _form_str(name)
    if not v:
        return None
    return int(v)

def _form_float(name):
    v = _form_str(name).replace(',', '.')
    if not v:
        return None
    return float(v)

def _form_first(*names):
    for name in names:
        value = _form_str(name)
        if value:
            return value
    return ''

def _form_first_int(*names):
    value = _form_first(*names)
    return int(value) if value else None

def _form_first_float(*names):
    value = _form_first(*names).replace(',', '.')
    return float(value) if value else None

def _equip_form_payload():
    return {
        'nome': _form_str('nome'),
        'local_id': _form_int('local_id'),
        'tag': _form_str('tag'),
        'especificacao': _form_str('especificacao'),
        'ano_instalacao': _form_str('ano_instalacao') or None,
        'quantidade': _form_int('quantidade') or 1,
        'categoria': _form_str('categoria'),
        'fabricante': _form_str('fabricante'),
        'modelo': _form_str('modelo'),
        'numero_serie': _form_str('numero_serie'),
        'custo_aquisicao': _form_first_float('custo_aquisicao', 'custo'),
        'vida_util_anos': _form_first_int('vida_util_anos', 'vida_util'),
        'criticidade': _form_str('criticidade'),
        'ativo': 1 if request.form.get('ativo') else 0,
        'potencia_kw': _form_float('potencia_kw'),
        'tensao_v': _form_float('tensao_v'),
        'corrente_a': _form_float('corrente_a'),
        'fornecedor': _form_str('fornecedor'),
        'contrato_num': _form_str('contrato_num'),
        'garantia_fim': _form_str('garantia_fim') or None,
        'sistema': _form_str('sistema'),
        'instalacao': _form_str('instalacao'),
        'estado_operacional': _form_str('estado_operacional'),
        'periodicidade_manutencao': _form_str('periodicidade_manutencao'),
        'sector_operacional': _form_str('sector_operacional'),
        'referencia_externa': _form_str('referencia_externa'),
    }

def _equip_validate_payload(payload):
    errors = []
    if not payload['nome']:
        errors.append('O nome do equipamento é obrigatório.')
    if payload['quantidade'] is not None and payload['quantidade'] <= 0:
        errors.append('Quantidade deve ser maior que zero.')
    ano = payload['ano_instalacao']
    if ano and (not str(ano).isdigit() or len(str(ano)) != 4):
        errors.append('Ano de instalação deve estar no formato AAAA.')
    if payload['criticidade'] and payload['criticidade'] not in ('Baixa', 'Média', 'Alta'):
        errors.append('Criticidade inválida.')
    return errors


def _equip_reference_conflict(reference, exclude_id=None):
    reference = (reference or '').strip()
    if not reference:
        return False
    conn = sqlite3.connect(DB_PATH)
    try:
        if exclude_id is None:
            row = conn.execute(
                "SELECT 1 FROM equipamentos WHERE referencia_externa=? LIMIT 1", (reference,)
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT 1 FROM equipamentos WHERE referencia_externa=? AND id<>? LIMIT 1",
                (reference, exclude_id),
            ).fetchone()
        return row is not None
    finally:
        conn.close()


def _equip_clean_text(value, fallback='—'):
    if value is None:
        return fallback
    if isinstance(value, float):
        try:
            if math.isnan(value):
                return fallback
        except Exception:
            pass
    text = str(value).strip()
    if not text or text.lower() in ('nan', 'none', 'null'):
        return fallback
    return text


def _equip_clean_number(value, decimals=2, fallback='—', zero_as_value=True):
    if value is None:
        return fallback
    try:
        number = float(value)
        if math.isnan(number):
            return fallback
        if not zero_as_value and abs(number) < 1e-12:
            return fallback
        if decimals == 0:
            return str(int(round(number)))
        return f"{number:.{decimals}f}"
    except Exception:
        return fallback


def _equip_bool(value):
    return 1 if str(value).strip() in ('1', 'True', 'true', 'on') else 0


def _equip_form_defaults(equipamento):
    if not equipamento:
        return {}
    return {
        'id': equipamento[0],
        'nome': equipamento[1] or '',
        'local_id': equipamento[2] or '',
        'tag': equipamento[3] or '',
        'especificacao': equipamento[4] or '',
        'ano_instalacao': equipamento[5] or '',
        'quantidade': equipamento[6] or 1,
        'ativo': _equip_bool(equipamento[7]),
        'categoria': equipamento[10] or '',
        'fabricante': equipamento[11] or '',
        'modelo': equipamento[12] or '',
        'numero_serie': equipamento[13] or '',
        'custo': '' if equipamento[14] in (None, '') else equipamento[14],
        'vida_util': '' if equipamento[15] in (None, '') else equipamento[15],
        'criticidade': equipamento[16] or '',
        'potencia_kw': '' if equipamento[19] in (None, '') else equipamento[19],
        'tensao_v': '' if equipamento[20] in (None, '') else equipamento[20],
        'corrente_a': '' if equipamento[21] in (None, '') else equipamento[21],
        'garantia_fim': equipamento[24] or '',
        'fornecedor': equipamento[25] or '',
        'contrato_num': equipamento[26] or '',
        'sistema': equipamento[27] or '' if len(equipamento) > 27 else '',
        'instalacao': equipamento[28] or '' if len(equipamento) > 28 else '',
        'estado_operacional': equipamento[29] or '' if len(equipamento) > 29 else '',
        'periodicidade_manutencao': equipamento[30] or '' if len(equipamento) > 30 else '',
        'sector_operacional': equipamento[31] or '' if len(equipamento) > 31 else '',
        'referencia_externa': equipamento[32] or '' if len(equipamento) > 32 else '',
    }

@app.route('/equipamentos')
def listar_equipamentos():
    q = request.args.get('q', '').strip()
    local_id = request.args.get('local_id', '').strip()
    incluir_inativos = request.args.get('incluir_inativos', '0') == '1'
    categoria = request.args.get('categoria', '').strip()
    fabricante = request.args.get('fabricante', '').strip()
    modelo = request.args.get('modelo', '').strip()
    criticidade = request.args.get('criticidade', '').strip()
    sector = request.args.get('sector', '').strip()
    sistema = request.args.get('sistema', '').strip()
    instalacao = request.args.get('instalacao', '').strip()
    estado_operacional = request.args.get('estado_operacional', '').strip()
    periodicidade = request.args.get('periodicidade', '').strip()
    ano_min = request.args.get('ano_min', '').strip()
    ano_max = request.args.get('ano_max', '').strip()
    sort = request.args.get('sort', 'local_nome')
    order = request.args.get('order', 'asc').lower()
    page = max(1, int(request.args.get('page', 1) or 1))
    per_page = int(request.args.get('per_page', 20) or 20)
    per_page = max(10, min(per_page, 200))
    offset = (page - 1) * per_page

    allowed_sort = {
        'nome': 'e.nome',
        'local_nome': 'l.nome',
        'tag': 'e.tag',
        'ano': 'CAST(COALESCE(e.ano_instalacao,0) AS INTEGER)',
        'quantidade': 'e.quantidade',
        'fabricante': 'e.fabricante',
        'modelo': 'e.modelo',
        'criticidade': 'e.criticidade',
        'sector': 'e.sector_operacional',
        'sistema': 'e.sistema',
        'instalacao': 'e.instalacao',
        'estado_operacional': 'e.estado_operacional'
    }
    sort_sql = allowed_sort.get(sort, 'l.nome, e.nome')
    order_sql = 'DESC' if order == 'desc' else 'ASC'

    where_clauses = ["COALESCE(e.deleted_at,'')=''"]
    params = []

    if q:
        _apply_advanced_query(q, where_clauses, params)

    if local_id and local_id.isdigit():
        local_ids_scope = get_descendant_local_ids(int(local_id), include_self=True)
        if not local_ids_scope:
            local_ids_scope = [int(local_id)]
        placeholders_local = ','.join('?' for _ in local_ids_scope)
        where_clauses.append(f"e.local_id IN ({placeholders_local})")
        params.extend(local_ids_scope)

    if categoria:
        where_clauses.append("COALESCE(e.categoria,'') LIKE ?")
        params.append(f"%{categoria}%")
    if fabricante:
        where_clauses.append("COALESCE(e.fabricante,'') LIKE ?")
        params.append(f"%{fabricante}%")
    if modelo:
        where_clauses.append("COALESCE(e.modelo,'') LIKE ?")
        params.append(f"%{modelo}%")
    if criticidade:
        where_clauses.append("COALESCE(e.criticidade,'') = ?")
        params.append(criticidade)
    if sector:
        where_clauses.append("COALESCE(e.sector_operacional,'') = ?")
        params.append(sector)
    if sistema:
        where_clauses.append("COALESCE(e.sistema,'') = ?")
        params.append(sistema)
    if instalacao:
        where_clauses.append("COALESCE(e.instalacao,'') = ?")
        params.append(instalacao)
    if estado_operacional:
        where_clauses.append("COALESCE(e.estado_operacional,'') = ?")
        params.append(estado_operacional)
    if periodicidade:
        where_clauses.append("COALESCE(e.periodicidade_manutencao,'') = ?")
        params.append(periodicidade)
    if ano_min and ano_min.isdigit():
        where_clauses.append("CAST(COALESCE(e.ano_instalacao,0) AS INTEGER) >= ?")
        params.append(int(ano_min))
    if ano_max and ano_max.isdigit():
        where_clauses.append("CAST(COALESCE(e.ano_instalacao,0) AS INTEGER) <= ?")
        params.append(int(ano_max))

    if not incluir_inativos:
        where_clauses.append("COALESCE(e.ativo,1)=1")

    where_sql = "WHERE " + " AND ".join(where_clauses)

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()

    c.execute(f'''
        SELECT COUNT(*),
               SUM(CASE WHEN COALESCE(e.ativo,1)=1 THEN 1 ELSE 0 END),
               SUM(CASE WHEN COALESCE(e.criticidade,'')='Alta' THEN 1 ELSE 0 END),
               SUM(CASE WHEN COALESCE(e.garantia_fim,'')<>'' AND date(e.garantia_fim)>=date('now') THEN 1 ELSE 0 END)
        FROM equipamentos e
        LEFT JOIN locais l ON e.local_id = l.id
        {where_sql}
    ''', params)
    stat_row = c.fetchone() or (0,0,0,0)
    total = stat_row[0] or 0
    ativos = stat_row[1] or 0
    inativos = max((total or 0) - (ativos or 0), 0)
    criticos = stat_row[2] or 0
    em_garantia = stat_row[3] or 0

    c.execute(f'''
        SELECT e.id, e.nome, COALESCE(l.nome,''), COALESCE(e.tag,''), COALESCE(e.especificacao,''),
               e.ano_instalacao, COALESCE(e.quantidade,0), COALESCE(e.ativo,1),
               COALESCE(e.categoria,''), COALESCE(e.fabricante,''), COALESCE(e.modelo,''), COALESCE(e.numero_serie,''),
               e.custo_aquisicao, COALESCE(e.vida_util_anos,''), COALESCE(e.criticidade,''),
               e.potencia_kw, e.tensao_v, e.corrente_a, e.garantia_fim,
               COALESCE(cp.thumb_filename,(SELECT thumb_filename FROM equipamentos_photos WHERE equipamento_id = e.id ORDER BY uploaded_at DESC LIMIT 1),''),
               COALESCE(e.fornecedor,''), COALESCE(e.contrato_num,''),
               COALESCE(e.sector_operacional,''), COALESCE(e.instalacao,''), COALESCE(e.sistema,''),
               COALESCE(e.estado_operacional,''), COALESCE(e.periodicidade_manutencao,''),
               COALESCE(e.referencia_externa,''), COALESCE(e.fonte_cadastro,''), COALESCE(e.ultima_sincronizacao,'')
        FROM equipamentos e
        LEFT JOIN locais l ON e.local_id = l.id
        LEFT JOIN equipamentos_photos cp ON cp.id = e.cover_photo_id
        {where_sql}
        ORDER BY {sort_sql} {order_sql}, e.id DESC
        LIMIT ? OFFSET ?
    ''', params + [per_page, offset])
    rows = c.fetchall()

    equipamentos = []
    for r in rows:
        ano_txt = _equip_clean_text(r[5], fallback='')
        equipamentos.append({
            'id': r[0],
            'nome': _equip_clean_text(r[1]),
            'local': _equip_clean_text(r[2]),
            'tag': _equip_clean_text(r[3]),
            'especificacao': _equip_clean_text(r[4], fallback=''),
            'ano': ano_txt if ano_txt != '—' else '',
            'quantidade': int(r[6] or 0),
            'ativo': _equip_bool(r[7]),
            'categoria': _equip_clean_text(r[8]),
            'fabricante': _equip_clean_text(r[9]),
            'modelo': _equip_clean_text(r[10]),
            'numero_serie': _equip_clean_text(r[11]),
            'custo': _equip_clean_number(r[12], decimals=2, fallback='0.00', zero_as_value=True),
            'vida_util': _equip_clean_text(r[13]),
            'criticidade': _equip_clean_text(r[14]),
            'potencia_kw': _equip_clean_number(r[15], decimals=2),
            'tensao_v': _equip_clean_number(r[16], decimals=0),
            'corrente_a': _equip_clean_number(r[17], decimals=2),
            'garantia_fim': _equip_clean_text(r[18]),
            'cover_thumb': r[19] or '',
            'fornecedor': _equip_clean_text(r[20]),
            'contrato_num': _equip_clean_text(r[21]),
            'sector_operacional': _equip_clean_text(r[22]),
            'instalacao': _equip_clean_text(r[23]),
            'sistema': _equip_clean_text(r[24]),
            'estado_operacional': _equip_clean_text(r[25]),
            'periodicidade_manutencao': _equip_clean_text(r[26]),
            'referencia_externa': _equip_clean_text(r[27]),
            'fonte_cadastro': _equip_clean_text(r[28]),
            'ultima_sincronizacao': _equip_clean_text(r[29]),
        })

    c.execute('SELECT id, nome FROM locais ORDER BY nome')
    locais = c.fetchall()
    opcoes = {}
    for chave, coluna in [('sectores','sector_operacional'),('sistemas','sistema'),('instalacoes','instalacao'),('estados_operacionais','estado_operacional'),('periodicidades','periodicidade_manutencao')]:
        opcoes[chave] = [r[0] for r in c.execute(f"SELECT DISTINCT {coluna} FROM equipamentos WHERE COALESCE(TRIM({coluna}),'')<>'' AND COALESCE(deleted_at,'')='' ORDER BY {coluna} COLLATE NOCASE").fetchall()]
    local_nome = ''
    if local_id and str(local_id).isdigit():
        for _lid, _lnome in locais:
            if str(_lid) == str(local_id):
                local_nome = _lnome or ''
                break
    conn.close()

    total_pages = max(1, math.ceil(total / per_page))

    return render_template('equipamentos.html',
                           equipamentos=equipamentos,
                           locais=locais,
                           q=q, sort=sort, order=order,
                           page=page, per_page=per_page,
                           total=total, total_pages=total_pages,
                           local_id=local_id, incluir_inativos=incluir_inativos,
                           categoria=categoria, fabricante=fabricante, modelo=modelo,
                           criticidade=criticidade, ano_min=ano_min, ano_max=ano_max,
                           sector=sector, sistema=sistema, instalacao=instalacao,
                           estado_operacional=estado_operacional, periodicidade=periodicidade,
                           **opcoes,
                           ativos=ativos, inativos=inativos, criticos=criticos,
                           em_garantia=em_garantia, local_nome=local_nome)
@app.route('/equipamentos/adicionar', methods=['GET', 'POST'])
def adicionar_equipamento():
    locais = get_locais()
    prefill_local_id = (request.args.get('local_id') or '').strip()
    if request.method == 'POST':
        try:
            payload = _equip_form_payload()
        except ValueError:
            flash('Há valores numéricos inválidos no formulário.', 'danger')
            return render_template('adicionar_equipamento.html', locais=locais, form=request.form)

        errors = _equip_validate_payload(payload)
        if _equip_reference_conflict(payload['referencia_externa']):
            errors.append('O código externo já está associado a outro equipamento.')
        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('adicionar_equipamento.html', locais=locais, form=request.form)

        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('''
            INSERT INTO equipamentos (
                nome, local_id, tag, especificacao, ano_instalacao, quantidade, ativo,
                created_at, updated_at, categoria, fabricante, modelo, numero_serie,
                custo_aquisicao, vida_util_anos, criticidade, potencia_kw, tensao_v,
                corrente_a, fornecedor, contrato_num, garantia_fim,
                sistema, instalacao, estado_operacional, periodicidade_manutencao,
                sector_operacional, referencia_externa
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, datetime('now','localtime'), datetime('now','localtime'),
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
        ''', (
            payload['nome'], payload['local_id'], payload['tag'], payload['especificacao'], payload['ano_instalacao'],
            payload['quantidade'], payload['ativo'], payload['categoria'], payload['fabricante'], payload['modelo'],
            payload['numero_serie'], payload['custo_aquisicao'], payload['vida_util_anos'], payload['criticidade'],
            payload['potencia_kw'], payload['tensao_v'], payload['corrente_a'], payload['fornecedor'],
            payload['contrato_num'], payload['garantia_fim'], payload['sistema'], payload['instalacao'],
            payload['estado_operacional'], payload['periodicidade_manutencao'], payload['sector_operacional'],
            payload['referencia_externa']
        ))
        equipamento_id = c.lastrowid
        conn.commit(); conn.close()
        log_equip_audit(equipamento_id, 'criar', f"nome={payload['nome']}")
        flash('Equipamento adicionado com sucesso.', 'success')
        return redirect(url_for('listar_equipamentos'))
    return render_template('adicionar_equipamento.html', locais=locais, form={'local_id': prefill_local_id} if prefill_local_id else None)
@app.route('/equipamentos/editar/<int:equipamento_id>', methods=['GET', 'POST'])
def editar_equipamento(equipamento_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT * FROM equipamentos WHERE id=?', (equipamento_id,))
    equipamento = c.fetchone()
    locais = get_locais()
    if not equipamento:
        conn.close()
        flash('Equipamento não encontrado.', 'warning')
        return redirect(url_for('listar_equipamentos'))
    if request.method == 'POST':
        try:
            payload = _equip_form_payload()
        except ValueError:
            flash('Há valores numéricos inválidos no formulário.', 'danger')
            conn.close()
            return render_template('editar_equipamento.html', equipamento=equipamento, locais=locais, form=request.form, defaults=_equip_form_defaults(equipamento))

        errors = _equip_validate_payload(payload)
        if _equip_reference_conflict(payload['referencia_externa'], equipamento_id):
            errors.append('O código externo já está associado a outro equipamento.')
        if errors:
            for e in errors:
                flash(e, 'danger')
            conn.close()
            return render_template('editar_equipamento.html', equipamento=equipamento, locais=locais, form=request.form, defaults=_equip_form_defaults(equipamento))

        c.execute('''
            UPDATE equipamentos
            SET nome=?, local_id=?, tag=?, especificacao=?, ano_instalacao=?, quantidade=?, ativo=?,
                categoria=?, fabricante=?, modelo=?, numero_serie=?, custo_aquisicao=?, vida_util_anos=?,
                criticidade=?, potencia_kw=?, tensao_v=?, corrente_a=?, fornecedor=?, contrato_num=?,
                garantia_fim=?, updated_at=datetime('now','localtime'),
                sistema=?, instalacao=?, estado_operacional=?, periodicidade_manutencao=?,
                sector_operacional=?, referencia_externa=?
            WHERE id=?
        ''', (
            payload['nome'], payload['local_id'], payload['tag'], payload['especificacao'], payload['ano_instalacao'],
            payload['quantidade'], payload['ativo'], payload['categoria'], payload['fabricante'], payload['modelo'],
            payload['numero_serie'], payload['custo_aquisicao'], payload['vida_util_anos'], payload['criticidade'],
            payload['potencia_kw'], payload['tensao_v'], payload['corrente_a'], payload['fornecedor'],
            payload['contrato_num'], payload['garantia_fim'], payload['sistema'], payload['instalacao'],
            payload['estado_operacional'], payload['periodicidade_manutencao'], payload['sector_operacional'],
            payload['referencia_externa'], equipamento_id
        ))
        conn.commit(); conn.close()
        log_equip_audit(equipamento_id, 'editar', f"nome={payload['nome']}")
        flash('Equipamento atualizado.', 'success')
        return redirect(url_for('listar_equipamentos'))

    conn.close()
    return render_template('editar_equipamento.html', equipamento=equipamento, locais=locais, defaults=_equip_form_defaults(equipamento))
# === CONFIG DE EQUIPAMENTO ===
@app.route('/equipamentos/config/<int:equipamento_id>', methods=['GET', 'POST'])
def equipamento_config(equipamento_id):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT id, nome FROM equipamentos WHERE id=?', (equipamento_id,))
    equipamento = c.fetchone()
    if not equipamento:
        conn.close()
        return redirect(url_for('listar_equipamentos'))

    if request.method == 'POST':
        tensao = request.form.get('tensao_nominal') or None
        corrente = request.form.get('corrente_nominal') or None
        pnom = request.form.get('potencia_nominal_kw') or None
        fpnom = request.form.get('fp_nominal') or None
        efic = request.form.get('eficiencia_nominal') or None
        lim_i = request.form.get('limite_corrente') or None
        lim_fp = request.form.get('limite_fp') or None

        c.execute('INSERT OR IGNORE INTO equipamentos_cfg (equipamento_id) VALUES (?)', (equipamento_id,))
        c.execute('''
            UPDATE equipamentos_cfg
            SET tensao_nominal=?, corrente_nominal=?, potencia_nominal_kw=?, fp_nominal=?,
                eficiencia_nominal=?, limite_corrente=?, limite_fp=?
            WHERE equipamento_id=?
        ''', (tensao, corrente, pnom, fpnom, efic, lim_i, lim_fp, equipamento_id))
        conn.commit(); conn.close()
        return redirect(url_for('listar_equipamentos'))

    c.execute('SELECT tensao_nominal, corrente_nominal, potencia_nominal_kw, fp_nominal, eficiencia_nominal, limite_corrente, limite_fp FROM equipamentos_cfg WHERE equipamento_id=?',
              (equipamento_id,))
    cfg = c.fetchone()
    conn.close()
    return render_template('equipamento_config.html', equipamento=equipamento, cfg=cfg)

# === LEITURAS POR LOCAL ===
