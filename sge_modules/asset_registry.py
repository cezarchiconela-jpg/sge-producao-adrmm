"""Cadastro mestre integrado de locais e activos."""

import json as _registry_json
import os as _registry_os
import re as _registry_re
import secrets as _registry_secrets
import sqlite3 as _registry_sqlite3
import time as _registry_time
from datetime import datetime as _registry_datetime
from io import BytesIO as _RegistryBytesIO

import xlsxwriter as _registry_xlsxwriter
from reportlab.lib import colors as _registry_colors
from reportlab.lib.enums import TA_CENTER as _REGISTRY_TA_CENTER
from reportlab.lib.pagesizes import A4 as _REGISTRY_A4, landscape as _registry_landscape
from reportlab.lib.styles import ParagraphStyle as _RegistryParagraphStyle, getSampleStyleSheet as _registry_styles
from reportlab.lib.units import cm as _registry_cm
from reportlab.platypus import (
    PageBreak as _RegistryPageBreak,
    Paragraph as _RegistryParagraph,
    SimpleDocTemplate as _RegistryDoc,
    Spacer as _RegistrySpacer,
    Table as _RegistryTable,
    TableStyle as _RegistryTableStyle,
)

from asset_registry_service import (
    clean_text as _registry_clean,
    import_registry as _registry_import,
    parse_registry_file as _registry_parse,
    preview_registry as _registry_preview,
    registry_dashboard as _registry_dashboard,
)


def _registry_preview_dir():
    path = _registry_os.path.join(app.config['UPLOAD_FOLDER'], 'registry_previews')
    _registry_os.makedirs(path, exist_ok=True)
    return path


def _registry_preview_path(token):
    if not _registry_re.fullmatch(r'[A-Za-z0-9_-]{20,80}', token or ''):
        raise ValueError('Identificador de pré-visualização inválido.')
    return _registry_os.path.join(_registry_preview_dir(), token + '.json')


def _registry_save_preview(parsed):
    cutoff = _registry_time.time() - 24 * 60 * 60
    for filename in _registry_os.listdir(_registry_preview_dir()):
        path_old = _registry_os.path.join(_registry_preview_dir(), filename)
        try:
            if filename.endswith('.json') and _registry_os.path.getmtime(path_old) < cutoff:
                _registry_os.remove(path_old)
        except OSError:
            pass
    token = _registry_secrets.token_urlsafe(24)
    path = _registry_preview_path(token)
    payload = {'created_at': _registry_datetime.now().isoformat(), 'parsed': parsed}
    with open(path, 'w', encoding='utf-8') as handle:
        _registry_json.dump(payload, handle, ensure_ascii=False)
    return token


def _registry_load_preview(token, consume=False):
    path = _registry_preview_path(token)
    with open(path, 'r', encoding='utf-8') as handle:
        payload = _registry_json.load(handle)
    if consume:
        try:
            _registry_os.remove(path)
        except OSError:
            pass
    return payload.get('parsed') or {}


