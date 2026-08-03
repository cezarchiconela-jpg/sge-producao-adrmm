"""Domínio de Eficiência Energética e Desempenho Operacional."""

import json as _json

from efficiency_service import (
    DEFAULT_MIN_COVERAGE_PCT,
    EfficiencyValidationError,
    audit as efficiency_audit,
    build_baseline_snapshot,
    build_dashboard as build_efficiency_dashboard,
)


EFFICIENCY_MEASURE_STATES = ("Planeada", "Em execução", "Implementada", "Verificada", "Cancelada")
EFFICIENCY_PRIORITIES = ("Alta", "Média", "Baixa")
EFFICIENCY_CATEGORIES = (
    "Operacional", "Motores e bombas", "Factor de potência", "Ponta",
    "Automação", "Instrumentação", "Manutenção", "Solar", "Outro",
)


def _efficiency_manager():
    return (not _login_required_enabled()) or _user_has_role("admin", "gestor")


def _efficiency_technical_writer():
    return (not _login_required_enabled()) or _user_has_role("admin", "gestor", "tecnico")


def _efficiency_period_args():
    now = datetime.now()
    try:
        year = int(request.args.get("ano") or now.year)
        month = int(request.args.get("mes") or now.month)
        if not 1 <= month <= 12 or not 2000 <= year <= 2200:
            raise ValueError
    except (TypeError, ValueError):
        year, month = now.year, now.month
    local_id = request.args.get("local_id", type=int)
    return year, month, local_id


def _efficiency_locals(conn):
    return conn.execute(
        "SELECT id, nome FROM locais WHERE COALESCE(ativo,1)=1 ORDER BY nome"
    ).fetchall()


@app.route("/eficiencia")
def eficiencia_dashboard():
    year, month, local_id = _efficiency_period_args()
    data = build_efficiency_dashboard(DB_PATH, year, month, local_id)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        locais = _efficiency_locals(conn)
    finally:
        conn.close()
    return render_template(
        "eficiencia_dashboard.html",
        data=data,
        locais=locais,
        ano=year,
        mes=f"{month:02d}",
        local_id=local_id,
        can_manage=_efficiency_manager(),
    )


@app.route("/eficiencia/api")
def eficiencia_api():
    year, month, local_id = _efficiency_period_args()
    return jsonify(build_efficiency_dashboard(DB_PATH, year, month, local_id))


