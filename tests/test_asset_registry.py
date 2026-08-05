import sqlite3
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from asset_registry_service import import_registry, parse_registry_file, preview_registry
from migrations import run_migrations


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILE = PROJECT_ROOT / 'data' / 'activos_dima_todos_20260804_154738.xlsx'


class AssetRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.parsed = parse_registry_file(SOURCE_FILE)

    def _new_database(self, folder):
        path = Path(folder) / 'sge.db'
        run_migrations(str(path))
        return path

    def test_source_is_read_with_the_expected_operational_structure(self):
        self.assertEqual(len(self.parsed['rows']), 3147)
        self.assertEqual(
            Counter(row['sector_operacional'] for row in self.parsed['rows']),
            Counter({'UMBELUZI': 1021, 'SABIE': 782, 'CDs': 707, 'ADUCAO': 637}),
        )
        self.assertEqual(len({row['source_key'] for row in self.parsed['rows']}), 3147)

    def test_full_import_is_idempotent_and_creates_both_etas(self):
        with tempfile.TemporaryDirectory(prefix='sge-cadastro-') as folder:
            db_path = self._new_database(folder)
            preview = preview_registry(str(db_path), self.parsed)
            self.assertEqual(preview['total'], 3147)
            self.assertEqual(preview['locations_count'], 29)
            self.assertEqual(preview['hierarchy_nodes_count'], 428)
            self.assertEqual(preview['duplicate_keys'], 0)

            first = import_registry(str(db_path), self.parsed, actor='teste')
            second = import_registry(str(db_path), self.parsed, actor='teste')
            self.assertEqual(first['inseridos'], 3147)
            self.assertEqual(second['sem_alteracao'], 3147)

            conn = sqlite3.connect(db_path)
            try:
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM locais').fetchone()[0], 428)
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM locais WHERE nivel_hierarquia='GRUPO'").fetchone()[0], 2
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM locais WHERE nivel_hierarquia='LOCAL_PRINCIPAL'").fetchone()[0], 29
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM locais WHERE nivel_hierarquia='INSTALACAO'").fetchone()[0], 175
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM locais WHERE nivel_hierarquia='SUBINSTALACAO'").fetchone()[0], 222
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM locais WHERE tipo_local='ETA'").fetchone()[0], 2
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM locais WHERE grupo_navegacao='CD' "
                        "AND nivel_hierarquia='LOCAL_PRINCIPAL' AND sector_operacional='CDs'"
                    ).fetchone()[0],
                    26,
                )
                self.assertEqual(
                    conn.execute(
                        """SELECT COUNT(*) FROM equipamentos e
                           JOIN locais l ON l.id=e.local_id
                           JOIN locais p ON p.id=l.parent_id
                           WHERE p.nome_exibicao='Tratamento 3'"""
                    ).fetchone()[0],
                    322,
                )
                self.assertEqual(
                    conn.execute("SELECT COUNT(*) FROM equipamentos WHERE COALESCE(deleted_at,'')='' ").fetchone()[0],
                    3147,
                )
                self.assertEqual(
                    conn.execute(
                        "SELECT COUNT(*) FROM (SELECT referencia_externa FROM equipamentos "
                        "WHERE COALESCE(referencia_externa,'')<>'' GROUP BY referencia_externa HAVING COUNT(*)>1)"
                    ).fetchone()[0],
                    0,
                )
            finally:
                conn.close()

    def test_reconciliation_preserves_manual_data_and_the_existing_id(self):
        with tempfile.TemporaryDirectory(prefix='sge-reconcile-') as folder:
            db_path = self._new_database(folder)
            row = self.parsed['rows'][0]
            conn = sqlite3.connect(db_path)
            cursor = conn.execute(
                "INSERT INTO locais(nome, ativo) VALUES(?,1)", (row['local_name'],)
            )
            local_id = cursor.lastrowid
            cursor = conn.execute(
                "INSERT INTO equipamentos(nome, local_id, tag, custo_aquisicao, ativo) VALUES(?,?,?,?,1)",
                (row['nome'], local_id, 'TAG-MANUAL', 12345.67),
            )
            equipment_id = cursor.lastrowid
            conn.commit()
            conn.close()

            reduced = dict(self.parsed)
            reduced['rows'] = [row]
            result = import_registry(str(db_path), reduced, actor='teste')
            self.assertEqual(result['reconciliados'], 1)

            conn = sqlite3.connect(db_path)
            try:
                saved = conn.execute(
                    "SELECT e.id, e.tag, e.custo_aquisicao, e.referencia_externa, l.nivel_hierarquia "
                    "FROM equipamentos e JOIN locais l ON l.id=e.local_id"
                ).fetchone()
                self.assertEqual(saved[0], equipment_id)
                self.assertEqual(saved[1], 'TAG-MANUAL')
                self.assertEqual(saved[2], 12345.67)
                self.assertEqual(saved[3], row['source_key'])
                self.assertIn(saved[4], ('INSTALACAO', 'SUBINSTALACAO'))
            finally:
                conn.close()


if __name__ == '__main__':
    unittest.main()