def _registry_query_filters():
    local_id = (request.args.get('local_id') or '').strip()
    sector = (request.args.get('sector') or '').strip()
    sistema = (request.args.get('sistema') or '').strip()
    instalacao = (request.args.get('instalacao') or '').strip()
    estado = (request.args.get('estado') or request.args.get('estado_operacional') or '').strip()
    periodicidade = (request.args.get('periodicidade') or '').strip()
    criticidade = (request.args.get('criticidade') or '').strip()
    categoria = (request.args.get('categoria') or '').strip()
    fabricante = (request.args.get('fabricante') or '').strip()
    modelo = (request.args.get('modelo') or '').strip()
    ano_min = (request.args.get('ano_min') or '').strip()
    ano_max = (request.args.get('ano_max') or '').strip()
    q = (request.args.get('q') or '').strip()
    where = ["COALESCE(e.deleted_at,'')='' "]
    params = []
    if local_id.isdigit():
        scope = get_descendant_local_ids(int(local_id), include_self=True) or [int(local_id)]
        where.append('e.local_id IN (' + ','.join('?' for _ in scope) + ')')
        params.extend(scope)
    if sector:
        where.append("COALESCE(e.sector_operacional,'')=?")
        params.append(sector)
    if sistema:
        where.append("COALESCE(e.sistema,'')=?")
        params.append(sistema)
    if instalacao:
        where.append("COALESCE(e.instalacao,'')=?")
        params.append(instalacao)
    if estado:
        where.append("COALESCE(e.estado_operacional,'')=?")
        params.append(estado)
    if periodicidade:
        where.append("COALESCE(e.periodicidade_manutencao,'')=?")
        params.append(periodicidade)
    if criticidade:
        where.append("COALESCE(e.criticidade,'')=?")
        params.append(criticidade)
    if categoria:
        where.append("COALESCE(e.categoria,'') LIKE ?")
        params.append(f'%{categoria}%')
    if fabricante:
        where.append("COALESCE(e.fabricante,'') LIKE ?")
        params.append(f'%{fabricante}%')
    if modelo:
        where.append("COALESCE(e.modelo,'') LIKE ?")
        params.append(f'%{modelo}%')
    if ano_min.isdigit():
        where.append("CAST(COALESCE(e.ano_instalacao,0) AS INTEGER)>=?")
        params.append(int(ano_min))
    if ano_max.isdigit():
        where.append("CAST(COALESCE(e.ano_instalacao,0) AS INTEGER)<=?")
        params.append(int(ano_max))
    if q:
        like = f'%{q}%'
        where.append("(e.nome LIKE ? OR e.tag LIKE ? OR e.fabricante LIKE ? OR e.modelo LIKE ? OR e.sistema LIKE ? OR e.instalacao LIKE ?)")
        params.extend([like] * 6)
    return ' AND '.join(where), params


def _registry_fetch_rows():
    where, params = _registry_query_filters()
    conn = _registry_sqlite3.connect(DB_PATH)
    conn.row_factory = _registry_sqlite3.Row
    try:
        rows = conn.execute(f"""
            SELECT e.id, e.referencia_externa, COALESCE(l.nome,'') AS local,
                   COALESCE(l.tipo_local,'') AS tipo_local,
                   COALESCE(e.sector_operacional,'') AS sector_operacional,
                   COALESCE(e.instalacao,'') AS instalacao,
                   COALESCE(e.sistema,'') AS sistema,
                   e.nome, COALESCE(e.categoria,'') AS categoria,
                   COALESCE(e.estado_operacional,'') AS estado_operacional,
                   COALESCE(e.criticidade,'') AS criticidade,
                   COALESCE(e.periodicidade_manutencao,'') AS periodicidade_manutencao,
                   COALESCE(e.tag,'') AS tag, COALESCE(e.fabricante,'') AS fabricante,
                   COALESCE(e.modelo,'') AS modelo, COALESCE(e.numero_serie,'') AS numero_serie,
                   COALESCE(e.especificacao,'') AS especificacao,
                   e.potencia_kw, e.tensao_v, e.corrente_a, e.ano_instalacao,
                   COALESCE(e.quantidade,1) AS quantidade, COALESCE(e.ativo,1) AS ativo,
                   COALESCE(e.fonte_cadastro,'') AS fonte_cadastro,
                   COALESCE(e.source_record_no,'') AS source_record_no,
                   COALESCE(e.ultima_sincronizacao,'') AS ultima_sincronizacao,
                   e.custo_aquisicao, e.vida_util_anos,
                   COALESCE(e.fornecedor,'') AS fornecedor, COALESCE(e.contrato_num,'') AS contrato_num,
                   COALESCE(e.garantia_fim,'') AS garantia_fim
            FROM equipamentos e LEFT JOIN locais l ON l.id=e.local_id
            WHERE {where}
            ORDER BY l.nome COLLATE NOCASE, e.instalacao COLLATE NOCASE,
                     e.sistema COLLATE NOCASE, e.nome COLLATE NOCASE, e.id
        """, params).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


@app.route('/equipamentos/cadastro')
def cadastro_activos():
    dashboard_data = _registry_dashboard(DB_PATH)
    return render_template('cadastro_activos.html', dashboard=dashboard_data, preview=None)


