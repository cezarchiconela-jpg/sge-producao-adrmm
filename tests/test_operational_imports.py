import io, sqlite3, tempfile, unittest
from datetime import date
from pathlib import Path
from openpyxl import Workbook

from efficiency_service import month_metrics
from migrations import run_migrations
from operational_import_service import match_local, parse_workbook


class OperationalImportTest(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(prefix="sge-operational-")
        self.db=Path(self.folder.name)/"sge.db"; run_migrations(str(self.db))
        self.conn=sqlite3.connect(self.db); self.conn.row_factory=sqlite3.Row
        self.conn.execute("INSERT INTO locais(nome,ativo,tipo_local) VALUES('CD Guava',1,'CD')")
        self.local_id=self.conn.execute("SELECT id FROM locais WHERE nome='CD Guava'").fetchone()[0]
        self.conn.commit()

    def tearDown(self): self.conn.close(); self.folder.cleanup()

    def _standard(self):
        wb=Workbook(); ws=wb.active; ws.title="Dados"
        ws.append(["Local","Data","Energia kWh","Água m3","Horas operação","Tipo dado"])
        ws.append(["Guava",date(2026,1,1),100,1000,18,"medido"])
        ws.append(["CD Guava",date(2026,1,2),120,1100,19,"medido"])
        output=io.BytesIO(); wb.save(output); return output.getvalue()

    def test_standard_parser_and_alias_mapping(self):
        parsed=parse_workbook(self._standard(),"energia_edm.xlsx")
        self.assertEqual(len(parsed["records"]),2)
        self.assertEqual(parsed["records"][0]["site"],"CD Guava")
        self.assertEqual(match_local(self.conn,"Guava"),self.local_id)

    def test_operational_data_has_priority_without_multiplication(self):
        self.conn.execute("""INSERT INTO operacional_dados(local_id,data,energia_kwh,volume_distribuido_m3,fonte,estado)
                           VALUES(?,?,?,?,?,'validado')""",(self.local_id,"2026-01-01",100,1000,"PIGI"))
        self.conn.execute("""INSERT INTO operacional_dados(local_id,data,energia_kwh,volume_distribuido_m3,fonte,estado)
                           VALUES(?,?,?,?,?,'validado')""",(self.local_id,"2026-01-01",99,990,"EDM_PLANILHA"))
        self.conn.commit(); result=month_metrics(self.conn,self.local_id,2026,1)
        self.assertEqual(result["energia_kwh"],99)
        self.assertEqual(result["agua_m3"],1000)
        self.assertEqual(result["fonte_energia"],"EDM_PLANILHA")
        self.assertEqual(result["fonte_agua"],"PIGI")
        self.assertAlmostEqual(result["consumo_especifico_kwh_m3"],.099)


if __name__=="__main__": unittest.main()
