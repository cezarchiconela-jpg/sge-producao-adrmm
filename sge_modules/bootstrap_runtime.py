"""Domínio bootstrap_runtime extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""

DB_PATH = os.environ.get('SGE_DB_PATH', os.path.join(BASE_DIR, 'sge.db'))

def _prepare_runtime_paths():
    # Permite deploy com base de dados e uploads em disco persistente (ex.: Render Disk).
    try:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
        seed_db = os.path.join(BASE_DIR, 'sge.db')
        if os.path.abspath(DB_PATH) != os.path.abspath(seed_db) and (not os.path.exists(DB_PATH)) and os.path.exists(seed_db):
            import shutil
            shutil.copy2(seed_db, DB_PATH)
    except Exception as _e:
        print('Aviso: preparação de paths de runtime falhou:', _e)

_prepare_runtime_paths()

# Backup diário consistente antes de qualquer alteração de estrutura/dados.
STARTUP_BACKUP_RESULT = None
try:
    if os.path.exists(DB_PATH) and os.path.getsize(DB_PATH) > 0:
        STARTUP_BACKUP_RESULT = maybe_create_daily_backup(
            DB_PATH,
            app.config['UPLOAD_FOLDER'],
            os.environ.get('SGE_BACKUP_DIR', os.path.join(os.path.dirname(DB_PATH), 'backups')),
            reason='pre_migracao_arranque',
            actor='sge',
        )
except Exception as _backup_error:
    print('Aviso: backup automático não foi concluído:', _backup_error)

# Migração canónica: garante uma instalação completa tanto em base nova como antiga.
run_migrations(DB_PATH)

# Cadastro mestre institucional: a primeira execução desta versão reconcilia
# o cadastro DIMA com a base existente. O processo é idempotente e preserva
# TAGs, custos, anexos, medições e outros dados preenchidos manualmente.
BUNDLED_REGISTRY_RESULT = None
try:
    from asset_registry_service import bootstrap_bundled_registry
    BUNDLED_REGISTRY_RESULT = bootstrap_bundled_registry(DB_PATH, BASE_DIR)
except Exception as _registry_error:
    print('Aviso: cadastro mestre DIMA não foi aplicado:', _registry_error)
if STARTUP_BACKUP_RESULT:
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute('''INSERT INTO backup_history(filename, sha256, size_bytes, verified, reason, actor)
                        VALUES(?,?,?,?,?,?)''',
                     (STARTUP_BACKUP_RESULT['filename'], STARTUP_BACKUP_RESULT['sha256'],
                      STARTUP_BACKUP_RESULT['size_bytes'], 1, 'pre_migracao_arranque', 'sge'))
        conn.commit(); conn.close()
    except Exception:
        pass

@app.context_processor
def _inject_global_template_helpers():
    return {'now': datetime.now}

try:
    migrate_pack3()
except Exception as _e:
    print("Migração de validações falhou:", _e)

# --- Locais operacional: enriquecimento do cadastro ---
def migrate_locais_operacional_fase3():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        cols = {row[1] for row in c.execute("PRAGMA table_info(locais)").fetchall()}
        wanted = {
            'tipo_local': "TEXT",
            'categoria_operacional': "TEXT",
            'email': "TEXT",
            'responsavel_alt': "TEXT",
            'estado_tecnico': "TEXT DEFAULT 'Normal'",
            'prioridade': "TEXT DEFAULT 'Média'",
            'parent_id': "INTEGER"
        }
        for col, spec in wanted.items():
            if col not in cols:
                c.execute(f"ALTER TABLE locais ADD COLUMN {col} {spec}")
        conn.commit()
    finally:
        conn.close()

try:
    migrate_locais_operacional_fase3()
except Exception as _e:
    print("Migração de locais falhou:", _e)


def migrate_locais_hierarquia_online_v3():
    """Migração segura para centros, sublocais e hierarquia de locais."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        cols = {row[1] for row in c.execute("PRAGMA table_info(locais)").fetchall()}
        if 'parent_id' not in cols:
            c.execute("ALTER TABLE locais ADD COLUMN parent_id INTEGER")
        c.execute("CREATE INDEX IF NOT EXISTS idx_locais_parent_id ON locais(parent_id)")
        conn.commit()
    finally:
        conn.close()

