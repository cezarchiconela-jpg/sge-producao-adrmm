"""Domínio monthly_readings_extended extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""

@app.route('/leituras_mensal/export_xlsx')
def leituras_mensal_export_xlsx():
    import io
    import xlsxwriter
    local = request.args.get('local','')
    mes = request.args.get('mes') or datetime.now().strftime('%m')
    ano = int(request.args.get('ano') or datetime.now().year)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    rows = c.execute('''SELECT data,hora,ativa,reativa,ponta,fp,potc,anterior,atual,diferenca,agua,esp,acum,valor
                        FROM leituras_mensais WHERE local=? AND mes=? AND ano=? ORDER BY data''',
                     (local, mes, ano)).fetchall()
    conn.close()
    output = io.BytesIO()
    wb = xlsxwriter.Workbook(output, {'in_memory': True})
    _set_xlsx_identity(wb, 'Exportação de Leituras Mensais')
    ws = wb.add_worksheet('Mensal')
    headers = ['Data','Hora','Ativa','Reativa','Ponta','FP','PotC','Anterior','Atual','Diferença','Água','Esp','Acum','Valor']
    for j,h in enumerate(headers): ws.write(0,j,h)
    for i,row in enumerate(rows, start=1):
        for j,val in enumerate(row):
            ws.write(i, j, val)
    wb.close()
    output.seek(0)
    return Response(output.read(), headers={
        'Content-Disposition': f'attachment; filename=leituras_mensais_{local}_{ano}-{mes}.xlsx'
    }, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/api/leituras_mensal_stats')
def api_leituras_mensal_stats():
    local = request.args.get('local','')
    mes = request.args.get('mes') or datetime.now().strftime('%m')
    ano = int(request.args.get('ano') or datetime.now().year)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    data = c.execute('''SELECT COUNT(*), SUM(ativa), SUM(diferenca), AVG(fp), MAX(ativa), MIN(ativa)
                        FROM leituras_mensais WHERE local=? AND mes=? AND ano=?''', (local, mes, ano)).fetchone()
    conn.close()
    total_dias, soma_kwh, soma_dif, fp_medio, pico, minimo = data or (0,0,0,0,0,0)
    return jsonify({
        'total_dias': total_dias or 0,
        'kwh_total': float(soma_kwh or 0),
        'consumo_total_diferenca': float(soma_dif or 0),
        'fp_medio': float(fp_medio or 0),
        'pico_ativa': float(pico or 0),
        'min_ativa': float(minimo or 0)
    })

@app.route('/leituras_mensal/clone_prev', methods=['POST'])
def leituras_mensal_clone_prev():
    # Clona o último mês preenchido para o mês atual (por local)
    local = request.form.get('local','')
    mes = request.form.get('mes') or datetime.now().strftime('%m')
    ano = int(request.form.get('ano') or datetime.now().year)
    # mês anterior
    prev_ano, prev_mes = ano, int(mes)-1
    if prev_mes == 0:
        prev_mes = 12; prev_ano = ano-1
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    prev_rows = c.execute('''SELECT data,hora,ativa,reativa,ponta,fp,potc,anterior,atual,diferenca,agua,esp,acum,valor
                             FROM leituras_mensais WHERE local=? AND mes=? AND ano=? ORDER BY data''',
                          (local, str(prev_mes).zfill(2), prev_ano)).fetchall()
    inseridos = 0
    num_dias = calendar.monthrange(ano, int(mes))[1]
    for i in range(num_dias):
        day = str(i+1).zfill(2)
        # find matching day from previous month if exists (same day index)
        if i < len(prev_rows):
            pr = prev_rows[i]
            data = f"{ano}-{mes}-{day}"
            # upsert
            c.execute('''INSERT INTO leituras_mensais(local,data,hora,ativa,reativa,ponta,fp,potc,anterior,atual,diferenca,agua,esp,acum,valor,mes,ano)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(local,data) DO UPDATE SET
                           hora=excluded.hora, ativa=excluded.ativa, reativa=excluded.reativa, ponta=excluded.ponta,
                           fp=excluded.fp, potc=excluded.potc, anterior=excluded.anterior, atual=excluded.atual,
                           diferenca=excluded.diferenca, agua=excluded.agua, esp=excluded.esp, acum=excluded.acum,
                           valor=excluded.valor, mes=excluded.mes, ano=excluded.ano''',
                      (local, data, pr[1], pr[2], pr[3], pr[4], pr[5], pr[6], pr[7], pr[8], pr[9], pr[10], pr[11], pr[12], pr[13], mes, ano))
            inseridos += 1
    conn.commit(); conn.close()
    flash(f'Clonado {inseridos} dias do mês anterior.', 'success')
    return redirect(url_for('leituras_mensal'))

@app.route('/api/leituras_mensal_series')
def api_leituras_mensal_series():
    local = request.args.get('local','')
    mes = request.args.get('mes') or datetime.now().strftime('%m')
    ano = int(request.args.get('ano') or datetime.now().year)
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    rows = c.execute('''SELECT data, diferenca, ativa FROM leituras_mensais 
                        WHERE local=? AND mes=? AND ano=? ORDER BY data''',
                        (local, mes, ano)).fetchall()
    conn.close()
    dias = [r[0] for r in rows]
    difs = [float(r[1] or 0) for r in rows]
    atv = [float(r[2] or 0) for r in rows]
    return jsonify({'labels': dias, 'diferenca': difs, 'ativa': atv})


@app.route('/leituras_mensal/template_csv')
def leituras_mensal_template_csv():
    # Template CSV com cabeçalho padrão para importação
    import io, csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['data','hora','ativa','reativa','ponta','fp','potc','anterior','atual','diferenca','agua','esp','acum','valor'])
    # exemplo de 3 linhas
    writer.writerow(['2025-01-01','00:00', '', '', '', '', '', '', '', '', '', '', '', ''])
    writer.writerow(['2025-01-02','00:00', '', '', '', '', '', '', '', '', '', '', '', ''])
    writer.writerow(['2025-01-03','00:00', '', '', '', '', '', '', '', '', '', '', '', ''])
    data = output.getvalue().encode('utf-8')
    return Response(data, headers={'Content-Disposition':'attachment; filename=template_leituras_mensais.csv'},
                    mimetype='text/csv')


@app.route('/config_validacao', methods=['GET','POST'])
def config_validacao():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    # populate locais list
    locais = [r[0] for r in c.execute("SELECT DISTINCT nome FROM locais ORDER BY nome").fetchall()]
    msg = None
    if request.method == 'POST':
        local = request.form.get('local','').strip()
        fp_min = float(request.form.get('fp_min', 0.85) or 0.85)
        kwh_dia_max = request.form.get('kwh_dia_max','').strip()
        kwh_val = float(kwh_dia_max) if kwh_dia_max != '' else None
        permitir_reg = 1 if request.form.get('permitir_regressivo') == 'on' else 0
        set_validacao_local(local, fp_min, kwh_val, permitir_reg)
        msg = "Configuração gravada com sucesso."
    # load configs
    rows = []
    for l in locais:
        cfg = get_validacao_local(l)
        rows.append({'local': l, **cfg})
    conn.close()
    return render_template('config_validacao.html', locais=locais, rows=rows, msg=msg)

@app.route('/leituras_mensal/audit')
def leituras_mensal_audit():
    local = request.args.get('local','')
    mes = (request.args.get('mes') or datetime.now().strftime('%m')).zfill(2)
    ano = int(request.args.get('ano') or datetime.now().year)

    # Auditoria operacional: além do histórico de alterações, avalia a coerência
    # técnica das leituras já gravadas no mês. Isto torna o botão útil para
    # validação antes de emitir a fatura.
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    try:
        logs = c.execute('''SELECT a.ts, a.field, a.old_value, a.new_value, a.acao, a.actor, lm.data
                            FROM leituras_mensais_audit a
                            JOIN leituras_mensais lm ON lm.rowid = a.lm_id
                            WHERE lm.local=? AND lm.mes=? AND lm.ano=?
                            ORDER BY a.ts DESC''', (local, mes, ano)).fetchall()
    except Exception:
        logs = []

    rows = c.execute('''SELECT data, ativa, reativa, ponta, fp, diferenca, agua, esp, valor
                        FROM leituras_mensais
                        WHERE local=? AND mes=? AND ano=?
                        ORDER BY data''', (local, mes, ano)).fetchall()
    conn.close()

    qfat = _quantidades_fatura_mensal(local, mes, ano) if local else {}

    anomalies = []
    prev_ativa = qfat.get('leitura_base_ativa', 0) if isinstance(qfat, dict) else 0
    prev_reativa = qfat.get('leitura_base_reativa', 0) if isinstance(qfat, dict) else 0
    prev_ponta = 0.0
    dias_preenchidos = 0
    fp_validos = []
    for r in rows:
        data = r['data']
        ativa = _safe_float(r['ativa'], None)
        reativa = _safe_float(r['reativa'], None)
        ponta = _safe_float(r['ponta'], None)
        fpv = _safe_float(r['fp'], None)
        dif = _safe_float(r['diferenca'], 0.0) or 0.0
        agua = _safe_float(r['agua'], 0.0) or 0.0
        if any(v is not None and v != 0 for v in (ativa, reativa, ponta)) or agua > 0:
            dias_preenchidos += 1
        if ativa is not None and ativa > 0:
            if prev_ativa and ativa < prev_ativa:
                anomalies.append({'tipo':'Leitura ativa decrescente', 'nivel':'critico', 'data':data, 'detalhe':f'Ativa {ativa:,.2f} menor que a base/anterior {prev_ativa:,.2f}. Verificar digitação, contador ou fator multiplicativo.'})
            else:
                prev_ativa = ativa
        if reativa is not None and reativa > 0:
            if prev_reativa and reativa < prev_reativa:
                anomalies.append({'tipo':'Leitura reativa decrescente', 'nivel':'critico', 'data':data, 'detalhe':f'Reativa {reativa:,.2f} menor que a base/anterior {prev_reativa:,.2f}. Verificar leitura reativa.'})
            else:
                prev_reativa = reativa
        if ponta is not None and ponta > 0:
            if prev_ponta and ponta < prev_ponta:
                anomalies.append({'tipo':'Ponta inferior à máxima anterior', 'nivel':'alerta', 'data':data, 'detalhe':f'Ponta {ponta:,.2f} menor que a máxima anterior {prev_ponta:,.2f}. Para faturação será considerada a maior ponta do mês.'})
            prev_ponta = max(prev_ponta, ponta)
        if fpv is not None and fpv > 0:
            fp_validos.append(fpv)
            if fpv < 0.85:
                anomalies.append({'tipo':'Fator de potência baixo', 'nivel':'alerta', 'data':data, 'detalhe':f'FP = {fpv:.3f}. Avaliar compensação reativa/capacitores.'})
        if dif > 0 and agua <= 0:
            anomalies.append({'tipo':'Energia sem água registada', 'nivel':'aviso', 'data':data, 'detalhe':'Há consumo de energia no dia, mas a água elevada está zero. O consumo específico fica incompleto.'})

    resumo_audit = {
        'dias_preenchidos': dias_preenchidos,
        'total_linhas': len(rows),
        'anomalias': len(anomalies),
        'fp_medio': (sum(fp_validos)/len(fp_validos)) if fp_validos else 0,
        'kwh_ativa': qfat.get('kwh_ativa', 0) if isinstance(qfat, dict) else 0,
        'kvarh_excedente': qfat.get('kvarh_excedente', 0) if isinstance(qfat, dict) else 0,
        'ponta_max': qfat.get('kw_ponta_lida', 0) if isinstance(qfat, dict) else 0,
        'agua_total': qfat.get('agua_total', 0) if isinstance(qfat, dict) else 0,
        'consumo_especifico': qfat.get('consumo_especifico', None) if isinstance(qfat, dict) else None,
        'avisos_fatura': qfat.get('avisos', []) if isinstance(qfat, dict) else [],
    }

    return render_template('leituras_mensal_audit.html', local=local, mes=mes, ano=ano, logs=logs, rows=rows, anomalies=anomalies, resumo=resumo_audit, qfat=qfat)


# === Pack 4: Importação CSV e Resumo Financeiro ===
@app.route('/leituras_mensal/import_csv', methods=['GET','POST'])
def leituras_mensal_import_csv():
    import io, csv
    msg = None; report = None
    hoje = datetime.now()
    if request.method == 'POST':
        local = (request.form.get('local') or '').strip()
        mes = (request.form.get('mes') or hoje.strftime('%m')).zfill(2)
        ano = int(request.form.get('ano') or hoje.year)
        fator_mult = float(request.form.get('fator_mult') or 1)
        file = request.files.get('csv_file')
        if not file or file.filename == '':
            msg = ('warning', 'Selecione um ficheiro CSV.')
        else:
            content = file.stream.read().decode('utf-8', errors='ignore')
            reader = csv.DictReader(io.StringIO(content))
            expected = ['data','hora','ativa','reativa','ponta','fp','potc','anterior','atual','diferenca','agua','esp','acum','valor']
            if [h.strip() for h in reader.fieldnames or []] != expected:
                msg = ('danger', 'Cabeçalho inválido. Baixe o template CSV e use exatamente as colunas esperadas.')
            else:
                conn = sqlite3.connect(DB_PATH); c = conn.cursor()
                ins = upd = err = 0
                for r in reader:
                    try:
                        data = r['data'].strip()
                        hora = r['hora'].strip()
                        ativa = float(r['ativa'] or 0) * fator_mult
                        reativa = float(r['reativa'] or 0) * fator_mult
                        ponta = float(r['ponta'] or 0) * fator_mult
                        fpv = float(r['fp'] or 0); fpv = max(0.0, min(1.0, fpv))
                        potc = float(r['potc'] or 0)
                        anterior = float(r['anterior'] or 0)
                        atual = float(r['atual'] or 0)
                        dif = float(r['diferenca'] or (max(0.0, atual - anterior)))
                        agua = float(r['agua'] or 0)
                        esp = float(r['esp'] or 0)
                        acum = float(r['acum'] or 0)
                        valor = float(r['valor'] or 0)
                        prev = c.execute("SELECT 1 FROM leituras_mensais WHERE local=? AND data=?", (local, data)).fetchone()
                        c.execute('''INSERT INTO leituras_mensais(local,data,hora,ativa,reativa,ponta,fp,potc,anterior,atual,diferenca,agua,esp,acum,valor,mes,ano)
                                     VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) 
                                     ON CONFLICT(local,data) DO UPDATE SET
                                       hora=excluded.hora, ativa=excluded.ativa, reativa=excluded.reativa, ponta=excluded.ponta,
                                       fp=excluded.fp, potc=excluded.potc, anterior=excluded.anterior, atual=excluded.atual,
                                       diferenca=excluded.diferenca, agua=excluded.agua, esp=excluded.esp, acum=excluded.acum,
                                       valor=excluded.valor, mes=excluded.mes, ano=excluded.ano''',
                                  (local, data, hora, ativa, reativa, ponta, fpv, potc, anterior, atual, dif, agua, esp, acum, valor, mes, ano))
                        if prev: upd += 1
                        else: ins += 1
                    except Exception:
                        err += 1
                conn.commit(); conn.close()
                report = {'ins': ins, 'upd': upd, 'err': err, 'local': local, 'mes': mes, 'ano': ano}
                msg = ('success', f'Importação concluída. Inseridos={ins}, Atualizados={upd}, Erros={err}.')
    # GET or after POST render
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    locais = [r[0] for r in c.execute("SELECT DISTINCT nome FROM locais ORDER BY nome").fetchall()]
    conn.close()
    return render_template('leituras_mensal_import_csv.html', locais=locais, msg=msg, report=report)
# === FATURA EDM A PARTIR DAS LEITURAS MENSAIS ===

@app.route('/leituras_mensal/fatura_edm')
def leituras_mensal_fatura_edm():
    """Gera a fatura mensal através do motor único e do tarifário histórico."""
    local = request.args.get('local', '').strip()
    mes = (request.args.get('mes') or '').strip().zfill(2)
    ano = (request.args.get('ano') or '').strip()
    if not local or not mes or not ano:
        return redirect(url_for('leituras_mensal'))
    try:
        ctx = _montar_contexto_fatura_mensal(local, mes, int(ano))
    except (TypeError, ValueError):
        flash('Período de faturação inválido.', 'warning')
        return redirect(url_for('leituras_mensal'))
    invoice_id = _arquivar_fatura_mensal_snapshot(ctx)
    return render_template('leituras_mensal_fatura_edm.html', invoice_id=invoice_id, **ctx)


@app.route('/leituras_mensal/financeiro')
def leituras_mensal_financeiro():
    local = request.args.get('local','').strip()
    mes = (request.args.get('mes') or datetime.now().strftime('%m')).zfill(2)
    ano = int(request.args.get('ano') or datetime.now().year)
    ctx = _montar_contexto_fatura_mensal(local, mes, ano)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """SELECT data, ativa, reativa, ponta, fp, diferenca, agua, esp, valor
           FROM leituras_mensais WHERE local=? AND mes=? AND ano=? ORDER BY data""",
        (local, mes, ano),
    ).fetchall()
    conn.close()
    fp_values = [float(r['fp']) for r in rows if r['fp'] is not None and float(r['fp'] or 0) > 0]
    resumo = dict(ctx)
    resumo.update({
        'valor_total': ctx['total'],
        'fp_medio': (sum(fp_values) / len(fp_values)) if fp_values else 0.0,
        'consumo_especifico': ctx['consumo_especifico_medio'],
        'avisos': ctx['avisos_fatura'],
    })
    local_id = next((lid for lid, nome in get_locais() if nome == local), None)
    return render_template(
        'leituras_mensal_financeiro.html', local=local, mes=mes, ano=ano,
        cfg=get_local_cfg_full(local_id) if local_id is not None else {},
        resumo=resumo, rows=rows, qfat=ctx['qfat'],
        tarifa_ativa=ctx['tarifa_ativa'], tarifa_reativa=ctx['tarifa_reativa'],
        tarifa_ponta=ctx['tarifa_ponta'], taxa_fixa=ctx['taxa_fixa'],
        taxa_radio=ctx['taxa_radio'], taxa_lixo=ctx['taxa_lixo'],
        pot_contratada=ctx['pot_contratada'],
    )


@app.route('/leituras_mensal/faturas')
def leituras_mensal_faturas_arquivo():
    ensure_faturas_mensais_archive_schema()
    local = request.args.get('local','').strip()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if local:
        faturas = c.execute('''SELECT * FROM faturas_mensais_arquivo WHERE local=? ORDER BY ano DESC, mes DESC''', (local,)).fetchall()
    else:
        faturas = c.execute('''SELECT * FROM faturas_mensais_arquivo ORDER BY atualizado_em DESC LIMIT 200''').fetchall()
    locais = [r[1] for r in get_locais()] if 'get_locais' in globals() else []
    conn.close()
    return render_template('leituras_mensal_faturas_arquivo.html', faturas=faturas, local=local, locais=locais)


@app.route('/leituras_mensal/arquivo')
def leituras_mensal_arquivo():
    ensure_leituras_mensais_phase2_schema()
    local = request.args.get('local','').strip()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if local:
        rows = c.execute('''
            SELECT local, mes, ano,
                   COUNT(*) AS total_linhas,
                   SUM(CASE WHEN (ativa IS NOT NULL AND ativa>0) OR (reativa IS NOT NULL AND reativa>0) OR (ponta IS NOT NULL AND ponta>0) OR (agua IS NOT NULL AND agua>0) THEN 1 ELSE 0 END) AS dias_preenchidos,
                   MAX(data) AS ultima_data,
                   SUM(COALESCE(agua,0)) AS agua_total,
                   SUM(COALESCE(diferenca,0)) AS soma_diferencas
            FROM leituras_mensais
            WHERE local=?
            GROUP BY local, mes, ano
            ORDER BY ano DESC, mes DESC
        ''', (local,)).fetchall()
    else:
        rows = c.execute('''
            SELECT local, mes, ano,
                   COUNT(*) AS total_linhas,
                   SUM(CASE WHEN (ativa IS NOT NULL AND ativa>0) OR (reativa IS NOT NULL AND reativa>0) OR (ponta IS NOT NULL AND ponta>0) OR (agua IS NOT NULL AND agua>0) THEN 1 ELSE 0 END) AS dias_preenchidos,
                   MAX(data) AS ultima_data,
                   SUM(COALESCE(agua,0)) AS agua_total,
                   SUM(COALESCE(diferenca,0)) AS soma_diferencas
            FROM leituras_mensais
            GROUP BY local, mes, ano
            ORDER BY ano DESC, mes DESC, local ASC
        ''').fetchall()
    locais = [r[1] for r in get_locais()] if 'get_locais' in globals() else []
    conn.close()
    return render_template('leituras_mensal_arquivo.html', rows=rows, local=local, locais=locais)


def _draw_right(c, x, y, txt, font='Helvetica', size=8):
    c.setFont(font, size); c.drawRightString(x, y, str(txt))


def _fmt_pdf(v, nd=2):
    try:
        return _fmt_mil(v, nd)
    except Exception:
        return str(v)


@app.route('/leituras_mensal/fatura_edm_pdf')
def leituras_mensal_fatura_edm_pdf():
    local = request.args.get('local','').strip()
    mes = (request.args.get('mes') or datetime.now().strftime('%m')).zfill(2)
    ano = int(request.args.get('ano') or datetime.now().year)
    if not local:
        return redirect(url_for('leituras_mensal'))
    ctx = _montar_contexto_fatura_mensal(local, mes, ano)
    invoice_id = _arquivar_fatura_mensal_snapshot(ctx)

    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib import colors
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=landscape(A4))
    _set_pdf_identity(c, 'Fatura de Energia - EDM (Modelo Interno)')
    W, H = landscape(A4)
    margin = 28
    logo_path = os.path.join(BASE_DIR, 'static', 'adrmm_logo.png')

    if os.path.exists(logo_path):
        try:
            c.saveState(); c.setFillAlpha(0.08)
            c.drawImage(logo_path, W/2-145, H/2-120, width=290, height=240, preserveAspectRatio=True, mask='auto')
            c.restoreState()
        except Exception:
            pass
    c.setStrokeColor(colors.HexColor('#073b78')); c.setLineWidth(1.2)
    c.line(margin, H-76, W-margin, H-76)
    if os.path.exists(logo_path):
        try: c.drawImage(logo_path, margin, H-68, width=46, height=46, preserveAspectRatio=True, mask='auto')
        except Exception: pass
    c.setFillColor(colors.HexColor('#073b78'))
    c.setFont('Helvetica-Bold', 17); c.drawString(margin+58, H-44, 'Fatura de Energia - EDM (Modelo Interno)')
    c.setFont('Helvetica', 8.5); c.setFillColor(colors.HexColor('#244f78'))
    c.drawString(margin+58, H-58, f'{INSTITUTION_NAME} · Sistema de Gestão de Energia')
    c.setFillColor(colors.black)
    _draw_right(c, W-margin, H-36, f"Local: {local}", 'Helvetica-Bold', 9)
    _draw_right(c, W-margin, H-50, f"Período: {ctx['periodo']}", 'Helvetica-Bold', 9)
    _draw_right(c, W-margin, H-64, f"Registo SGE: #{invoice_id or '-'}", 'Helvetica', 8)

    y = H-94
    c.setFont('Helvetica-Bold', 9); c.setFillColor(colors.HexColor('#073b78'))
    c.drawString(margin, y, 'Parâmetros:')
    c.setFillColor(colors.black); c.setFont('Helvetica', 8)
    c.drawString(margin+75, y, f"Pot. contratada: {_fmt_pdf(ctx['pot_contratada'],2)} kVA")
    c.drawString(margin+230, y, f"Tarifa ativa: {_fmt_pdf(ctx['tarifa_ativa'],4)} MT/kWh")
    c.drawString(margin+385, y, f"Tarifa reativa: {_fmt_pdf(ctx['tarifa_reativa'],4)} MT/kVArh")
    c.drawString(margin+555, y, f"Tarifa ponta: {_fmt_pdf(ctx['tarifa_ponta'],4)} MT/kW")
    y -= 18
    c.setFillColor(colors.HexColor('#f4faff')); c.rect(margin, y-18, W-2*margin, 28, fill=1, stroke=0)
    c.setFillColor(colors.HexColor('#102b43')); c.setFont('Helvetica', 7.6)
    c.drawString(margin+8, y-2, f"Base: Ativa = {_fmt_pdf(ctx['leitura_final_ativa'],2)} - {_fmt_pdf(ctx['leitura_base_ativa'],2)} = {_fmt_pdf(ctx['kwh_ativa'],2)} kWh | Reativa = {_fmt_pdf(ctx['leitura_final_reativa'],2)} - {_fmt_pdf(ctx['leitura_base_reativa'],2)} = {_fmt_pdf(ctx['kvarh_reativa'],2)} kVArh | Excedente = máx(Reativa - 0,75 × Ativa, 0)")

    def table_header(x, y, w, title):
        c.setFillColor(colors.HexColor('#eaf4ff')); c.rect(x, y, w, 18, fill=1, stroke=0)
        c.setFillColor(colors.HexColor('#073b78')); c.setFont('Helvetica-Bold', 9); c.drawString(x+7, y+5, title)
        c.setStrokeColor(colors.HexColor('#cfddeb')); c.rect(x, y-120, w, 138, fill=0, stroke=1)
    left_x = margin; right_x = W/2+6; box_w = W/2-margin-12; top = y-46
    table_header(left_x, top, box_w, 'Resumo de energia')
    table_header(right_x, top, box_w, 'Taxas, IVA e total')
    def row(x, y, name, qty, tarifa, valor, bold=False, dark=False):
        if dark:
            c.setFillColor(colors.HexColor('#0f2337')); c.rect(x, y-2, box_w, 17, fill=1, stroke=0); c.setFillColor(colors.white)
        else:
            c.setFillColor(colors.black)
        c.setFont('Helvetica-Bold' if bold else 'Helvetica', 8)
        c.drawString(x+7, y+3, name)
        if qty is not None: _draw_right(c, x+box_w-170, y+3, qty, 'Helvetica-Bold' if bold else 'Helvetica', 8)
        if tarifa is not None: _draw_right(c, x+box_w-88, y+3, tarifa, 'Helvetica-Bold' if bold else 'Helvetica', 8)
        _draw_right(c, x+box_w-8, y+3, valor, 'Helvetica-Bold' if bold else 'Helvetica', 8)
    yy = top-20
    row(left_x, yy, 'Energia ativa', f"{_fmt_pdf(ctx['kwh_ativa'],2)} kWh", _fmt_pdf(ctx['tarifa_ativa'],4), _fmt_pdf(ctx['valor_ativa'],2)); yy-=19
    row(left_x, yy, 'Reativa excedente', f"{_fmt_pdf(ctx['kvarh_excedente'],2)} kVArh", _fmt_pdf(ctx['tarifa_reativa'],4), _fmt_pdf(ctx['valor_reativa'],2)); yy-=19
    row(left_x, yy, 'Demanda de ponta', f"{_fmt_pdf(ctx['demanda_ponta_kw'],2)} kW", _fmt_pdf(ctx['tarifa_ponta'],4), _fmt_pdf(ctx['valor_ponta'],2)); yy-=22
    row(left_x, yy, 'Subtotal energia', None, None, _fmt_pdf(ctx['subtotal_energia'],2), True); yy-=22
    c.setFont('Helvetica', 7.2); c.setFillColor(colors.HexColor('#4e6982'))
    c.drawString(left_x+7, yy+5, f"Ponta máxima considerada: {_fmt_pdf(ctx['kw_ponta_lida'],2)} kW | Limite reativa: {_fmt_pdf(ctx['limite_reativa'],2)} kVArh")

    yy = top-20
    row(right_x, yy, 'Taxa fixa', None, None, _fmt_pdf(ctx['taxa_fixa'],2)); yy-=17
    row(right_x, yy, 'Taxa rádio', None, None, _fmt_pdf(ctx['taxa_radio'],2)); yy-=17
    row(right_x, yy, 'Taxa lixo', None, None, _fmt_pdf(ctx['taxa_lixo'],2)); yy-=18
    row(right_x, yy, 'Subtotal taxas', None, None, _fmt_pdf(ctx['subtotal_taxas'],2), True); yy-=18
    row(right_x, yy, 'Subtotal', None, None, _fmt_pdf(ctx['subtotal'],2)); yy-=17
    row(right_x, yy, f"Base IVA ({_fmt_pdf(ctx['base_iva_percent'],0)}%)", None, None, _fmt_pdf(ctx['base_iva'],2)); yy-=17
    row(right_x, yy, f"IVA {_fmt_pdf(ctx['iva_percent'],0)}%", None, None, _fmt_pdf(ctx['valor_iva'],2)); yy-=20
    row(right_x, yy, 'TOTAL A PAGAR', None, None, _fmt_pdf(ctx['total'],2), True, True)

    y2 = top-158
    c.setFillColor(colors.HexColor('#f8fbff')); c.rect(margin, y2-38, W-2*margin, 42, fill=1, stroke=1)
    c.setFillColor(colors.HexColor('#073b78')); c.setFont('Helvetica-Bold', 8.5); c.drawString(margin+8, y2-10, 'Valor a pagar por extenso:')
    c.setFillColor(colors.black); c.setFont('Helvetica', 8)
    ext = ctx.get('total_extenso') or _mzn_extenso(ctx['total'])
    max_chars = 145
    lines = [ext[i:i+max_chars] for i in range(0, len(ext), max_chars)]
    for i, line in enumerate(lines[:2]): c.drawString(margin+8, y2-24-(i*10), line)

    y3 = y2-58
    c.setFont('Helvetica-Bold', 8.5); c.setFillColor(colors.HexColor('#073b78')); c.drawString(margin, y3, 'Indicadores adicionais')
    c.setFillColor(colors.black); c.setFont('Helvetica', 8)
    c.drawString(margin, y3-14, f"Água total: {_fmt_pdf(ctx['agua_total'],2)} m³")
    ce = '-' if ctx['consumo_especifico_medio'] is None else f"{_fmt_pdf(ctx['consumo_especifico_medio'],3)} kWh/m³"
    c.drawString(margin+150, y3-14, f"Consumo específico médio: {ce}")
    c.drawRightString(W-margin, y3-14, 'Documento gerado pelo SGE / Equipa de Eficiência Energética')
    c.setStrokeColor(colors.HexColor('#cfddeb')); c.line(margin, 34, W-margin, 34)
    c.setFont('Helvetica', 7); c.setFillColor(colors.HexColor('#607d9d'))
    c.drawCentredString(W/2, 22, 'Documento interno de apoio à conferência da fatura EDM. Valores sujeitos à validação da fatura oficial e parâmetros tarifários vigentes.')
    c.showPage(); c.save(); buffer.seek(0)
    filename = f"Fatura_EDM_{local.replace(' ','_')}_{mes}_{ano}.pdf"
    return Response(buffer.getvalue(), mimetype='application/pdf', headers={'Content-Disposition': f'attachment; filename="{filename}"'})

def _mt_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def _mt_exec(conn, sql, args=()):
    cur = conn.cursor()
    cur.execute(sql, args)
    conn.commit()
    return cur

# --- Migração MT ---
def _mt_init_db():
    conn = _mt_conn(); c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS mt_config (
            id INTEGER PRIMARY KEY CHECK (id=1),
            alfa_reativa REAL DEFAULT 0.75,
            iva_taxa REAL DEFAULT 0.16,
            iva_base REAL DEFAULT 0.62,
            tarifa_ativa REAL DEFAULT 4.780,
            tarifa_reativa REAL DEFAULT 1.430,
            tarifa_potencia REAL DEFAULT 497.03
        )
    """)
    c.execute("INSERT OR IGNORE INTO mt_config (id) VALUES (1)")

    c.execute("""
        CREATE TABLE IF NOT EXISTS mt_leituras_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            local_id INTEGER NOT NULL,
            data TEXT NOT NULL,
            hora TEXT NOT NULL,
            ea_leitura REAL NOT NULL,
            er_leitura REAL NOT NULL,
            demanda_lida REAL NOT NULL,
            obs TEXT,
            UNIQUE(local_id, data, hora),
            FOREIGN KEY(local_id) REFERENCES locais(id) ON DELETE CASCADE
        )
    """)
    conn.commit(); conn.close()

