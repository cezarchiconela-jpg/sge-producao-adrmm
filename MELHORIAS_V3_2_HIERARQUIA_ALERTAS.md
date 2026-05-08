# SGE  — Hierarquia de Locais e Optimização dos Alertas

## 1. Hierarquia de locais e sublocais

Esta versão adiciona suporte operacional para estrutura pai/filho no módulo Centros e Locais.

### Comportamento aplicado

- Um local pode ter sublocais associados através da coluna `parent_id`.
- O sublocal continua a funcionar como local independente.
- Equipamentos registados no sublocal pertencem directamente ao sublocal.
- Quando o utilizador abre ou filtra pelo local pai, o sistema considera também os equipamentos dos seus sublocais.
- Quando o utilizador abre ou filtra directamente pelo sublocal, vê os equipamentos específicos desse sublocal.

### Áreas melhoradas

- `/locais`
- `/locais/<id>`
- `/equipamentos`
- `/motores`
- `/alertas`

## 2. Comunicação entre sublocais e módulos

A leitura hierárquica foi preparada para que os módulos principais aceitem a lógica:

- Local pai = local pai + todos os sublocais descendentes;
- Sublocal = o sublocal específico e seus próprios descendentes, caso existam;
- Equipamentos = continuam cadastrados por `local_id`, mas agora os filtros por pai também procuram os filhos.

## 3. Alertas Correctivos — melhoria de velocidade

O módulo de Alertas Correctivos foi optimizado porque podia ficar lento ao carregar muitos equipamentos sem medições.

### Causas corrigidas

- O sistema gerava muitos alertas informativos do tipo “sem medições” para todos os equipamentos.
- As consultas percorriam grandes volumes de leituras e medições sem limite suficiente.
- O Centro de Alertas carregava todas as origens mesmo quando o utilizador filtrava uma origem específica.

### Correcções aplicadas

- O módulo deixou de criar centenas de alertas informativos “sem medições” no centro de alertas.
- Foram adicionados limites de consulta para evitar renderização excessiva.
- Foram criados índices em tabelas críticas:
  - `leituras(datahora, local)`
  - `leituras(local, equipamento)`
  - `leituras_mensais(data, local)`
  - `motor_medicoes(datahora, equipamento_id)`
  - `motor_runs(equipamento_id, start_time)`
  - `equipamentos(local_id)`
  - `locais(parent_id)`
- O Centro de Alertas passa a coletar apenas a origem necessária quando o filtro de origem está activo.

## 4. Migração de base de dados

A coluna `parent_id` é criada automaticamente no arranque do sistema se ainda não existir.

Também foi actualizada a base de dados incluída no ZIP para já conter a coluna `parent_id`.

## 5. Observação importante

Esta versão preserva as funções existentes. A lógica nova acrescenta hierarquia e melhora desempenho sem apagar os módulos anteriores.
