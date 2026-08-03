import importlib
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path


class SecurityPermissionsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory(prefix="sge-security-")
        root = Path(cls.folder.name)
        cls.db = root / "sge.db"
        cls.db.touch()
        os.environ.update({
            "SGE_DB_PATH": str(cls.db),
            "SGE_UPLOAD_FOLDER": str(root / "uploads"),
            "SGE_BACKUP_DIR": str(root / "backups"),
            "SGE_REQUIRE_LOGIN": "1",
            "SECRET_KEY": "segredo-apenas-para-testes",
        })
        cls.module = importlib.import_module("app")
        cls.module.app.testing = True
        conn = sqlite3.connect(cls.db)
        conn.execute("INSERT INTO locais(nome, ativo) VALUES('LOCAL DE TESTE',1)")
        cls.local_id = conn.execute("SELECT id FROM locais WHERE nome='LOCAL DE TESTE'").fetchone()[0]
        conn.commit(); conn.close()

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    def setUp(self):
        conn = sqlite3.connect(self.db)
        conn.execute("UPDATE locais SET ativo=1 WHERE id=?", (self.local_id,))
        conn.commit(); conn.close()

    def _client_for(self, role, token="csrf-teste"):
        client = self.module.app.test_client()
        with client.session_transaction() as session:
            session["sge_logged_in"] = True
            session["username"] = f"teste-{role}"
            session["role"] = role
            session["_csrf_token"] = token
        return client

    def _active(self):
        conn = sqlite3.connect(self.db)
        value = conn.execute("SELECT ativo FROM locais WHERE id=?", (self.local_id,)).fetchone()[0]
        conn.close()
        return value

    def test_state_change_is_not_available_by_get(self):
        response = self._client_for("admin").get(f"/locais/toggle/{self.local_id}")
        self.assertEqual(response.status_code, 405)
        self.assertEqual(self._active(), 1)

    def test_read_only_role_cannot_change_state(self):
        response = self._client_for("consulta").post(
            f"/locais/toggle/{self.local_id}", data={"_csrf_token": "csrf-teste"}
        )
        self.assertIn(response.status_code, (302, 403))
        self.assertEqual(self._active(), 1)

    def test_admin_needs_csrf_and_valid_request_succeeds(self):
        client = self._client_for("admin")
        invalid = client.post(f"/locais/toggle/{self.local_id}")
        self.assertIn(invalid.status_code, (302, 400))
        self.assertEqual(self._active(), 1)
        valid = client.post(f"/locais/toggle/{self.local_id}", data={"_csrf_token": "csrf-teste"})
        self.assertEqual(valid.status_code, 302)
        self.assertEqual(self._active(), 0)

    def test_invoice_api_uses_the_same_fixed_vat_rule(self):
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT OR IGNORE INTO locais_cfg(local_id) VALUES(?)", (self.local_id,))
        conn.execute(
            """UPDATE locais_cfg SET fator_mult=1, pot_contratada=500,
                      tarifa_ativa=4.78, tarifa_reativa=1.43, tarifa_ponta=497.03,
                      tarifa_perdas=4.78, taxa_fixa=207.28, taxa_radio=297,
                      taxa_lixo=150, iva=99 WHERE local_id=?""",
            (self.local_id,),
        )
        conn.execute("DELETE FROM tarifas_historico WHERE local_id=?", (self.local_id,))
        conn.execute("DELETE FROM leituras_mensais WHERE local='LOCAL DE TESTE'")
        conn.execute(
            """INSERT INTO leituras_mensais(local,data,hora,ativa,reativa,ponta,mes,ano)
               VALUES('LOCAL DE TESTE','2026-01-01','08:00',1000,500,100,'01',2026),
                     ('LOCAL DE TESTE','2026-01-31','08:00',2000,1400,300,'01',2026)"""
        )
        conn.commit(); conn.close()
        response = self._client_for("admin").post(
            "/api/leituras_mensal/calcular",
            headers={"X-CSRF-Token": "csrf-teste"},
            json={"local": "LOCAL DE TESTE", "mes": "01", "ano": 2026},
        )
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data["tarifas"]["ponta"], 497.03)
        self.assertEqual(data["taxas"]["iva_percent"], 16)
        self.assertEqual(data["taxas"]["iva_base_percent"], 62)
        self.assertAlmostEqual(data["iva"]["valor"], data["total"]["sem_iva"] * 0.62 * 0.16)

    def test_future_tariff_does_not_reprice_the_current_period(self):
        conn = sqlite3.connect(self.db)
        conn.execute("INSERT OR IGNORE INTO locais_cfg(local_id) VALUES(?)", (self.local_id,))
        conn.execute("UPDATE locais_cfg SET tarifa_ponta=497.03 WHERE local_id=?", (self.local_id,))
        conn.commit(); conn.close()
        response = self._client_for("admin").post(
            f"/locais/config/{self.local_id}",
            data={
                "_csrf_token": "csrf-teste", "fator_mult": "1", "pot_contratada": "500",
                "pot_instalada": "700", "tarifa_ativa": "5", "tarifa_reativa": "2",
                "tarifa_ponta": "999", "tarifa_perdas": "5", "taxa_fixa": "10",
                "taxa_radio": "20", "taxa_lixo": "30", "tarifa_valid_from": "2099-01-01",
            },
        )
        self.assertEqual(response.status_code, 302)
        conn = sqlite3.connect(self.db)
        current = conn.execute("SELECT tarifa_ponta, iva FROM locais_cfg WHERE local_id=?", (self.local_id,)).fetchone()
        future = conn.execute(
            "SELECT tarifa_ponta, iva_rate, iva_base_factor FROM tarifas_historico WHERE local_id=? AND valid_from='2099-01-01'",
            (self.local_id,),
        ).fetchone()
        conn.close()
        self.assertEqual(current, (497.03, 16.0))
        self.assertEqual(future, (999.0, 16.0, 0.62))

    def test_consulta_cannot_create_efficiency_measure(self):
        response = self._client_for("consulta").post(
            "/eficiencia/medidas",
            data={
                "_csrf_token": "csrf-teste", "local_id": self.local_id,
                "titulo": "Medida não autorizada", "categoria": "Operacional",
                "prioridade": "Média",
            },
        )
        self.assertIn(response.status_code, (302, 403))
        conn = sqlite3.connect(self.db)
        count = conn.execute("SELECT COUNT(*) FROM eficiencia_medidas").fetchone()[0]
        conn.close()
        self.assertEqual(count, 0)

    def test_tecnico_can_register_measure_but_cannot_create_baseline(self):
        client = self._client_for("tecnico")
        measure = client.post(
            "/eficiencia/medidas",
            data={
                "_csrf_token": "csrf-teste", "local_id": self.local_id,
                "titulo": "Otimizar horário de bombagem", "categoria": "Operacional",
                "prioridade": "Alta",
            },
        )
        self.assertEqual(measure.status_code, 302)
        baseline = client.post(
            "/eficiencia/linhas-base",
            data={
                "_csrf_token": "csrf-teste", "local_id": self.local_id,
                "nome": "Base indevida", "periodo_inicio": "2026-01",
                "periodo_fim": "2026-03", "cobertura_minima_pct": "80",
            },
        )
        self.assertIn(baseline.status_code, (302, 403))
        conn = sqlite3.connect(self.db)
        measures = conn.execute("SELECT COUNT(*) FROM eficiencia_medidas").fetchone()[0]
        baselines = conn.execute("SELECT COUNT(*) FROM eficiencia_baselines").fetchone()[0]
        conn.close()
        self.assertEqual(measures, 1)
        self.assertEqual(baselines, 0)


if __name__ == "__main__":
    unittest.main()
