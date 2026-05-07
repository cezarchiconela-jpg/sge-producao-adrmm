"""Entrada WSGI para produção.
Usar com: gunicorn wsgi:app
"""
from app import app