_mt_init_db()

def _mt_cfg():
    conn = _mt_conn()
    row = _mt_exec(conn, "SELECT * FROM mt_config WHERE id=1").fetchone(); conn.close()
    return row

def _mt_get_local_cfg(local_id: int):
    """Obtém FM, PC e tarifas do local a partir de locais_cfg, com defaults de segurança."""
    conn = _mt_conn()
    row = _mt_exec(conn, """
        SELECT COALESCE(fator_mult,1.0) AS fm,
               COALESCE(pot_contratada,0.0) AS pc,
               COALESCE(tarifa_ativa,4.780) AS t_ativa,
               COALESCE(tarifa_reativa,1.430) AS t_reat,
               COALESCE(tarifa_ponta,497.03) AS t_pot
          FROM locais_cfg WHERE local_id=?
    """, (local_id,)).fetchone()
    conn.close()
    if not row:
        return (1.0, 0.0, 4.780, 1.430, 497.03)
    return (float(row["fm"]), float(row["pc"]), float(row["t_ativa"]), float(row["t_reat"]), float(row["t_pot"]))

def _mt_month_bounds(ano: int, mes: int):
    import calendar
    from datetime import date
    first = date(ano, mes, 1)
    last = date(ano, mes, calendar.monthrange(ano, mes)[1])
    return first.isoformat(), last.isoformat()

