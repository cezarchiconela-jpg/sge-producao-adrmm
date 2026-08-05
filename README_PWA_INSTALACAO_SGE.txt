SGE ASM — ACTUALIZAÇÃO DE NOMENCLATURA E APLICATIVO INSTALÁVEL
================================================================

1. O QUE MUDA

- "Telemetria e Eficiência Energética" passa a chamar-se "Telemetria Energética".
- "Eficiência Energética" mantém o nome para o módulo de kWh/m³, MZN/m³,
  referências de consumo, metas, ranking, poupanças e medidas.
- O SGE passa a poder ser instalado como aplicativo web (PWA) em telemóveis,
  tablets e computadores.

2. COMO APLICAR

Copiar as pastas e ficheiros deste pacote para a raiz do repositório do SGE,
mantendo a mesma estrutura. Confirmar a substituição dos ficheiros existentes.
Depois, fazer commit/push no GitHub e aguardar a publicação automática no Render.

O pacote não contém base de dados, uploads, credenciais ou dados operacionais.

3. LINK DE INSTALAÇÃO

Depois de publicado, o link que deve ser enviado aos utilizadores é:

https://DOMINIO-DO-SGE/instalar

Substituir DOMINIO-DO-SGE pelo endereço real onde o SGE está publicado.

4. INSTALAÇÃO NO ANDROID

- Abrir o link no Google Chrome.
- Tocar em "Instalar aplicativo" e confirmar.
- Se o botão não aparecer, usar o menu ⋮ e escolher "Instalar app" ou
  "Adicionar ao ecrã principal".

5. INSTALAÇÃO NO IPHONE/IPAD

- Abrir o link no Safari.
- Tocar em Partilhar.
- Escolher "Adicionar ao ecrã principal" e confirmar.

6. FUNCIONAMENTO E SEGURANÇA

- O aplicativo usa a mesma base de dados e o mesmo sistema online.
- Cada utilizador entra com o seu utilizador e senha habituais.
- As permissões existentes permanecem válidas.
- É necessária internet para consultar ou alterar dados atualizados.
- Sem internet, o aplicativo apenas informa que a ligação está indisponível;
  não guarda páginas com dados internos para consulta offline.
- A instalação PWA exige que o sistema esteja publicado por HTTPS. O Render
  já fornece HTTPS nos endereços públicos normais.

7. FICHEIROS DA ACTUALIZAÇÃO

- sge_modules/dashboard_core.py
- sge_modules/security.py
- templates/base.html
- templates/index.html
- templates/instalar_app.html
- templates/offline.html
- static/theme_sge.css
- static/manifest.webmanifest
- static/service-worker.js
- static/pwa-install.js
- static/icons/sge-192.png
- static/icons/sge-512.png

