SGE - Versao corrigida para arranque

1) Abrir PowerShell na pasta do projecto.
2) Criar/activar ambiente virtual, se necessario:
   py -3.11 -m venv .venv
   .\.venv\Scripts\activate

3) Instalar dependencias:
   pip install -r requirements.txt

4) Iniciar o sistema:
   python app.py

5) Abrir no navegador:
   http://127.0.0.1:5000

Correccao aplicada nesta versao:
- Reposta a funcao get_local_by_id(), usada por Leituras Mensais, Leituras por Local, Solar e APIs.
- Corrigido o erro 500 do endpoint /leituras_mensal.
- requirements.txt actualizado com dependencias reais do app.py.

Validacao feita:
- Importacao do app.py sem erro.
- Compilacao do app.py sem erro.
- Teste de rotas principais: Dashboard, Locais, Equipamentos, Leituras, Leituras Mensais, Solar, Motores, Alertas e Health.