# --------- Rotas: Configuração MT ---------
@app.route("/mt/config", methods=["GET"])
def mt_config():
    cfg = _mt_cfg()
    return render_template("config_mt.html", cfg=cfg)

# --------- Rotas: Leituras MT ---------
@app.route("/mt/<int:local_id>/leituras")
def mt_leituras(local_id):
    from datetime import date
    hoje = date.today()
    ano = int(request.args.get("ano", hoje.year))
    mes = int(request.args.get("mes", hoje.month))
    first, last = _mt_month_bounds(ano, mes)

    conn = _mt_conn()
    local = _mt_exec(conn, "SELECT id, nome FROM locais WHERE id=?", (local_id,)).fetchone()
    if not local:
        conn.close()
        flash("Local não encontrado.", "danger")
        return redirect(url_for("index"))

    rows = _mt_exec(conn, """
        SELECT * FROM mt_leituras_raw
        WHERE local_id=? AND date(data) BETWEEN ? AND ?
        ORDER BY date(data), time(hora)
    """, (local_id, first, last)).fetchall()
    fm, Pc, t_ativa_l, t_reat_l, t_pot_l = _mt_get_local_cfg(local_id)
    tarifas_periodo = _tarifas_local_periodo(local_id, mes, ano)
    conn.close()

    # última leitura do dia
    by_day = {}
    for r in rows:
        d = r["data"]
        if d not in by_day or r["hora"] > by_day[d]["hora"]:
            by_day[d] = dict(r)

    dias = sorted(by_day.keys())
    tabela = []
    EA_total = ER_total = 0.0
    Dmax = 0.0
    prev_ea = prev_er = None

    for d in dias:
        r = by_day[d]
        ea_aj = float(r["ea_leitura"]) * fm
        er_aj = float(r["er_leitura"]) * fm
        demanda_aj = float(r["demanda_lida"]) * fm

        if prev_ea is None:
            dea = 0.0; der = 0.0
        else:
            dea = max(0.0, ea_aj - prev_ea)
            der = max(0.0, er_aj - prev_er)

        custo_ativo_d = dea * float(tarifas_periodo["tarifa_ativa"])

        # indicadores simples
        P_d = (dea/24.0) if dea>0 else 0.0
        Q_d = (der/24.0) if der>0 else 0.0
        S_d = math.sqrt(P_d**2 + Q_d**2) if (P_d or Q_d) else 0.0
        FP_d = (P_d/S_d) if S_d>0 else None

        tabela.append({
            "data": d, "hora": r["hora"],
            "ea_leitura": ea_aj, "er_leitura": er_aj,
            "dea": dea, "der": der,
            "custo_ativo_d": custo_ativo_d,
            "demanda": demanda_aj,
            "FP_d": FP_d
        })

        EA_total += dea; ER_total += der
        Dmax = max(Dmax, demanda_aj)
        prev_ea, prev_er = ea_aj, er_aj

    fatura = calculate_invoice(
        active_kwh=EA_total,
        reactive_kvarh=ER_total,
        measured_peak_kw=Dmax,
        contracted_power_kw=Pc,
        tariffs={
            **tarifas_periodo,
            # Este resumo MT legado nunca incluiu taxas fixas; preserva-se essa
            # apresentação, mantendo as mesmas regras centrais de energia e IVA.
            "taxa_fixa": 0.0,
            "taxa_radio": 0.0,
            "taxa_lixo": 0.0,
        },
    )
    alfa = REACTIVE_LIMIT_FACTOR
    ER_exced = fatura["reactive_excess_kvarh"]
    C_ativo = fatura["active_cost_mzn"]
    C_reativa = fatura["reactive_cost_mzn"]
    P_fat = fatura["billing_demand_kw"]
    C_pot = fatura["demand_cost_mzn"]
    subtotal = fatura["subtotal_mzn"]
    iva = fatura["vat_mzn"]
    total = fatura["total_mzn"]

    resumo = {
        "EA_total": EA_total, "ER_total": ER_total,
        "ER_exced": ER_exced, "C_ativo": C_ativo, "C_reativa": C_reativa,
        "Dmax": Dmax, "Pc": Pc, "P_fat": P_fat, "C_pot": C_pot,
        "subtotal": subtotal, "iva": iva, "total": total,
        "alfa": alfa,
        "iva_taxa": VAT_RATE, "iva_base": VAT_BASE_FACTOR,
        "tarifa_ativa": float(tarifas_periodo["tarifa_ativa"]),
        "tarifa_reativa": float(tarifas_periodo["tarifa_reativa"]),
        "tarifa_potencia": float(tarifas_periodo["tarifa_ponta"]),
        "ano": ano, "mes": mes
    }

    return render_template_string("""
    {% extends "base.html" %}
    {% block content %}
    <div class="d-flex justify-content-between align-items-center">
      <h3>Leituras Mensais (MT) — {{ local['nome'] }}</h3>
      <div><a class="btn btn-sm btn-primary" href="{{ url_for('mt_nova_leitura', local_id=local['id']) }}">+ Nova leitura</a></div>
    </div>

    <form method="get" class="row g-2 my-2">
      <div class="col-auto">
        <label class="form-label">Mês</label>
        <input class="form-control" type="number" name="mes" value="{{ mes }}" min="1" max="12">
      </div>
      <div class="col-auto">
        <label class="form-label">Ano</label>
        <input class="form-control" type="number" name="ano" value="{{ ano }}" min="2000" max="2100">
      </div>
      <div class="col-auto align-self-end">
        <button class="btn btn-outline-secondary">Ir</button>
      </div>
    </form>

    <div class="table-responsive">
    <table class="table table-striped table-sm align-middle">
      <thead>
        <tr>
          <th>Data</th><th>Hora</th>
          <th>Leitura Ativa (aj.)</th>
          <th>Leitura Reativa (aj.)</th>
          <th>Δ Ativa (kWh)</th>
          <th>Δ Reativa (kVArh)</th>
          <th>Custo ativo (MZN)</th>
          <th>Demanda lida (kVA)</th>
          <th>FP (aprox.)</th>
        </tr>
      </thead>
      <tbody>
        {% for r in tabela %}
          <tr>
            <td>{{ r.data }}</td>
            <td>{{ r.hora }}</td>
            <td>{{ '%.3f'|format(r.ea_leitura) }}</td>
            <td>{{ '%.3f'|format(r.er_leitura) }}</td>
            <td>{{ '%.3f'|format(r.dea) }}</td>
            <td>{{ '%.3f'|format(r.der) }}</td>
            <td>{{ '%.2f'|format(r.custo_ativo_d) }}</td>
            <td>{{ '%.3f'|format(r.demanda) }}</td>
            <td>
              {% if r.FP_d is not none %}
                <span class="badge bg-{{ 'success' if r.FP_d>=0.92 else 'warning' }}">{{ '%.3f'|format(r.FP_d) }}</span>
              {% else %} — {% endif %}
            </td>
          </tr>
        {% else %}
          <tr><td colspan="9" class="text-center text-muted">Sem leituras para o mês.</td></tr>
        {% endfor %}
      </tbody>
    </table>
    </div>

    <hr>
    <h5>Resumo do mês {{ "%02d"|format(mes) }}/{{ ano }}</h5>
    <div class="row g-3">
      <div class="col-md-3">
        <div class="card"><div class="card-body">
          <div class="small text-muted">Energia Ativa total</div>
          <div class="h5">{{ '%.3f'|format(resumo.EA_total) }} kWh</div>
          <div class="small text-muted">Tarifa ativa: {{ '%.3f'|format(resumo.tarifa_ativa) }} MZN/kWh</div>
          <div class="small">Custo: <strong>{{ '%.2f'|format(resumo.C_ativo) }} MZN</strong></div>
        </div></div>
      </div>
      <div class="col-md-3">
        <div class="card"><div class="card-body">
          <div class="small text-muted">Energia Reativa total</div>
          <div class="h5">{{ '%.3f'|format(resumo.ER_total) }} kVArh</div>
          <div class="small text-muted">Excedente (α={{ '%.2f'|format(resumo.alfa) }}): <strong>{{ '%.3f'|format(resumo.ER_exced) }} kVArh</strong></div>
          <div class="small">Custo: <strong>{{ '%.2f'|format(resumo.C_reativa) }} MZN</strong></div>
        </div></div>
      </div>
      <div class="col-md-3">
        <div class="card"><div class="card-body">
          <div class="small text-muted">Demanda máxima (Dmax)</div>
          <div class="h5">{{ '%.3f'|format(resumo.Dmax) }} kVA</div>
          <div class="small text-muted">Ponta faturável = 0,2·PC + 0,8·Dmax</div>
          <div class="small">PC: {{ '%.2f'|format(resumo.Pc) }} kVA</div>
          <div class="small">P_fat: <strong>{{ '%.3f'|format(resumo.P_fat) }} kVA</strong></div>
          <div class="small">Custo potência: <strong>{{ '%.2f'|format(resumo.C_pot) }} MZN</strong></div>
        </div></div>
      </div>
      <div class="col-md-3">
        <div class="card"><div class="card-body">
          <div class="small text-muted">Totais</div>
          <div class="small">Subtotal: <strong>{{ '%.2f'|format(resumo.subtotal) }} MZN</strong></div>
          <div class="small">IVA ({{ '%.2f'|format(resumo.iva_taxa*100) }}% de {{ '%.0f'|format(resumo.iva_base*100) }}%):
            <strong>{{ '%.2f'|format(resumo.iva) }} MZN</strong></div>
          <div class="h5">Total: {{ '%.2f'|format(resumo.total) }} MZN</div>
        </div></div>
      </div>
    </div>

    <div class="mt-3">
      <a class="btn btn-secondary" href="{{ url_for('index') }}">Início</a>
      <a class="btn btn-outline-primary" href="{{ url_for('mt_nova_leitura', local_id=local['id']) }}">Lançar outra leitura</a>
    </div>
    {% endblock %}
    """, local=local, tabela=tabela, resumo=resumo, ano=ano, mes=mes)

