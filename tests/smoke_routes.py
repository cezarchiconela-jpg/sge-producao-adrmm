import importlib
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pprint import pprint
from collections import defaultdict

modname = 'app'

def run():
    mod = importlib.import_module(modname)
    app = getattr(mod, 'app')
    client = app.test_client()

    duplicates = []
    by_rule = defaultdict(list)
    for rule in app.url_map.iter_rules():
        methods = tuple(sorted(m for m in rule.methods if m not in {'HEAD', 'OPTIONS'}))
        by_rule[(rule.rule, methods)].append(rule.endpoint)
    for key, endpoints in by_rule.items():
        if len(endpoints) > 1:
            duplicates.append({'rule': key[0], 'methods': key[1], 'endpoints': endpoints})

    urls = [
        ('GET','/'),
        ('GET','/dashboard'),
        ('GET','/locais'),
        ('GET','/equipamentos'),
        ('GET','/motores'),
        ('GET','/alertas'),
        ('GET','/solar'),
        ('GET','/leituras_mensal'),
        ('GET','/leituras_mensais'),
        ('GET','/mt/config'),
    ]

    results = []
    for method, path in urls:
        resp = client.open(path, method=method, follow_redirects=False)
        results.append({'method':method, 'path':path, 'status':resp.status_code, 'location':resp.headers.get('Location')})

    pprint({'duplicates': duplicates, 'routes': results})
    if duplicates:
        raise SystemExit(1)
    if any(r['status'] >= 500 for r in results):
        raise SystemExit(2)

if __name__ == '__main__':
    run()