try:
    migrate_locais_hierarquia_online_v3()
except Exception as _e:
    print("Migração de hierarquia de locais falhou:", _e)


# --- Locais operacional: histórico, alertas e exportação executiva ---
def migrate_locais_operacional_fase4():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute("""CREATE TABLE IF NOT EXISTS locais_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            local_id INTEGER NOT NULL,
            evento TEXT NOT NULL,
            detalhe TEXT,
            actor TEXT DEFAULT 'sge',
            ts TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.commit()
    finally:
        conn.close()

def log_local_history(local_id, evento, detalhe='', actor='sge'):
    try:
        if actor in ('sge', 'locais_fase4', 'pack3'):
            actor = _actor_name(actor)
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('INSERT INTO locais_history(local_id, evento, detalhe, actor) VALUES(?,?,?,?)',
                  (local_id, evento, detalhe, actor))
        conn.commit(); conn.close()
    except Exception:
        pass

def get_local_history(local_id, limit=12):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('SELECT evento, detalhe, actor, ts FROM locais_history WHERE local_id=? ORDER BY id DESC LIMIT ?', (local_id, int(limit)))
    rows = c.fetchall(); conn.close()
    return [{'evento':r[0], 'detalhe':r[1], 'actor':r[2], 'ts':r[3]} for r in rows]

def get_local_alertas(local, cfg, overview):
    itens = []
    if not (local.get('contato_nome') or '').strip() and not (local.get('contato_tel') or '').strip() and not (local.get('email') or '').strip():
        itens.append(('warning', 'Sem contacto principal registado', 'Definir responsável, telefone ou email para garantir governança do local.'))
    if float(cfg.get('pot_contratada', 0) or 0) <= 0:
        itens.append(('danger', 'Potência contratada não definida', 'Sem este parâmetro a pré-fatura e os controlos de ponta ficam limitados.'))
    if float(cfg.get('pot_instalada', 0) or 0) <= 0:
        itens.append(('info', 'Potência instalada não definida', 'Preenche este campo para relatórios e indicadores executivos.'))
    if overview.get('leituras_mensais_count', 0) == 0:
        itens.append(('info', 'Sem histórico de leituras mensais', 'Abrir Leituras Mensais para começar o histórico do local.'))
    if (local.get('estado_tecnico') or 'Normal').lower() in ['atenção', 'atencao', 'crítico', 'critico']:
        itens.append(('warning', f"Estado técnico: {local.get('estado_tecnico')}", 'Este local merece acompanhamento mais próximo no plano operacional.'))
    if (local.get('prioridade') or 'Média').lower() == 'alta':
        itens.append(('danger', 'Local marcado como prioridade alta', 'Convém validar cadastro, configuração, leituras e equipamentos com maior frequência.'))
    return itens

try:
    migrate_locais_operacional_fase4()
except Exception as _e:
    print("Migração de locais falhou:", _e)


# --- Auto-migrations for leituras_mensais ---
def migrate_leituras_mensais():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    # Table may already exist; ensure schema columns exist
    c.execute('''CREATE TABLE IF NOT EXISTS leituras_mensais (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        local TEXT,
        data TEXT,
        hora TEXT,
        ativa REAL, reativa REAL, ponta REAL,
        fp REAL, potc REAL,
        anterior REAL, atual REAL, diferenca REAL,
        agua REAL, esp REAL, acum REAL, valor REAL,
        mes TEXT, ano INTEGER
    )''')
    # Add unique index to avoid duplicates per (local, data)
    try:
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_leituras_mensais_unique ON leituras_mensais(local, data)')
    except Exception:
        pass
    # Audit table
    c.execute('''CREATE TABLE IF NOT EXISTS leituras_mensais_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lm_id INTEGER,
        acao TEXT,
        field TEXT,
        old_value TEXT,
        new_value TEXT,
        actor TEXT,
        ts TEXT DEFAULT (datetime('now','localtime'))
    )''')
    conn.commit(); conn.close()

# === BANCO DE DADOS E TABELAS ===


def _migrar_audit_leituras():
    try:
        conn = sqlite3.connect(DB_PATH); c = conn.cursor()
        c.execute('''
            CREATE TABLE IF NOT EXISTS leituras_audit (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                leitura_id INTEGER,
                acao TEXT,
                field TEXT,
                old_value TEXT,
                new_value TEXT,
                actor TEXT,
                ts TEXT DEFAULT (datetime('now','localtime'))
            )
        ''')
        conn.commit(); conn.close()
    except Exception:
        pass
def init_db():
    # Pacote 2: migrações (idempotente)
    try:
        _apply_pacote2_migrations()
    except Exception:
        pass
    _migrar_audit_leitras_safe = _migrar_audit_leituras()


    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Config de Local (tabela + índices)
    c.execute('''
        CREATE TABLE IF NOT EXISTS locais_cfg (
            local_id INTEGER PRIMARY KEY,
            fator_mult REAL DEFAULT 1.0,
            pot_contratada REAL DEFAULT 0.0,
            tarifa_ativa REAL DEFAULT 4.780,
            tarifa_reativa REAL DEFAULT 1.430,
            tarifa_ponta REAL DEFAULT 497.03,
            tarifa_perdas REAL DEFAULT 4.780,
            taxa_fixa REAL DEFAULT 207.28,
            taxa_radio REAL DEFAULT 297.00,
            taxa_lixo REAL DEFAULT 150.00,
            iva REAL DEFAULT 16.0,
            FOREIGN KEY (local_id) REFERENCES locais(id)
        )
    ''')
    try:
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS idx_leit_mensal_unique ON leituras_mensais(local, data, mes, ano)')
        c.execute('CREATE INDEX IF NOT EXISTS idx_leit_mensal_periodo ON leituras_mensais(mes, ano, local)')
    except Exception as _e:
        pass
    # MIGRATION: add pot_instalada if missing
    try:
        c.execute("PRAGMA table_info(locais_cfg)")
        cols_cfg = {row[1] for row in c.fetchall()}
        if 'pot_instalada' not in cols_cfg:
            c.execute("ALTER TABLE locais_cfg ADD COLUMN pot_instalada REAL DEFAULT 0.0")
    except Exception:
        pass

    # Locais (base)
    c.execute('''
        CREATE TABLE IF NOT EXISTS locais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE
        )
    ''')
    # --- MIGRAÇÕES EQUIPAMENTOS (Excelência) ---
    try:
        c.execute("PRAGMA table_info(equipamentos)")
        cols = [r[1] for r in c.fetchall()]
        if "ativo" not in cols:
            c.execute("ALTER TABLE equipamentos ADD COLUMN ativo INTEGER DEFAULT 1")
        if "created_at" not in cols:
            c.execute("ALTER TABLE equipamentos ADD COLUMN created_at TEXT")
        if "updated_at" not in cols:
            c.execute("ALTER TABLE equipamentos ADD COLUMN updated_at TEXT")
    except Exception:
        pass


    # --- MIGRAÇÕES EQUIPAMENTOS (Campos avançados + Fotos) ---
    try:
        c.execute("PRAGMA table_info(equipamentos)")
        cols = [r[1] for r in c.fetchall()]
        if "categoria" not in cols:
            c.execute("ALTER TABLE equipamentos ADD COLUMN categoria TEXT")
        if "fabricante" not in cols:
            c.execute("ALTER TABLE equipamentos ADD COLUMN fabricante TEXT")
        if "modelo" not in cols:
            c.execute("ALTER TABLE equipamentos ADD COLUMN modelo TEXT")
        if "numero_serie" not in cols:
            c.execute("ALTER TABLE equipamentos ADD COLUMN numero_serie TEXT")
        if "custo_aquisicao" not in cols:
            c.execute("ALTER TABLE equipamentos ADD COLUMN custo_aquisicao REAL")
        if "vida_util_anos" not in cols:
            c.execute("ALTER TABLE equipamentos ADD COLUMN vida_util_anos INTEGER")
        if "criticidade" not in cols:
            c.execute("ALTER TABLE equipamentos ADD COLUMN criticidade TEXT")
        if "cover_photo_id" not in cols:
            c.execute("ALTER TABLE equipamentos ADD COLUMN cover_photo_id INTEGER")
    except Exception:
        pass

    c.execute('''
        CREATE TABLE IF NOT EXISTS equipamentos_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipamento_id INTEGER,
            filename TEXT,
            thumb_filename TEXT,
            caption TEXT,
            width INTEGER,
            height INTEGER,
            uploaded_at TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_ep_equip ON equipamentos_photos(equipamento_id)")
    except Exception:
        pass

    # Audit log
    c.execute('''
        CREATE TABLE IF NOT EXISTS equipamentos_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipamento_id INTEGER,
            acao TEXT,
            detalhes TEXT,
            ts TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')

    # Files for equipamentos
    c.execute('''
        CREATE TABLE IF NOT EXISTS equipamentos_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipamento_id INTEGER,
            filename TEXT,
            original_name TEXT,
            mime TEXT,
            size INTEGER,
            uploaded_at TEXT DEFAULT (datetime('now','localtime'))
        )
    ''')

    # Índices
    try:
        c.execute("CREATE INDEX IF NOT EXISTS idx_equip_local ON equipamentos(local_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_equip_nome ON equipamentos(nome)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_equip_ativo ON equipamentos(ativo)")
    except Exception:
        pass
    # --- MIGRAÇÕES EQUIPAMENTOS (Excelência Pack 3) ---
    try:
        c.execute('''
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        ''')
        c.execute("INSERT OR IGNORE INTO settings (key,value) VALUES ('unique_tag','0')")
        c.execute("INSERT OR IGNORE INTO settings (key,value) VALUES ('unique_nome_local','0')")
        c.execute("CREATE INDEX IF NOT EXISTS idx_equip_tag ON equipamentos(tag)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_equip_nome_local ON equipamentos(nome, local_id)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_equip_numero_serie ON equipamentos(numero_serie)")
    except Exception:
        pass

    # --- Links de documentação por equipamento ---
    try:
        c.execute('''
            CREATE TABLE IF NOT EXISTS equipamentos_links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipamento_id INTEGER,
                url TEXT,
                title TEXT,
                added_at TEXT DEFAULT (datetime('now','localtime'))
            )
        ''')
        # Fecho seguro da ligação principal do init_db.
        # Na versão anterior esta ligação ficava aberta e podia bloquear o sge.db.
        conn.commit()
        conn.close()
    except Exception:
        pass



        # ===

        # === MIGRAÇÃO: colunas extras em locais ===
        try:
            c.execute("PRAGMA table_info(locais)")
            cols = {row[1] for row in c.fetchall()}
            if "codigo" not in cols:
                c.execute("ALTER TABLE locais ADD COLUMN codigo TEXT")
            if "endereco" not in cols:
                c.execute("ALTER TABLE locais ADD COLUMN endereco TEXT")
            if "contato_nome" not in cols:
                c.execute("ALTER TABLE locais ADD COLUMN contato_nome TEXT")
            if "contato_tel" not in cols:
                c.execute("ALTER TABLE locais ADD COLUMN contato_tel TEXT")
            if "notas" not in cols:
                c.execute("ALTER TABLE locais ADD COLUMN notas TEXT")
            if "ativo" not in cols:
                c.execute("ALTER TABLE locais ADD COLUMN ativo INTEGER DEFAULT 1")
        except Exception:
            pass

        # Equipamentos
        c.execute('''
            CREATE TABLE IF NOT EXISTS equipamentos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                nome TEXT NOT NULL,
                local_id INTEGER,
                tag TEXT,
                especificacao TEXT,
                ano_instalacao TEXT,
                quantidade INTEGER,
                FOREIGN KEY (local_id) REFERENCES locais (id)
            )
        ''')

        # Leituras Diárias
        c.execute('''
            CREATE TABLE IF NOT EXISTS leituras (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                datahora TEXT,
                local TEXT,
                equipamento TEXT,
                energia_ativa REAL,
                energia_reativa REAL,
                energia_aparente REAL,
                pot_ativa REAL,
                pot_reativa REAL,
                pot_aparente REAL,
                fp REAL,
                ponta REAL,
                caudal_elevada REAL,
                corrente REAL,
                tensao REAL,
                observacoes TEXT
            )
        ''')

        # Leituras Mensais
        c.execute('''
            CREATE TABLE IF NOT EXISTS leituras_mensais (
                local TEXT, data TEXT, hora TEXT, ativa REAL, reativa REAL, ponta REAL, fp REAL, potc REAL,
                anterior REAL, atual REAL, diferenca REAL, agua REAL, esp REAL, acum REAL, valor REAL,
                mes TEXT, ano INTEGER
            )
        ''')


# Config de Local


        # --- MIGRATION: add pot_instalada if missing ---
        try:
            c.execute("PRAGMA table_info(locais_cfg)")
            cols_cfg = {row[1] for row in c.fetchall()}
            if 'pot_instalada' not in cols_cfg:
                c.execute("ALTER TABLE locais_cfg ADD COLUMN pot_instalada REAL DEFAULT 0.0")
        except Exception:
            pass

        # MOTORES – medições
        c.execute('''
            CREATE TABLE IF NOT EXISTS motor_medicoes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipamento_id INTEGER NOT NULL,
                datahora TEXT NOT NULL,
                tensao_v REAL,
                corrente_a REAL,
                fator_potencia REAL,
                frequencia_hz REAL,
                fases INTEGER DEFAULT 3,
                pot_ativa_kw REAL,
                pot_reativa_kvar REAL,
                pot_aparente_kva REAL,
                eficiencia REAL,
                energia_kwh REAL,
                observacoes TEXT,
                FOREIGN KEY (equipamento_id) REFERENCES equipamentos(id)
            )
        ''')

        # MOTORES – runs
        c.execute('''
            CREATE TABLE IF NOT EXISTS motor_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                equipamento_id INTEGER NOT NULL,
                start_time TEXT NOT NULL,
                stop_time TEXT,
                duracao_min REAL,
                FOREIGN KEY (equipamento_id) REFERENCES equipamentos(id)
            )
        ''')

        # Config por equipamento
        c.execute('''
            CREATE TABLE IF NOT EXISTS equipamentos_cfg (
                equipamento_id INTEGER PRIMARY KEY,
                tensao_nominal REAL,
                corrente_nominal REAL,
                potencia_nominal_kw REAL,
                fp_nominal REAL,
                eficiencia_nominal REAL,
                limite_corrente REAL,
                limite_fp REAL DEFAULT 0.80,
                FOREIGN KEY (equipamento_id) REFERENCES equipamentos(id)
            )
        ''')

        # === Tabela de projetos solares ===
        c.execute('''
            CREATE TABLE IF NOT EXISTS solar_projetos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                criado_em TEXT,
                local_id INTEGER,
                local_nome TEXT,
                periodo TEXT,
                modo TEXT,
                tipo_sistema TEXT,
                daily_kwh REAL,
                total_mes_kwh REAL,
                psh REAL,
                derate REAL,
                panel_wp REAL,
                panel_area REAL,
                n_paineis INTEGER,
                kwp_necessario REAL,
                kwp_real REAL,
                area_total REAL,
                inv_dcac REAL,
                inversor_kw REAL,
                tarifa_kwh REAL,
                economia_mensal REAL,
                autonomy_days REAL,
                battery_dod REAL,
                battery_eff REAL,
                system_voltage REAL,
                battery_module_kwh REAL,
                bateria_kwh_util REAL,
                bateria_kwh_bruta REAL,
                n_modulos_bateria INTEGER,
                mes TEXT,
                ano INTEGER,
                dias_utilizados INTEGER,
                fator_mult REAL,
                resultado_json TEXT,
                params_json TEXT
            )
        ''')
        # Migração (campos novos)
        new_cols = [
            ('capex_kwp', 'REAL'), ('capex_total', 'REAL'), ('opex_pct', 'REAL'),
            ('opex_anual', 'REAL'), ('tarifa_esc', 'REAL'), ('desconto', 'REAL'),
            ('anos_analise', 'INTEGER'), ('payback_anos', 'REAL'), ('npv', 'REAL'),
            ('co2_factor', 'REAL'), ('co2_t_ano', 'REAL'),
            ('producao_anual_kwh', 'REAL'), ('producao_mensal_json', 'TEXT'),
            ('perfil_sazonal_json', 'TEXT')
        ]
        c.execute("PRAGMA table_info('solar_projetos')")
        existing = {row[1] for row in c.fetchall()}
        for col, typ in new_cols:
            if col not in existing:
                c.execute(f"ALTER TABLE solar_projetos ADD COLUMN {col} {typ}")

        conn.commit()
        conn.close()

try:
    _ensure_users_schema()
except Exception:
    pass

init_db()

# === TELEMETRIA AUTOMÁTICA / F650 ===
# O módulo é separado para manter o app.py estável e permitir expansão para
# outros contadores, relés, caudalímetros e sensores.
try:
    from telemetria import register_telemetry
    register_telemetry(app, DB_PATH)
except Exception as _telemetry_error:
    print('Falha ao inicializar módulo de telemetria:', _telemetry_error)

try:
    _ensure_users_schema()
except Exception:
    pass


def _to_float(val, default=0.0):
    try:
        if val is None: 
            return float(default)
        s = str(val).strip().replace(",", ".")
        if s == "": 
            return float(default)
        return float(s)
    except Exception:
        return float(default)
# === UTILITÁRIOS ===


def _apply_pacote2_migrations():
    """Cria/altera colunas e índices do Pacote 2 (sem PMP). Idempotente."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute("PRAGMA table_info(equipamentos)")
            cols = [r[1] for r in c.fetchall()]
            to_add = []
            if "deleted_at" not in cols: to_add.append("ALTER TABLE equipamentos ADD COLUMN deleted_at TEXT")
            if "potencia_kw" not in cols: to_add.append("ALTER TABLE equipamentos ADD COLUMN potencia_kw REAL")
            if "tensao_v" not in cols: to_add.append("ALTER TABLE equipamentos ADD COLUMN tensao_v REAL")
            if "corrente_a" not in cols: to_add.append("ALTER TABLE equipamentos ADD COLUMN corrente_a REAL")
            if "ip_class" not in cols: to_add.append("ALTER TABLE equipamentos ADD COLUMN ip_class TEXT")
            if "peso_kg" not in cols: to_add.append("ALTER TABLE equipamentos ADD COLUMN peso_kg REAL")
            if "garantia_fim" not in cols: to_add.append("ALTER TABLE equipamentos ADD COLUMN garantia_fim TEXT")
            if "fornecedor" not in cols: to_add.append("ALTER TABLE equipamentos ADD COLUMN fornecedor TEXT")
            if "contrato_num" not in cols: to_add.append("ALTER TABLE equipamentos ADD COLUMN contrato_num TEXT")
            for sqlx in to_add:
                c.execute(sqlx)
        except Exception:
            pass

        c.execute('''
            CREATE TABLE IF NOT EXISTS equipamentos_componentes (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              equipamento_id INTEGER NOT NULL,
              nome TEXT NOT NULL,
              fabricante TEXT,
              modelo TEXT,
              qtd INTEGER DEFAULT 1,
              created_at TEXT DEFAULT (datetime('now','localtime')),
              FOREIGN KEY(equipamento_id) REFERENCES equipamentos(id) ON DELETE CASCADE
            )
        ''')

        c.execute('''
            CREATE TABLE IF NOT EXISTS saved_filters (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              user TEXT,
              modulo TEXT,
              nome TEXT,
              query_json TEXT,
              created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        ''')

        try:
            c.execute("CREATE INDEX IF NOT EXISTS idx_equip_local ON equipamentos(local_id)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_equip_categoria ON equipamentos(categoria)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_equip_fabricante ON equipamentos(fabricante)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_equip_modelo ON equipamentos(modelo)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_equip_crit ON equipamentos(criticidade)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_equip_ativo ON equipamentos(ativo)")
            c.execute("CREATE INDEX IF NOT EXISTS idx_equip_deleted ON equipamentos(deleted_at)")
        except Exception:
            pass

        conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

# ==== /MIGRAÇÕES PACOTE 2 ====


