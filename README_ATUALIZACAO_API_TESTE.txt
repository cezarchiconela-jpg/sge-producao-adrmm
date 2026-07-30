SGE - ACTUALIZAÇÃO DO TESTE DE API

Ficheiro a substituir no GitHub:
- telemetria.py (na raiz do repositório)

A alteração acrescenta:
GET /api/v1/telemetria/ping

O endpoint confirma:
- endereço do servidor;
- token do dispositivo;
- cadastro do F650;
- quantidade de canais.

Não grava leituras e não altera o F650.
Depois do commit, aguarde o deploy ficar Live no Render.
