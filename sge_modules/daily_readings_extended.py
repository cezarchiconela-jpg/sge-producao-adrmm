"""Domínio daily_readings_extended extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""

@app.route('/leituras/save_filter', methods=['POST'])
def leituras_save_filter():
    """Guarda filtros (por utilizador, nome)."""
    user = (request.form.get('user') or 'default').strip()
    nome = (request.form.get('nome') or '').strip() or datetime.now().strftime('filtro_%Y%m%d_%H%M')
    query = {
        'inicio': request.form.get('inicio') or '',
        'fim': request.form.get('fim') or '',
        'local': request.form.get('local') or '',
        'equipamento': request.form.get('equipamento') or '',
        'q': request.form.get('q') or '',
        'per': request.form.get('per') or '50'
    }
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('INSERT INTO saved_filters (user, modulo, nome, query_json) VALUES (?, ?, ?, ?)',
              (user, 'leituras', nome, json.dumps(query)))
    conn.commit(); conn.close()
    flash("Filtro guardado.", "success")
    return redirect(url_for('leituras_list', **query))

@app.route('/leituras/list_filters')
def leituras_list_filters():
    user = (request.args.get('user') or 'default').strip()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    rows = c.execute("SELECT id, nome, query_json, created_at FROM saved_filters WHERE modulo='leituras' AND user=? ORDER BY created_at DESC", (user,)).fetchall()
    conn.close()
    return jsonify([{'id': r[0], 'nome': r[1], 'query': json.loads(r[2] or '{}'), 'created_at': r[3]} for r in rows])

@app.route('/leituras/apply_filter/<int:fid>')
def leituras_apply_filter(fid):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    r = c.execute("SELECT query_json FROM saved_filters WHERE id=? AND modulo='leituras'", (fid,)).fetchone()
    conn.close()
    if not r:
        flash("Filtro não encontrado.", "warning")
        return redirect(url_for('leituras_list'))
    q = json.loads(r[0] or "{}")
    return redirect(url_for('leituras_list', **q))



@app.route('/leituras/<int:lid>/update_field', methods=['POST'])
def leituras_update_field(lid):
    """Atualiza um único campo (edição inline)."""
    data = request.get_json(silent=True) or {}
    field = (data.get('field') or '').strip()
    value = data.get('value')

    allowed = {
        'datahora','local','equipamento','energia_ativa','energia_reativa','energia_aparente',
        'pot_ativa','pot_reativa','pot_aparente','fp','ponta','caudal_elevada','corrente','tensao','observacoes'
    }
    if field not in allowed:
        return jsonify({'ok': False, 'error': 'Campo não permitido.'}), 400

    # normalização básica
    num_fields = {'energia_ativa','energia_reativa','energia_aparente','pot_ativa','pot_reativa','pot_aparente','fp','ponta','caudal_elevada','corrente','tensao'}
    if field in num_fields:
        try:
            s = ('' if value is None else str(value)).replace(',', '.').strip()
            value = None if s=='' else float(s)
        except Exception:
            return jsonify({'ok': False, 'error': 'Valor numérico inválido.'}), 400

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute(f"UPDATE leituras SET {field}=? WHERE id=?", (value, lid))
    conn.commit(); conn.close()
    return jsonify({'ok': True})



@app.route('/leituras/export_xlsx')
def leituras_export_xlsx():
    """Exporta o filtro actual para XLSX."""
    end = request.args.get('fim') or datetime.now().strftime('%Y-%m-%d')
    start = request.args.get('inicio') or (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d')
    local = request.args.get('local','').strip()
    q = request.args.get('q','').strip()

    base_sql = " FROM leituras WHERE date(datahora) BETWEEN ? AND ?"
    params = [start, end]
    if local:
        base_sql += " AND local = ?"
        params.append(local)
    if q:
        base_sql += " AND (equipamento LIKE ? OR observacoes LIKE ?)"
        params.extend([f"%{q}%", f"%{q}%"])

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    rows = c.execute("SELECT *" + base_sql + " ORDER BY datahora DESC", params).fetchall()
    conn.close()

    out = io.BytesIO()
    wb = xlsxwriter.Workbook(out, {'in_memory': True})
    _set_xlsx_identity(wb, 'Exportação de Leituras')
    ws = wb.add_worksheet('Leituras')
    header = ["id","datahora","local","equipamento","energia_ativa","energia_reativa","energia_aparente","pot_ativa","pot_reativa","pot_aparente","fp","ponta","caudal_elevada","corrente","tensao","observacoes"]
    for j,h in enumerate(header): ws.write(0,j,h)
    for i,row in enumerate(rows, start=1):
        for j,val in enumerate(row): ws.write(i,j,val)
    wb.close()
    out.seek(0)
    filename = f"leituras_{start}_a_{end}.xlsx"
    return Response(out.read(), mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})



@app.route('/leituras/import_preview', methods=['GET','POST'])
def leituras_import_preview():
    """Pré-visualização do CSV antes de importar."""
    if request.method == 'POST':
        f = request.files.get('arquivo')
        if not f or f.filename == '':
            flash("Selecione um CSV.", "warning")
            return redirect(url_for('leituras_import_preview'))
        content = f.read().decode('utf-8', errors='ignore')
        delimiter = ';' if content.count(';')>=content.count(',') else ','
        import csv as _csv
        reader = _csv.reader(content.splitlines(), delimiter=delimiter)
        rows = list(reader)
        head = rows[0] if rows else []
        preview = rows[1:101]  # primeiras 100
        # guarda em sessão mínima (fallback: reenvia o arquivo no próximo passo se necessário)
        return render_template('leituras_import_preview.html', header=head, preview=preview, delimiter=delimiter, raw=content)
    return render_template('leituras_import_preview.html', header=[], preview=[], delimiter=';', raw='')

@app.route('/leituras/import_commit', methods=['POST'])
def leituras_import_commit():
    """Confirma import do CSV recebido da pré-visualização."""
    content = request.form.get('raw','')
    delimiter = request.form.get('delimiter',';')
    if not content:
        flash("Conteúdo do CSV ausente.", "danger")
        return redirect(url_for('leituras_import_preview'))
    import csv as _csv
    reader = _csv.DictReader(content.splitlines(), delimiter=delimiter)
    required = {'datahora','local','equipamento'}
    if not required.issubset({(h or '').strip().lower() for h in (reader.fieldnames or [])}):
        flash("Cabeçalho obrigatório: datahora, local, equipamento.", "danger")
        return redirect(url_for('leituras_import_preview'))

    to_float = lambda v: (None if v is None or str(v).strip()=='' else float(str(v).replace(',','.')))
    ok, err = 0, 0
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    for row in reader:
        try:
            c.execute("""
                INSERT INTO leituras
                (datahora, local, equipamento, energia_ativa, energia_reativa, energia_aparente,
                 pot_ativa, pot_reativa, pot_aparente, fp, ponta, caudal_elevada, corrente, tensao, observacoes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                row.get('datahora'), row.get('local'), row.get('equipamento'),
                to_float(row.get('energia_ativa')), to_float(row.get('energia_reativa')), to_float(row.get('energia_aparente')),
                to_float(row.get('pot_ativa')), to_float(row.get('pot_reativa')), to_float(row.get('pot_aparente')),
                to_float(row.get('fp')), to_float(row.get('ponta')), to_float(row.get('caudal_elevada')),
                to_float(row.get('corrente')), to_float(row.get('tensao')), row.get('observacoes')
            ))
            ok += 1
        except Exception:
            err += 1
    conn.commit(); conn.close()
    flash(f"Importação concluída: {ok} ok, {err} erros.", "success" if err==0 else "warning")
    return redirect(url_for('leituras_list'))


