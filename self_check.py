
import os, importlib.util, sqlite3, sys
from pathlib import Path

BASE = Path(__file__).parent
print("[1] Working dir:", os.getcwd())
print("[2] Script dir:", BASE)

# Check dependencies
missing = []
for mod in ["flask","PIL","reportlab","openpyxl","xlsxwriter"]:
    if importlib.util.find_spec(mod) is None:
        missing.append(mod)
print("[3] Missing modules:", missing if missing else "OK")

# Check folders
uploads = BASE/"uploads"
print("[4] Uploads:", uploads, "exists:", uploads.exists())
(uploads/"photos").mkdir(parents=True, exist_ok=True)
(uploads/"thumbs").mkdir(parents=True, exist_ok=True)

# Check DB
db = BASE/"sge.db"
print("[5] DB path:", db)
conn = sqlite3.connect(db); c = conn.cursor()
# Quick probe
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
print("[6] Tables:", tables[:10], "...", len(tables))
conn.close()
print("Done")