@app.route("/eficiencia/linhas-base", methods=["GET", "POST"])
def eficiencia_linhas_base():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if request.method == "POST":
            if not _efficiency_manager():
                return _deny_access("Apenas gestores e administradores podem criar linhas de base.")
            local_id = request.form.get("local_id", type=int)
            name = (request.form.get("nome") or "Linha de base operacional").strip()[:160]
            start = (request.form.get("periodo_inicio") or "").strip()
            end = (request.form.get("periodo_fim") or "").strip()
            coverage = request.form.get("cobertura_minima_pct", type=float)
            coverage = DEFAULT_MIN_COVERAGE_PCT if coverage is None else coverage
            notes = (request.form.get("observacoes") or "").strip()[:2000]
            try:
                snapshot = build_baseline_snapshot(
                    conn, local_id, start, end, minimum_coverage_pct=coverage
                )
                cursor = conn.execute(
                    """
                    INSERT INTO eficiencia_baselines(
                        local_id,nome,periodo_inicio,periodo_fim,metodo,cobertura_minima_pct,
                        meses_elegiveis,energia_total_kwh,agua_total_m3,custo_total_mzn,
                        energia_media_mensal_kwh,agua_media_mensal_m3,custo_medio_mensal_mzn,
                        consumo_especifico_kwh_m3,custo_especifico_mzn_m3,meses_json,
                        estado,observacoes,criado_por
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        local_id, name, start, end, "normalizacao_por_volume",
                        snapshot["cobertura_minima_pct"], snapshot["meses_elegiveis"],
                        snapshot["energia_total_kwh"], snapshot["agua_total_m3"],
                        snapshot["custo_total_mzn"], snapshot["energia_media_mensal_kwh"],
                        snapshot["agua_media_mensal_m3"], snapshot["custo_medio_mensal_mzn"],
                        snapshot["consumo_especifico_kwh_m3"], snapshot["custo_especifico_mzn_m3"],
                        _json.dumps(snapshot["meses"], ensure_ascii=False), "rascunho", notes,
                        _actor_name("sge"),
                    ),
                )
                efficiency_audit(conn, "baseline", cursor.lastrowid, "criada", f"{start} a {end}", _actor_name("sge"))
                conn.commit()
                flash("Linha de base calculada e guardada como rascunho. Revise antes de aprovar.", "success")
                return redirect(url_for("eficiencia_linhas_base"))
            except EfficiencyValidationError as exc:
                conn.rollback()
                flash(str(exc), "warning")
            except Exception:
                conn.rollback()
                flash("Não foi possível criar a linha de base. Verifique os dados e tente novamente.", "danger")

        baselines = conn.execute(
            """
            SELECT b.*, l.nome AS local
            FROM eficiencia_baselines b JOIN locais l ON l.id=b.local_id
            ORDER BY CASE b.estado WHEN 'aprovada' THEN 1 WHEN 'rascunho' THEN 2 ELSE 3 END,
                     b.criado_em DESC, b.id DESC
            """
        ).fetchall()
        locais = _efficiency_locals(conn)
        return render_template(
            "eficiencia_baselines.html",
            baselines=baselines,
            locais=locais,
            can_manage=_efficiency_manager(),
        )
    finally:
        conn.close()


@app.post("/eficiencia/linhas-base/<int:baseline_id>/estado")
def eficiencia_linha_base_estado(baseline_id):
    if not _efficiency_manager():
        return _deny_access("Apenas gestores e administradores podem aprovar ou arquivar linhas de base.")
    action = (request.form.get("acao") or "").strip().lower()
    if action not in ("aprovar", "arquivar"):
        flash("Ação de linha de base inválida.", "warning")
        return redirect(url_for("eficiencia_linhas_base"))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM eficiencia_baselines WHERE id=?", (baseline_id,)).fetchone()
        if not row:
            flash("Linha de base não encontrada.", "warning")
            return redirect(url_for("eficiencia_linhas_base"))
        actor = _actor_name("sge")
        if action == "aprovar":
            if int(row["meses_elegiveis"] or 0) < 3 or float(row["agua_total_m3"] or 0) <= 0:
                flash("A linha de base não cumpre os requisitos mínimos para aprovação.", "warning")
                return redirect(url_for("eficiencia_linhas_base"))
            conn.execute(
                "UPDATE eficiencia_baselines SET estado='arquivada', arquivado_em=datetime('now','localtime') WHERE local_id=? AND estado='aprovada' AND id<>?",
                (row["local_id"], baseline_id),
            )
            conn.execute(
                "UPDATE eficiencia_baselines SET estado='aprovada', aprovado_por=?, aprovado_em=datetime('now','localtime'), arquivado_em=NULL WHERE id=?",
                (actor, baseline_id),
            )
            message = "Linha de base aprovada e ativada para o local."
        else:
            conn.execute(
                "UPDATE eficiencia_baselines SET estado='arquivada', arquivado_em=datetime('now','localtime') WHERE id=?",
                (baseline_id,),
            )
            message = "Linha de base arquivada."
        efficiency_audit(conn, "baseline", baseline_id, action, message, actor)
        conn.commit()
        flash(message, "success")
    finally:
        conn.close()
    return redirect(url_for("eficiencia_linhas_base"))


@app.post("/eficiencia/metas/guardar")
def eficiencia_meta_guardar():
    if not _efficiency_manager():
        return _deny_access("Apenas gestores e administradores podem definir metas de eficiência.")
    local_id = request.form.get("local_id", type=int)
    year = request.form.get("ano", type=int)
    reduction = request.form.get("reducao_percentual", type=float)
    notes = (request.form.get("observacoes") or "").strip()[:1000]
    if not local_id or not year or reduction is None or not 0 <= reduction < 100:
        flash("Preencha local, ano e uma redução entre 0% e 99,99%.", "warning")
        return redirect(request.referrer or url_for("eficiencia_dashboard"))
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        baseline = conn.execute(
            "SELECT * FROM eficiencia_baselines WHERE local_id=? AND estado='aprovada' ORDER BY aprovado_em DESC,id DESC LIMIT 1",
            (local_id,),
        ).fetchone()
        if not baseline:
            flash("Aprove uma linha de base antes de definir a meta.", "warning")
            return redirect(request.referrer or url_for("eficiencia_linhas_base"))
        target_specific = float(baseline["consumo_especifico_kwh_m3"]) * (1.0 - reduction / 100.0)
        target_cost = float(baseline["custo_especifico_mzn_m3"]) * (1.0 - reduction / 100.0)
        actor = _actor_name("sge")
        conn.execute(
            """
            INSERT INTO eficiencia_metas(local_id,ano,baseline_id,reducao_percentual,meta_kwh_m3,meta_mzn_m3,observacoes,criado_por)
            VALUES(?,?,?,?,?,?,?,?)
            ON CONFLICT(local_id,ano) DO UPDATE SET
              baseline_id=excluded.baseline_id,reducao_percentual=excluded.reducao_percentual,
              meta_kwh_m3=excluded.meta_kwh_m3,meta_mzn_m3=excluded.meta_mzn_m3,
              observacoes=excluded.observacoes,atualizado_em=datetime('now','localtime')
            """,
            (local_id, year, baseline["id"], reduction, target_specific, target_cost, notes, actor),
        )
        target_id = conn.execute("SELECT id FROM eficiencia_metas WHERE local_id=? AND ano=?", (local_id, year)).fetchone()[0]
        efficiency_audit(conn, "meta", target_id, "guardada", f"Redução {reduction:.2f}%", actor)
        conn.commit()
        flash("Meta anual de eficiência guardada.", "success")
    finally:
        conn.close()
    return redirect(request.referrer or url_for("eficiencia_dashboard", local_id=local_id, ano=year))


@app.route("/eficiencia/medidas", methods=["GET", "POST"])
def eficiencia_medidas():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        if request.method == "POST":
            if not _efficiency_technical_writer():
                return _deny_access("Este perfil não pode registar medidas de eficiência.")
            local_id = request.form.get("local_id", type=int)
            title = (request.form.get("titulo") or "").strip()[:200]
            category = (request.form.get("categoria") or "Operacional").strip()
            priority = (request.form.get("prioridade") or "Média").strip()
            if not local_id or not title or category not in EFFICIENCY_CATEGORIES or priority not in EFFICIENCY_PRIORITIES:
                flash("Preencha corretamente o local, título, categoria e prioridade.", "warning")
            else:
                baseline = conn.execute(
                    "SELECT id FROM eficiencia_baselines WHERE local_id=? AND estado='aprovada' ORDER BY aprovado_em DESC,id DESC LIMIT 1",
                    (local_id,),
                ).fetchone()
                cursor = conn.execute(
                    """
                    INSERT INTO eficiencia_medidas(
                        local_id,titulo,categoria,descricao,responsavel,estado,prioridade,
                        data_inicio,data_conclusao_prevista,investimento_mzn,
                        poupanca_prevista_kwh_ano,poupanca_prevista_mzn_ano,baseline_id,
                        observacoes,criado_por
                    ) VALUES(?,?,?,?,?,'Planeada',?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        local_id, title, category, (request.form.get("descricao") or "").strip()[:3000],
                        (request.form.get("responsavel") or "").strip()[:160], priority,
                        request.form.get("data_inicio") or None,
                        request.form.get("data_conclusao_prevista") or None,
                        max(0.0, request.form.get("investimento_mzn", type=float) or 0.0),
                        max(0.0, request.form.get("poupanca_prevista_kwh_ano", type=float) or 0.0),
                        max(0.0, request.form.get("poupanca_prevista_mzn_ano", type=float) or 0.0),
                        baseline[0] if baseline else None,
                        (request.form.get("observacoes") or "").strip()[:2000], _actor_name("sge"),
                    ),
                )
                efficiency_audit(conn, "medida", cursor.lastrowid, "criada", title, _actor_name("sge"))
                conn.commit()
                flash("Medida de eficiência registada.", "success")
                return redirect(url_for("eficiencia_medidas"))
        measures = conn.execute(
            """
            SELECT m.*, l.nome AS local,
                   CASE WHEN m.poupanca_prevista_mzn_ano>0 THEN m.investimento_mzn/m.poupanca_prevista_mzn_ano ELSE NULL END AS payback_anos
            FROM eficiencia_medidas m JOIN locais l ON l.id=m.local_id
            ORDER BY CASE m.prioridade WHEN 'Alta' THEN 1 WHEN 'Média' THEN 2 ELSE 3 END,
                     CASE m.estado WHEN 'Em execução' THEN 1 WHEN 'Planeada' THEN 2 WHEN 'Implementada' THEN 3 ELSE 4 END,
                     m.id DESC
            """
        ).fetchall()
        return render_template(
            "eficiencia_medidas.html",
            medidas=measures,
            locais=_efficiency_locals(conn),
            estados=EFFICIENCY_MEASURE_STATES,
            prioridades=EFFICIENCY_PRIORITIES,
            categorias=EFFICIENCY_CATEGORIES,
            can_write=_efficiency_technical_writer(),
        )
    finally:
        conn.close()


