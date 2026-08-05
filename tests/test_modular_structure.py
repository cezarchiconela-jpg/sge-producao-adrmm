import ast
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ModularStructureTest(unittest.TestCase):
    EXPECTED_MODULES = {
        "security", "bootstrap_runtime", "locations_core", "locations_routes",
        "dashboard_core", "dashboard_executive", "equipment_core",
        "equipment_extended", "daily_readings_core", "daily_readings_extended",
        "daily_readings_api", "monthly_readings_core", "monthly_readings_api",
        "monthly_readings_extended", "motors", "alerts", "solar",
        "administration", "compatibility", "efficiency", "operational_imports",
    }

    def test_app_is_a_small_composition_root(self):
        app_path = ROOT / "app.py"
        source = app_path.read_text(encoding="utf-8")
        self.assertLessEqual(len(source.splitlines()), 300)
        ast.parse(source, filename=str(app_path))
        self.assertIn("_load_sge_feature", source)

    def test_expected_domains_exist_and_parse(self):
        modules_dir = ROOT / "sge_modules"
        actual = {path.stem for path in modules_dir.glob("*.py") if path.name != "__init__.py"}
        self.assertEqual(actual, self.EXPECTED_MODULES)
        for name in sorted(actual):
            path = modules_dir / f"{name}.py"
            ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    def test_domain_files_remain_bounded(self):
        modules_dir = ROOT / "sge_modules"
        for path in modules_dir.glob("*.py"):
            if path.name == "__init__.py":
                continue
            with self.subTest(module=path.name):
                self.assertLessEqual(len(path.read_text(encoding="utf-8").splitlines()), 1800)


if __name__ == "__main__":
    unittest.main()