@app.route("/mt/<int:local_id>/leituras/novo", methods=["GET","POST"])
def mt_nova_leitura(local_id):
    conn = _mt_conn()
    local = _mt_exec(conn, "SELECT id, nome FROM locais WHERE id=?", (local_id,)).fetchone()
    if not local:
        conn.close()
        flash("Local não encontrado.", "danger")
        return redirect(url_for("index"))
    if request.method == "POST":
        data = (request.form.get("data") or "").strip()
        hora = (request.form.get("hora") or "").strip()
        try:
            _ = data and hora  # formatos validados pelo HTML5; backend tolerante
        except:
            pass
        ea = float(request.form.get("ea_leitura", 0) or 0)
        er = float(request.form.get("er_leitura", 0) or 0)
        demanda = float(request.form.get("demanda_lida", 0) or 0)
        obs = request.form.get("obs")
        try:
            _mt_exec(conn, """INSERT INTO mt_leituras_raw (local_id, data, hora, ea_leitura, er_leitura, demanda_lida, obs)
                              VALUES (?,?,?,?,?,?,?)""",
                     (local_id, data, hora, ea, er, demanda, obs))
            conn.close()
            flash("Leitura registada (MT).", "success")
        except sqlite3.IntegrityError:
            conn.close()
            flash("Já existe leitura para este local nesta data/hora.", "warning")
        return redirect(url_for("mt_leituras", local_id=local_id))
    conn.close()
    return render_template_string("""
    {% extends "base.html" %}
    {% block content %}
    <h3>Nova leitura (MT) — {{ local['nome'] }}</h3>
    <form method="post" class="row g-3">
      <div class="col-md-3">
        <label class="form-label">Data</label>
        <input name="data" type="date" class="form-control" required>
      </div>
      <div class="col-md-2">
        <label class="form-label">Hora</label>
        <input name="hora" type="time" class="form-control" required>
      </div>
      <div class="col-md-3">
        <label class="form-label">Leitura Ativa (kWh)</label>
        <input name="ea_leitura" type="number" step="0.001" class="form-control" required>
      </div>
      <div class="col-md-3">
        <label class="form-label">Leitura Reativa (kVArh)</label>
        <input name="er_leitura" type="number" step="0.001" class="form-control" required>
      </div>
      <div class="col-md-3">
        <label class="form-label">Demanda lida (kVA máx. no mês)</label>
        <input name="demanda_lida" type="number" step="0.001" class="form-control" required>
      </div>
      <div class="col-12">
        <label class="form-label">Observações</label>
        <textarea name="obs" class="form-control" rows="2"></textarea>
      </div>
      <div class="col-12">
        <button class="btn btn-primary">Registar</button>
        <a class="btn btn-secondary" href="{{ url_for('mt_leituras', local_id=local['id']) }}">Voltar</a>
      </div>
    </form>
    {% endblock %}
    """, local=local)


