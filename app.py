
# --- Pack3: Validations per local + stronger audit table ---
def migrate_pack3():
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    # Config table for validations per local
    c.execute('''CREATE TABLE IF NOT EXISTS validacoes_locais (
        local TEXT PRIMARY KEY,
        fp_min REAL DEFAULT 0.85,
        kwh_dia_max REAL,
        permitir_regressivo INTEGER DEFAULT 0
    )''')
    # Strengthen audit with actor and period
    c.execute('''CREATE TABLE IF NOT EXISTS leituras_mensais_audit (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        local TEXT, data TEXT, mes TEXT, ano INTEGER,
        field TEXT, old_value TEXT, new_value TEXT,
        acao TEXT,
        actor TEXT,
        ts TEXT DEFAULT (datetime('now','localtime'))
    )''')
    conn.commit(); conn.close()


def get_validacao_local(local: str):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    row = c.execute("SELECT fp_min, kwh_dia_max, permitir_regressivo FROM validacoes_locais WHERE local=?",(local,)).fetchone()
    conn.close()
    if not row:
        return {'fp_min':0.85, 'kwh_dia_max':None, 'permitir_regressivo':0}
    return {'fp_min': float(row[0] or 0.85), 'kwh_dia_max': (float(row[1]) if row[1] is not None else None), 'permitir_regressivo': int(row[2] or 0)}

def set_validacao_local(local, fp_min, kwh_dia_max, permitir_regressivo):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('''INSERT INTO validacoes_locais(local, fp_min, kwh_dia_max, permitir_regressivo)
                 VALUES(?,?,?,?)
                 ON CONFLICT(local) DO UPDATE SET
                   fp_min=excluded.fp_min, kwh_dia_max=excluded.kwh_dia_max, permitir_regressivo=excluded.permitir_regressivo''',
              (local, fp_min, kwh_dia_max, permitir_regressivo))
    conn.commit(); conn.close()

def log_audit(local, data, mes, ano, field, old, new, acao="update", actor="pack3"):
    conn = sqlite3.connect(DB_PATH); c = conn.cursor()
    c.execute('''INSERT INTO leituras_mensais_audit(local,data,mes,ano,field,old_value,new_value,acao,actor)
                 VALUES(?,?,?,?,?,?,?,?,?)''', (local, data, mes, ano, field, str(old), str(new), acao, actor))
    conn.commit(); conn.close()
from flask import Flask, request, render_template, redirect, url_for, Response, flash, jsonify, send_from_directory, send_file, g, session
import os
import secrets
print(">> SGE a arrancar a partir do ficheiro:", __file__)
print(">> Pasta atual:", os.getcwd())
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from PIL import Image
from PIL import Image, ImageOps
from reportlab.lib.units import cm, mm
import zipfile
import io
import time 
import sqlite3
import calendar
from functools import wraps
from datetime import datetime, timedelta
import math
from io import StringIO
import json
import re
from jinja2 import TemplateNotFound
from io import BytesIO
import csv
import xlsxwriter
import qrcode
from urllib.parse import urlsplit
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from werkzeug.utils import secure_filename

from billing import (
    DEFAULT_TARIFFS,
    REACTIVE_LIMIT_FACTOR,
    VAT_BASE_FACTOR,
    VAT_RATE,
    billing_demand,
    calculate_invoice,
    normalise_tariffs,
    resolve_tariffs,
)
from backup_sge import create_backup, maybe_create_daily_backup, verify_backup
from migrations import run_migrations

app = Flask(__name__)
RATE_LIMIT_UPLOADS = {}

app.secret_key = os.environ.get('SECRET_KEY') or os.environ.get('FLASK_SECRET_KEY') or secrets.token_hex(32)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get('SGE_DB_PATH', os.path.join(BASE_DIR, 'sge.db'))
INSTITUTION_NAME = 'Águas e Saneamento de Maputo'


def _set_xlsx_identity(workbook, title):
    """Aplica a identidade institucional aos metadados dos ficheiros Excel."""
    try:
        workbook.set_properties({
            'title': title,
            'subject': 'Documento produzido pelo Sistema de Gestão de Energia',
            'author': INSTITUTION_NAME,
            'company': INSTITUTION_NAME,
            'comments': f'Gerado pelo SGE · {INSTITUTION_NAME}',
        })
    except Exception:
        pass


def _set_pdf_identity(pdf_canvas, title):
    """Aplica a identidade institucional aos metadados dos ficheiros PDF."""
    try:
        pdf_canvas.setTitle(title)
        pdf_canvas.setAuthor(INSTITUTION_NAME)
        pdf_canvas.setSubject('Documento produzido pelo Sistema de Gestão de Energia')
        pdf_canvas.setCreator(f'SGE · {INSTITUTION_NAME}')
    except Exception:
        pass


from sge_loader import load_feature as _load_sge_feature
from sge_loader import sync_feature_context as _sync_sge_feature_context

# Domínio modular: security
_load_sge_feature('security', globals())

# Domínio modular: bootstrap_runtime
_load_sge_feature('bootstrap_runtime', globals())

# Domínio modular: locations_core
_load_sge_feature('locations_core', globals())

# Domínio modular: dashboard_core
_load_sge_feature('dashboard_core', globals())

# Domínio modular: locations_routes
_load_sge_feature('locations_routes', globals())

# Domínio modular: equipment_core
_load_sge_feature('equipment_core', globals())

# Domínio modular: daily_readings_core
_load_sge_feature('daily_readings_core', globals())

# Domínio modular: monthly_readings_core
_load_sge_feature('monthly_readings_core', globals())

# Domínio modular: motors
_load_sge_feature('motors', globals())

# Domínio modular: alerts
_load_sge_feature('alerts', globals())

# Domínio modular: solar
_load_sge_feature('solar', globals())

# Domínio modular: equipment_extended
_load_sge_feature('equipment_extended', globals())

# Domínio modular: monthly_readings_api
_load_sge_feature('monthly_readings_api', globals())

# Domínio modular: daily_readings_extended
_load_sge_feature('daily_readings_extended', globals())

# Domínio modular: administration
_load_sge_feature('administration', globals())

# Domínio modular: monthly_readings_extended
_load_sge_feature('monthly_readings_extended', globals())

# Domínio modular: daily_readings_api
_load_sge_feature('daily_readings_api', globals())

# Domínio modular: compatibility
_load_sge_feature('compatibility', globals())

# Domínio modular: dashboard_executive
_load_sge_feature('dashboard_executive', globals())

# Consolida as redefinições finais usadas pelos endpoints já registados.
_sync_sge_feature_context(globals())

if __name__ == '__main__':
    port = int(os.environ.get('PORT', '5000'))
    debug = os.environ.get('FLASK_DEBUG', '0').lower() in ('1','true','yes')
    app.run(host='0.0.0.0', port=port, debug=debug, use_reloader=debug)
