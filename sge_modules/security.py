"""Domínio security extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""

# === LOGGING ESTRUTURADO ===
import logging, uuid, time
from logging.handlers import RotatingFileHandler

def _setup_logging():
    logger = logging.getLogger('sge')
    if not logger.handlers:
        logger.setLevel(logging.INFO)
        fh = RotatingFileHandler(os.path.join(BASE_DIR, 'sge.log'), maxBytes=1_000_000, backupCount=3)
        fmt = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
        fh.setFormatter(fmt)
        logger.addHandler(fh)
    return logger

_logger = None
try:
    _logger = _setup_logging()
    _logger.info("SGE logging inicializado")
except Exception as _e:
    print("Falha ao iniciar logging:", _e)

@app.before_request
def _add_request_context():
    # Contexto de correlação para cada request
    rid = str(uuid.uuid4())[:8]
    setattr(g, 'rid', rid)
    setattr(g, 't0', time.time())

@app.after_request
def _after_request(resp):
    try:
        dt = time.time() - getattr(g, 't0', time.time())
        _logger and _logger.info("RID=%s %s %s %s %.3fs", getattr(g,'rid','-'), request.remote_addr, request.method, request.path, dt)
    except Exception:
        pass
    # Compatibilidade segura com todos os templates antigos e novos: qualquer
    # formulário POST recebe CSRF e qualquer fetch mutável recebe o cabeçalho.
    try:
        if resp.status_code < 400 and 'text/html' in (resp.content_type or '').lower():
            html = resp.get_data(as_text=True)
            token = _csrf_token()
            hidden = f'<input type="hidden" name="_csrf_token" value="{token}">'
            form_pattern = re.compile(r'(<form\b(?=[^>]*\bmethod\s*=\s*["\']?post["\']?)[^>]*>)', re.I)
            html = form_pattern.sub(lambda match: match.group(1) + hidden, html)
            fetch_guard = (
                '<script data-sge-csrf>(function(){const t=' + json.dumps(token) + ';'
                'const original=window.fetch;if(!original)return;window.fetch=function(input,init){'
                'init=init||{};const method=String(init.method||"GET").toUpperCase();'
                'if(["POST","PUT","PATCH","DELETE"].includes(method)){'
                'init.headers=new Headers(init.headers||{});init.headers.set("X-CSRF-Token",t);}'
                'return original.call(this,input,init);};})();</script>'
            )
            if '</body>' in html.lower():
                position = html.lower().rfind('</body>')
                html = html[:position] + fetch_guard + html[position:]
            else:
                html += fetch_guard
            resp.set_data(html)
            resp.headers['Content-Length'] = str(len(resp.get_data()))
    except Exception:
        pass
    # Cabeçalhos defensivos para ambiente online.
    resp.headers.setdefault('X-Content-Type-Options', 'nosniff')
    resp.headers.setdefault('X-Frame-Options', 'SAMEORIGIN')
    resp.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    resp.headers.setdefault('Permissions-Policy', 'geolocation=(), microphone=(), camera=()')
    resp.headers.setdefault(
        'Content-Security-Policy',
        "default-src 'self'; img-src 'self' data: blob:; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.jsdelivr.net https://cdn.plot.ly; "
        "font-src 'self' data: https://cdn.jsdelivr.net; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'self'",
    )
    if os.environ.get('SGE_HSTS', '0').lower() in ('1','true','yes'):
        resp.headers.setdefault('Strict-Transport-Security', 'max-age=31536000; includeSubDomains')
    return resp


@app.after_request
def _audit_state_change(resp):
    """Regista alterações e tentativas recusadas sem guardar dados sensíveis."""
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return resp
    if (request.path or '').startswith('/api/v1/telemetria'):
        return resp
    try:
        db_path = globals().get('DB_PATH')
        if db_path and os.path.exists(db_path):
            user = current_user() if 'current_user' in globals() else None
            conn = sqlite3.connect(db_path, timeout=5)
            conn.execute(
                """INSERT INTO security_audit(
                       request_id, actor, role, method, endpoint, path,
                       status_code, remote_ip, outcome
                   ) VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    getattr(g, 'rid', None),
                    (user or {}).get('username') or 'anonimo',
                    (user or {}).get('role') or 'sem_sessao',
                    request.method,
                    request.endpoint,
                    (request.path or '')[:500],
                    int(resp.status_code),
                    (request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:100],
                    'recusado' if getattr(g, 'security_denied', False) or int(resp.status_code) >= 400 else 'permitido',
                ),
            )
            conn.commit()
            conn.close()
    except Exception:
        pass
    return resp
