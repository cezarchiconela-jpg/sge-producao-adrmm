import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from backup_sge import create_backup, verify_backup
from migrations import run_migrations


class MigrationsAndBackupsTest(unittest.TestCase):
    def test_empty_database_becomes_complete(self):
        with tempfile.TemporaryDirectory(prefix="sge-new-") as folder:
            db = Path(folder) / "sge.db"
            run_migrations(str(db))
            conn = sqlite3.connect(db)
            tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
            conn.close()
            required = {
                "locais", "locais_cfg", "equipamentos", "leituras", "leituras_mensais",
                "motor_medicoes", "solar_projetos", "tarifas_historico",
                "security_audit", "backup_history", "mt_config",
            }
            self.assertFalse(required - tables)
            self.assertEqual(integrity, "ok")

    def test_old_database_is_upgraded_and_umbeluzi_corrected(self):
        with tempfile.TemporaryDirectory(prefix="sge-old-") as folder:
            db = Path(folder) / "sge.db"
            conn = sqlite3.connect(db)
            conn.executescript(
                """
                CREATE TABLE locais(id INTEGER PRIMARY KEY, nome TEXT UNIQUE);
                CREATE TABLE locais_cfg(local_id INTEGER PRIMARY KEY, tarifa_ponta REAL, iva REAL);
                INSERT INTO locais VALUES(1, 'ETA DE UMBELUZI');
                INSERT INTO locais_cfg VALUES(1, 4.970, 17);
                """
            )
            conn.commit(); conn.close()
            run_migrations(str(db))
            run_migrations(str(db))  # idempotência
            conn = sqlite3.connect(db)
            values = conn.execute("SELECT tarifa_ponta, iva FROM locais_cfg WHERE local_id=1").fetchone()
            history = conn.execute("SELECT tarifa_ponta, iva_rate, iva_base_factor FROM tarifas_historico WHERE local_id=1").fetchone()
            conn.close()
            self.assertEqual(values, (497.03, 16.0))
            self.assertEqual(history, (497.03, 16.0, 0.62))

    def test_backup_is_restorable_and_verified(self):
        with tempfile.TemporaryDirectory(prefix="sge-backup-test-") as folder:
            root = Path(folder); db = root / "sge.db"; uploads = root / "uploads"; backups = root / "backups"
            uploads.mkdir(); (uploads / "prova.txt").write_text("SGE", encoding="utf-8")
            run_migrations(str(db))
            result = create_backup(db, uploads, backups, retention_days=30, max_backups=3)
            checked = verify_backup(result["path"])
            self.assertTrue(result["verified"])
            self.assertTrue(checked["ok"])
            self.assertEqual(len(result["sha256"]), 64)


if __name__ == "__main__":
    unittest.main()
