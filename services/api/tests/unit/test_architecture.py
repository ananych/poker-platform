"""Dependency direction guard (SDD §14): the poker domain stays pure."""

import ast
from pathlib import Path

DOMAIN = Path(__file__).resolve().parents[2] / "app" / "domain" / "poker"
FORBIDDEN = (
    "fastapi",
    "sqlalchemy",
    "starlette",
    "websockets",
    "app.api",
    "app.realtime",
    "app.persistence",
    "app.services",
    "random",
)


def test_domain_has_no_framework_imports():
    for py in DOMAIN.glob("*.py"):
        tree = ast.parse(py.read_text())
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names = [node.module]
            for n in names:
                # `random` is allowed only inside the test-only SeededRandomSource
                if n == "random" and py.name == "deck.py":
                    continue
                assert not n.startswith(FORBIDDEN), f"{py.name} imports {n}"
