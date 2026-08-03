# Eficiência Energética e Desempenho Operacional do SGE

## Objetivo

Esta fase transforma dados já existentes de energia, água, tarifas e telemetria em indicadores de eficiência e decisão. Não altera leituras históricas, programação do F650, regras de faturação ou dados de equipamentos.

## Novas funções

- Dashboard institucional e por local em `/eficiencia`.
- Indicadores de energia, água, custo, kWh/m³ e MZN/m³.
- Ranking de eficiência apenas para locais com energia e água disponíveis.
- Linhas de base calculadas por normalização do volume de água.
- Aprovação e arquivo controlados de linhas de base.
- Metas anuais de redução e meta específica em kWh/m³.
- Poupança energética e financeira, com classificação `verificada`, `indicativa` ou `indisponível`.
- Deteção de desvios de desempenho e estado Eficiente, Dentro da base, Atenção ou Crítico.
- Demanda média em intervalos de 15 minutos a partir da potência ativa real da telemetria.
- Carteira de medidas de eficiência com investimento, poupança prevista, responsável, prioridade, estado e payback simples.
- Exportações Excel e PDF ligadas ao mesmo motor de cálculo do dashboard.
- API de leitura em `/eficiencia/api`.

## Critérios técnicos

### Consumo e custo específicos

- `kWh/m³ = energia ativa do período / água produzida ou elevada`.
- `MZN/m³ = fatura estimada completa / água produzida ou elevada`.
- Sem volume de água, estes indicadores ficam indisponíveis; o SGE não inventa nem substitui o dado.

### Linha de base

- Mínimo de três meses elegíveis.
- Cada mês precisa de energia ativa, água e cobertura igual ou superior ao limite configurado; o recomendado é 80%.
- A linha de base específica é ponderada: energia total dos meses elegíveis dividida pela água total desses meses.
- A linha de base nasce como rascunho e só passa a orientar poupanças depois de aprovação por gestor ou administrador.
- A aprovação de uma nova linha de base arquiva a anterior do mesmo local, preservando o histórico.

### Poupança

- `energia esperada = kWh/m³ da linha de base × água real do período`.
- `poupança energética = energia esperada - energia real`.
- Valor positivo representa redução; valor negativo representa consumo acima da linha de base.
- A poupança é `verificada` somente quando existe linha de base aprovada, água válida, pelo menos três meses elegíveis na base e cobertura atual mínima de 80%.
- A poupança financeira representa energia ativa evitada com a tarifa vigente e incidência efetiva do IVA aprovado. Não presume redução de ponta, energia reativa ou taxas fixas.

### Demanda de 15 minutos

- Usa o canal `potencia_activa_total_mw` do dispositivo ativo associado ao local.
- Converte MW para kW, integra por intervalos reais e ignora lacunas superiores a dez minutos.
- Um intervalo é válido com pelo menos 80% de cobertura; abaixo de 95% é identificado como estimado.
- Nenhum fator multiplicativo é aplicado à telemetria recebida do F650.

## Permissões

- Consulta: visualiza dashboards, relatórios, linhas de base e medidas.
- Técnico: pode registar e atualizar medidas de eficiência.
- Gestor: pode também criar/aprovar linhas de base e definir metas.
- Administrador: acesso total.
- Todas as alterações usam POST, CSRF e auditoria.

## Migração e compatibilidade

A migração cria as tabelas `eficiencia_baselines`, `eficiencia_metas`, `eficiencia_medidas` e `eficiencia_audit` de forma idempotente. Os dados existentes não são recalculados nem alterados. As tarifas continuam a ser resolvidas pela vigência histórica e a fatura mantém IVA de 16% sobre 62% do subtotal.

## Utilização recomendada

1. Completar e validar as leituras mensais de energia e água.
2. Abrir `Eficiência > Linhas de base` e selecionar um período representativo.
3. Rever o rascunho e aprová-lo.
4. Definir a meta anual.
5. Acompanhar kWh/m³, MZN/m³, desvio e poupança no dashboard.
6. Registar medidas de eficiência e acompanhar o resultado após implementação.

