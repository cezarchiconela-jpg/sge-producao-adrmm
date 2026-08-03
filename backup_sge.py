"""Backups consistentes, verificáveis e com retenção para o SGE."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_backup(path: str | Path) -> dict:
    archive = Path(path)
    with zipfile.ZipFile(archive, "r") as bundle:
        bad_member = bundle.testzip()
        names = set(bundle.namelist())
        if bad_member:
            raise ValueError(f"ficheiro corrompido no backup: {bad_member}")
        if "sge.db" not in names or "manifest.json" not in names:
            raise ValueError("backup incompleto: base de dados ou manifesto ausente")
        manifest = json.loads(bundle.read("manifest.json").decode("utf-8"))
        with tempfile.TemporaryDirectory(prefix="sge_verify_") as tmp:
            db_file = Path(tmp) / "sge.db"
            db_file.write_bytes(bundle.read("sge.db"))
            expected_hash = str(manifest.get("database_sha256") or "")
            if expected_hash and _sha256(db_file) != expected_hash:
                raise ValueError("a assinatura da base de dados não coincide com o manifesto")
            conn = sqlite3.connect(db_file)
            try:
                result = conn.execute("PRAGMA integrity_check").fetchone()[0]
            finally:
                conn.close()
            if str(result).lower() != "ok":
                raise ValueError(f"integridade SQLite inválida: {result}")
    return {"ok": True, "manifest": manifest, "sha256": _sha256(archive)}


def _prune(backups_dir: Path, retention_days: int, max_backups: int) -> None:
    archives = sorted(backups_dir.glob("sge_backup_*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    cutoff = dt.datetime.now().timestamp() - max(1, retention_days) * 86400
    for index, archive in enumerate(archives):
        if index >= max(1, max_backups) or archive.stat().st_mtime < cutoff:
            try:
                archive.unlink()
            except OSError:
                pass


def create_backup(
    db_path: str | Path,
    upload_dir: str | Path,
    backup_dir: str | Path,
    *,
    reason: str = "manual",
    actor: str = "sge",
    retention_days: int = 30,
    max_backups: int = 30,
    mirror_dir: str | Path | None = None,
) -> dict:
    database = Path(db_path)
    uploads = Path(upload_dir)
    backups = Path(backup_dir)
    if not database.exists():
        raise FileNotFoundError(f"base de dados não encontrada: {database}")
    backups.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output = backups / f"sge_backup_{stamp}.zip"

    with tempfile.TemporaryDirectory(prefix="sge_backup_") as tmp:
        snapshot = Path(tmp) / "sge.db"
        source = sqlite3.connect(database, timeout=30)
        target = sqlite3.connect(snapshot)
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        manifest = {
            "format": "sge-backup-v2",
            "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "reason": reason,
            "actor": actor,
            "database_sha256": _sha256(snapshot),
            "institution": "Águas e Saneamento de Maputo",
        }
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.write(snapshot, "sge.db")
            if uploads.exists():
                for item in uploads.rglob("*"):
                    if item.is_file():
                        bundle.write(item, "uploads/" + item.relative_to(uploads).as_posix())
            bundle.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    verified = verify_backup(output)
    if mirror_dir:
        mirror = Path(mirror_dir)
        mirror.mkdir(parents=True, exist_ok=True)
        shutil.copy2(output, mirror / output.name)
        _prune(mirror, retention_days, max_backups)
    _prune(backups, retention_days, max_backups)
    return {
        "path": str(output),
        "filename": output.name,
        "size_bytes": output.stat().st_size,
        "sha256": verified["sha256"],
        "verified": True,
    }


def maybe_create_daily_backup(
    db_path: str | Path,
    upload_dir: str | Path,
    backup_dir: str | Path,
    *,
    reason: str = "arranque_diario",
    actor: str = "sge",
) -> dict | None:
    backups = Path(backup_dir)
    backups.mkdir(parents=True, exist_ok=True)
    today = dt.date.today().strftime("%Y%m%d")
    if any(backups.glob(f"sge_backup_{today}_*.zip")):
        return None
    lock = backups / f".backup_{today}.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(descriptor)
    except FileExistsError:
        # Um processo interrompido não deve bloquear todos os backups do dia.
        try:
            if dt.datetime.now().timestamp() - lock.stat().st_mtime > 3600:
                lock.unlink()
                descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(descriptor)
            else:
                return None
        except (FileNotFoundError, FileExistsError, OSError):
            return None
    try:
        return create_backup(
            db_path,
            upload_dir,
            backup_dir,
            reason=reason,
            actor=actor,
            retention_days=int(os.environ.get("SGE_BACKUP_RETENTION_DAYS", "30")),
            max_backups=int(os.environ.get("SGE_BACKUP_MAX_COUNT", "30")),
            mirror_dir=os.environ.get("SGE_BACKUP_MIRROR_DIR") or None,
        )
    finally:
        try:
            lock.unlink()
        except OSError:
            pass


def _main() -> None:
    parser = argparse.ArgumentParser(description="Criar ou verificar backup do SGE")
    parser.add_argument("--verify", help="Verificar um backup existente")
    args = parser.parse_args()
    if args.verify:
        print(json.dumps(verify_backup(args.verify), ensure_ascii=False, indent=2))
        return
    result = create_backup(
        os.environ.get("SGE_DB_PATH", BASE_DIR / "sge.db"),
        os.environ.get("SGE_UPLOAD_FOLDER", BASE_DIR / "uploads"),
        os.environ.get("SGE_BACKUP_DIR", BASE_DIR / "backups"),
        reason="linha_de_comando",
        actor=os.environ.get("USER", "operador"),
        retention_days=int(os.environ.get("SGE_BACKUP_RETENTION_DAYS", "30")),
        max_backups=int(os.environ.get("SGE_BACKUP_MAX_COUNT", "30")),
        mirror_dir=os.environ.get("SGE_BACKUP_MIRROR_DIR") or None,
    )
    print(f"Backup criado e verificado: {result['path']}")


if __name__ == "__main__":
    _main()