@app.route('/equipamentos/cadastro/importar', methods=['POST'])
def cadastro_activos_preview():
    uploaded = request.files.get('arquivo')
    if not uploaded or not uploaded.filename:
        flash('Seleccione um ficheiro Excel ou CSV.', 'warning')
        return redirect(url_for('cadastro_activos'))
    try:
        parsed = _registry_parse(uploaded.stream, uploaded.filename)
        preview = _registry_preview(DB_PATH, parsed)
        token = _registry_save_preview(parsed)
        return render_template(
            'cadastro_activos.html', dashboard=_registry_dashboard(DB_PATH),
            preview=preview, preview_token=token,
        )
    except Exception as exc:
        flash(f'Não foi possível analisar o cadastro: {_registry_clean(exc)}', 'danger')
        return redirect(url_for('cadastro_activos'))


@app.route('/equipamentos/cadastro/confirmar', methods=['POST'])
def cadastro_activos_confirmar():
    token = (request.form.get('preview_token') or '').strip()
    try:
        parsed = _registry_load_preview(token, consume=True)
        result = _registry_import(DB_PATH, parsed, actor=_actor_name('cadastro_activos'))
        flash(
            'Cadastro actualizado: '
            f"{result.get('inseridos',0)} inseridos, {result.get('actualizados',0)} actualizados, "
            f"{result.get('reconciliados',0)} reconciliados, {result.get('sem_alteracao',0)} sem alteração e "
            f"{result.get('locais_criados',0)} novos locais.",
            'success',
        )
    except Exception as exc:
        flash(f'A actualização do cadastro falhou sem alterar parcialmente a base: {_registry_clean(exc)}', 'danger')
    return redirect(url_for('cadastro_activos'))