def _audit_leitura(leitura_id, acao, field=None, old_value=None, new_value=None, actor=None):
    try:
        actor = actor or request.headers.get('X-User') or 'anon'
    except Exception:
        actor = 'anon'
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('''INSERT INTO leituras_audit (leitura_id, acao, field, old_value, new_value, actor)
                     VALUES (?,?,?,?,?,?)''', (leitura_id, acao, field, str(old_value) if old_value is not None else None,
                                               str(new_value) if new_value is not None else None, actor))
        conn.commit(); conn.close()
    except Exception:
        pass


@app.route('/leituras/bulk', methods=['GET'])
def leituras_bulk_form():
    return render_template('leituras_bulk_edit.html')

@app.route('/leituras/bulk_apply', methods=['POST'])
def leituras_bulk_apply():
    ids = request.form.get('ids','').strip()
    op = request.form.get('op','')
    actor = request.headers.get('X-User') or 'anon'
    if not ids:
        flash("Indique IDs separados por vírgula.", "warning")
        return redirect(url_for('leituras_bulk_form'))
    try:
        ids_list = [int(x) for x in ids.split(',') if x.strip().isdigit()]
    except Exception:
        flash("IDs inválidos.", "danger")
        return redirect(url_for('leituras_bulk_form'))

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    count = 0

    if op == 'shift_time':
        minutes = int(request.form.get('minutes','0') or 0)
        for lid in ids_list:
            old = c.execute("SELECT datahora FROM leituras WHERE id=?", (lid,)).fetchone()
            if not old or not old[0]: continue
            try:
                dt = datetime.strptime(old[0][:16], "%Y-%m-%d %H:%M")
            except Exception:
                try:
                    dt = datetime.fromisoformat(old[0].replace('Z',''))
                except Exception:
                    continue
            new_dt = dt + timedelta(minutes=minutes)
            nds = new_dt.strftime("%Y-%m-%d %H:%M")
            c.execute("UPDATE leituras SET datahora=? WHERE id=?", (nds, lid))
            _audit_leitura(lid, "bulk_shift_time", "datahora", old[0], nds, actor=actor)
            count += 1

    elif op == 'set_local':
        new_local = (request.form.get('new_local') or '').strip()
        if not new_local:
            conn.close()
            flash("Informe o novo local.", "warning")
            return redirect(url_for('leituras_bulk_form'))
        for lid in ids_list:
            old = c.execute("SELECT local FROM leituras WHERE id=?", (lid,)).fetchone()
            c.execute("UPDATE leituras SET local=? WHERE id=?", (new_local, lid))
            _audit_leitura(lid, "bulk_set_local", "local", old[0] if old else None, new_local, actor=actor)
            count += 1

    elif op == 'set_equip':
        new_eq = (request.form.get('new_equip') or '').strip()
        if not new_eq:
            conn.close()
            flash("Informe o novo equipamento.", "warning")
            return redirect(url_for('leituras_bulk_form'))
        for lid in ids_list:
            old = c.execute("SELECT equipamento FROM leituras WHERE id=?", (lid,)).fetchone()
            c.execute("UPDATE leituras SET equipamento=? WHERE id=?", (new_eq, lid))
            _audit_leitura(lid, "bulk_set_equip", "equipamento", old[0] if old else None, new_eq, actor=actor)
            count += 1

    conn.commit(); conn.close()
    flash(f"Edição em massa concluída: {count} linhas.", "success")
    return redirect(url_for('leituras_list'))


