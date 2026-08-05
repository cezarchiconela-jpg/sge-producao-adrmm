# Cadastro Mestre de Locais e Activos do SGE

Esta actualização integra o cadastro DIMA de 4 de Agosto de 2026 no SGE e mantém as funções já existentes de equipamentos, locais, fotografias, documentos, medições, histórico, custos, energia e manutenção.

## Resultado esperado no primeiro arranque

- 3.147 activos do ficheiro DIMA identificados por uma referência estável.
- 29 locais operacionais representados no cadastro-fonte.
- 2 ETAs: ETA Umbeluzi e ETA Sabié.
- CDs, campos de furos, estações de bombagem, transferências e pequenos sistemas mantidos como locais reais.
- Sector, instalação e sistema guardados separadamente para permitir filtros e relatórios correctos.
- 4 sectores de origem preservados: UMBELUZI, SABIE, CDs e ADUCAO.

Numa base SGE já preenchida, o total pode ser superior a 3.147 porque os activos antigos sem correspondência não são eliminados automaticamente. Na base analisada, 693 registos existentes foram reconciliados e 3 ficaram preservados para revisão manual.

## Actualização segura

No primeiro arranque desta versão, o SGE executa a migração e reconcilia automaticamente o ficheiro incluído em `data/activos_dima_todos_20260804_154738.xlsx`.

A reconciliação:

- actualiza o mesmo activo em vez de criar duplicados;
- preserva ID, TAG manual, custo, vida útil, fotografias, anexos, medições e histórico quando o ficheiro novo não fornece esses dados;
- não elimina nem arquiva activos ausentes do novo ficheiro;
- cria um lote de importação auditável;
- executa toda a importação numa transacção: em caso de erro, não deixa uma actualização parcial.

O arranque já mantém a cópia de segurança automática anterior à migração.

## Utilização no SGE

Abra **Equipamentos → Cadastro mestre** para:

1. carregar Excel ou CSV;
2. pré-visualizar inserções, actualizações, reconciliações, novos locais e lacunas de dados;
3. confirmar a actualização;
4. descarregar o modelo Excel de activos ou de locais;
5. exportar o cadastro completo em Excel ou PDF;
6. consultar os últimos lotes processados.

Os formulários manuais de Locais e Equipamentos incluem agora sector, instalação, sistema, estado operacional, periodicidade, localização geográfica e referência externa. O Excel de locais aceita um local-pai mesmo quando este aparece numa linha posterior da mesma folha.

## Qualidade de dados

O ficheiro de origem deixa campos por completar. O painel do cadastro mostra essas lacunas para preenchimento posterior, sem inventar valores. No ficheiro actual existem, entre outros:

- 1.731 activos sem fabricante;
- 1.052 sem modelo;
- 648 sem estado operacional informado;
- 639 sem criticidade normalizada.

Esses campos podem ser preenchidos manualmente ou por um novo Excel. Província, município, distrito, bairro e coordenadas também permanecem disponíveis para confirmação institucional.

## Instalação do pacote de actualização

1. Faça uma cópia de segurança do projecto e da base `sge.db`.
2. Extraia o ZIP na raiz do projecto SGE, preservando a estrutura das pastas.
3. Instale as dependências de `requirements.txt`, se necessário.
4. Reinicie o SGE e aguarde a conclusão do primeiro arranque.
5. Confirme em **Equipamentos → Cadastro mestre** os totais e o lote de importação.

Os testes automatizados cobrem migração em base vazia, reconciliação numa base existente, preservação de dados manuais e repetição idempotente da importação.