@app.route('/equipamentos/cadastro/modelo.xlsx')
def cadastro_activos_modelo_xlsx():
    out = _RegistryBytesIO()
    workbook = _registry_xlsxwriter.Workbook(out, {'in_memory': True})
    _set_xlsx_identity(workbook, 'Modelo do Cadastro Mestre de Activos')
    title = workbook.add_format({'bold': True, 'font_size': 16, 'font_color': '#0B3B75'})
    header = workbook.add_format({'bold': True, 'bg_color': '#0B3B75', 'font_color': '#FFFFFF', 'border': 1, 'text_wrap': True})
    input_fmt = workbook.add_format({'bg_color': '#FFF8DC', 'border': 1})
    note_fmt = workbook.add_format({'font_color': '#53677A', 'text_wrap': True, 'valign': 'top'})
    sheet = workbook.add_worksheet('Cadastro_Activos')
    headers = [
        'codigo_activo','local','sector','instalacao','sistema','equipamento','estado','criticidade',
        'periodicidade','marca','modelo','tag','numero_serie','categoria','especificacao','ano_instalacao',
        'quantidade','potencia_kw','tensao_v','corrente_a','fornecedor','contrato_num','garantia_fim','observacoes',
    ]
    sheet.write('A1', 'CADASTRO MESTRE DE ACTIVOS — MODELO SGE', title)
    sheet.merge_range(0, 0, 0, len(headers) - 1, 'CADASTRO MESTRE DE ACTIVOS — MODELO SGE', title)
    for col, value in enumerate(headers):
        sheet.write(2, col, value, header)
    example = [
        'ASM-EXEMPLO-001','ETA Umbeluzi','UMBELUZI','Captação 1','Água Bruta','Motor 01',
        'Operacional','Alta','Trimestral','WEG','145 kW; 380 V; 293 A','MOT-001','',
        'Motor eléctrico','Motor de accionamento da bomba','2026',1,145,380,293,'','','','Linha de exemplo; pode ser apagada',
    ]
    for col, value in enumerate(example):
        sheet.write(3, col, value, input_fmt)
    sheet.freeze_panes(3, 0)
    sheet.autofilter(2, 0, 3, len(headers) - 1)
    widths = [20,24,16,22,28,28,18,14,17,18,28,18,18,22,34,15,12,14,14,14,20,18,15,32]
    for col, width in enumerate(widths):
        sheet.set_column(col, col, width)
    sheet.data_validation(3, 6, 10003, 6, {'validate': 'list', 'source': ['Operacional','Avariado','Fora de serviço','Não informado']})
    sheet.data_validation(3, 7, 10003, 7, {'validate': 'list', 'source': ['Baixa','Média','Alta']})
    sheet.data_validation(3, 8, 10003, 8, {'validate': 'list', 'source': ['Mensal','Trimestral','Semestral','Anual']})
    instructions = workbook.add_worksheet('Instruções')
    instructions.set_column('A:A', 30)
    instructions.set_column('B:B', 95)
    instructions.write('A1', 'REGRA', header); instructions.write('B1', 'ORIENTAÇÃO', header)
    notes = [
        ('Actualização segura', 'O código do activo identifica o mesmo equipamento em futuras importações. Sem código, o SGE usa local, instalação, sistema e nome para reconciliar.'),
        ('Campos obrigatórios', 'Preencha equipamento e local. Para o formato DIMA, sector e instalação também permitem determinar automaticamente o local.'),
        ('Dados manuais', 'Campos não presentes no novo ficheiro, como custos, fotografias, medições e histórico, são preservados.'),
        ('Novos locais', 'Um local inexistente pode ser criado a partir da coluna local; os restantes dados institucionais podem ser completados no módulo Locais.'),
        ('Não apagar', 'A importação não elimina nem arquiva automaticamente activos que não apareçam no novo ficheiro.'),
    ]
    for row, (rule, note) in enumerate(notes, start=1):
        instructions.write(row, 0, rule, input_fmt); instructions.write(row, 1, note, note_fmt)
        instructions.set_row(row, 38)
    workbook.close(); out.seek(0)
    return Response(out.getvalue(), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename=modelo_cadastro_mestre_activos.xlsx'})


@app.route('/locais/template.xlsx')
def locais_template_xlsx():
    out = _RegistryBytesIO()
    workbook = _registry_xlsxwriter.Workbook(out, {'in_memory': True})
    _set_xlsx_identity(workbook, 'Modelo de Importação de Locais')
    sheet = workbook.add_worksheet('Locais')
    header = workbook.add_format({'bold': True, 'bg_color': '#0B3B75', 'font_color': '#FFFFFF', 'border': 1, 'text_wrap': True})
    input_fmt = workbook.add_format({'bg_color': '#FFF8DC', 'border': 1})
    headers = [
        'nome','codigo','tipo_local','categoria_operacional','sector_operacional','parent_nome','provincia',
        'municipio','distrito','bairro','endereco','latitude','longitude','contato_nome','contato_tel','email',
        'responsavel_alt','estado_tecnico','prioridade','ativo','fator_mult','pot_contratada','pot_instalada',
        'tarifa_ativa','tarifa_reativa','tarifa_ponta','tarifa_perdas','taxa_fixa','taxa_radio','taxa_lixo','iva','notas',
    ]
    for col, value in enumerate(headers): sheet.write(0, col, value, header)
    example = ['ETA Umbeluzi','ETA-UMB','ETA','Produção e tratamento','UMBELUZI','','Maputo Província','Boane','','Umbeluzi','',-26.05,32.34,'','','','','Normal','Alta',1,1,0,0,4.78,1.43,497.03,4.78,207.28,297,150,16,'Complete os campos em falta']
    for col, value in enumerate(example): sheet.write(1, col, value, input_fmt)
    sheet.freeze_panes(1, 0); sheet.autofilter(0, 0, 1, len(headers)-1)
    for col in range(len(headers)): sheet.set_column(col, col, 18)
    sheet.set_column(0, 0, 28); sheet.set_column(3, 5, 24); sheet.set_column(10, 10, 32); sheet.set_column(31, 31, 36)
    sheet.data_validation(1, 17, 10001, 17, {'validate': 'list', 'source': ['Normal','Atenção','Crítico']})
    sheet.data_validation(1, 18, 10001, 18, {'validate': 'list', 'source': ['Baixa','Média','Alta']})
    workbook.close(); out.seek(0)
    return Response(out.getvalue(), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename=modelo_locais_sge.xlsx'})


@app.route('/equipamentos/cadastro/export.xlsx')
def cadastro_activos_export_xlsx():
    rows = _registry_fetch_rows()
    out = _RegistryBytesIO()
    workbook = _registry_xlsxwriter.Workbook(out, {'in_memory': True})
    _set_xlsx_identity(workbook, 'Cadastro Mestre de Activos')
    header = workbook.add_format({'bold': True, 'bg_color': '#0B3B75', 'font_color': '#FFFFFF', 'border': 1, 'text_wrap': True})
    text_fmt = workbook.add_format({'border': 1, 'valign': 'top'})
    number_fmt = workbook.add_format({'border': 1, 'num_format': '0.00'})
    summary = workbook.add_worksheet('Resumo')
    dashboard_data = _registry_dashboard(DB_PATH)
    summary.write('A1', 'CADASTRO MESTRE DE ACTIVOS', workbook.add_format({'bold': True, 'font_size': 18, 'font_color': '#0B3B75'}))
    metrics = [('Total exportado', len(rows)), ('Total no SGE', dashboard_data['total']), ('Locais activos', dashboard_data['locations']), ('ETAs', dashboard_data['etas']), ('Sem fabricante', dashboard_data['missing_manufacturer']), ('Sem modelo', dashboard_data['missing_model'])]
    for index, (label, value) in enumerate(metrics, start=2):
        summary.write(index, 0, label, header); summary.write(index, 1, value, number_fmt)
    summary.set_column('A:A', 28); summary.set_column('B:B', 18)
    sheet = workbook.add_worksheet('Activos')
    headers = [
        ('id','ID'),('referencia_externa','Código do activo'),('local','Local'),('tipo_local','Tipo local'),
        ('sector_operacional','Sector'),('instalacao','Instalação'),('sistema','Sistema'),('nome','Equipamento'),
        ('categoria','Categoria'),('estado_operacional','Estado operacional'),('criticidade','Criticidade'),
        ('periodicidade_manutencao','Periodicidade'),('tag','TAG'),('fabricante','Marca/Fabricante'),('modelo','Modelo'),
        ('numero_serie','Nº série'),('especificacao','Especificação'),('potencia_kw','Potência kW'),('tensao_v','Tensão V'),
        ('corrente_a','Corrente A'),('ano_instalacao','Ano'),('quantidade','Quantidade'),('ativo','Activo no SGE'),
        ('fonte_cadastro','Fonte'),('source_record_no','Nº na fonte'),('ultima_sincronizacao','Última sincronização'),
        ('custo_aquisicao','Custo de aquisição'),('vida_util_anos','Vida útil (anos)'),
        ('fornecedor','Fornecedor'),('contrato_num','Contrato'),('garantia_fim','Garantia até'),
    ]
    for col, (_, label) in enumerate(headers): sheet.write(0, col, label, header)
    for row_index, row in enumerate(rows, start=1):
        for col, (key, _) in enumerate(headers):
            value = row.get(key)
            fmt = number_fmt if key in {'potencia_kw','tensao_v','corrente_a','quantidade','custo_aquisicao','vida_util_anos'} and value not in (None, '') else text_fmt
            sheet.write(row_index, col, value, fmt)
    sheet.freeze_panes(1, 0); sheet.autofilter(0, 0, max(len(rows), 1), len(headers)-1)
    widths = [8,30,27,18,14,24,30,28,22,20,14,17,16,20,30,20,38,14,12,12,10,12,13,24,12,20,18,16,20,18,14]
    for col, width in enumerate(widths): sheet.set_column(col, col, width)
    locations = workbook.add_worksheet('Locais')
    conn = _registry_sqlite3.connect(DB_PATH)
    loc_rows = conn.execute("""
        SELECT l.id,l.nome,COALESCE(l.tipo_local,''),COALESCE(l.categoria_operacional,''),
               COALESCE(l.sector_operacional,''),COALESCE(l.codigo,''),COALESCE(l.provincia,''),
               COALESCE(l.municipio,''),COALESCE(l.distrito,''),COALESCE(l.bairro,''),
               l.latitude,l.longitude,COALESCE(l.endereco,''),COALESCE(l.contato_nome,''),
               COALESCE(l.contato_tel,''),COALESCE(l.email,''),COALESCE(l.responsavel_alt,''),
               COALESCE(l.estado_tecnico,''),COALESCE(l.prioridade,''),COALESCE(l.ativo,1),
               COUNT(e.id)
        FROM locais l LEFT JOIN equipamentos e ON e.local_id=l.id AND COALESCE(e.deleted_at,'')=''
        GROUP BY l.id ORDER BY l.nome COLLATE NOCASE
    """).fetchall(); conn.close()
    loc_headers = ['ID','Nome','Tipo','Categoria','Sector','Código','Província','Município','Distrito','Bairro','Latitude','Longitude','Endereço','Responsável','Telefone','Email','Responsável alternativo','Estado técnico','Prioridade','Activo','Nº equipamentos']
    for col, label in enumerate(loc_headers): locations.write(0, col, label, header)
    for row_index, row in enumerate(loc_rows, start=1):
        for col, value in enumerate(row): locations.write(row_index, col, value, text_fmt)
    locations.freeze_panes(1,0); locations.autofilter(0,0,max(len(loc_rows),1),len(loc_headers)-1)
    for col in range(len(loc_headers)): locations.set_column(col,col,18)
    locations.set_column(1,1,30); locations.set_column(3,4,24); locations.set_column(12,12,34)
    workbook.close(); out.seek(0)
    return Response(out.getvalue(), mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', headers={'Content-Disposition': 'attachment; filename=cadastro_mestre_activos_sge.xlsx'})


def _registry_pdf_page(canvas, document, title):
    canvas.saveState()
    width, height = document.pagesize
    canvas.setFont('Helvetica-Bold', 8)
    canvas.setFillColor(_registry_colors.HexColor('#0B3B75'))
    canvas.drawString(1.2 * _registry_cm, height - 0.8 * _registry_cm, title)
    canvas.setFont('Helvetica', 7)
    canvas.setFillColor(_registry_colors.HexColor('#66788A'))
    canvas.drawRightString(width - 1.2 * _registry_cm, 0.6 * _registry_cm, f'Águas e Saneamento de Maputo · SGE · Página {document.page}')
    canvas.restoreState()


@app.route('/equipamentos/cadastro/export.pdf')
def cadastro_activos_export_pdf():
    rows = _registry_fetch_rows()
    out = _RegistryBytesIO()
    pagesize = _registry_landscape(_REGISTRY_A4)
    document = _RegistryDoc(out, pagesize=pagesize, leftMargin=1.0*_registry_cm, rightMargin=1.0*_registry_cm, topMargin=1.35*_registry_cm, bottomMargin=1.0*_registry_cm, title='Cadastro Mestre de Activos', author=INSTITUTION_NAME)
    styles = _registry_styles()
    small = _RegistryParagraphStyle('small', parent=styles['BodyText'], fontSize=6.2, leading=7.2)
    title_style = _RegistryParagraphStyle('registry_title', parent=styles['Title'], fontSize=18, leading=22, textColor=_registry_colors.HexColor('#0B3B75'), alignment=_REGISTRY_TA_CENTER)
    story = [_RegistryParagraph('Cadastro Mestre de Activos', title_style), _RegistrySpacer(1, 0.25*_registry_cm)]
    dashboard_data = _registry_dashboard(DB_PATH)
    story.append(_RegistryParagraph(f"Exportados: <b>{len(rows)}</b> · Locais activos: <b>{dashboard_data['locations']}</b> · ETAs: <b>{dashboard_data['etas']}</b> · Gerado em {_registry_datetime.now().strftime('%d/%m/%Y %H:%M')}", styles['BodyText']))
    story.append(_RegistrySpacer(1, 0.35*_registry_cm))
    data = [['#','Local','Instalação','Sistema','Equipamento','Estado','Crit.','Marca','Modelo','Periodic.']]
    for row in rows:
        data.append([
            row['id'], _RegistryParagraph(_registry_clean(row['local']), small), _RegistryParagraph(_registry_clean(row['instalacao']), small),
            _RegistryParagraph(_registry_clean(row['sistema']), small), _RegistryParagraph(_registry_clean(row['nome']), small),
            _RegistryParagraph(_registry_clean(row['estado_operacional']), small), row['criticidade'],
            _RegistryParagraph(_registry_clean(row['fabricante']), small), _RegistryParagraph(_registry_clean(row['modelo']), small),
            row['periodicidade_manutencao'],
        ])
    table = _RegistryTable(
        data, repeatRows=1,
        colWidths=[value * _registry_cm for value in [0.7,2.5,2.4,3.2,3.2,1.6,1.0,1.6,3.2,1.5]],
        rowHeights=None,
    )
    table.setStyle(_RegistryTableStyle([
        ('BACKGROUND',(0,0),(-1,0),_registry_colors.HexColor('#0B3B75')),('TEXTCOLOR',(0,0),(-1,0),_registry_colors.white),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),6.2),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('GRID',(0,0),(-1,-1),0.25,_registry_colors.HexColor('#D7E0EA')),('ROWBACKGROUNDS',(0,1),(-1,-1),[_registry_colors.white,_registry_colors.HexColor('#F5F8FB')]),
        ('LEFTPADDING',(0,0),(-1,-1),2),('RIGHTPADDING',(0,0),(-1,-1),2),('TOPPADDING',(0,0),(-1,-1),2),('BOTTOMPADDING',(0,0),(-1,-1),2),
    ]))
    story.append(table)
    document.build(story, onFirstPage=lambda c,d: _registry_pdf_page(c,d,'Cadastro Mestre de Activos'), onLaterPages=lambda c,d: _registry_pdf_page(c,d,'Cadastro Mestre de Activos'))
    return Response(out.getvalue(), mimetype='application/pdf', headers={'Content-Disposition': 'attachment; filename=cadastro_mestre_activos_sge.pdf'})


@app.route('/locais/export.pdf')
def locais_export_pdf():
    conn = _registry_sqlite3.connect(DB_PATH)
    rows = conn.execute("""
        SELECT l.id,l.nome,COALESCE(l.tipo_local,''),COALESCE(l.categoria_operacional,''),
               COALESCE(l.sector_operacional,''),COALESCE(l.codigo,''),COALESCE(l.estado_tecnico,''),
               COALESCE(l.prioridade,''),COALESCE(l.ativo,1),COUNT(e.id)
        FROM locais l LEFT JOIN equipamentos e ON e.local_id=l.id AND COALESCE(e.deleted_at,'')=''
        GROUP BY l.id ORDER BY l.nome COLLATE NOCASE
    """).fetchall(); conn.close()
    out = _RegistryBytesIO()
    document = _RegistryDoc(out, pagesize=_REGISTRY_A4, leftMargin=1.2*_registry_cm, rightMargin=1.2*_registry_cm, topMargin=1.4*_registry_cm, bottomMargin=1.0*_registry_cm, title='Lista de Locais', author=INSTITUTION_NAME)
    styles = _registry_styles(); story = [_RegistryParagraph('Lista Institucional de Locais', styles['Title']), _RegistrySpacer(1,0.3*_registry_cm)]
    data = [['#','Local','Tipo','Categoria','Sector','Código','Estado','Prior.','Activo','Equip.']]
    small = _RegistryParagraphStyle('locations_small', parent=styles['BodyText'], fontSize=7, leading=8)
    for row in rows:
        data.append([row[0],_RegistryParagraph(_registry_clean(row[1]),small),row[2],_RegistryParagraph(_registry_clean(row[3]),small),row[4],row[5],row[6],row[7],'Sim' if row[8] else 'Não',row[9]])
    table = _RegistryTable(
        data, repeatRows=1,
        colWidths=[value * _registry_cm for value in [0.55,2.9,1.8,2.4,1.4,1.45,1.3,1.15,0.8,0.8]],
    )
    table.setStyle(_RegistryTableStyle([
        ('BACKGROUND',(0,0),(-1,0),_registry_colors.HexColor('#0B3B75')),('TEXTCOLOR',(0,0),(-1,0),_registry_colors.white),
        ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),('FONTSIZE',(0,0),(-1,-1),7),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('GRID',(0,0),(-1,-1),0.25,_registry_colors.HexColor('#D7E0EA')),('ROWBACKGROUNDS',(0,1),(-1,-1),[_registry_colors.white,_registry_colors.HexColor('#F5F8FB')]),
        ('LEFTPADDING',(0,0),(-1,-1),2),('RIGHTPADDING',(0,0),(-1,-1),2),('TOPPADDING',(0,0),(-1,-1),3),('BOTTOMPADDING',(0,0),(-1,-1),3),
    ]))
    story.append(table)
    document.build(story, onFirstPage=lambda c,d: _registry_pdf_page(c,d,'Lista Institucional de Locais'), onLaterPages=lambda c,d: _registry_pdf_page(c,d,'Lista Institucional de Locais'))
    return Response(out.getvalue(), mimetype='application/pdf', headers={'Content-Disposition': 'attachment; filename=locais_sge.pdf'})
