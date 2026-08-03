import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from flask import Flask

from telemetria import DEVICE_CODE_F650, register_telemetry


class TelemetryAlertsTest(unittest.TestCase):
    def setUp(self):
        handle, self.db_path = tempfile.mkstemp(prefix="sge-telemetry-", suffix=".db")
        os.close(handle)
        conn = sqlite3.connect(self.db_path)
        conn.execute("CREATE TABLE locais (id INTEGER PRIMARY KEY, nome TEXT NOT NULL)")
        conn.execute("INSERT INTO locais(id, nome) VALUES(1, 'ETA DE UMBELUZI')")
        conn.execute(
            """
            CREATE TABLE locais_cfg (
                local_id INTEGER PRIMARY KEY,
                fator_mult REAL,
                pot_contratada REAL,
                tarifa_ativa REAL,
                tarifa_reativa REAL,
                tarifa_ponta REAL,
                taxa_fixa REAL,
                taxa_radio REAL,
                taxa_lixo REAL,
                iva REAL
            )
            """
        )
        conn.execute(
            """
            INSERT INTO locais_cfg VALUES(1, 300.0, 3500.0, 4.780, 1.430,
                                           497.03, 207.28, 297.0, 150.0, 16.0)
            """
        )
        conn.commit()
        conn.close()

        self.previous_token = os.environ.get("SGE_F650_API_TOKEN")
        os.environ["SGE_F650_API_TOKEN"] = "token-de-teste"
        app = Flask(__name__, template_folder="../templates", static_folder="../static")
        app.secret_key = "teste"
        app.testing = True
        register_telemetry(app, self.db_path)
        self.client = app.test_client()

    def tearDown(self):
        if self.previous_token is None:
            os.environ.pop("SGE_F650_API_TOKEN", None)
        else:
            os.environ["SGE_F650_API_TOKEN"] = self.previous_token
        try:
            os.unlink(self.db_path)
        except FileNotFoundError:
            pass

    def _post(self, timestamp, **overrides):
        values = {
            "tensao_ab_kv": 33.10,
            "tensao_bc_kv": 33.20,
            "tensao_ca_kv": 33.15,
            "corrente_fase_a_a": 84.0,
            "corrente_fase_b_a": 83.5,
            "corrente_fase_c_a": 84.5,
            "potencia_activa_total_mw": -3.80,
            "potencia_reactiva_total_mvar": -2.39,
            "factor_potencia_total": -0.843,
            "frequencia_hz": 50.0,
        }
        values.update(overrides)
        return self.client.post(
            "/api/v1/telemetria",
            headers={"Authorization": "Bearer token-de-teste"},
            json={
                "device": DEVICE_CODE_F650,
                "timestamp": timestamp.isoformat(),
                "quality": "good",
                "values": values,
            },
        )

    def test_values_are_processed_without_losing_raw_sign(self):
        response = self._post(datetime.now(timezone.utc) - timedelta(seconds=2))
        self.assertEqual(response.status_code, 200)
        overview = self.client.get(
            f"/telemetria/api/overview?device={DEVICE_CODE_F650}"
        ).get_json()
        channels = {item["code"]: item for item in overview["channels"]}
        self.assertEqual(channels["potencia_activa_total_mw"]["raw_value"], -3.8)
        self.assertEqual(channels["potencia_activa_total_mw"]["value"], 3.8)
        self.assertEqual(channels["potencia_activa_total_mw"]["direction"], "reverso")
        self.assertEqual(channels["factor_potencia_total"]["value"], 0.843)

    def test_power_cut_is_distinct_and_resolves_after_voltage_returns(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(self._post(now - timedelta(seconds=3)).status_code, 200)
        cut = self._post(
            now - timedelta(seconds=2),
            tensao_ab_kv=0.0,
            tensao_bc_kv=0.0,
            tensao_ca_kv=0.0,
            frequencia_hz=0.0,
            potencia_activa_total_mw=0.0,
            potencia_reactiva_total_mvar=0.0,
            factor_potencia_total=0.0,
        )
        self.assertEqual(cut.status_code, 200)
        cut_confirmed = self._post(
            now - timedelta(milliseconds=1500),
            tensao_ab_kv=0.0,
            tensao_bc_kv=0.0,
            tensao_ca_kv=0.0,
            frequencia_hz=0.0,
            potencia_activa_total_mw=0.0,
            potencia_reactiva_total_mvar=0.0,
            factor_potencia_total=0.0,
        )
        self.assertEqual(cut_confirmed.status_code, 200)
        alerts = self.client.get(
            f"/telemetria/api/alerts?device={DEVICE_CODE_F650}&hours=24"
        ).get_json()["alerts"]
        outage = next(item for item in alerts if item["alert_type"] == "corte_energia")
        self.assertEqual(outage["status"], "open")
        self.assertEqual(outage["severity"], "critical")

        restored = self._post(now - timedelta(seconds=1))
        self.assertEqual(restored.status_code, 200)
        restored_confirmed = self._post(now - timedelta(milliseconds=500))
        self.assertEqual(restored_confirmed.status_code, 200)
        alerts = self.client.get(
            f"/telemetria/api/alerts?device={DEVICE_CODE_F650}&hours=24"
        ).get_json()["alerts"]
        outage = next(item for item in alerts if item["alert_type"] == "corte_energia")
        self.assertEqual(outage["status"], "resolved")
        self.assertGreaterEqual(outage["duration_seconds"], 1)

    def test_analysis_and_pdf_report(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(self._post(now - timedelta(seconds=62)).status_code, 200)
        self.assertEqual(self._post(now - timedelta(seconds=2), potencia_activa_total_mw=-4.2).status_code, 200)
        response = self.client.get(
            f"/telemetria/api/analysis?device={DEVICE_CODE_F650}&hours=24"
        )
        self.assertEqual(response.status_code, 200)
        summary = response.get_json()["analysis"]["summary"]
        self.assertGreater(summary["energy_kwh"], 0)
        self.assertEqual(summary["measured_flow_direction"], "reverso")

        analysis = response.get_json()["analysis"]
        finance = analysis["finance"]
        self.assertAlmostEqual(
            finance["active_cost_mzn"],
            finance["active_energy_kwh"] * 4.780,
            delta=0.15,
        )
        self.assertFalse(finance["tariffs"]["factor_multiplicative_applied"])
        # O factor 300 configurado para leituras manuais não pode escalar a
        # energia real já convertida no F650.
        self.assertLess(finance["active_energy_kwh"], 1000)

        pdf = self.client.get(
            f"/telemetria/relatorio.pdf?device={DEVICE_CODE_F650}&hours=24"
        )
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.mimetype, "application/pdf")
        self.assertTrue(pdf.data.startswith(b"%PDF"))

    def test_calendar_periods_and_specific_day(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(self._post(now - timedelta(seconds=65)).status_code, 200)
        self.assertEqual(self._post(now - timedelta(seconds=5)).status_code, 200)

        today = self.client.get(
            f"/telemetria/api/analysis?device={DEVICE_CODE_F650}&period=today"
        )
        self.assertEqual(today.status_code, 200)
        today_data = today.get_json()["analysis"]
        self.assertEqual(today_data["period"]["key"], "today")
        self.assertGreater(today_data["finance"]["energy_cost_mzn"], 0)
        self.assertTrue(today_data["energy_profile"]["points"])

        maputo_day = (now + timedelta(hours=2)).strftime("%Y-%m-%d")
        selected = self.client.get(
            f"/telemetria/api/analysis?device={DEVICE_CODE_F650}&period=day&date={maputo_day}"
        )
        self.assertEqual(selected.status_code, 200)
        self.assertEqual(selected.get_json()["analysis"]["period"]["key"], "day")

    def test_long_gap_is_not_billed(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(self._post(now - timedelta(minutes=25)).status_code, 200)
        self.assertEqual(self._post(now - timedelta(seconds=5)).status_code, 200)
        analysis = self.client.get(
            f"/telemetria/api/analysis?device={DEVICE_CODE_F650}&hours=24"
        ).get_json()["analysis"]
        self.assertEqual(analysis["finance"]["active_energy_kwh"], 0)
        self.assertGreaterEqual(analysis["summary"]["ignored_data_gaps"], 1)

    def test_communication_loss_does_not_claim_power_cut(self):
        now = datetime.now(timezone.utc)
        self.assertEqual(self._post(now - timedelta(seconds=2)).status_code, 200)
        old = (now - timedelta(minutes=20)).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        conn = sqlite3.connect(self.db_path)
        conn.execute(
            "UPDATE telemetry_devices SET last_seen=? WHERE code=?",
            (old, DEVICE_CODE_F650),
        )
        conn.commit()
        conn.close()

        alerts = self.client.get(
            f"/telemetria/api/alerts?device={DEVICE_CODE_F650}&hours=24"
        ).get_json()["alerts"]
        active_types = {
            item["alert_type"]
            for item in alerts
            if item["status"] in ("open", "acknowledged")
        }
        self.assertIn("sem_comunicacao", active_types)
        self.assertNotIn("corte_energia", active_types)


if __name__ == "__main__":
    unittest.main()