@app.route('/leituras/export_pdf')
def leituras_export_pdf():
    end = request.args.get('fim') or datetime.now().strftime('%Y-%m-%d')
    start = request.args.get('inicio') or (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d')
    local = request.args.get('local','').strip()
    q = request.args.get('q','').strip()

    base_sql = " FROM leituras WHERE date(datahora) BETWEEN ? AND ?"
    params = [start, end]
    if local:
        base_sql += " AND local = ?"; params.append(local)
    if q:
        base_sql += " AND (equipamento LIKE ? OR observacoes LIKE ?)"; params.extend([f"%{q}%", f"%{q}%"])

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    rows = c.execute("SELECT id, datahora, local, equipamento, energia_ativa, ponta, fp " + base_sql + " ORDER BY datahora DESC LIMIT 1000", params).fetchall()
    conn.close()

    buffer = io.BytesIO()
    cpdf = canvas.Canvas(buffer, pagesize=A4)
    _set_pdf_identity(cpdf, 'Relatório de Leituras')
    w, h = A4
    y = h - 30
    cpdf.setFont("Helvetica-Bold", 12)
    cpdf.drawString(30, y, f"Leituras {start} a {end}  (Local: {local or 'todos'})"); y -= 20
    cpdf.setFont("Helvetica", 9)
    header = "ID   Data/Hora           Local            Equipamento         kWh     Ponta   FP"
    cpdf.drawString(30, y, header); y -= 12
    cpdf.line(30, y+5, w-30, y+5)

    for rid, dh, loc, eq, kwh, ponta, fp in rows:
        line = f"{str(rid).ljust(4)} {str(dh or '')[:16].ljust(18)} {str(loc or '')[:14].ljust(16)} {str(eq or '')[:18].ljust(20)} {kwh or 0:6.1f}  {ponta or 0:6.1f}  {fp or 0:4.2f}"
        if y < 50:
            cpdf.showPage(); y = h - 30
            cpdf.setFont("Helvetica", 9)
        cpdf.drawString(30, y, line); y -= 12

    cpdf.showPage(); cpdf.save()
    pdf = buffer.getvalue()
    buffer.close()
    return Response(pdf, mimetype="application/pdf", headers={"Content-Disposition": f"attachment; filename=leituras_{start}_{end}.pdf"})


# ===== API REST (token simples via ?token= ou Header Authorization: Bearer) =====
API_TOKEN = os.environ.get('SGE_API_TOKEN', 'sge-api-token')

def _api_check_token():
    tok = request.args.get('token') or ''
    if not tok:
        auth = request.headers.get('Authorization','')
        if auth.lower().startswith('bearer '):
            tok = auth.split(' ',1)[1].strip()
    return tok == API_TOKEN

@app.route('/api/leituras', methods=['GET'])
def api_leituras_list():
    if not _api_check_token():
        return jsonify({'error':'unauthorized'}), 401
    end = request.args.get('fim') or datetime.now().strftime('%Y-%m-%d')
    start = request.args.get('inicio') or (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d')
    local = request.args.get('local','').strip()
    q = request.args.get('q','').strip()

    base_sql = " FROM leituras WHERE date(datahora) BETWEEN ? AND ?"
    params = [start, end]
    if local: base_sql += " AND local = ?"; params.append(local)
    if q: base_sql += " AND (equipamento LIKE ? OR observacoes LIKE ?)"; params.extend([f"%{q}%", f"%{q}%"])

    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    rows = c.execute("SELECT *" + base_sql + " ORDER BY datahora DESC LIMIT 1000", params).fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({
            "id": r[0], "datahora": r[1], "local": r[2], "equipamento": r[3],
            "energia_ativa": r[4], "energia_reativa": r[5], "energia_aparente": r[6],
            "pot_ativa": r[7], "pot_reativa": r[8], "pot_aparente": r[9],
            "fp": r[10], "ponta": r[11], "caudal_elevada": r[12], "corrente": r[13], "tensao": r[14],
            "observacoes": r[15]
        })
    return jsonify(out)

@app.route('/api/leituras', methods=['POST'])
def api_leituras_create():
    if not _api_check_token():
        return jsonify({'error':'unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    fields = ['datahora','local','equipamento','energia_ativa','energia_reativa','energia_aparente','pot_ativa','pot_reativa','pot_aparente','fp','ponta','caudal_elevada','corrente','tensao','observacoes']
    vals = [data.get(f) for f in fields]
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""
        INSERT INTO leituras
        (datahora,local,equipamento,energia_ativa,energia_reativa,energia_aparente,pot_ativa,pot_reativa,pot_aparente,fp,ponta,caudal_elevada,corrente,tensao,observacoes)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, tuple(vals))
    lid = c.lastrowid
    conn.commit(); conn.close()
    _audit_leitura(lid, "api_create", actor="api")
    return jsonify({'ok':True,'id':lid}), 201

@app.route('/api/leituras/<int:lid>', methods=['PATCH'])
def api_leituras_patch(lid):
    if not _api_check_token():
        return jsonify({'error':'unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    allowed = {'datahora','local','equipamento','energia_ativa','energia_reativa','energia_aparente','pot_ativa','pot_reativa','pot_aparente','fp','ponta','caudal_elevada','corrente','tensao','observacoes'}
    sets, params = [], []
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    for k,v in data.items():
        if k in allowed:
            old = c.execute(f"SELECT {k} FROM leituras WHERE id=?", (lid,)).fetchone()
            sets.append(f"{k}=?"); params.append(v)
            _audit_leitura(lid, "api_patch", k, old[0] if old else None, v, actor="api")
    if not sets:
        conn.close()
        return jsonify({'ok':False, 'error':'sem campos válidos'}), 400
    params.append(lid)
    c.execute(f"UPDATE leituras SET {', '.join(sets)} WHERE id=?", params)
    conn.commit(); conn.close()
    return jsonify({'ok':True})

@app.route('/api/leituras/<int:lid>', methods=['DELETE'])
def api_leituras_delete(lid):
    if not _api_check_token():
        return jsonify({'error':'unauthorized'}), 401
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("DELETE FROM leituras WHERE id=?", (lid,))
    conn.commit(); conn.close()
    _audit_leitura(lid, "api_delete", actor="api")
    return jsonify({'ok':True})


