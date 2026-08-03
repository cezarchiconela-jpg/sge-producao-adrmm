# Arquitetura Modular do SGE

## Objetivo

O `app.py` é agora o ponto de composição e arranque da aplicação. As funções
do SGE estão separadas por domínio em `sge_modules/`, mantendo as rotas, os
nomes dos endpoints, os templates e a base de dados existentes.

Esta reorganização é deliberadamente progressiva: o carregador de
compatibilidade mantém as dependências históricas sincronizadas durante o
arranque, enquanto novos desenvolvimentos devem usar serviços explícitos como
`billing.py`, `migrations.py`, `backup_sge.py` e `telemetria.py`.

## Estrutura

| Ficheiro / módulo | Responsabilidade |
| --- | --- |
| `app.py` | Configuração base, composição dos módulos e arranque Flask |
| `sge_loader.py` | Carga ordenada e compatibilidade entre módulos históricos |
| `billing.py` | Motor único de faturação e resolução tarifária |
| `migrations.py` | Migrações canónicas para bases novas e existentes |
| `backup_sge.py` | Criação, retenção e verificação dos backups |
| `telemetria.py` | Telemetria automática, F650, análises e alertas associados |
| `sge_modules/security.py` | Login, perfis, permissões, CSRF e auditoria de pedidos |
| `sge_modules/bootstrap_runtime.py` | Preparação de caminhos, base de dados e migrações de compatibilidade |
| `sge_modules/locations_*` | Cadastro, hierarquia, configuração e tarifas dos locais |
| `sge_modules/dashboard_*` | Indicadores operacionais e dashboard executivo |
| `sge_modules/equipment_*` | Cadastro, ficheiros, fotos, importações e relatórios de equipamentos |
| `sge_modules/daily_readings_*` | Leituras operacionais, filtros, importações e API |
| `sge_modules/monthly_readings_*` | Leituras mensais, faturação, arquivos, PDF, Excel e APIs |
| `sge_modules/motors.py` | Medições, funcionamento e diagnóstico de motores |
| `sge_modules/alerts.py` | Centro de alertas, ações, histórico e relatórios |
| `sge_modules/solar.py` | Dimensionamento, iluminação e portefólio solar |
| `sge_modules/administration.py` | Backups e diagnóstico administrativo |
| `sge_modules/compatibility.py` | Endpoints legados e tratamento de erros |

## Regras para novas melhorias

1. Não acrescentar novas rotas diretamente ao `app.py`.
2. Colocar a alteração no domínio correspondente ou criar um novo módulo.
3. Colocar cálculos reutilizáveis num serviço independente, sem dependência de
   `request`, `session` ou templates.
4. Manter o mesmo endpoint quando uma função existente for reorganizada.
5. Adicionar testes para cálculos, permissões e alterações de base de dados.
6. Executar os testes e a verificação de rotas antes de cada publicação.
7. Não duplicar regras financeiras: todos os cálculos devem usar `billing.py`.

## Validação obrigatória

```bash
python -m compileall -q app.py sge_loader.py sge_modules billing.py migrations.py backup_sge.py telemetria.py
python -m unittest discover -s tests -p "test_*.py" -v
python tests/smoke_routes.py
```

O teste estrutural protege o limite do `app.py` e confirma a existência dos
domínios esperados. O teste de rotas impede endpoints duplicados e verifica as
páginas principais.
