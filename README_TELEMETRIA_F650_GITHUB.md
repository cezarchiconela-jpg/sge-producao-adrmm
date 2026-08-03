# Actualização SGE — Telemetria automática do F650

Esta actualização acrescenta ao SGE uma camada de telemetria automática, mantendo intactos os módulos de leituras manuais, importação Excel, facturação, equipamentos, motores, alertas e energia solar.

## Actualização actual — análise, alertas e relatórios

Esta versão mantém o mesmo endpoint, dispositivo, token e formato JSON já usado
pelo PC ligado ao F650. Basta publicar o projecto no servidor: **não é necessário
alterar nada no PC de aquisição nem no relé**.

Foram acrescentados tratamento dos sinais negativos, energia estimada em kWh,
estatísticas, gráficos por grupo, alertas persistentes, distinção entre corte de
energia e perda de comunicação e relatório PDF profissional. Consulte
`ACTUALIZACAO_TELEMETRIA_ALERTAS_RELATORIOS.md` para os limites e a validação.

## Ficheiros a substituir no GitHub

- `app.py`
- `.env.example`
- `render.yaml`
- `templates/base.html`

## Ficheiros novos

- `telemetria.py`
- `templates/telemetria.html`
- `static/telemetria.css`
- `static/telemetria.js`
- `README_TELEMETRIA_F650_GITHUB.md`

## O que é criado automaticamente na base de dados

No primeiro arranque, o SGE cria tabelas idempotentes:

- `telemetry_devices`
- `telemetry_channels`
- `telemetry_readings`
- `telemetry_ingest_log`
- `telemetry_alert_config`
- `telemetry_alerts`

Também regista automaticamente o dispositivo piloto:

- Local: `ETA DE UMBELUZI`
- Código: `F650_ENTRADA_GERAL_33KV`
- Modelo: `GE Multilin F650`
- Firmware: `5.40`
- Protocolo: `Modbus TCP`
- IP de campo: `169.254.219.155`

Nenhuma tabela existente é apagada ou recriada.

## Configuração obrigatória no Render

No Render, abra o serviço do SGE e adicione uma variável de ambiente:

```text
SGE_F650_API_TOKEN=<token-longo-e-secreto>
```

Gere um token no computador com:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Guarde exactamente o mesmo token no PC de aquisição. Não publique o token no GitHub.

Depois faça o deploy da nova versão. O `render.yaml` também inclui a variável como `sync: false`, mas o valor deve ser introduzido manualmente no Render.

## Endpoint de recepção

```text
POST /api/v1/telemetria
Authorization: Bearer <SGE_F650_API_TOKEN>
Content-Type: application/json
```

Exemplo:

```json
{
  "site": "ETA_UMBELUZI",
  "device": "F650_ENTRADA_GERAL_33KV",
  "timestamp": "2026-07-29T22:10:00+02:00",
  "quality": "good",
  "values": {
    "tensao_ab_kv": 34.62,
    "tensao_bc_kv": 34.58,
    "tensao_ca_kv": 34.65,
    "corrente_fase_a_a": 182.4,
    "potencia_activa_total_mw": 9.43,
    "potencia_reactiva_total_mvar": 3.12,
    "factor_potencia_total": 0.949,
    "frequencia_hz": 50.01
  }
}
```

A API aceita apenas dispositivos e canais cadastrados, valida números e timestamps, evita duplicados e exige token. Ela não possui qualquer função de comando sobre o F650.

## Painel no SGE

Depois do deploy, aceda a:

```text
/telemetria
```

O menu `Operação` passa a mostrar `Telemetria Automática`.

O painel apresenta:

- Estado online, atrasado ou offline;
- Últimas tensões, correntes, potência, factor de potência e frequência;
- Histórico gráfico;
- Alertas de limite informativos;
- Registo das últimas transmissões;
- Exportação CSV.

## Segurança

- A rota de recepção não usa a sessão do navegador, mas exige o token próprio do dispositivo.
- O token é guardado na base apenas como hash.
- A rota aceita somente dados; não envia comandos ao relé.
- O F650 continua isolado da Internet. O PC de aquisição é quem envia dados por HTTPS ao SGE.
- Não crie ponte entre a Ethernet do F650 e a interface Wi-Fi do PC.

## Validação após o deploy

1. Confirmar que o SGE abre normalmente.
2. Abrir `/telemetria`.
3. Confirmar que aparece `F650 – Entrada Geral 33 kV`.
4. Antes da primeira transmissão, o estado esperado é `SEM COMUNICAÇÃO`.
5. Depois de configurar o PC, enviar uma leitura de teste.
6. Confirmar que o estado passa para `ONLINE` e que os valores aparecem no painel.