app.config['UPLOAD_FOLDER'] = os.environ.get('SGE_UPLOAD_FOLDER', os.path.join(BASE_DIR, 'uploads'))
app.config['MAX_CONTENT_LENGTH'] = int(os.environ.get('SGE_MAX_UPLOAD_MB', '25')) * 1024 * 1024
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=os.environ.get('SESSION_COOKIE_SAMESITE', 'Lax'),
    SESSION_COOKIE_SECURE=os.environ.get('SESSION_COOKIE_SECURE', '0').lower() in ('1','true','yes'),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=max(1, int(os.environ.get('SGE_SESSION_HOURS', '8')))),
    SESSION_REFRESH_EACH_REQUEST=True,
)

# === AUTENTICAÇÃO OPCIONAL PARA AMBIENTE ONLINE ===
# Em produção recomenda-se activar: SGE_REQUIRE_LOGIN=1
# Credenciais via variáveis de ambiente: SGE_ADMIN_USER e SGE_ADMIN_PASSWORD
# Alternativa mais segura: SGE_ADMIN_PASSWORD_HASH com hash Werkzeug.
AUTH_EXEMPT_PREFIXES = ('/static/', '/api/v1/telemetria')
AUTH_EXEMPT_PATHS = {'/login', '/logout', '/healthz', '/robots.txt', '/favicon.ico'}
CSRF_EXEMPT_PREFIXES = ('/api/v1/telemetria',)
LOGIN_FAILURES = {}

def _truthy_env(name, default='0'):
    return os.environ.get(name, default).lower() in ('1', 'true', 'yes', 'on')

def _login_required_enabled():
    return _truthy_env('SGE_REQUIRE_LOGIN', '0')

def _auth_configured():
    return bool(os.environ.get('SGE_ADMIN_PASSWORD') or os.environ.get('SGE_ADMIN_PASSWORD_HASH'))

def _check_admin_password(password):
    stored_hash = os.environ.get('SGE_ADMIN_PASSWORD_HASH')
    stored_plain = os.environ.get('SGE_ADMIN_PASSWORD')
    if stored_hash:
        try:
            return check_password_hash(stored_hash, password or '')
        except Exception:
            return False
    return bool(stored_plain and secrets.compare_digest(stored_plain, password or ''))


# === GESTÃO DE UTILIZADORES E PERMISSÕES () ===
USER_ROLES = {
    'admin': 'Administrador',
    'gestor': 'Gestor / Supervisor',
    'tecnico': 'Técnico Operacional',
    'leitura': 'Operador de Leituras',
    'consulta': 'Consulta / Visualizador',
}

ROLE_DESCRIPTIONS = {
    'admin': 'Acesso total ao SGE, incluindo criação de utilizadores e configurações.',
    'gestor': 'Acesso operacional amplo, sem gestão de utilizadores.',
    'tecnico': 'Pode registar e actualizar dados técnicos, alertas, equipamentos e leituras.',
    'leitura': 'Focado em registo e consulta de leituras operacionais e mensais.',
    'consulta': 'Apenas consulta e relatórios, sem alterações de dados.',
}

def _ensure_users_schema():
    """Cria a tabela de utilizadores e garante um administrador inicial."""
    conn = None
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                full_name TEXT,
                role TEXT NOT NULL DEFAULT 'consulta',
                email TEXT,
                ativo INTEGER NOT NULL DEFAULT 1,
                must_change_password INTEGER NOT NULL DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now','localtime')),
                updated_at TEXT,
                last_login TEXT
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_users_username ON users(username)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_users_ativo ON users(ativo)")
        c.execute("SELECT COUNT(*) FROM users")
        count = int(c.fetchone()[0] or 0)
        if count == 0:
            admin_user = os.environ.get('SGE_ADMIN_USER', 'admin').strip() or 'admin'
            admin_hash = os.environ.get('SGE_ADMIN_PASSWORD_HASH')
            admin_plain = os.environ.get('SGE_ADMIN_PASSWORD')
            phash = admin_hash if admin_hash else generate_password_hash(admin_plain or 'admin123')
            c.execute("""INSERT INTO users(username, password_hash, full_name, role, ativo, must_change_password)
                         VALUES (?, ?, ?, 'admin', 1, ?)""",
                      (admin_user, phash, 'Administrador do Sistema', 0 if (admin_hash or admin_plain) else 1))
        conn.commit()
    except Exception as e:
        print('Falha ao preparar tabela users:', e)
    finally:
        try:
            conn and conn.close()
        except Exception:
            pass

