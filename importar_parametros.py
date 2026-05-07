import sqlite3
import pandas as pd

EXCEL_ARQUIVO = "parametros_locais.xlsx"  # <=== renomeie para o seu arquivo
DB = "sge.db"

# mapeamento de possíveis nomes de colunas
CAND_LOCAL = ["instalação", "Instalação", "Local", "local", "Instalacao"]
CAND_FATOR = ["FATOR_MULTIPLICATIVO", "Fator", "fator", "Coeficiente", "coeficiente"]
CAND_CONTR = ["POT_CONTRATADA", "Potência Contratada", "pot_contratada", "Potencia Contratada"]

def achar_coluna(cols, candidatos):
    s = set(cols)
    for c in candidatos:
        if c in s:
            return c
    return None

def ensure_tabelas():
    con = sqlite3.connect(DB); c = con.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS locais (id INTEGER PRIMARY KEY AUTOINCREMENT, nome TEXT UNIQUE)")
    c.execute("""
        CREATE TABLE IF NOT EXISTS locais_cfg (
            local_id INTEGER PRIMARY KEY,
            fator_mult REAL DEFAULT 1.0,
            pot_contratada REAL DEFAULT 0.0,
            tarifa_ativa REAL DEFAULT 4.780,
            tarifa_reativa REAL DEFAULT 1.430,
            tarifa_ponta REAL DEFAULT 4.970,
            tarifa_perdas REAL DEFAULT 4.780,
            taxa_fixa REAL DEFAULT 207.28,
            taxa_radio REAL DEFAULT 297.00,
            taxa_lixo REAL DEFAULT 150.00,
            iva REAL DEFAULT 16.0,
            FOREIGN KEY (local_id) REFERENCES locais(id)
        )
    """)
    con.commit(); con.close()

def get_local_id(con, nome):
    c = con.cursor()
    c.execute("SELECT id FROM locais WHERE nome=?", (nome,))
    r = c.fetchone()
    if r: return r[0]
    c.execute("INSERT OR IGNORE INTO locais (nome) VALUES (?)", (nome,))
    con.commit()
    c.execute("SELECT id FROM locais WHERE nome=?", (nome,))
    return c.fetchone()[0]

def ensure_cfg(con, local_id):
    c = con.cursor()
    c.execute("SELECT 1 FROM locais_cfg WHERE local_id=?", (local_id,))
    if not c.fetchone():
        c.execute("INSERT INTO locais_cfg (local_id) VALUES (?)", (local_id,))
        con.commit()

def main():
    ensure_tabelas()
    df = pd.read_excel(EXCEL_ARQUIVO)
    cols = list(df.columns)

    col_local = achar_coluna(cols, CAND_LOCAL)
    col_fator = achar_coluna(cols, CAND_FATOR)
    col_contr = achar_coluna(cols, CAND_CONTR)

    if not col_local:
        raise RuntimeError("Coluna de local não encontrada no Excel.")
    # fator/contratada podem faltar; se faltarem, assume defaults

    con = sqlite3.connect(DB)
    add, upd = 0, 0
    for _, row in df.iterrows():
        nome = str(row[col_local]).strip() if pd.notna(row[col_local]) else ""
        if not nome: continue

        fator = float(row[col_fator]) if (col_fator and pd.notna(row[col_fator])) else None
        contrat = float(row[col_contr]) if (col_contr and pd.notna(row[col_contr])) else None

        lid = get_local_id(con, nome)
        ensure_cfg(con, lid)

        c = con.cursor()
        # pega valores atuais para não sobrescrever o que não veio
        c.execute("""SELECT fator_mult, pot_contratada FROM locais_cfg WHERE local_id=?""", (lid,))
        cur = c.fetchone() or (1.0, 0.0)
        new_fator = fator if fator is not None else cur[0]
        new_contr = contrat if contrat is not None else cur[1]
        c.execute("""UPDATE locais_cfg SET fator_mult=?, pot_contratada=? WHERE local_id=?""",
                  (new_fator, new_contr, lid))
        con.commit()
        upd += 1

    con.close()
    print(f"Parâmetros importados/atualizados: {upd}")

if __name__ == "__main__":
    main()
