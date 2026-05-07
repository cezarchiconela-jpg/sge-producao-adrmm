# Auditoria de Produção do SGE

## Resultado geral
O ZIP foi auditado e preparado para publicação online em ambiente Flask/Gunicorn. Foram corrigidos problemas de rotas duplicadas, falhas em páginas internas, configuração insegura de desenvolvimento, dependências de produção e preparação para base de dados persistente.

## Correcções aplicadas

### 1. Rotas duplicadas
Foram eliminadas duplicações activas no mapa de rotas Flask. Antes da correcção havia duplicação nos seguintes caminhos:

- `/locais`
- `/leituras`
- `/mt/config`
- `/leituras_mensais`

A compatibilidade com endpoints antigos foi mantida através de rotas legadas internas em `/legacy/...`, evitando conflitos sem quebrar links antigos gerados por `url_for()`.

### 2. Segurança para ambiente online
Foram aplicadas as seguintes melhorias:

- Remoção da chave secreta fixa `sge-secret-key`.
- Uso de `SECRET_KEY` ou `FLASK_SECRET_KEY` por variável de ambiente.
- Execução local com `debug` desligado por padrão.
- `app.run()` agora usa `host=0.0.0.0`, `PORT` e `FLASK_DEBUG` via ambiente.
- Limite de upload configurável por `SGE_MAX_UPLOAD_MB`.
- Cookies de sessão com `HttpOnly`, `SameSite=Lax` e opção `Secure` por ambiente.
- Cabeçalhos defensivos: `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` e HSTS opcional.

### 3. Base de dados e persistência
Foi adicionada configuração por ambiente:

- `SGE_DB_PATH`: caminho da base de dados SQLite em produção.
- `SGE_UPLOAD_FOLDER`: caminho persistente dos uploads.

Se a aplicação arrancar num disco persistente vazio e existir `sge.db` no pacote, a base inicial é copiada automaticamente para o caminho definido em `SGE_DB_PATH`.

### 4. Deploy
Foram adicionados ficheiros próprios para deploy:

- `wsgi.py`
- `Procfile`
- `runtime.txt`
- `render.yaml`
- `.env.example`
- `.gitignore`

O arranque recomendado em produção é:

```bash
gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120
```

### 5. Dependências
O ficheiro `requirements.txt` foi actualizado para incluir `gunicorn`, necessário para produção. Também foi harmonizado o ficheiro `requirements-fixed.txt`.

### 6. Falhas internas corrigidas
Durante o smoke test das rotas GET sem parâmetros dinâmicos, foram encontradas e corrigidas falhas em:

- `/equipamentos/filtros`: compatibilização da tabela `saved_filters` quando a base antiga tinha coluna `name` em vez de `nome`.
- `/leituras/list_filters`: mesma compatibilização da tabela `saved_filters`.
- `/leituras/bulk`: template ausente criado como página funcional de edição em lote.
- `/leituras/export_pdf`: correcção de SQL que duplicava a cláusula `FROM leituras`.
- `/leituras_mensal/import_csv`: disponibilização global de `now()` para templates Jinja.

## Testes executados

- Compilação Python de `app.py`: OK.
- Importação da aplicação Flask: OK.
- Auditoria de duplicação no `url_map`: 0 duplicações activas.
- Smoke test de 118 rotas GET sem parâmetros dinâmicos: 0 erros 500.
- Teste manual dos módulos principais:
  - `/`
  - `/dashboard`
  - `/locais`
  - `/equipamentos`
  - `/motores`
  - `/alertas`
  - `/solar`
  - `/leituras_mensal`
  - `/leituras_mensais`
  - `/mt/config`

## Recomendação importante antes de publicar
Para Render, Railway, VPS ou servidor cloud, usar sempre disco persistente para `sge.db` e `uploads`. Em Render, o `render.yaml` já está preparado com disco em `/var/data`.

## Comandos locais de validação

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Para produção local:

```bash
gunicorn wsgi:app --bind 0.0.0.0:5000 --workers 2 --threads 4 --timeout 120
```

No Windows, para testar apenas com Flask, pode usar:

```bash
python app.py
```
