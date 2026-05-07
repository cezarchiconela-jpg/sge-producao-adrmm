# Guia de Publicação Online do SGE — Render

Este pacote está preparado para produção com Flask + Gunicorn.

## Variáveis de ambiente recomendadas

```text
FLASK_DEBUG=0
SECRET_KEY=<gerar uma chave longa e secreta>
SESSION_COOKIE_SECURE=1
SGE_HSTS=1
SGE_REQUIRE_LOGIN=1
SGE_ADMIN_USER=admin
SGE_ADMIN_PASSWORD=<definir palavra-passe forte>
SGE_DB_PATH=/var/data/sge.db
SGE_UPLOAD_FOLDER=/var/data/uploads
SGE_MAX_UPLOAD_MB=25
```

## Disco persistente obrigatório

```text
Mount Path: /var/data
```

Isto evita perda da base de dados e uploads em cada redeploy.

## Build e arranque

```text
Build Command: pip install -r requirements.txt
Start Command: gunicorn wsgi:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120
```

## Verificação pós-deploy

Abra `/healthz`. Resposta esperada:

```json
{"app":"SGE","database":true,"status":"ok"}
```

## Backups

Execute periodicamente:

```bash
python backup_sge.py
```