# === API: Configurações do Local por ID ===
@app.route("/api/local_cfg_by_id/<int:local_id>")
def api_local_cfg_by_id(local_id):
    from flask import jsonify, g
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute(
        "SELECT l.id, l.nome, "
        "COALESCE(lc.pot_contratada,0.0), COALESCE(lc.pot_instalada,0.0), COALESCE(lc.fator_mult,1.0), "
        "COALESCE(lc.tarifa_ativa,0.0), COALESCE(lc.tarifa_reativa,0.0), COALESCE(lc.tarifa_ponta,0.0), COALESCE(lc.tarifa_perdas,0.0), "
        "COALESCE(lc.taxa_fixa,0.0), COALESCE(lc.taxa_radio,0.0), COALESCE(lc.taxa_lixo,0.0), COALESCE(lc.iva,0.0) "
        "FROM locais l LEFT JOIN locais_cfg lc ON l.id = lc.local_id WHERE l.id = ?",
        (local_id,)
    )
    row = c.fetchone(); conn.close()
    if not row:
        return jsonify({"erro":"Local não encontrado","id":local_id}), 404
    keys = ["id","nome","pot_contratada","pot_instalada","fator_mult",
            "tarifa_ativa","tarifa_reativa","tarifa_ponta","tarifa_perdas",
            "taxa_fixa","taxa_radio","taxa_lixo","iva"]
    payload = dict(zip(keys, row)); payload['iva'] = 16.0
    return jsonify(payload)


