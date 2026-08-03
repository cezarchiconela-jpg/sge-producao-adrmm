"""Domínio compatibility extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""

# --- Compat: rota alias entre /leituras_mensal e /leituras_mensais ---
try:
    from flask import redirect, url_for, request, g, render_template

    # 1) /leituras_mensal → rota principal do módulo mensal
    #    Se já existir uma função 'leituras_mensal' noutro sítio, este bloco NÃO cria outra.
    if not any(r.endpoint == 'leituras_mensal' for r in app.url_map.iter_rules()):
        @app.route('/leituras_mensal', methods=['GET'], endpoint='leituras_mensal')
        def leituras_mensal():
            # Abre o template mensal (sem redirecionar para export, nem procurar outras rotas)
            return render_template('leituras_mensal.html')

    # 2) /leituras_mensais → alias simples para /leituras_mensal
    #    Não usa mais procura por substring 'mensais' ou 'mensal', evitando cair em export.
    if not any(r.endpoint == 'leituras_mensais' for r in app.url_map.iter_rules()):
        @app.route('/leituras_mensais', methods=['GET'], endpoint='leituras_mensais')
        def _alias_leituras_mensais():
            return redirect(url_for('leituras_mensal'))

except Exception as _e:
    # Não falhar a app por causa de alias
    print("Alias leituras_mensal/mensais falhou:", _e)


# --- Safe single-shot DB init after all defs ---
try:
    init_db()
except Exception as _e:
    print("init_db falhou:", _e)


# === RESPOSTAS JSON PADRÃO PARA ERROS EM AJAX/JSON ===
from flask import jsonify, g
def _wants_json():
    if request.is_json:
        return True
    hx = request.headers.get('X-Requested-With','').lower()
    return 'xmlhttprequest' in hx or request.path.startswith('/api/')

@app.errorhandler(400)
def _err_400(e):
    if _wants_json():
        return jsonify(success=False, error="bad_request", message=str(e)), 400
    return e

@app.errorhandler(404)
def _err_404(e):
    if _wants_json():
        return jsonify(success=False, error="not_found", message="Recurso não encontrado"), 404
    return e

@app.errorhandler(500)
def _err_500(e):
    if _wants_json():
        return jsonify(success=False, error="server_error", message="Erro interno no servidor"), 500
    return e


# === VALIDAÇÕES POR LOCAL PARA LEITURAS_MENSAIS ===
from flask import abort, g

def _get_validacao_local(local):
    try:
        return get_validacao_local(local)
    except Exception:
        return {'fp_min': 0.85, 'kwh_dia_max': None, 'permitir_regressivo': 0}

def _calc_fp(ativa, reativa):
    try:
        ativa = float(str(ativa).replace(',','.'))
        reativa = float(str(reativa).replace(',','.'))
    except Exception:
        return None
    try:
        import math
        aparente = (ativa**2 + reativa**2)**0.5
        if aparente <= 0: 
            return None
        return round(ativa/aparente, 4)
    except Exception:
        return None

@app.before_request
def _leituras_mensais_guard():
    # Intercepta apenas POST aos módulos de leituras_mensais
    if request.method != 'POST':
        return
    p = request.path.lower()
    if 'leituras_mensal' not in p:  # cobre 'mensal' e 'mensais' pelo contains
        return
    try:
        local = request.form.get('local') or request.json.get('local') if request.is_json else None
        ativa = request.form.get('ativa') or request.json.get('ativa') if request.is_json else None
        reativa = request.form.get('reativa') or request.json.get('reativa') if request.is_json else None
        anterior = request.form.get('anterior') or request.json.get('anterior') if request.is_json else None
        atual = request.form.get('atual') or request.json.get('atual') if request.is_json else None

        if not local:
            return  # deixa a rota tratar campos obrigatórios

        rules = _get_validacao_local(local)
        # FP mínimo
        if ativa is not None and reativa is not None and rules.get('fp_min'):
            fp = _calc_fp(ativa, reativa)
            if fp is not None and fp < float(rules['fp_min']):
                msg = f"Fator de potência ({fp}) abaixo do mínimo ({rules['fp_min']}) definido para o local {local}."
                if _wants_json():
                    return jsonify(success=False, error="fp_min", message=msg), 400
                abort(400, description=msg)

        # Regressivo
        if rules.get('permitir_regressivo') in (0, '0', None):
            try:
                a0 = float(str(anterior).replace(',','.')) if anterior is not None else None
                a1 = float(str(atual).replace(',','.')) if atual is not None else None
                if a0 is not None and a1 is not None and a1 < a0:
                    msg = "Leitura atual inferior à anterior (regressivo não permitido para este local)."
                    if _wants_json():
                        return jsonify(success=False, error="regressivo", message=msg), 400
                    abort(400, description=msg)
            except Exception:
                pass

        # Limite diário de kWh (se front enviar um 'delta' já calculado)
        kwh_dia = request.form.get('kwh_dia') or (request.json.get('kwh_dia') if request.is_json else None)
        if rules.get('kwh_dia_max') and kwh_dia is not None:
            try:
                kd = float(str(kwh_dia).replace(',','.'))
                if kd > float(rules['kwh_dia_max']):
                    msg = f"Consumo diário ({kd} kWh) excede o limite ({rules['kwh_dia_max']} kWh) deste local."
                    if _wants_json():
                        return jsonify(success=False, error="kwh_dia_max", message=msg), 400
                    abort(400, description=msg)
            except Exception:
                pass
    except Exception as _e:
        # Não bloquear request em caso de exceção de validação
        if _logger:
            _logger.warning("Validação leituras_mensais falhou: %s", _e)
        return


def _ensure_indices():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    try:
        c.execute("CREATE TABLE IF NOT EXISTS saved_filters (id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, modulo TEXT, nome TEXT, query_json TEXT, created_at TEXT DEFAULT (datetime('now','localtime')) )")
        cols = {r[1] for r in c.execute('PRAGMA table_info(saved_filters)').fetchall()}
        if 'nome' not in cols:
            c.execute("ALTER TABLE saved_filters ADD COLUMN nome TEXT")
            if 'name' in cols:
                c.execute("UPDATE saved_filters SET nome = COALESCE(nome, name)")
        if 'name' not in cols:
            c.execute("ALTER TABLE saved_filters ADD COLUMN name TEXT")
            c.execute("UPDATE saved_filters SET name = COALESCE(name, nome)")
        if 'query_json' not in cols:
            c.execute("ALTER TABLE saved_filters ADD COLUMN query_json TEXT")
    except Exception:
        pass
    try:
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_leit_mensal_unique ON leituras_mensais(local, data, mes, ano)")
    except Exception:
        pass
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_leit_mensal_periodo ON leituras_mensais(mes, ano, local)")
    except Exception:
        pass
    try:
        c.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_locais_nome ON locais(nome)")
    except Exception:
        pass
    conn.commit(); conn.close()

# Garante criação após migrações
try:
    _ensure_indices()
except Exception as _e:
    print("Falha ao garantir índices:", _e)

# --- Endpoint aliases para compatibilidade com templates antigos ---
from flask import redirect, url_for, request

def _alias_to(endpoint, **kwargs):
    try:
        return redirect(url_for(endpoint, **kwargs))
    except Exception:
        # fallback: redireciona para home
        return redirect(url_for('index'))

# /leituras  (endpoint antigo 'leituras' aponta para função 'leituras_list')
try:
    if not any(r.endpoint == 'leituras' for r in app.url_map.iter_rules()):
        @app.route('/legacy/leituras', methods=['GET'], endpoint='leituras')
        def leituras():
            return _alias_to('leituras_list', **request.args.to_dict())
except Exception:
    pass

# 'locais' (endpoint antigo) -> 'listar_locais'
try:
    if not any(r.endpoint == 'locais' for r in app.url_map.iter_rules()):
        @app.route('/legacy/locais', methods=['GET'], endpoint='locais')
        def locais():
            return _alias_to('listar_locais', **request.args.to_dict())
except Exception:
    pass

# 'config_mt' -> 'mt_config'
try:
    if not any(r.endpoint == 'config_mt' for r in app.url_map.iter_rules()):
        @app.route('/legacy/mt/config', methods=['GET','POST'], endpoint='config_mt')
        def config_mt():
            return _alias_to('mt_config', **request.args.to_dict())
except Exception:
    pass

# 'leituras_diarias_*' -> mapeamentos aproximados
try:
    if not any(r.endpoint == 'leituras_diarias_view' for r in app.url_map.iter_rules()):
        @app.route('/leituras_diarias/view', methods=['GET'], endpoint='leituras_diarias_view')
        def leituras_diarias_view():
            return _alias_to('leituras_list', **request.args.to_dict())
except Exception:
    pass

try:
    if not any(r.endpoint == 'leituras_diarias_add' for r in app.url_map.iter_rules()):
        @app.route('/leituras_diarias/add', methods=['GET','POST'], endpoint='leituras_diarias_add')
        def leituras_diarias_add():
            return _alias_to('leituras_mensal', **request.args.to_dict())
except Exception:
    pass

try:
    if not any(r.endpoint == 'leituras_diarias_export' for r in app.url_map.iter_rules()):
        @app.route('/leituras_diarias/export', methods=['GET'], endpoint='leituras_diarias_export')
        def leituras_diarias_export():
            # se existir export específico mensal, prioriza
            for r in app.url_map.iter_rules():
                if r.endpoint == 'leituras_mensal_export':
                    return _alias_to('leituras_mensal_export', **request.args.to_dict())
            return _alias_to('leituras_export_csv', **request.args.to_dict())
except Exception:
    pass


# === ERROS: Render de template para navegação normal ===
from flask import render_template

def _render_error(status_code:int, message:str):
    try:
        # Tenta usar um template dedicado se existir
        return render_template('error.html', status_code=status_code, message=message), status_code
    except Exception:
        # Fallback simples em HTML
        return f"<h2>Erro {status_code}</h2><p>{message}</p>", status_code

@app.errorhandler(400)
def _err_400_page(e):
    if _wants_json():
        from flask import jsonify
        return jsonify(success=False, error="bad_request", message=str(getattr(e, 'description', e))), 400
    return _render_error(400, str(getattr(e, 'description', e)))

@app.errorhandler(404)
def _err_404_page(e):
    if _wants_json():
        from flask import jsonify
        return jsonify(success=False, error="not_found", message="Recurso não encontrado"), 404
    return _render_error(404, "Recurso não encontrado")

@app.errorhandler(500)
def _err_500_page(e):
    if _wants_json():
        from flask import jsonify
        return jsonify(success=False, error="server_error", message="Erro interno no servidor"), 500
    return _render_error(500, "Erro interno no servidor")


# === Normalização de endpoints (nomes padronizados) ===
# Mantém compatibilidade com os existentes e os legados.
try:
    # lista padronizada
    if not any(r.endpoint == 'leituras_mensais_list' for r in app.url_map.iter_rules()):
        @app.route('/legacy/leituras_mensais', methods=['GET'], endpoint='leituras_mensais_list')
        def leituras_mensais_list():
            return _alias_to('leituras_list', **request.args.to_dict())

    if not any(r.endpoint == 'leituras_mensais_add' for r in app.url_map.iter_rules()):
        @app.route('/leituras_mensais/add', methods=['GET','POST'], endpoint='leituras_mensais_add')
        def leituras_mensais_add():
            return _alias_to('leituras_mensal', **request.args.to_dict())

    if not any(r.endpoint == 'leituras_mensais_export' for r in app.url_map.iter_rules()):
        @app.route('/leituras_mensais/export', methods=['GET'], endpoint='leituras_mensais_export')
        def leituras_mensais_export():
            for r in app.url_map.iter_rules():
                if r.endpoint == 'leituras_mensal_export':
                    return _alias_to('leituras_mensal_export', **request.args.to_dict())
            return _alias_to('leituras_export_csv', **request.args.to_dict())
except Exception as _e:
    pass


