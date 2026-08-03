import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from efficiency_service import (
    build_baseline_snapshot,
    demand_15min,
    evaluate_month,
    month_metrics,
)
from migrations import run_migrations


class EfficiencyServiceTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="sge-efficiency-")
        self.db = Path(self.folder.name) / "sge.db"
        run_migrations(str(self.db))
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("INSERT INTO locais(nome,ativo,tipo_local) VALUES('ETA TESTE',1,'ETA')")
        self.local_id = self.conn.execute("SELECT id FROM locais WHERE nome='ETA TESTE'").fetchone()[0]
        self.conn.execute("INSERT INTO locais_cfg(local_id,pot_contratada,tarifa_ativa,tarifa_reativa,tarifa_ponta) VALUES(?,?,?,?,?)", (self.local_id, 500, 4.78, 1.43, 497.03))
        self._meter = 100000.0
        for year, month, energy in ((2026, 1, 1000), (2026, 2, 900), (2026, 3, 800), (2026, 4, 700)):
            self._insert_month(year, month, energy, 1000.0)
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.folder.cleanup()

    def _insert_month(self, year, month, energy, water):
        import calendar
        days = calendar.monthrange(year, month)[1]
        start = self._meter
        for day in range(1, days + 1):
            fraction = (day - 1) / max(days - 1, 1)
            active = start + energy * fraction
            reactive = 50000 + (active - 100000) * 0.4
            self.conn.execute(
                """INSERT INTO leituras_mensais(local,data,hora,ativa,reativa,ponta,fp,agua,mes,ano)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                ('ETA TESTE', f'{year:04d}-{month:02d}-{day:02d}', '08:00', active, reactive, 300, .92, water / days, f'{month:02d}', year),
            )
        self._meter = start + energy

    def _approve_baseline(self):
        snapshot = build_baseline_snapshot(self.conn, self.local_id, '2026-01', '2026-03')
        cursor = self.conn.execute(
            """INSERT INTO eficiencia_baselines(
                 local_id,nome,periodo_inicio,periodo_fim,cobertura_minima_pct,meses_elegiveis,
                 energia_total_kwh,agua_total_m3,custo_total_mzn,energia_media_mensal_kwh,
                 agua_media_mensal_m3,custo_medio_mensal_mzn,consumo_especifico_kwh_m3,
                 custo_especifico_mzn_m3,meses_json,estado,aprovado_por,aprovado_em)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,datetime('now','localtime'))""",
            (
                self.local_id, 'Base 2026', '2026-01', '2026-03', 80,
                snapshot['meses_elegiveis'], snapshot['energia_total_kwh'], snapshot['agua_total_m3'],
                snapshot['custo_total_mzn'], snapshot['energia_media_mensal_kwh'],
                snapshot['agua_media_mensal_m3'], snapshot['custo_medio_mensal_mzn'],
                snapshot['consumo_especifico_kwh_m3'], snapshot['custo_especifico_mzn_m3'],
                '[]', 'aprovada', 'teste',
            ),
        )
        self.conn.commit()
        return cursor.lastrowid, snapshot

    def test_month_metrics_normalise_energy_by_water(self):
        item = month_metrics(self.conn, self.local_id, 2026, 2)
        self.assertAlmostEqual(item['energia_kwh'], 900.0, places=4)
        self.assertAlmostEqual(item['agua_m3'], 1000.0, places=4)
        self.assertAlmostEqual(item['consumo_especifico_kwh_m3'], .9, places=5)
        self.assertEqual(item['cobertura_pct'], 100.0)

    def test_baseline_is_weighted_and_savings_are_verified(self):
        _, snapshot = self._approve_baseline()
        self.assertEqual(snapshot['meses_elegiveis'], 3)
        self.assertAlmostEqual(snapshot['consumo_especifico_kwh_m3'], .9, places=5)
        april = evaluate_month(self.conn, self.local_id, 2026, 4)
        self.assertAlmostEqual(april['energia_esperada_kwh'], 900.0, places=4)
        self.assertAlmostEqual(april['poupanca_energia_kwh'], 200.0, places=4)
        self.assertEqual(april['qualidade_poupanca'], 'verificada')
        self.assertEqual(april['estado_eficiencia'], 'Eficiente')

    def test_target_is_derived_from_approved_baseline(self):
        baseline_id, _ = self._approve_baseline()
        self.conn.execute(
            "INSERT INTO eficiencia_metas(local_id,ano,baseline_id,reducao_percentual,meta_kwh_m3,meta_mzn_m3) VALUES(?,?,?,?,?,?)",
            (self.local_id, 2026, baseline_id, 10, .81, 1.0),
        )
        self.conn.commit()
        april = evaluate_month(self.conn, self.local_id, 2026, 4)
        self.assertAlmostEqual(april['meta_kwh_m3'], .81, places=5)
        self.assertLess(april['desvio_meta_pct'], 0)

    def test_demand_15min_uses_observed_average_and_coverage(self):
        self.conn.executescript(
            """
            CREATE TABLE telemetry_devices(id INTEGER PRIMARY KEY,local_id INTEGER,code TEXT,name TEXT,active INTEGER);
            CREATE TABLE telemetry_channels(id INTEGER PRIMARY KEY,device_id INTEGER,code TEXT);
            CREATE TABLE telemetry_readings(id INTEGER PRIMARY KEY,device_id INTEGER,channel_id INTEGER,measured_at TEXT,value REAL,quality TEXT);
            INSERT INTO telemetry_devices VALUES(1,1,'F650-TESTE','F650 Teste',1);
            INSERT INTO telemetry_channels VALUES(1,1,'potencia_activa_total_mw');
            """
        )
        start = datetime(2026, 3, 31, 22, 0, tzinfo=timezone.utc)
        for index in range(7):
            moment = start + timedelta(minutes=5 * index)
            self.conn.execute(
                "INSERT INTO telemetry_readings(device_id,channel_id,measured_at,value,quality) VALUES(?,?,?,?,?)",
                (1, 1, moment.isoformat(), 1.0, 'good'),
            )
        self.conn.commit()
        demand = demand_15min(self.conn, self.local_id, 2026, 4)
        self.assertTrue(demand['available'])
        self.assertEqual(demand['valid_intervals'], 2)
        self.assertAlmostEqual(demand['peak_kw'], 1000.0, places=3)


if __name__ == '__main__':
    unittest.main()
