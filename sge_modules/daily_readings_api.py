"""Domínio daily_readings_api extraído do app.py consolidado.

Carregado no arranque pelo mecanismo transitório de compatibilidade.
"""

# ----------------- API AUX: leitura anterior (para auto-preenchimento) -----------------
from flask import jsonify, request
import sqlite3

@app.get('/api/leituras/prev')
def api_prev_leitura():
    """Retorna a última leitura atual (leit_atual/leitura_atual) anterior à 'data' para o 'local' dado.
    Params: local (int), data (YYYY-MM-DD)"""
    try:
        local = request.args.get('local', type=int)
        data = request.args.get('data', type=str)
        if not local or not data:
            return jsonify(success=False, error="missing_params"), 400
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute("""
                SELECT COALESCE(leit_atual, leitura_atual, 0)
                FROM leituras_mensais
                WHERE local=? AND date(data) < date(?)
                ORDER BY date(data) DESC, rowid DESC
                LIMIT 1
            """, (local, data))
        except Exception:
            c.execute("""
                SELECT COALESCE(leit_atual, leitura_atual, 0)
                FROM leituras_mensais
                WHERE local=? AND data < ?
                ORDER BY data DESC, rowid DESC
                LIMIT 1
            """, (local, data))
        row = c.fetchone()
        conn.close()
        prev = float(row[0]) if row and row[0] is not None else 0.0
        return jsonify(success=True, prev=prev)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500
