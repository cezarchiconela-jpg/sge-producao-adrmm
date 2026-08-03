"""Domínio administration extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""

@app.route('/admin/backup_db')
@admin_required
def admin_backup_db():
    return redirect(url_for('admin_backups'))


@app.route('/admin/backups')
@admin_required
def admin_backups():
    backup_dir = os.environ.get('SGE_BACKUP_DIR', os.path.join(os.path.dirname(DB_PATH), 'backups'))
    os.makedirs(backup_dir, exist_ok=True)
    files = []
    for name in sorted(os.listdir(backup_dir), reverse=True):
        path = os.path.join(backup_dir, name)
        if name.startswith('sge_backup_') and name.endswith('.zip') and os.path.isfile(path):
            files.append({'name': name, 'size': os.path.getsize(path), 'mtime': datetime.fromtimestamp(os.path.getmtime(path))})
    return render_template('admin_backups.html', backups=files, backup_dir=backup_dir,
                           retention_days=int(os.environ.get('SGE_BACKUP_RETENTION_DAYS', '30')))


@app.route('/admin/backups/criar', methods=['POST'])
@admin_required
def admin_backups_criar():
    backup_dir = os.environ.get('SGE_BACKUP_DIR', os.path.join(os.path.dirname(DB_PATH), 'backups'))
    try:
        result = create_backup(
            DB_PATH, app.config['UPLOAD_FOLDER'], backup_dir, reason='manual', actor=_actor_name(),
            retention_days=int(os.environ.get('SGE_BACKUP_RETENTION_DAYS', '30')),
            max_backups=int(os.environ.get('SGE_BACKUP_MAX_COUNT', '30')),
            mirror_dir=os.environ.get('SGE_BACKUP_MIRROR_DIR') or None,
        )
        conn = sqlite3.connect(DB_PATH)
        conn.execute('''INSERT INTO backup_history(filename, sha256, size_bytes, verified, reason, actor)
                        VALUES(?,?,?,?,?,?)''',
                     (result['filename'], result['sha256'], result['size_bytes'], 1, 'manual', _actor_name()))
        conn.commit(); conn.close()
        flash('Backup criado e verificado com sucesso.', 'success')
    except Exception as exc:
        flash(f'Não foi possível criar o backup: {exc}', 'danger')
    return redirect(url_for('admin_backups'))


@app.route('/admin/backups/<path:filename>/verificar', methods=['POST'])
@admin_required
def admin_backups_verificar(filename):
    safe_name = os.path.basename(filename)
    if safe_name != filename or not safe_name.startswith('sge_backup_') or not safe_name.endswith('.zip'):
        return _deny_access('Nome de backup inválido.')
    backup_dir = os.environ.get('SGE_BACKUP_DIR', os.path.join(os.path.dirname(DB_PATH), 'backups'))
    try:
        verify_backup(os.path.join(backup_dir, safe_name))
        flash('Integridade do backup confirmada.', 'success')
    except Exception as exc:
        flash(f'Backup inválido: {exc}', 'danger')
    return redirect(url_for('admin_backups'))


@app.route('/admin/backups/<path:filename>/download')
@admin_required
def admin_backups_download(filename):
    safe_name = os.path.basename(filename)
    if safe_name != filename or not safe_name.startswith('sge_backup_') or not safe_name.endswith('.zip'):
        return _deny_access('Nome de backup inválido.')
    backup_dir = os.environ.get('SGE_BACKUP_DIR', os.path.join(os.path.dirname(DB_PATH), 'backups'))
    return send_from_directory(backup_dir, safe_name, as_attachment=True)

@app.route('/admin/health')
@admin_required
def admin_health():
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute("SELECT 1"); conn.close()
        return jsonify({"ok": True, "db": "connected"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


