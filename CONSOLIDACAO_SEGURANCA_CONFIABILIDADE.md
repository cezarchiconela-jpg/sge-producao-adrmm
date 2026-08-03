# Consolidação, Segurança e Confiabilidade do SGE

Pacote de consolidação preparado para o SGE da Águas e Saneamento de Maputo.
É cumulativo: também preserva nos ficheiros necessários a identidade institucional e o logotipo já aprovados, podendo ser aplicado diretamente sobre o ZIP original analisado.

## Regras definitivas de faturação

- Tarifa de ponta da ETA Umbeluzi: **497,03 MZN/kW**.
- Energia reativa faturável: apenas o excedente acima de 75% da energia ativa.
- Ponta faturável: 20% da potência contratada + 80% da ponta medida.
- IVA: **16% aplicado a 62% do subtotal**, em todas as páginas, APIs, relatórios e estimativas da telemetria.
- Todas as rotas de faturação usam `billing.py`. Valores de IVA enviados pelo navegador são ignorados.
- As tarifas passam a ter vigência histórica por local; uma fatura antiga usa o tarifário válido no seu período.

## Segurança e permissões

| Perfil | Escrita permitida |
|---|---|
| Administrador | Todas as áreas, utilizadores, backups e configurações |
| Gestor / Supervisor | Locais, configurações, equipamentos, leituras, alertas, motores, solar e telemetria |
| Técnico Operacional | Equipamentos, leituras/monitoria, alertas, motores e solar |
| Operador de Leituras | Leituras e monitoria |
| Consulta / Visualizador | Nenhuma alteração; apenas consulta, relatórios e simulações |

Controlos aplicados:

- Operações que alteram dados usam POST/PUT/PATCH/DELETE; já não são executadas por links GET.
- Proteção CSRF central em formulários e pedidos JavaScript.
- Verificação de permissão no servidor, independentemente do que o menu apresenta.
- Configurações sensíveis restritas aos perfis autorizados.
- Uploads exigem sessão autenticada.
- Bloqueio temporário após cinco tentativas de login falhadas em quinze minutos.
- Sessão com cookie `HttpOnly`, `SameSite`, validade configurável e cabeçalhos defensivos.
- Auditoria de alterações e tentativas recusadas, com utilizador, perfil, rota, IP, estado e request ID.

## Migrações, backups e recuperação

- `migrations.py` cria todas as tabelas essenciais numa base vazia e atualiza bases antigas de forma idempotente.
- No primeiro arranque, corrige a ETA Umbeluzi para 497,03 e cria o histórico tarifário inicial.
- Antes da migração, o arranque cria uma cópia diária da base existente.
- O backup usa a API online do SQLite, inclui uploads, manifesto e SHA-256 e executa `PRAGMA integrity_check`.
- A retenção padrão é de 30 dias/30 cópias. `SGE_BACKUP_MIRROR_DIR` permite uma segunda localização persistente.
- A área **Administração → Backups** permite criar, verificar e descarregar cópias.

## Telemetria

- O F650 fica registado com o IP informativo correto: `169.254.219.155`.
- O painel **Telemetria → Dispositivos** permite associar vários medidores a locais, definir limites de comunicação e gerar tokens individuais.
- O F650 continua exclusivamente em leitura; o SGE não envia comandos ao relé.

## Instalação

1. Fazer um backup do projeto e da base atual.
2. Extrair o ZIP na raiz do projeto e substituir os ficheiros existentes.
3. Confirmar as variáveis do `.env.example`, sobretudo `SECRET_KEY`, `SGE_ADMIN_PASSWORD` e caminhos persistentes.
4. Reiniciar o serviço. A migração e o backup pré-migração são automáticos.
5. Entrar como administrador, abrir **Backups**, verificar a cópia e confirmar a tarifa na configuração da ETA Umbeluzi.

O pacote não contém `sge.db`, uploads, logs, credenciais nem ficheiros temporários.

## Validação executada

- Compilação Python dos módulos alterados.
- Migração sobre base vazia e sobre cópia da base atual, ambas com integridade SQLite `ok`.
- Testes do motor de faturação, vigências históricas, backup/restauro, CSRF e perfis.
- Seis testes da telemetria F650.
- Smoke test das rotas principais, sem respostas 500 e sem rotas duplicadas.