# === API: Calcular Fatura (Leituras Mensais) ===

# === API: Configurações do Local por NOME ===
@app.route("/api/local_cfg_by_name/<path:local_name>")
def api_local_cfg_by_name(local_name):
    from flask import jsonify, g
    name = (local_name or "").strip()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute(
        "SELECT l.id, l.nome, "
        "COALESCE(lc.pot_contratada,0.0), COALESCE(lc.pot_instalada,0.0), COALESCE(lc.fator_mult,1.0), "
        "COALESCE(lc.tarifa_ativa,0.0), COALESCE(lc.tarifa_reativa,0.0), COALESCE(lc.tarifa_ponta,0.0), COALESCE(lc.tarifa_perdas,0.0), "
        "COALESCE(lc.taxa_fixa,0.0), COALESCE(lc.taxa_radio,0.0), COALESCE(lc.taxa_lixo,0.0), COALESCE(lc.iva,0.0) "
        "FROM locais l LEFT JOIN locais_cfg lc ON l.id = lc.local_id WHERE l.nome = ?",
        (name,)
    )
    row = c.fetchone(); conn.close()
    if not row:
        return jsonify({"erro":"Local não encontrado","nome":name}), 404
    keys = ["id","nome","pot_contratada","pot_instalada","fator_mult",
            "tarifa_ativa","tarifa_reativa","tarifa_ponta","tarifa_perdas",
            "taxa_fixa","taxa_radio","taxa_lixo","iva"]
    payload = dict(zip(keys, row)); payload['iva'] = 16.0
    return jsonify(payload)

