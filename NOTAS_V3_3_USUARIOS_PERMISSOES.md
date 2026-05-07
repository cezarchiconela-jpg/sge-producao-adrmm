# SGE V3.3 — Utilizadores e Permissões

Melhorias adicionadas:

- Botão Login/Logout no topo do sistema.
- Menu do utilizador autenticado.
- Gestão de utilizadores em `/usuarios`.
- Criação, edição, ativação/desativação e redefinição de passwords.
- Tabela `users` no SQLite, criada automaticamente.
- Hash seguro de palavras-passe com Werkzeug.
- Admin inicial criado automaticamente a partir de `SGE_ADMIN_USER` e `SGE_ADMIN_PASSWORD` já configurados no Render.
- Níveis de acesso:
  - admin: acesso total;
  - gestor: operação ampla sem gerir utilizadores;
  - tecnico: operação técnica;
  - leitura: apenas registos de leituras e monitoria;
  - consulta: apenas consulta e relatórios.

Após deploy:

1. Entrar com o utilizador admin já definido no Render.
2. Abrir `/usuarios`.
3. Criar utilizadores reais.
4. Redefinir passwords iniciais.
5. Testar login/logout com cada perfil.

Atenção:

Depois que a tabela `users` for criada, a gestão das passwords passa a ser feita no próprio SGE. Alterar `SGE_ADMIN_PASSWORD` no Render já não altera automaticamente a senha do admin existente na base de dados.