@app.post("/eficiencia/medidas/<int:measure_id>/estado")
def eficiencia_medida_estado(measure_id):
    if not _efficiency_technical_writer():
        return _deny_access("Este perfil não pode atualizar medidas de eficiência.")
    state = (request.form.get("estado") or "").strip()
    if state not in EFFICIENCY_MEASURE_STATES:
        flash("Estado da medida inválido.", "warning")
        return redirect(url_for("eficiencia_medidas"))
    conn = sqlite3.connect(DB_PATH)
    try:
        actor = _actor_name("sge")
        implementation = "datetime('now','localtime')" if state == "Implementada" else "data_implementacao"
        conn.execute(
            f"UPDATE eficiencia_medidas SET estado=?, data_implementacao={implementation}, atualizado_por=?, atualizado_em=datetime('now','localtime') WHERE id=?",
            (state, actor, measure_id),
        )
        efficiency_audit(conn, "medida", measure_id, "estado", state, actor)
        conn.commit()
        flash("Estado da medida atualizado.", "success")
    finally:
        conn.close()
    return redirect(url_for("eficiencia_medidas"))


@app.route("/eficiencia/export.xlsx")
def eficiencia_export_xlsx():
    year, month, local_id = _efficiency_period_args()
    data = build_efficiency_dashboard(DB_PATH, year, month, local_id)
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    _set_xlsx_identity(workbook, f"Eficiência Energética {year}-{month:02d}")
    title = workbook.add_format({"bold": True, "font_size": 16, "font_color": "#0B4F8F"})
    header = workbook.add_format({"bold": True, "bg_color": "#0B4F8F", "font_color": "#FFFFFF", "border": 1})
    number = workbook.add_format({"num_format": "#,##0.00"})
    decimal = workbook.add_format({"num_format": "0.0000"})
    ws = workbook.add_worksheet("Desempenho")
    ws.write("A1", "Águas e Saneamento de Maputo · Eficiência Energética", title)
    ws.write("A2", f"Período: {year}-{month:02d}")
    columns = [
        "Local", "Energia (kWh)", "Água (m³)", "kWh/m³", "Custo (MZN)", "MZN/m³",
        "Cobertura (%)", "Linha de base", "Desvio base (%)", "Poupança (kWh)",
        "Poupança (MZN)", "Qualidade", "Estado",
    ]
    for col, value in enumerate(columns):
        ws.write(3, col, value, header)
    for row_index, item in enumerate(data["evaluations"], 4):
        values = [
            item["local"], item["energia_kwh"], item["agua_m3"], item["consumo_especifico_kwh_m3"],
            item["custo_total_mzn"], item["custo_especifico_mzn_m3"], item["cobertura_pct"],
            item["baseline"]["nome"] if item["baseline"] else "", item["desvio_baseline_pct"],
            item["poupanca_energia_kwh"], item["poupanca_financeira_mzn"],
            item["qualidade_poupanca"], item["estado_eficiencia"],
        ]
        for col, value in enumerate(values):
            ws.write(row_index, col, value, decimal if col in (3, 5) else (number if col in (1, 2, 4, 6, 8, 9, 10) else None))
    ws.freeze_panes(4, 1)
    ws.autofilter(3, 0, max(3, 3 + len(data["evaluations"])), len(columns) - 1)
    ws.set_column("A:A", 30); ws.set_column("B:M", 18)

    history_ws = workbook.add_worksheet("Histórico")
    history_columns = ["Período", "Energia (kWh)", "Água (m³)", "kWh/m³", "MZN/m³", "Desvio base (%)", "Cobertura (%)"]
    for col, value in enumerate(history_columns):
        history_ws.write(0, col, value, header)
    for row_index, item in enumerate(data["history"], 1):
        for col, value in enumerate([
            item["periodo"], item["energia_kwh"], item["agua_m3"], item["consumo_especifico_kwh_m3"],
            item["custo_especifico_mzn_m3"], item["desvio_baseline_pct"], item["cobertura_pct"],
        ]):
            history_ws.write(row_index, col, value, decimal if col in (3, 4) else (number if col else None))
    history_ws.set_column("A:G", 20)

    measures_ws = workbook.add_worksheet("Medidas")
    measure_columns = ["Local", "Medida", "Categoria", "Estado", "Prioridade", "Investimento (MZN)", "Poupança prevista (MZN/ano)", "Payback (anos)", "Responsável"]
    for col, value in enumerate(measure_columns):
        measures_ws.write(0, col, value, header)
    for row_index, item in enumerate(data["measures"], 1):
        payback = item["investimento_mzn"] / item["poupanca_prevista_mzn_ano"] if item["poupanca_prevista_mzn_ano"] else None
        for col, value in enumerate([item["local"], item["titulo"], item["categoria"], item["estado"], item["prioridade"], item["investimento_mzn"], item["poupanca_prevista_mzn_ano"], payback, item["responsavel"]]):
            measures_ws.write(row_index, col, value, number if col in (5, 6, 7) else None)
    measures_ws.set_column("A:A", 28); measures_ws.set_column("B:B", 42); measures_ws.set_column("C:I", 20)
    workbook.close()
    output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"eficiencia_energetica_{year}-{month:02d}.xlsx", mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.route("/eficiencia/relatorio.pdf")