@app.route('/api/leituras_mensal/calcular', methods=['POST'])
def api_calc_fatura_leituras():
    data = request.get_json(silent=True) or {}
    local = (data.get('local') or '').strip()
    mes   = str(data.get('mes') or '').zfill(2)
    ano   = int(data.get('ano') or 0)
    if not local or not mes or not ano:
        return jsonify({'erro':'Parâmetros inválidos'}), 400

    lid = None
    for (lid_, nome) in get_locais():
        if nome == local:
            lid = lid_
            break
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    rows = c.execute(
        "SELECT IFNULL(ativa,0), IFNULL(reativa,0), IFNULL(ponta,0) "
        "FROM leituras_mensais WHERE local=? AND mes=? AND ano=?",
        (local, mes, ano)
    ).fetchall()
    conn.close()
    if not rows:
        return jsonify({'erro':'Sem dados de leituras para o período selecionado.'}), 404

    ctx = _montar_contexto_fatura_mensal(local, mes, ano)

    return jsonify({
        'local': local, 'mes': mes, 'ano': ano,
        'totais': {'kwh': ctx['kwh_ativa'], 'kvarh': ctx['kvarh_reativa'], 'demanda_kw': ctx['kw_ponta_lida']},
        'tarifas': {'ativa': ctx['tarifa_ativa'], 'reativa': ctx['tarifa_reativa'],
                    'ponta': ctx['tarifa_ponta'], 'perdas': ctx['tarifa_perdas']},
        'taxas': {'fixa': ctx['taxa_fixa'], 'radio': ctx['taxa_radio'], 'lixo': ctx['taxa_lixo'],
                  'iva_percent': VAT_RATE * 100, 'iva_base_percent': VAT_BASE_FACTOR * 100},
        'subtotal': {'ativa': ctx['valor_ativa'], 'reativa': ctx['valor_reativa'],
                     'ponta': ctx['valor_ponta'], 'perdas': ctx['valor_perdas'],
                     'energia': ctx['subtotal_energia'], 'taxas': ctx['subtotal_taxas']},
        'iva': {'base': ctx['base_iva'], 'valor': ctx['valor_iva']},
        'total': {'sem_iva': ctx['subtotal'], 'com_iva': ctx['total']}
    })