def _user_row_to_dict(row):
    if not row:
        return None
    return {
        'id': row[0], 'username': row[1], 'full_name': row[2] or row[1], 'role': row[3] or 'consulta',
        'email': row[4] or '', 'ativo': int(row[5] or 0), 'must_change_password': int(row[6] or 0),
        'created_at': row[7], 'updated_at': row[8], 'last_login': row[9],
        'role_label': USER_ROLES.get(row[3] or 'consulta', row[3] or 'Consulta')
    }

def _get_user_by_username(username):
    _ensure_users_schema()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, username, full_name, role, email, ativo, must_change_password, created_at, updated_at, last_login, password_hash
                 FROM users WHERE username=? LIMIT 1""", ((username or '').strip(),))
    row = c.fetchone(); conn.close()
    return row

def _get_user_by_id(user_id):
    _ensure_users_schema()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("""SELECT id, username, full_name, role, email, ativo, must_change_password, created_at, updated_at, last_login
                 FROM users WHERE id=? LIMIT 1""", (int(user_id),))
    row = c.fetchone(); conn.close()
    return _user_row_to_dict(row)

def current_user():
    uid = session.get('user_id')
    if uid:
        user = _get_user_by_id(uid)
        if user and user.get('ativo') == 1:
            return user
    if session.get('sge_logged_in'):
        return {
            'id': None,
            'username': session.get('username', 'admin'),
            'full_name': session.get('full_name') or session.get('username', 'admin'),
            'role': session.get('role', 'admin'),
            'role_label': USER_ROLES.get(session.get('role', 'admin'), 'Administrador'),
            'ativo': 1,
        }
    return None

def _user_has_role(*roles):
    u = current_user()
    return bool(u and u.get('role') in roles)


ROLE_CAPABILITIES = {
    'admin': {'*'},
    'gestor': {'locais', 'configuracao', 'equipamentos', 'leituras', 'alertas', 'motores', 'solar', 'telemetria', 'calculo', 'eficiencia'},
    'tecnico': {'equipamentos', 'leituras', 'monitoria', 'alertas', 'motores', 'solar', 'calculo', 'eficiencia'},
    'leitura': {'leituras', 'monitoria', 'calculo'},
    'consulta': {'calculo'},
}


def _request_scope():
    path = (request.path or '/').lower()
    endpoint = (request.endpoint or '').lower()
    if path.startswith('/usuarios') or path.startswith('/admin'):
        return 'admin'
    if path.startswith('/telemetria/dispositivos'):
        return 'configuracao'
    if path.startswith('/locais/config') or '/tarifas' in path or path.startswith('/config'):
        return 'configuracao'
    if path.startswith('/mt/config'):
        return 'configuracao'
    if path.startswith('/mt/'):
        return 'leituras'
    if path.startswith('/locais') or endpoint in {'adicionar_local', 'editar_local'}:
        return 'locais'
    if path.startswith('/equipamentos') or endpoint.startswith('equipamento'):
        return 'equipamentos'
    if path.startswith('/leituras') or path.startswith('/energia'):
        return 'leituras'
    if endpoint == 'add':
        return 'leituras'
    if path.startswith('/monitoria'):
        return 'monitoria'
    if path.startswith('/alertas') or '/alerts/' in path:
        return 'alertas'
    if path.startswith('/motores') or path.startswith('/motor'):
        return 'motores'
    if path.startswith('/solar'):
        return 'solar'
    if path.startswith('/telemetria'):
        return 'telemetria'
    if path.startswith('/eficiencia'):
        return 'eficiencia'
    if endpoint in {'calcular_fatura', 'fatura_mes', 'api_calc_fatura_mensal_v2'}:
        return 'calculo'
    return 'configuracao'


def _role_can(role, scope):
    capabilities = ROLE_CAPABILITIES.get(role or 'consulta', set())
    return '*' in capabilities or scope in capabilities


def can_write(scope):
    if not _login_required_enabled():
        return True
    user = current_user()
    return bool(user and _role_can(user.get('role'), scope))


def _actor_name(default='sge'):
    user = current_user()
    if not user:
        return default
    return str(user.get('username') or user.get('full_name') or default)[:100]

def _deny_access(message='Sem permissão para executar esta acção.'):
    setattr(g, 'security_denied', True)
    if request.path.startswith('/api/') or request.headers.get('X-Requested-With','').lower() == 'xmlhttprequest':
        return jsonify(success=False, error='forbidden', message=message), 403
    flash(message, 'warning')
    return redirect(request.referrer or url_for('index'))

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not _user_has_role('admin'):
            return _deny_access('Apenas administradores podem aceder à gestão de utilizadores.')
        return fn(*args, **kwargs)
    return wrapper

@app.context_processor
def _inject_user_context():
    return {
        'current_user': current_user(),
        'USER_ROLES': USER_ROLES,
        'ROLE_DESCRIPTIONS': ROLE_DESCRIPTIONS,
    }

def _permission_guard_after_login():
    u = current_user()
    if not u:
        session.clear()
        if request.path.startswith('/api/'):
            return jsonify(success=False, error='auth_required', message='Sessão inválida ou utilizador desativado.'), 401
        return redirect(url_for('login'))
    role = u.get('role') or 'consulta'
    path = (request.path or '/').lower()
    method = (request.method or 'GET').upper()
    if request.endpoint == 'perfil_password':
        return None
    if role == 'admin':
        return None
    if path.startswith('/usuarios') or path.startswith('/admin'):
        return _deny_access('Esta área é reservada ao administrador.')
    if method in ('GET', 'HEAD', 'OPTIONS'):
        sensitive_read = (
            path.startswith('/locais/config')
            or '/tarifas' in path
            or path.startswith('/mt/config')
            or path.startswith('/telemetria/dispositivos')
        )
        if sensitive_read and not _role_can(role, 'configuracao'):
            return _deny_access('Este perfil não possui acesso às configurações do sistema.')
        return None
    scope = _request_scope()
    if not _role_can(role, scope):
        return _deny_access(f'O perfil {USER_ROLES.get(role, role)} não possui permissão de escrita nesta área.')
    return None

@app.before_request
def _require_login_online():
    if not _login_required_enabled():
        return
    path = request.path or '/'
    if path in AUTH_EXEMPT_PATHS or any(path.startswith(prefix) for prefix in AUTH_EXEMPT_PREFIXES):
        return
    if session.get('sge_logged_in'):
        return _permission_guard_after_login()
    if request.path.startswith('/api/') or request.headers.get('X-Requested-With','').lower() == 'xmlhttprequest':
        return jsonify(success=False, error='auth_required', message='Autenticação necessária.'), 401
    return redirect(url_for('login', next=request.url))


def _csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token


def _csrf_failure():
    setattr(g, 'security_denied', True)
    if request.path.startswith('/api/') or request.is_json:
        return jsonify(success=False, error='csrf_invalid', message='Token de segurança ausente ou inválido.'), 400
    flash('O formulário expirou ou é inválido. Atualize a página e tente novamente.', 'warning')
    return redirect(request.referrer or url_for('index'))


@app.before_request
def _protect_state_changes():
    if request.method not in ('POST', 'PUT', 'PATCH', 'DELETE'):
        return None
    if any((request.path or '').startswith(prefix) for prefix in CSRF_EXEMPT_PREFIXES):
        return None
    expected = session.get('_csrf_token')
    supplied = request.headers.get('X-CSRF-Token') or request.form.get('_csrf_token')
    if not expected or not supplied or not secrets.compare_digest(str(expected), str(supplied)):
        return _csrf_failure()
    return None


def _safe_next_url(value, fallback_endpoint='index'):
    text = str(value or '').strip()
    if not text:
        return url_for(fallback_endpoint)
    parsed = urlsplit(text)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith('/'):
        return url_for(fallback_endpoint)
    return parsed.path + (('?' + parsed.query) if parsed.query else '')


def _login_is_limited(ip):
    now = time.time()
    recent = [stamp for stamp in LOGIN_FAILURES.get(ip, []) if now - stamp < 900]
    LOGIN_FAILURES[ip] = recent
    return len(recent) >= 5


def _record_login_failure(ip):
    LOGIN_FAILURES.setdefault(ip, []).append(time.time())


@app.context_processor
def _inject_security_helpers():
    return {'csrf_token': _csrf_token, 'can_write': can_write}

@app.route('/login', methods=['GET', 'POST'])
def login():
    if not _login_required_enabled():
        flash('Autenticação não está activa neste ambiente.', 'info')
        return redirect(url_for('index'))
    _ensure_users_schema()
    if request.method == 'POST':
        client_ip = (request.headers.get('X-Forwarded-For') or request.remote_addr or 'unknown').split(',')[0].strip()
        if _login_is_limited(client_ip):
            flash('Muitas tentativas de acesso. Aguarde 15 minutos e tente novamente.', 'danger')
            return render_template('login.html'), 429
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        row = _get_user_by_username(username)
        if row:
            uid, uname, full_name, role, email, ativo, must_change, created_at, updated_at, last_login, phash = row
            if int(ativo or 0) != 1:
                flash('Este utilizador está desativado. Contacte o administrador.', 'error')
            elif check_password_hash(phash, password or ''):
                conn = sqlite3.connect(DB_PATH); c = conn.cursor()
                c.execute("UPDATE users SET last_login=datetime('now','localtime') WHERE id=?", (uid,))
                conn.commit(); conn.close()
                session.clear()
                session['sge_logged_in'] = True
                session['user_id'] = uid
                session['username'] = uname
                session['full_name'] = full_name or uname
                session['role'] = role or 'consulta'
                session.permanent = True
                LOGIN_FAILURES.pop(client_ip, None)
                if int(must_change or 0) == 1:
                    return redirect(url_for('perfil_password'))
                return redirect(_safe_next_url(request.args.get('next')))
            else:
                _record_login_failure(client_ip)
                flash('Credenciais inválidas.', 'error')
        elif _auth_configured():
            expected_user = os.environ.get('SGE_ADMIN_USER', 'admin')
            if secrets.compare_digest(username, expected_user) and _check_admin_password(password):
                session.clear()
                session['sge_logged_in'] = True
                session['username'] = username
                session['full_name'] = 'Administrador do Sistema'
                session['role'] = 'admin'
                session.permanent = True
                LOGIN_FAILURES.pop(client_ip, None)
                return redirect(_safe_next_url(request.args.get('next')))
            _record_login_failure(client_ip)
            flash('Credenciais inválidas.', 'error')
        else:
            flash('Login activo, mas ainda não existe administrador configurado.', 'error')
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    flash('Sessão terminada com sucesso.', 'success')
    return redirect(url_for('login') if _login_required_enabled() else url_for('index'))


@app.route('/perfil/password', methods=['GET', 'POST'])
def perfil_password():
    u = current_user()
    if not u:
        return redirect(url_for('login'))
    if not u.get('id'):
        flash('Este login usa variáveis de ambiente. Para alterar a senha, actualize SGE_ADMIN_PASSWORD no Render.', 'info')
        return redirect(url_for('index'))
    if request.method == 'POST':
        atual = request.form.get('atual','')
        nova = request.form.get('nova','')
        confirmar = request.form.get('confirmar','')
        row = _get_user_by_username(u['username'])
        if not row or not check_password_hash(row[10], atual or ''):
            flash('Palavra-passe actual inválida.', 'danger')
        elif len(nova) < 8:
            flash('A nova palavra-passe deve ter pelo menos 8 caracteres.', 'warning')
        elif nova != confirmar:
            flash('A confirmação da palavra-passe não coincide.', 'warning')
        else:
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("UPDATE users SET password_hash=?, must_change_password=0, updated_at=datetime('now','localtime') WHERE id=?", (generate_password_hash(nova), u['id']))
            conn.commit(); conn.close()
            flash('Palavra-passe actualizada com sucesso.', 'success')
            return redirect(url_for('index'))
    return render_template('perfil_password.html')

@app.route('/usuarios')
@admin_required
def usuarios_list():
    _ensure_users_schema()
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    rows = c.execute("""SELECT id, username, full_name, role, email, ativo, must_change_password, created_at, updated_at, last_login
                        FROM users ORDER BY ativo DESC, username COLLATE NOCASE""").fetchall()
    conn.close()
    users = [_user_row_to_dict(r) for r in rows]
    return render_template('usuarios.html', users=users)

@app.route('/usuarios/novo', methods=['GET', 'POST'])
@admin_required
def usuarios_novo():
    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        full_name = (request.form.get('full_name') or '').strip()
        email = (request.form.get('email') or '').strip()
        role = (request.form.get('role') or 'consulta').strip()
        password = request.form.get('password') or ''
        ativo = 1 if request.form.get('ativo','1') == '1' else 0
        must_change = 1 if request.form.get('must_change_password') == '1' else 0
        if not username:
            flash('O nome de utilizador é obrigatório.', 'warning')
        elif role not in USER_ROLES:
            flash('Nível de acesso inválido.', 'warning')
        elif len(password) < 8:
            flash('A palavra-passe deve ter pelo menos 8 caracteres.', 'warning')
        else:
            try:
                conn = sqlite3.connect(DB_PATH); c = conn.cursor()
                c.execute("""INSERT INTO users(username, password_hash, full_name, role, email, ativo, must_change_password)
                             VALUES (?, ?, ?, ?, ?, ?, ?)""",
                          (username, generate_password_hash(password), full_name, role, email, ativo, must_change))
                conn.commit(); conn.close()
                flash('Utilizador criado com sucesso.', 'success')
                return redirect(url_for('usuarios_list'))
            except sqlite3.IntegrityError:
                flash('Já existe um utilizador com esse nome.', 'danger')
            except Exception as e:
                flash(f'Não foi possível criar o utilizador: {e}', 'danger')
    return render_template('usuario_form.html', mode='novo', user=None)

@app.route('/usuarios/<int:user_id>/editar', methods=['GET', 'POST'])
@admin_required
def usuarios_editar(user_id):
    user = _get_user_by_id(user_id)
    if not user:
        flash('Utilizador não encontrado.', 'warning')
        return redirect(url_for('usuarios_list'))
    if request.method == 'POST':
        full_name = (request.form.get('full_name') or '').strip()
        email = (request.form.get('email') or '').strip()
        role = (request.form.get('role') or 'consulta').strip()
        ativo = 1 if request.form.get('ativo','0') == '1' else 0
        if role not in USER_ROLES:
            flash('Nível de acesso inválido.', 'warning')
        else:
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("""UPDATE users SET full_name=?, email=?, role=?, ativo=?, updated_at=datetime('now','localtime') WHERE id=?""",
                      (full_name, email, role, ativo, user_id))
            conn.commit(); conn.close()
            flash('Utilizador actualizado com sucesso.', 'success')
            return redirect(url_for('usuarios_list'))
    return render_template('usuario_form.html', mode='editar', user=user)

@app.route('/usuarios/<int:user_id>/password', methods=['GET', 'POST'])
@admin_required
def usuarios_password(user_id):
    user = _get_user_by_id(user_id)
    if not user:
        flash('Utilizador não encontrado.', 'warning')
        return redirect(url_for('usuarios_list'))
    if request.method == 'POST':
        password = request.form.get('password') or ''
        must_change = 1 if request.form.get('must_change_password') == '1' else 0
        if len(password) < 8:
            flash('A palavra-passe deve ter pelo menos 8 caracteres.', 'warning')
        else:
            conn = sqlite3.connect(DB_PATH); c = conn.cursor()
            c.execute("UPDATE users SET password_hash=?, must_change_password=?, updated_at=datetime('now','localtime') WHERE id=?",
                      (generate_password_hash(password), must_change, user_id))
            conn.commit(); conn.close()
            flash('Palavra-passe redefinida com sucesso.', 'success')
            return redirect(url_for('usuarios_list'))
    return render_template('usuario_password.html', user=user)

@app.route('/usuarios/<int:user_id>/toggle', methods=['POST'])
@admin_required
def usuarios_toggle(user_id):
    user = _get_user_by_id(user_id)
    if not user:
        flash('Utilizador não encontrado.', 'warning')
        return redirect(url_for('usuarios_list'))
    if user.get('id') == session.get('user_id'):
        flash('Não podes desativar o teu próprio utilizador.', 'warning')
        return redirect(url_for('usuarios_list'))
    novo = 0 if int(user.get('ativo',1)) == 1 else 1
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute("UPDATE users SET ativo=?, updated_at=datetime('now','localtime') WHERE id=?", (novo, user_id))
    conn.commit(); conn.close()
    flash('Estado do utilizador actualizado.', 'success')
    return redirect(url_for('usuarios_list'))

@app.get('/healthz')
def healthz():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute('SELECT 1')
        conn.close()
        db_ok = True
    except Exception:
        db_ok = False
    status = 200 if db_ok else 503
    return jsonify(status='ok' if db_ok else 'degraded', app='SGE', database=db_ok), status
