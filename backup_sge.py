"""Cria backup local do SGE: base de dados + uploads + ficheiros críticos."""
import os, zipfile, datetime
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('SGE_DB_PATH', BASE_DIR / 'sge.db'))
UPLOAD_DIR = Path(os.environ.get('SGE_UPLOAD_FOLDER', BASE_DIR / 'uploads'))
BACKUP_DIR = Path(os.environ.get('SGE_BACKUP_DIR', BASE_DIR / 'backups'))
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
stamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
out = BACKUP_DIR / f'sge_backup_{stamp}.zip'
with zipfile.ZipFile(out, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
    if DB_PATH.exists(): zf.write(DB_PATH, 'sge.db')
    if (BASE_DIR / '.env.example').exists(): zf.write(BASE_DIR / '.env.example', '.env.example')
    if UPLOAD_DIR.exists():
        for f in UPLOAD_DIR.rglob('*'):
            if f.is_file(): zf.write(f, 'uploads/' + str(f.relative_to(UPLOAD_DIR)).replace('\\','/'))
print(f'Backup criado: {out}')