def eficiencia_relatorio_pdf():
    year, month, local_id = _efficiency_period_args()
    data = build_efficiency_dashboard(DB_PATH, year, month, local_id)
    output = BytesIO()
    pdf = canvas.Canvas(output, pagesize=A4)
    _set_pdf_identity(pdf, f"Relatório de Eficiência Energética {year}-{month:02d}")
    width, height = A4

    def page_header(page):
        pdf.setFillColorRGB(0.04, 0.31, 0.56)
        pdf.rect(0, height - 78, width, 78, fill=1, stroke=0)
        pdf.setFillColorRGB(1, 1, 1); pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(36, height - 40, "Eficiência Energética e Desempenho Operacional")
        pdf.setFont("Helvetica", 9)
        pdf.drawString(36, height - 58, f"Águas e Saneamento de Maputo · Período {year}-{month:02d} · Página {page}")
        return height - 100

    y = page_header(1)
    summary = data["summary"]
    pdf.setFillColorRGB(0.08, 0.12, 0.19); pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(36, y, "Resumo executivo"); y -= 20
    pdf.setFont("Helvetica", 9)
    lines = [
        f"Energia: {summary['energia_kwh']:,.2f} kWh | Água: {summary['agua_m3']:,.2f} m³ | Custo: {summary['custo_mzn']:,.2f} MZN",
        f"Consumo específico: {summary['consumo_especifico_kwh_m3'] if summary['consumo_especifico_kwh_m3'] is not None else '—'} kWh/m³ | Custo específico: {summary['custo_especifico_mzn_m3'] if summary['custo_especifico_mzn_m3'] is not None else '—'} MZN/m³",
        f"Locais com linha de base: {summary['locais_com_baseline']} | Críticos: {summary['locais_criticos']} | Medidas abertas: {summary['medidas_abertas']}",
        f"Poupança verificada: {summary['poupanca_verificada_kwh']:,.2f} kWh | {summary['poupanca_verificada_mzn']:,.2f} MZN",
    ]
    for line in lines:
        pdf.drawString(36, y, line); y -= 16
    y -= 8
    pdf.setFont("Helvetica-Bold", 8)
    headers = ["Local", "kWh", "m³", "kWh/m³", "Desvio", "Poupança", "Estado"]
    positions = [36, 205, 280, 345, 405, 460, 525]
    for x, value in zip(positions, headers): pdf.drawString(x, y, value)
    y -= 13; pdf.line(36, y + 8, width - 36, y + 8)
    pdf.setFont("Helvetica", 7.5)
    page = 1
    for item in data["evaluations"]:
        if y < 55:
            pdf.showPage(); page += 1; y = page_header(page)
            pdf.setFont("Helvetica", 7.5)
        row = [
            str(item["local"])[:28], f"{item['energia_kwh']:,.1f}", f"{item['agua_m3']:,.1f}",
            "—" if item["consumo_especifico_kwh_m3"] is None else f"{item['consumo_especifico_kwh_m3']:.4f}",
            "—" if item["desvio_baseline_pct"] is None else f"{item['desvio_baseline_pct']:+.1f}%",
            "—" if item["poupanca_energia_kwh"] is None else f"{item['poupanca_energia_kwh']:+,.1f}",
            item["estado_eficiencia"],
        ]
        for x, value in zip(positions, row): pdf.drawString(x, y, value)
        y -= 13
    pdf.setFont("Helvetica-Oblique", 7.5)
    pdf.drawString(36, 30, "Poupança verificada requer linha de base aprovada, água registada e cobertura mensal mínima de 80%. Valores financeiros excluem alterações de ponta e taxas fixas.")
    pdf.save(); output.seek(0)
    return send_file(output, as_attachment=True, download_name=f"relatorio_eficiencia_{year}-{month:02d}.pdf", mimetype="application/pdf")
