"""Migrações idempotentes e completas para bases novas e existentes do SGE."""
from __future__ import annotations

import sqlite3
from datetime import date


SCHEMA_VERSION = 2026080501


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
    existing = _columns(conn, table)
    for name, declaration in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}")


def _create_core_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            description TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS locais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL UNIQUE,
            fator_potencia REAL,
            potencia_contratada REAL,
            fator_multiplicativo REAL,
            codigo TEXT,
            endereco TEXT,
            contato_nome TEXT,
            contato_tel TEXT,
            notas TEXT,
            ativo INTEGER DEFAULT 1,
            potencia_contratada_kva REAL DEFAULT 0,
            potencia_instalada_kw REAL DEFAULT 0,
            tipo_local TEXT,
            categoria_operacional TEXT,
            email TEXT,
            responsavel_alt TEXT,
            estado_tecnico TEXT DEFAULT 'Normal',
            prioridade TEXT DEFAULT 'Média',
            parent_id INTEGER,
            FOREIGN KEY(parent_id) REFERENCES locais(id)
        );
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
            pot_instalada REAL DEFAULT 0.0,
            FOREIGN KEY(local_id) REFERENCES locais(id)
        );
        CREATE TABLE IF NOT EXISTS equipamentos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT NOT NULL,
            local_id INTEGER,
            tag TEXT,
            especificacao TEXT,
            ano_instalacao TEXT,
            quantidade INTEGER,
            ativo INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT,
            categoria TEXT,
            fabricante TEXT,
            modelo TEXT,
            numero_serie TEXT,
            custo_aquisicao REAL,
            vida_util_anos INTEGER,
            criticidade TEXT,
            cover_photo_id INTEGER,
            deleted_at TEXT,
            potencia_kw REAL,
            tensao_v REAL,
            corrente_a REAL,
            ip_class TEXT,
            peso_kg REAL,
            garantia_fim TEXT,
            fornecedor TEXT,
            contrato_num TEXT,
            FOREIGN KEY(local_id) REFERENCES locais(id)
        );
        CREATE TABLE IF NOT EXISTS leituras (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            datahora TEXT, local TEXT, equipamento TEXT,
            energia_ativa REAL, energia_reativa REAL, energia_aparente REAL,
            pot_ativa REAL, pot_reativa REAL, pot_aparente REAL,
            fp REAL, ponta REAL, caudal_elevada REAL, corrente REAL, tensao REAL,
            observacoes TEXT
        );
        CREATE TABLE IF NOT EXISTS leituras_mensais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            local TEXT, data TEXT, hora TEXT, ativa REAL, reativa REAL, ponta REAL,
            fp REAL, potc REAL, anterior REAL, atual REAL, diferenca REAL,
            agua REAL, esp REAL, acum REAL, valor REAL, mes TEXT, ano INTEGER
        );
        CREATE TABLE IF NOT EXISTS motor_medicoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipamento_id INTEGER NOT NULL,
            datahora TEXT NOT NULL,
            tensao_v REAL, corrente_a REAL, fator_potencia REAL, frequencia_hz REAL,
            fases INTEGER DEFAULT 3, pot_ativa_kw REAL, pot_reativa_kvar REAL,
            pot_aparente_kva REAL, eficiencia REAL, energia_kwh REAL, observacoes TEXT,
            FOREIGN KEY(equipamento_id) REFERENCES equipamentos(id)
        );
        CREATE TABLE IF NOT EXISTS motor_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            equipamento_id INTEGER NOT NULL,
            start_time TEXT NOT NULL, stop_time TEXT, duracao_min REAL,
            FOREIGN KEY(equipamento_id) REFERENCES equipamentos(id)
        );
        CREATE TABLE IF NOT EXISTS equipamentos_cfg (
            equipamento_id INTEGER PRIMARY KEY,
            tensao_nominal REAL, corrente_nominal REAL, potencia_nominal_kw REAL,
            fp_nominal REAL, eficiencia_nominal REAL, limite_corrente REAL,
            limite_fp REAL DEFAULT 0.80,
            FOREIGN KEY(equipamento_id) REFERENCES equipamentos(id)
        );
        CREATE TABLE IF NOT EXISTS solar_projetos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT, criado_em TEXT, nome_projeto TEXT, local_id INTEGER,
            local_nome TEXT, periodo TEXT, modo TEXT, tipo_sistema TEXT,
            daily_kwh REAL, total_mes_kwh REAL, psh REAL, derate REAL,
            panel_wp REAL, panel_area REAL, n_paineis INTEGER,
            kwp_necessario REAL, kwp_real REAL, area_total REAL,
            inv_dcac REAL, inversor_kw REAL, tarifa_kwh REAL, economia_mensal REAL,
            autonomy_days REAL, battery_dod REAL, battery_eff REAL,
            system_voltage REAL, battery_module_kwh REAL, bateria_kwh_util REAL,
            bateria_kwh_bruta REAL, n_modulos_bateria INTEGER,
            mes TEXT, ano INTEGER, dias_utilizados INTEGER, fator_mult REAL,
            resultado_json TEXT, params_json TEXT, raw_json TEXT,
            capex_kwp REAL, capex_total REAL, opex_pct REAL, opex_anual REAL,
            tarifa_esc REAL, desconto REAL, anos_analise INTEGER, payback_anos REAL,
            npv REAL, co2_factor REAL, co2_t_ano REAL, producao_anual_kwh REAL,
            producao_mensal_json TEXT, perfil_sazonal_json TEXT, obs TEXT
        );
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL,
            full_name TEXT, role TEXT NOT NULL DEFAULT 'consulta', email TEXT,
            ativo INTEGER NOT NULL DEFAULT 1, must_change_password INTEGER NOT NULL DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now','localtime')), updated_at TEXT, last_login TEXT
        );
        CREATE TABLE IF NOT EXISTS tarifas_historico (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            local_id INTEGER NOT NULL,
            valid_from TEXT NOT NULL,
            valid_to TEXT,
            tarifa_ativa REAL NOT NULL,
            tarifa_reativa REAL NOT NULL,
            tarifa_ponta REAL NOT NULL,
            tarifa_perdas REAL NOT NULL DEFAULT 0,
            taxa_fixa REAL NOT NULL DEFAULT 0,
            taxa_radio REAL NOT NULL DEFAULT 0,
            taxa_lixo REAL NOT NULL DEFAULT 0,
            pot_contratada REAL NOT NULL DEFAULT 0,
            iva_rate REAL NOT NULL DEFAULT 16.0 CHECK(iva_rate=16.0),
            iva_base_factor REAL NOT NULL DEFAULT 0.62 CHECK(iva_base_factor=0.62),
            created_by TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            notes TEXT,
            UNIQUE(local_id, valid_from),
            FOREIGN KEY(local_id) REFERENCES locais(id)
        );
        CREATE TABLE IF NOT EXISTS security_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            request_id TEXT, actor TEXT, role TEXT, method TEXT NOT NULL,
            endpoint TEXT, path TEXT NOT NULL, status_code INTEGER,
            remote_ip TEXT, outcome TEXT
        );
        CREATE TABLE IF NOT EXISTS backup_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            filename TEXT NOT NULL, sha256 TEXT, size_bytes INTEGER,
            verified INTEGER NOT NULL DEFAULT 0, reason TEXT, actor TEXT
        );
        CREATE TABLE IF NOT EXISTS equipamentos_photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT, equipamento_id INTEGER,
            filename TEXT, thumb_filename TEXT, caption TEXT, width INTEGER,
            height INTEGER, uploaded_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS equipamentos_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT, equipamento_id INTEGER,
            filename TEXT, original_name TEXT, mime TEXT, size INTEGER,
            uploaded_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS equipamentos_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT, equipamento_id INTEGER,
            url TEXT, title TEXT, added_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS equipamentos_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, equipamento_id INTEGER,
            acao TEXT, detalhes TEXT, actor TEXT,
            ts TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS locais_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT, local_id INTEGER NOT NULL,
            evento TEXT NOT NULL, detalhe TEXT, actor TEXT DEFAULT 'sge',
            ts TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS leituras_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, leitura_id INTEGER, acao TEXT,
            field TEXT, old_value TEXT, new_value TEXT, actor TEXT,
            ts TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS leituras_mensais_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT, lm_id INTEGER, local TEXT,
            data TEXT, mes TEXT, ano INTEGER, acao TEXT, field TEXT,
            old_value TEXT, new_value TEXT, actor TEXT,
            ts TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS validacoes_locais (
            local TEXT PRIMARY KEY, fp_min REAL DEFAULT 0.85,
            kwh_dia_max REAL, permitir_regressivo INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS saved_filters (
            id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT, modulo TEXT,
            name TEXT, nome TEXT, query_json TEXT,
            created_at TEXT DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS equipamentos_componentes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, equipamento_id INTEGER NOT NULL,
            nome TEXT NOT NULL, fabricante TEXT, modelo TEXT, qtd INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(equipamento_id) REFERENCES equipamentos(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS faturas_mensais_arquivo (
            id INTEGER PRIMARY KEY AUTOINCREMENT, local TEXT NOT NULL,
            mes TEXT NOT NULL, ano INTEGER NOT NULL, periodo TEXT,
            total REAL DEFAULT 0, subtotal REAL DEFAULT 0, kwh_ativa REAL DEFAULT 0,
            kvarh_excedente REAL DEFAULT 0, demanda_ponta_kw REAL DEFAULT 0,
            agua_total REAL DEFAULT 0, consumo_especifico REAL, snapshot_json TEXT,
            criado_em TEXT DEFAULT (datetime('now','localtime')),
            atualizado_em TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(local, mes, ano)
        );
        CREATE TABLE IF NOT EXISTS leituras_mensais_status (
            id INTEGER PRIMARY KEY AUTOINCREMENT, local TEXT NOT NULL,
            mes TEXT NOT NULL, ano INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'aberto',
            fechado_em TEXT, fechado_por TEXT, reaberto_em TEXT, reaberto_por TEXT,
            observacao TEXT, atualizado_em TEXT DEFAULT (datetime('now','localtime')),
            UNIQUE(local, mes, ano)
        );
        CREATE TABLE IF NOT EXISTS alertas_acoes (
            alerta_id TEXT PRIMARY KEY, estado TEXT DEFAULT 'Novo', responsavel TEXT,
            observacao TEXT, atualizado_em TEXT DEFAULT (datetime('now','localtime')),
            prazo TEXT, acao_tomada TEXT, fechado_em TEXT, prioridade_manual TEXT,
            evidencia TEXT, custo_estimado REAL DEFAULT 0, snapshot_nivel TEXT,
            snapshot_origem TEXT, snapshot_categoria TEXT, snapshot_local TEXT,
            snapshot_equipamento TEXT, snapshot_tipo TEXT, snapshot_causa TEXT,
            snapshot_impacto TEXT, snapshot_acao TEXT, snapshot_ultima TEXT,
            snapshot_link TEXT, manual INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS mt_config (
            id INTEGER PRIMARY KEY CHECK (id=1),
            alfa_reativa REAL DEFAULT 0.75,
            iva_taxa REAL DEFAULT 0.16,
            iva_base REAL DEFAULT 0.62,
            tarifa_ativa REAL DEFAULT 4.780,
            tarifa_reativa REAL DEFAULT 1.430,
            tarifa_potencia REAL DEFAULT 497.03
        );
        INSERT OR IGNORE INTO mt_config(id) VALUES(1);
        CREATE TABLE IF NOT EXISTS mt_leituras_raw (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            local_id INTEGER NOT NULL, data TEXT NOT NULL, hora TEXT NOT NULL,
            ea_leitura REAL NOT NULL, er_leitura REAL NOT NULL,
            demanda_lida REAL NOT NULL, obs TEXT,
            UNIQUE(local_id, data, hora),
            FOREIGN KEY(local_id) REFERENCES locais(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS eficiencia_baselines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            local_id INTEGER NOT NULL,
            nome TEXT NOT NULL,
            periodo_inicio TEXT NOT NULL,
            periodo_fim TEXT NOT NULL,
            metodo TEXT NOT NULL DEFAULT 'normalizacao_por_volume',
            cobertura_minima_pct REAL NOT NULL DEFAULT 80.0,
            meses_elegiveis INTEGER NOT NULL DEFAULT 0,
            energia_total_kwh REAL NOT NULL DEFAULT 0,
            agua_total_m3 REAL NOT NULL DEFAULT 0,
            custo_total_mzn REAL NOT NULL DEFAULT 0,
            energia_media_mensal_kwh REAL NOT NULL DEFAULT 0,
            agua_media_mensal_m3 REAL NOT NULL DEFAULT 0,
            custo_medio_mensal_mzn REAL NOT NULL DEFAULT 0,
            consumo_especifico_kwh_m3 REAL NOT NULL DEFAULT 0,
            custo_especifico_mzn_m3 REAL NOT NULL DEFAULT 0,
            meses_json TEXT NOT NULL DEFAULT '[]',
            estado TEXT NOT NULL DEFAULT 'rascunho',
            observacoes TEXT,
            criado_por TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            aprovado_por TEXT,
            aprovado_em TEXT,
            arquivado_em TEXT,
            FOREIGN KEY(local_id) REFERENCES locais(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS eficiencia_metas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            local_id INTEGER NOT NULL,
            ano INTEGER NOT NULL,
            baseline_id INTEGER,
            reducao_percentual REAL NOT NULL DEFAULT 0,
            meta_kwh_m3 REAL,
            meta_mzn_m3 REAL,
            observacoes TEXT,
            criado_por TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            atualizado_em TEXT,
            UNIQUE(local_id, ano),
            FOREIGN KEY(local_id) REFERENCES locais(id) ON DELETE CASCADE,
            FOREIGN KEY(baseline_id) REFERENCES eficiencia_baselines(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS eficiencia_medidas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            local_id INTEGER NOT NULL,
            titulo TEXT NOT NULL,
            categoria TEXT NOT NULL DEFAULT 'Operacional',
            descricao TEXT,
            responsavel TEXT,
            estado TEXT NOT NULL DEFAULT 'Planeada',
            prioridade TEXT NOT NULL DEFAULT 'Média',
            data_inicio TEXT,
            data_conclusao_prevista TEXT,
            data_implementacao TEXT,
            investimento_mzn REAL NOT NULL DEFAULT 0,
            poupanca_prevista_kwh_ano REAL NOT NULL DEFAULT 0,
            poupanca_prevista_mzn_ano REAL NOT NULL DEFAULT 0,
            poupanca_verificada_kwh REAL,
            poupanca_verificada_mzn REAL,
            baseline_id INTEGER,
            observacoes TEXT,
            criado_por TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            atualizado_por TEXT,
            atualizado_em TEXT,
            FOREIGN KEY(local_id) REFERENCES locais(id) ON DELETE CASCADE,
            FOREIGN KEY(baseline_id) REFERENCES eficiencia_baselines(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS eficiencia_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entidade TEXT NOT NULL,
            entidade_id INTEGER,
            acao TEXT NOT NULL,
            detalhe TEXT,
            actor TEXT,
            ts TEXT NOT NULL DEFAULT (datetime('now','localtime'))
        );

        CREATE TABLE IF NOT EXISTS operacional_importacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT, lote_uid TEXT NOT NULL UNIQUE,
            ficheiro_nome TEXT NOT NULL, ficheiro_hash TEXT NOT NULL, formato TEXT NOT NULL,
            periodo TEXT, estado TEXT NOT NULL DEFAULT 'previsualizacao',
            total_linhas INTEGER NOT NULL DEFAULT 0, linhas_importadas INTEGER NOT NULL DEFAULT 0,
            linhas_rejeitadas INTEGER NOT NULL DEFAULT 0, criado_por TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            confirmado_por TEXT, confirmado_em TEXT
        );
        CREATE TABLE IF NOT EXISTS operacional_importacao_linhas (
            id INTEGER PRIMARY KEY AUTOINCREMENT, lote_id INTEGER NOT NULL,
            linha_origem INTEGER, folha_origem TEXT, local_origem TEXT NOT NULL,
            local_id INTEGER, data TEXT NOT NULL, energia_kwh REAL, volume_m3 REAL,
            horas_operacao REAL, tipo_dado TEXT NOT NULL DEFAULT 'medido',
            qualidade TEXT NOT NULL DEFAULT 'provisoria', estado TEXT NOT NULL DEFAULT 'pendente',
            avisos TEXT, payload_json TEXT,
            FOREIGN KEY(lote_id) REFERENCES operacional_importacoes(id) ON DELETE CASCADE,
            FOREIGN KEY(local_id) REFERENCES locais(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS operacional_dados (
            id INTEGER PRIMARY KEY AUTOINCREMENT, local_id INTEGER NOT NULL, data TEXT NOT NULL,
            periodo_tipo TEXT NOT NULL DEFAULT 'dia', energia_kwh REAL,
            volume_captado_m3 REAL, volume_produzido_m3 REAL, volume_distribuido_m3 REAL,
            horas_operacao REAL, cortes_programados_min REAL, cortes_nao_programados_min REAL,
            fonte TEXT NOT NULL, tipo_dado TEXT NOT NULL DEFAULT 'medido',
            estado TEXT NOT NULL DEFAULT 'validado', cobertura_pct REAL NOT NULL DEFAULT 100,
            lote_id INTEGER, ficheiro_origem TEXT, observacoes TEXT, criado_por TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')), atualizado_em TEXT,
            FOREIGN KEY(local_id) REFERENCES locais(id) ON DELETE CASCADE,
            FOREIGN KEY(lote_id) REFERENCES operacional_importacoes(id) ON DELETE SET NULL,
            UNIQUE(local_id, data, periodo_tipo, fonte)
        );
        CREATE TABLE IF NOT EXISTS operacional_ocorrencias (
            id INTEGER PRIMARY KEY AUTOINCREMENT, data TEXT NOT NULL, local_id INTEGER,
            descricao TEXT NOT NULL, categoria TEXT NOT NULL DEFAULT 'Operacional',
            fonte TEXT NOT NULL DEFAULT 'PIGI', lote_id INTEGER,
            estado TEXT NOT NULL DEFAULT 'validada', criado_por TEXT,
            criado_em TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(local_id) REFERENCES locais(id) ON DELETE SET NULL,
            FOREIGN KEY(lote_id) REFERENCES operacional_importacoes(id) ON DELETE SET NULL,
            UNIQUE(data, descricao, fonte)
        );
        """
    )


def _upgrade_existing_tables(conn: sqlite3.Connection) -> None:
    _ensure_columns(conn, "locais", {
        "fator_potencia": "REAL", "potencia_contratada": "REAL",
        "fator_multiplicativo": "REAL", "codigo": "TEXT", "endereco": "TEXT",
        "contato_nome": "TEXT", "contato_tel": "TEXT", "notas": "TEXT",
        "ativo": "INTEGER DEFAULT 1", "potencia_contratada_kva": "REAL DEFAULT 0",
        "potencia_instalada_kw": "REAL DEFAULT 0", "tipo_local": "TEXT",
        "categoria_operacional": "TEXT", "email": "TEXT", "responsavel_alt": "TEXT",
        "estado_tecnico": "TEXT DEFAULT 'Normal'", "prioridade": "TEXT DEFAULT 'Média'",
        "parent_id": "INTEGER",
    })
    _ensure_columns(conn, "locais_cfg", {
        "fator_mult": "REAL DEFAULT 1.0", "pot_contratada": "REAL DEFAULT 0.0",
        "tarifa_ativa": "REAL DEFAULT 4.780", "tarifa_reativa": "REAL DEFAULT 1.430",
        "tarifa_ponta": "REAL DEFAULT 497.03", "tarifa_perdas": "REAL DEFAULT 4.780",
        "taxa_fixa": "REAL DEFAULT 207.28", "taxa_radio": "REAL DEFAULT 297.00",
        "taxa_lixo": "REAL DEFAULT 150.00", "iva": "REAL DEFAULT 16.0",
        "pot_instalada": "REAL DEFAULT 0.0",
    })
    _ensure_columns(conn, "equipamentos_audit", {"actor": "TEXT"})
    # Bases antigas possuem leituras_mensais sem id; as funções atuais toleram isso.
    for table, columns in {
        "equipamentos": {
            "ativo": "INTEGER DEFAULT 1", "created_at": "TEXT", "updated_at": "TEXT",
            "categoria": "TEXT", "fabricante": "TEXT", "modelo": "TEXT",
            "numero_serie": "TEXT", "custo_aquisicao": "REAL", "vida_util_anos": "INTEGER",
            "criticidade": "TEXT", "cover_photo_id": "INTEGER", "deleted_at": "TEXT",
            "potencia_kw": "REAL", "tensao_v": "REAL", "corrente_a": "REAL",
            "ip_class": "TEXT", "peso_kg": "REAL", "garantia_fim": "TEXT",
            "fornecedor": "TEXT", "contrato_num": "TEXT",
        },
        "leituras": {
            "datahora": "TEXT", "local": "TEXT", "equipamento": "TEXT",
            "energia_ativa": "REAL", "energia_reativa": "REAL", "energia_aparente": "REAL",
            "pot_ativa": "REAL", "pot_reativa": "REAL", "pot_aparente": "REAL",
            "fp": "REAL", "ponta": "REAL", "caudal_elevada": "REAL",
            "corrente": "REAL", "tensao": "REAL", "observacoes": "TEXT",
        },
        "leituras_mensais": {
            "local": "TEXT", "data": "TEXT", "hora": "TEXT", "ativa": "REAL",
            "reativa": "REAL", "ponta": "REAL", "fp": "REAL", "potc": "REAL",
            "anterior": "REAL", "atual": "REAL", "diferenca": "REAL", "agua": "REAL",
            "esp": "REAL", "acum": "REAL", "valor": "REAL", "mes": "TEXT", "ano": "INTEGER",
        },
        "users": {
            "full_name": "TEXT", "role": "TEXT NOT NULL DEFAULT 'consulta'", "email": "TEXT",
            "ativo": "INTEGER NOT NULL DEFAULT 1", "must_change_password": "INTEGER NOT NULL DEFAULT 0",
            "created_at": "TEXT", "updated_at": "TEXT", "last_login": "TEXT",
        },
        "solar_projetos": {
            "created_at": "TEXT", "criado_em": "TEXT", "nome_projeto": "TEXT",
            "local_id": "INTEGER", "resultado_json": "TEXT", "params_json": "TEXT",
            "raw_json": "TEXT", "capex_kwp": "REAL", "capex_total": "REAL",
            "opex_pct": "REAL", "opex_anual": "REAL", "tarifa_esc": "REAL",
            "desconto": "REAL", "anos_analise": "INTEGER", "payback_anos": "REAL",
            "npv": "REAL", "co2_factor": "REAL", "co2_t_ano": "REAL",
            "producao_anual_kwh": "REAL", "producao_mensal_json": "TEXT",
            "perfil_sazonal_json": "TEXT", "obs": "TEXT",
        },
        "saved_filters": {"name": "TEXT", "nome": "TEXT"},
        "leituras_mensais_audit": {
            "lm_id": "INTEGER", "local": "TEXT", "data": "TEXT", "mes": "TEXT",
            "ano": "INTEGER", "acao": "TEXT", "field": "TEXT", "old_value": "TEXT",
            "new_value": "TEXT", "actor": "TEXT",
        },
    }.items():
        _ensure_columns(conn, table, columns)


def _apply_business_corrections(conn: sqlite3.Connection) -> None:
    marker = 2026080301
    if conn.execute("SELECT 1 FROM schema_migrations WHERE version=?", (marker,)).fetchone():
        return
    conn.execute("UPDATE locais_cfg SET iva=16.0")
    umbeluzi_ids = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM locais WHERE lower(nome) LIKE '%umbeluzi%'"
        ).fetchall()
    ]
    for local_id in umbeluzi_ids:
        conn.execute("INSERT OR IGNORE INTO locais_cfg(local_id) VALUES(?)", (local_id,))
        conn.execute(
            "UPDATE locais_cfg SET tarifa_ponta=497.03, iva=16.0 WHERE local_id=?",
            (local_id,),
        )
    try:
        conn.execute("UPDATE mt_config SET alfa_reativa=0.75, tarifa_potencia=497.03, iva_taxa=0.16, iva_base=0.62 WHERE id=1")
    except sqlite3.Error:
        pass
    conn.execute(
        "INSERT INTO schema_migrations(version, description) VALUES(?,?)",
        (marker, "Tarifa de ponta da ETA Umbeluzi = 497,03 e IVA 16% sobre 62%"),
    )


def _seed_tariff_history(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT l.id, l.nome, COALESCE(c.tarifa_ativa,4.780),
               COALESCE(c.tarifa_reativa,1.430),
               CASE WHEN lower(l.nome) LIKE '%umbeluzi%' THEN 497.03
                    ELSE COALESCE(c.tarifa_ponta,497.03) END,
               COALESCE(c.tarifa_perdas,4.780), COALESCE(c.taxa_fixa,207.28),
               COALESCE(c.taxa_radio,297.00), COALESCE(c.taxa_lixo,150.00),
               COALESCE(c.pot_contratada,0)
        FROM locais l LEFT JOIN locais_cfg c ON c.local_id=l.id
        """
    ).fetchall()
    for row in rows:
        if conn.execute("SELECT 1 FROM tarifas_historico WHERE local_id=? LIMIT 1", (row[0],)).fetchone():
            continue
        conn.execute(
            """
            INSERT INTO tarifas_historico(
                local_id, valid_from, tarifa_ativa, tarifa_reativa, tarifa_ponta,
                tarifa_perdas, taxa_fixa, taxa_radio, taxa_lixo, pot_contratada,
                created_by, notes
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (row[0], "2000-01-01", *row[2:], "migração_sge", "Configuração existente preservada como histórico inicial"),
        )


def _create_indexes(conn: sqlite3.Connection) -> None:
    statements = (
        "CREATE INDEX IF NOT EXISTS idx_locais_parent_id ON locais(parent_id)",
        "CREATE INDEX IF NOT EXISTS idx_equip_local ON equipamentos(local_id)",
        "CREATE INDEX IF NOT EXISTS idx_equip_ativo ON equipamentos(ativo)",
        "CREATE INDEX IF NOT EXISTS idx_equip_deleted ON equipamentos(deleted_at)",
        "CREATE INDEX IF NOT EXISTS idx_leituras_local_datahora ON leituras(local, datahora)",
        "CREATE INDEX IF NOT EXISTS idx_leituras_mensais_periodo ON leituras_mensais(local, mes, ano, data)",
        "CREATE INDEX IF NOT EXISTS idx_tarifas_historico_periodo ON tarifas_historico(local_id, valid_from, valid_to)",
        "CREATE INDEX IF NOT EXISTS idx_security_audit_time ON security_audit(occurred_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_users_role ON users(role)",
        "CREATE INDEX IF NOT EXISTS idx_users_ativo ON users(ativo)",
        "CREATE INDEX IF NOT EXISTS idx_eficiencia_baselines_local_estado ON eficiencia_baselines(local_id, estado, aprovado_em DESC)",
        "CREATE INDEX IF NOT EXISTS idx_eficiencia_metas_local_ano ON eficiencia_metas(local_id, ano)",
        "CREATE INDEX IF NOT EXISTS idx_eficiencia_medidas_local_estado ON eficiencia_medidas(local_id, estado, prioridade)",
        "CREATE INDEX IF NOT EXISTS idx_eficiencia_audit_time ON eficiencia_audit(ts DESC)",
        "CREATE INDEX IF NOT EXISTS idx_operacional_local_data ON operacional_dados(local_id,data,estado)",
        "CREATE INDEX IF NOT EXISTS idx_operacional_lote ON operacional_dados(lote_id)",
        "CREATE INDEX IF NOT EXISTS idx_operacional_preview_lote ON operacional_importacao_linhas(lote_id,estado)",
        "CREATE INDEX IF NOT EXISTS idx_operacional_ocorrencias_data ON operacional_ocorrencias(data,local_id)",
    )
    for statement in statements:
        conn.execute(statement)


def run_migrations(db_path: str) -> int:
    """Cria uma base completa e atualiza dados existentes de forma idempotente."""
    conn = sqlite3.connect(db_path, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        _create_core_schema(conn)
        conn.commit()
        conn.execute("BEGIN IMMEDIATE")
        _upgrade_existing_tables(conn)
        _apply_business_corrections(conn)
        _seed_tariff_history(conn)
        _create_indexes(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version, description) VALUES(?,?)",
            (SCHEMA_VERSION, "Integração PIGI e dados operacionais de água e energia"),
        )
        conn.commit()
        return SCHEMA_VERSION
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
