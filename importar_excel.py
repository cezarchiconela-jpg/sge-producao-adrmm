import sqlite3
import pandas as pd

# Caminhos dos arquivos
excel_file = 'registo_ativo-CDs e PSAA_ atualizada em 16.12.24.xlsx'
db_file = 'sge.db'

# Ler Excel
df = pd.read_excel(excel_file)

# Conectar ao banco
conn = sqlite3.connect(db_file)
c = conn.cursor()

# 1. Importar LOCAIS (evita duplicados)
locais_excel = df['instalação'].dropna().unique()
locais_existentes = set(row[0] for row in c.execute('SELECT nome FROM locais').fetchall())

for local in locais_excel:
    if local not in locais_existentes:
        c.execute('INSERT INTO locais (nome) VALUES (?)', (local,))
        print(f'Adicionado local: {local}')
conn.commit()

# Função para buscar id do local pelo nome
def get_local_id(nome_local):
    c.execute('SELECT id FROM locais WHERE nome=?', (nome_local,))
    row = c.fetchone()
    return row[0] if row else None

# 2. Importar EQUIPAMENTOS
equip_existentes = set()
for row in c.execute('SELECT nome, local_id FROM equipamentos'):
    equip_existentes.add((row[0], row[1]))

for idx, row in df.iterrows():
    nome_eq = row.get('Nome', '')
    local_nome = row.get('instalação', '')
    tag = row.get('TAG', '')
    especificacao = row.get('Especificação', '')
    ano = str(row.get('Data Instalação', ''))
    quantidade = row.get('Quantidade', 1)
    if not nome_eq or not local_nome:
        continue
    local_id = get_local_id(local_nome)
    if not local_id:
        continue
    if (nome_eq, local_id) not in equip_existentes:
        c.execute('''
            INSERT INTO equipamentos (nome, local_id, tag, especificacao, ano_instalacao, quantidade)
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (nome_eq, local_id, tag, especificacao, ano, quantidade))
        print(f'Adicionado equipamento: {nome_eq} em {local_nome}')

conn.commit()
conn.close()

print('\nImportação concluída!')
