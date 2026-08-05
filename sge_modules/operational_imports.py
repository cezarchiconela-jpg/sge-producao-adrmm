"""Rotas de importação PIGI/EDM para o núcleo operacional."""
import io as _io, json as _json, uuid as _uuid
from operational_import_service import OperationalImportError, file_hash, match_local, parse_workbook

def _operational_writer():
    return (not _login_required_enabled()) or _user_has_role("admin","gestor","tecnico")

def _operational_approver():
    return (not _login_required_enabled()) or _user_has_role("admin","gestor")

@app.route("/eficiencia/dados")
def eficiencia_dados_operacionais():
    conn=sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row
    try:
        batches=conn.execute("SELECT * FROM operacional_importacoes ORDER BY id DESC LIMIT 50").fetchall()
        totals=conn.execute("""SELECT COUNT(*) registos,COUNT(DISTINCT local_id) locais,
            MIN(data) inicio,MAX(data) fim,SUM(COALESCE(energia_kwh,0)) energia,
            SUM(COALESCE(volume_distribuido_m3,volume_produzido_m3,volume_captado_m3,0)) volume
            FROM operacional_dados WHERE estado='validado'""").fetchone()
        return render_template("eficiencia_dados.html",batches=batches,totals=totals,can_import=_operational_writer())
    finally: conn.close()

