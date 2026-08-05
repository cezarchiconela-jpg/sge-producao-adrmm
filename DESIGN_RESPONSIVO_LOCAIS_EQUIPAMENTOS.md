# SGE — Design Responsivo dos Módulos Locais e Equipamentos

## Objectivo

Harmonizar os módulos de Locais e Equipamentos com a linguagem visual dos restantes módulos do SGE, mantendo integralmente a hierarquia ETA/CD, os cadastros, filtros, exportações, permissões e acções operacionais existentes.

## Melhorias aplicadas

### Linguagem visual comum

- Locais e Equipamentos usam agora o cabeçalho, a navegação e a identidade visual global do SGE.
- Cores, tipografia, cartões, indicadores, botões, filtros e estados seguem o mesmo padrão.
- A navegação principal apresenta os nomes claros “Locais” e “Equipamentos”.

### Módulo Locais

- Entrada visual directa por ETAs ou CDs.
- Cartões de selecção com totais de instalações e equipamentos.
- Indicadores compactos de locais, potência, maturidade e qualidade do cadastro.
- Filtros recolhíveis, com contagem dos filtros activos.
- Lista reorganizada com hierarquia, estado técnico, prioridade, maturidade e acções.
- Em telemóveis, cada local passa a ser apresentado como cartão legível.

### Módulo Equipamentos

- Página integrada no layout global do SGE.
- Pesquisa principal por nome, TAG, referência ou especificação.
- Filtros completos por local, categoria, fabricante, modelo, sector, instalação, sistema, estado, manutenção, ano e criticidade.
- Ordenação visível por nome, local, TAG, categoria, fabricante, ano, criticidade e estado.
- Informação consolidada por equipamento: fotografia, localização exacta, classificação, dados eléctricos, manutenção, criticidade, estado e custo.
- Paginação numerada e preservação de todos os filtros ao mudar de página.
- Selecção em lote com contador em tempo real.
- Em telemóveis, cada equipamento transforma-se num cartão operacional, sem tabela lateral extensa.

## Segurança e compatibilidade

- Botões de criação e alteração respeitam as permissões existentes.
- Não foi removida nenhuma rota, função de importação, exportação, edição, arquivo ou consulta.
- A base `sge.db` não faz parte deste pacote e não deve ser substituída.
- A actualização foi aplicada sobre a versão com hierarquia ETAs/CDs, instalações e subinstalações.

## Validação

- 28 testes automatizados aprovados.
- Rotas de Locais, Equipamentos, filtros e ficheiros estáticos renderizadas sem erro.
- Segunda validação de arranque e rotas principais concluída.

## Instalação

1. Faça uma cópia de segurança da pasta actual do SGE.
2. Extraia o ZIP na raiz do projecto.
3. Autorize a substituição dos ficheiros com o mesmo nome.
4. Não elimine nem substitua o ficheiro `sge.db`.
5. Reinicie o SGE e abra os módulos Locais e Equipamentos.

