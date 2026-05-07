"""Checklist rápido antes de publicar o SGE."""
import importlib, sys
from collections import defaultdict
checks=[]
def ok(name,status,detail=''): checks.append((name,status,detail))
for pkg in ['flask','jinja2','werkzeug','PIL','reportlab','openpyxl','xlsxwriter','qrcode','pandas']:
    try: importlib.import_module(pkg); ok(f'dependência {pkg}', True)
    except Exception as e: ok(f'dependência {pkg}', False, str(e))
try:
    import app
    ok('importação app.py', True)
    d=defaultdict(list)
    for r in app.app.url_map.iter_rules():
        key=(r.rule, tuple(sorted(m for m in r.methods if m not in {'HEAD','OPTIONS'})))
        d[key].append(r.endpoint)
    dup=[(k,v) for k,v in d.items() if len(v)>1]
    ok('rotas duplicadas com mesmo método', not dup, str(dup[:5]))
    with app.app.test_client() as c:
        resp=c.get('/healthz')
        ok('/healthz', resp.status_code in (200,503), f'HTTP {resp.status_code}')
except Exception as e:
    ok('importação app.py', False, str(e))
print('\nCHECKLIST DE PRODUÇÃO SGE')
print('='*32)
failed=0
for name,status,detail in checks:
    mark='OK' if status else 'FALHA'
    if not status: failed += 1
    print(f'[{mark}] {name}' + (f' — {detail}' if detail else ''))
print('='*32)
sys.exit(1 if failed else 0)
