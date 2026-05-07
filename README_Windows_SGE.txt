SGE – Passos para Windows (testado com Python 3.11 64‑bit)

1) Descompacte o projeto em uma pasta sem espaços, por exemplo: C:\SGE\sge

2) APAGUE a pasta incluída "sge\.venv" (virtuais inclusas em .zip geralmente quebram em outras máquinas).

3) Instale o Python 3.11 (64‑bit) do site oficial e marque "Add Python to PATH".

4) No PowerShell:
   cd C:\SGE\sge
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   pip install -r requirements-fixed.txt

5) Substitua o arquivo app.py pelo app_fixed.py (renomeie este arquivo para app.py dentro da pasta sge).

6) (Opcional) Verifique o ambiente:
   python self_check.py

7) Rode o sistema:
   python app.py
   Abra: http://127.0.0.1:5000

Dicas:
- Se aparecer "TemplateNotFound", garanta que está dentro da pasta sge ao rodar o python app.py.
- Se houver erro ao salvar imagens, confira permissões da pasta "uploads" e que ela existe (self_check cria).
- Caso a porta 5000 esteja ocupada, edite o final do arquivo app.py: app.run(debug=True, port=8000)