@app.route("/eficiencia/dados/importar",methods=["GET","POST"])
def eficiencia_dados_importar():
    if not _operational_writer(): return _deny_access("Este perfil não pode importar dados operacionais.")
    if request.method=="GET": return render_template("eficiencia_importar.html")
    upload=request.files.get("ficheiro")
    if not upload or not upload.filename:
        flash("Selecione um ficheiro .xlsx ou .xlsb.","warning"); return redirect(url_for("eficiencia_dados_importar"))
    content=upload.read()
    if len(content)>25*1024*1024:
        flash("O ficheiro excede o limite de 25 MB.","warning"); return redirect(url_for("eficiencia_dados_importar"))
    conn=sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row
    try:
        digest=file_hash(content)
        duplicate=conn.execute("SELECT id,estado FROM operacional_importacoes WHERE ficheiro_hash=? AND estado='confirmado'",(digest,)).fetchone()
        if duplicate:
            flash("Este mesmo ficheiro já foi confirmado. A duplicação foi bloqueada.","warning"); return redirect(url_for("eficiencia_dados_operacionais"))
        parsed=parse_workbook(content,upload.filename,request.form.get("tipo") or "auto")
        lote_uid=_uuid.uuid4().hex
        cur=conn.execute("""INSERT INTO operacional_importacoes(lote_uid,ficheiro_nome,ficheiro_hash,formato,periodo,total_linhas,criado_por)
             VALUES(?,?,?,?,?,?,?)""",(lote_uid,upload.filename[:240],digest,parsed["format"],parsed.get("period"),len(parsed["records"]),_actor_name("sge")))
        lote_id=cur.lastrowid
        for item in parsed["records"]:
            local_id=match_local(conn,item["site"]); warnings=list(item.get("warnings") or [])
            if not local_id: warnings.append("local não mapeado")
            if "transferencia" in item["site"].lower(): warnings.append("ponto de transferência: não incluir em totais institucionais")
            conn.execute("""INSERT INTO operacional_importacao_linhas(
              lote_id,linha_origem,folha_origem,local_origem,local_id,data,energia_kwh,volume_m3,
              horas_operacao,tipo_dado,qualidade,avisos,payload_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
              (lote_id,item.get("source_row"),item.get("sheet"),item["site"],local_id,item["date"],item.get("energy_kwh"),item.get("volume_m3"),item.get("hours"),item.get("data_type","medido"),item.get("quality","provisoria"),"; ".join(warnings),_json.dumps(item,ensure_ascii=False)))
        for item in parsed.get("occurrences",[]):
            conn.execute("INSERT OR IGNORE INTO operacional_ocorrencias(data,descricao,lote_id,fonte,estado,criado_por) VALUES(?,? ,?,'PIGI','provisoria',?)",(item["date"],item["description"],lote_id,_actor_name("sge")))
        conn.commit(); return redirect(url_for("eficiencia_dados_previsualizar",lote_uid=lote_uid))
    except (OperationalImportError,ValueError) as exc:
        conn.rollback(); flash(str(exc),"warning"); return redirect(url_for("eficiencia_dados_importar"))
    except Exception:
        conn.rollback(); flash("Não foi possível analisar o ficheiro. Verifique o formato e tente novamente.","danger"); return redirect(url_for("eficiencia_dados_importar"))
    finally: conn.close()

@app.route("/eficiencia/dados/previsualizar/<lote_uid>")
def eficiencia_dados_previsualizar(lote_uid):
    conn=sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row
    try:
        batch=conn.execute("SELECT * FROM operacional_importacoes WHERE lote_uid=?",(lote_uid,)).fetchone()
        if not batch: return _deny_access("Lote de importação não encontrado.")
        rows=conn.execute("SELECT * FROM operacional_importacao_linhas WHERE lote_id=? ORDER BY data,local_origem,id",(batch["id"],)).fetchall()
        locals_=conn.execute("SELECT id,nome FROM locais WHERE COALESCE(ativo,1)=1 ORDER BY nome").fetchall()
        return render_template("eficiencia_import_preview.html",batch=batch,rows=rows,locais=locals_,can_confirm=_operational_approver())
    finally: conn.close()

@app.post("/eficiencia/dados/confirmar/<lote_uid>")
def eficiencia_dados_confirmar(lote_uid):
    if not _operational_approver(): return _deny_access("Apenas gestores e administradores podem validar definitivamente os dados.")
    conn=sqlite3.connect(DB_PATH); conn.row_factory=sqlite3.Row
    try:
        batch=conn.execute("SELECT * FROM operacional_importacoes WHERE lote_uid=? AND estado='previsualizacao'",(lote_uid,)).fetchone()
        if not batch:
            flash("O lote não está disponível para confirmação.","warning"); return redirect(url_for("eficiencia_dados_operacionais"))
        rows=conn.execute("SELECT * FROM operacional_importacao_linhas WHERE lote_id=?",(batch["id"],)).fetchall(); imported=rejected=0
        source="PIGI" if batch["formato"]=="PIGI" else "EDM_PLANILHA"
        for row in rows:
            selected=request.form.get(f"usar_{row['id']}")=="1"
            local_id=request.form.get(f"local_{row['id']}",type=int) or row["local_id"]
            if not selected or not local_id or (row["energia_kwh"] is None and row["volume_m3"] is None):
                conn.execute("UPDATE operacional_importacao_linhas SET estado='rejeitada' WHERE id=?",(row["id"],)); rejected+=1; continue
            try:
                conn.execute("""INSERT INTO operacional_dados(local_id,data,energia_kwh,volume_distribuido_m3,horas_operacao,
                  fonte,tipo_dado,estado,cobertura_pct,lote_id,ficheiro_origem,observacoes,criado_por)
                  VALUES(?,?,?,?,?,?,?,'validado',100,?,?,?,?)""",
                  (local_id,row["data"],row["energia_kwh"],row["volume_m3"],row["horas_operacao"],source,row["tipo_dado"],batch["id"],batch["ficheiro_nome"],row["avisos"],_actor_name("sge")))
                conn.execute("UPDATE operacional_importacao_linhas SET estado='importada',local_id=? WHERE id=?",(local_id,row["id"])); imported+=1
            except sqlite3.IntegrityError:
                conn.execute("UPDATE operacional_importacao_linhas SET estado='rejeitada',avisos=COALESCE(avisos||'; ','')||'duplicado' WHERE id=?",(row["id"],)); rejected+=1
        conn.execute("UPDATE operacional_ocorrencias SET estado='validada' WHERE lote_id=?",(batch["id"],))
        conn.execute("""UPDATE operacional_importacoes SET estado='confirmado',linhas_importadas=?,linhas_rejeitadas=?,
          confirmado_por=?,confirmado_em=datetime('now','localtime') WHERE id=?""",(imported,rejected,_actor_name("sge"),batch["id"]))
        efficiency_audit(conn,"importacao_operacional",batch["id"],"confirmada",f"{imported} importadas; {rejected} rejeitadas",_actor_name("sge")); conn.commit()
        flash(f"Importação concluída: {imported} linha(s) validadas e {rejected} rejeitada(s).","success")
        return redirect(url_for("eficiencia_dados_operacionais"))
    except Exception:
        conn.rollback(); flash("Não foi possível confirmar a importação.","danger"); return redirect(url_for("eficiencia_dados_previsualizar",lote_uid=lote_uid))
    finally: conn.close()

@app.get("/eficiencia/dados/modelo.xlsx")
def eficiencia_dados_modelo():
    out=_io.BytesIO(); wb=xlsxwriter.Workbook(out,{"in_memory":True}); _set_xlsx_identity(wb,"Modelo de importação operacional")
    ws=wb.add_worksheet("Dados"); headers=["Local","Data","Energia kWh","Leitura energia kWh","Água m3","Horas operação","Tipo dado","Observações"]
    fmt=wb.add_format({"bold":True,"font_color":"white","bg_color":"#075985","border":1}); datefmt=wb.add_format({"num_format":"yyyy-mm-dd"})
    for c,h in enumerate(headers): ws.write(0,c,h,fmt)
    ws.write_row(1,0,["CD Guava",datetime.now().date(),1250,"",8600,18,"medido","Exemplo"],datefmt)
    ws.set_column("A:A",24); ws.set_column("B:B",13); ws.set_column("C:F",18); ws.set_column("G:G",14); ws.set_column("H:H",34); ws.freeze_panes(1,0); wb.close(); out.seek(0)
    return send_file(out,as_attachment=True,download_name="Modelo_Importacao_Agua_Energia_SGE.xlsx",mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
