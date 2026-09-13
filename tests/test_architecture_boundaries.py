"""分层依赖边界测试。"""

import ast
import unittest
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent.parent


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


class TestArchitectureBoundaries(unittest.TestCase):
    def test_app_root_contains_only_entrypoints_and_runtime(self):
        root_modules = {
            path.name
            for path in (BASE_DIR / "app").glob("*.py")
        }
        self.assertEqual(
            root_modules,
            {"__init__.py", "cli.py", "runtime.py"},
        )

    def test_domain_does_not_depend_on_outer_layers(self):
        forbidden = (
            "fastapi",
            "langgraph",
            "sqlalchemy",
            "app.adapters",
            "app.harness",
            "app.application",
            "app.web",
        )
        for path in (BASE_DIR / "app" / "domain").glob("*.py"):
            imports = imported_modules(path)
            for module in forbidden:
                self.assertFalse(
                    any(name == module or name.startswith(module + ".") for name in imports),
                    f"{path.name} 不应依赖 {module}",
                )

    def test_application_does_not_depend_on_web_framework(self):
        for path in (BASE_DIR / "app" / "application").glob("*.py"):
            imports = imported_modules(path)
            self.assertFalse(
                any(
                    name == "fastapi" or name.startswith("fastapi.")
                    for name in imports
                )
            )

    def test_web_routes_do_not_import_persistence_or_graph(self):
        forbidden = (
            "langgraph",
            "sqlalchemy",
            "app.adapters.persistence",
            "app.harness.session_graph",
            "app.domain.answer_template",
        )
        for path in (BASE_DIR / "app" / "web").glob("*.py"):
            imports = imported_modules(path)
            for module in forbidden:
                self.assertFalse(
                    any(
                        name == module or name.startswith(module + ".")
                        for name in imports
                    ),
                    f"{path.name} 不应直接依赖 {module}",
                )


if __name__ == "__main__":
    unittest.main()
