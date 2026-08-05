# Integração PIGI — Produção, Distribuição e Eficiência Operacional

## Objetivo

Preparar o SGE para receber dados históricos e futuros de água e energia sem misturar faturação, telemetria e dados operacionais. O sistema importa grandezas brutas, guarda a fonte e recalcula os indicadores de eficiência.

## Formatos aceites

- PIGI em `.xlsb` ou `.xlsx`;
- Modelo simples SGE em `.xlsx`;
- Planilhas EDM com consumo em kWh ou leituras acumuladas em kWh.

## Fluxo controlado

1. Técnico, gestor ou administrador carrega o ficheiro.
2. O SGE deteta o formato e cria uma pré-visualização.
3. Nomes como Mathemele/Matlhemele, Katembe/Ka Tembe e Umbeluze/Umbeluzi são normalizados.
4. Linhas com local desconhecido, ausência de grandezas ou divergências internas ficam assinaladas.
5. O utilizador revê o mapeamento e seleciona as linhas utilizáveis.
6. Apenas gestor ou administrador confirma os dados como validados.
7. O módulo de Eficiência Energética passa a utilizar os registos confirmados.

## Prioridade das fontes

As fontes nunca são somadas para a mesma grandeza e período.

- Energia: telemetria, contador EDM, PIGI, SCADA e manual.
- Água: SCADA, PIGI, planilha operacional e manual.

Assim, é possível usar energia do contador EDM e água do PIGI no mesmo mês, mantendo a origem de ambas.

## Tratamento dos dados

- O PIGI é lido na folha `Energia kw`.
- São extraídos valores diários de energia e volume, não o indicador calculado da planilha.
- O SGE recalcula `kWh/m³` depois da validação.
- Ocorrências são extraídas e preservadas por lote.
- O hash do ficheiro impede confirmação repetida do mesmo documento.
- A chave local + data + tipo de período + fonte impede duplicação de linhas.
- Pontos de transferência são sinalizados para evitar dupla contagem institucional.
- Divergências entre a tabela energética com coeficiente e o bloco de consumo específico ficam desmarcadas até revisão.

## Planilha simples EDM

A folha deve chamar-se `Dados` ou `Leituras`. Cabeçalhos reconhecidos incluem:

- Local;
- Data;
- Energia kWh; ou Leitura energia kWh;
- Água m3;
- Horas operação;
- Tipo dado;
- Observações.

Quando são fornecidas leituras acumuladas, a primeira serve apenas de referência. O consumo é calculado pela diferença entre leituras consecutivas e regressões são rejeitadas.

## Efeito no módulo de eficiência

O cálculo mensal pode combinar a melhor fonte validada para cada grandeza. A cobertura é calculada pelos dias efetivamente disponíveis. Sem energia e água no mesmo período, o indicador permanece indisponível. A faturação oficial e os dados do F650 continuam separados.
