# SGE — Actualização de telemetria, alertas e relatórios

## Instalação sem alterações no PC do F650

Esta versão mantém a API, o código do dispositivo, o token e o formato JSON já
utilizados pelo PC de aquisição. Para activar as melhorias basta publicar o
projecto actualizado no servidor. Não é necessário voltar ao PC ligado ao relé,
alterar o mapa Modbus ou reconfigurar o F650.

A migração da base de dados é automática e idempotente. No primeiro arranque o
SGE cria apenas as novas tabelas de configuração e ocorrências; as leituras e os
módulos existentes não são apagados nem recriados.

## Alertas automáticos úteis

O sistema passa a registar início, última detecção, resolução, duração, gravidade
e quantidade de leituras para:

- corte de energia confirmado pelas três tensões entre fases próximas de zero;
- subtensão e sobretensão;
- factor de potência baixo, avaliado em módulo;
- frequência fora da faixa;
- desequilíbrio de tensão e corrente;
- dados atrasados;
- perda de comunicação com o PC de aquisição.

Um corte de energia e uma perda de comunicação são eventos diferentes. Se os
dados deixarem de chegar, o SGE não afirma que houve corte; orienta a verificar o
PC, a Internet e o serviço de envio. O corte só é confirmado pelas tensões.

Limites iniciais de supervisão para a rede de 33 kV:

- tensão normal: 31,35 a 34,65 kV;
- tensão crítica baixa: abaixo de 29,70 kV;
- tensão crítica alta: acima de 36,30 kV;
- corte confirmado: três tensões iguais ou inferiores a 3,30 kV;
- factor de potência: atenção abaixo de 0,85 e crítico abaixo de 0,80;
- frequência: atenção fora de 49,5–50,5 Hz e crítica fora de 49–51 Hz;
- comunicação: atraso após 3 minutos e perda após 15 minutos.

Estes limites pertencem ao SGE e não modificam as protecções do F650.

## Tratamento e análise

- Potências e factor de potência são apresentados em módulo para representar o
  consumo; o valor bruto e o sentido medido continuam guardados.
- A exportação CSV contém valor bruto, valor operacional e sentido medido.
- A energia activa em kWh é estimada por integração da potência ao longo do
  tempo e ignora lacunas superiores a 10 minutos.
- São calculados mínimo, média, máximo, pico, desequilíbrio, cobertura de dados,
  disponibilidade de energia e disponibilidade de comunicação.
- O painel inclui vistas rápidas para tensões, correntes, potências, factor de
  potência e frequência, com escalas separadas quando as unidades diferem.

## Relatório PDF

O botão **Relatório PDF** gera um documento profissional para o período
seleccionado contendo:

- estado operacional e alertas activos;
- energia estimada, pico, factor de potência e faixa de tensão;
- disponibilidade, cobertura e duração de cortes;
- tabela de mínimo, média e máximo;
- histórico de ocorrências;
- recomendações operacionais;
- nota técnica sobre valores em módulo e preservação do sinal bruto.

## Validação incluída

Os testes cobrem:

- preservação do sinal bruto e apresentação operacional positiva;
- abertura e resolução de corte de energia;
- distinção entre corte e perda de comunicação;
- cálculo de energia e indicadores;
- geração válida do relatório PDF;
- ausência de rotas duplicadas e funcionamento das páginas principais.
