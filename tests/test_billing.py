import sqlite3
import unittest

from billing import calculate_invoice, resolve_tariffs


class BillingEngineTest(unittest.TestCase):
    def test_central_rules_are_fixed(self):
        bill = calculate_invoice(
            active_kwh=1000,
            reactive_kvarh=900,
            measured_peak_kw=300,
            contracted_power_kw=500,
            tariffs={
                "tarifa_ativa": 4.78,
                "tarifa_reativa": 1.43,
                "tarifa_ponta": 497.03,
                "taxa_fixa": 207.28,
                "taxa_radio": 297,
                "taxa_lixo": 150,
                "iva": 99,
                "iva_base_factor": 1,
            },
        )
        self.assertAlmostEqual(bill["reactive_excess_kvarh"], 150)
        self.assertAlmostEqual(bill["billing_demand_kw"], 340)
        self.assertAlmostEqual(bill["demand_cost_mzn"], 340 * 497.03)
        self.assertEqual(bill["vat_rate"], 0.16)
        self.assertEqual(bill["vat_base_factor"], 0.62)
        self.assertAlmostEqual(bill["vat_mzn"], bill["subtotal_mzn"] * 0.62 * 0.16)

    def test_tariff_history_is_resolved_by_invoice_period(self):
        conn = sqlite3.connect(":memory:")
        conn.executescript(
            """
            CREATE TABLE tarifas_historico(
              id INTEGER PRIMARY KEY, local_id INTEGER, valid_from TEXT, valid_to TEXT,
              tarifa_ativa REAL, tarifa_reativa REAL, tarifa_ponta REAL,
              tarifa_perdas REAL, taxa_fixa REAL, taxa_radio REAL, taxa_lixo REAL,
              pot_contratada REAL
            );
            INSERT INTO tarifas_historico VALUES
              (1,1,'2025-01-01','2025-12-31',4,1,400,4,10,20,30,100),
              (2,1,'2026-01-01',NULL,5,2,497.03,5,11,21,31,120);
            """
        )
        old = resolve_tariffs(conn, 1, "2025-06-01")
        new = resolve_tariffs(conn, 1, "2026-06-01")
        conn.close()
        self.assertEqual(old["tarifa_ponta"], 400)
        self.assertEqual(new["tarifa_ponta"], 497.03)
        self.assertEqual(new["iva"], 16)
        self.assertEqual(new["iva_base_factor"], 0.62)


if __name__ == "__main__":
    unittest.main()
