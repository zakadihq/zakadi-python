"""``zakadi.models``, generated from ``openapi/openapi.yaml`` (D84, D133)."""

import ast
import importlib.metadata
import re
import unittest
from dataclasses import fields
from pathlib import Path

from zakadi import Result, Session, WebhookEvent, models


class ModelTests(unittest.TestCase):
    def test_the_dataclasses_carry_every_key_of_their_models(self) -> None:
        for model, cls in (
            (models.SessionCreated, Session),
            (models.Result, Result),
            (models.WebhookEvent, WebhookEvent),
        ):
            with self.subTest(model=model.__name__):
                names = {f.name for f in fields(cls)}
                self.assertTrue(model.__annotations__)
                self.assertLessEqual(set(model.__annotations__), names)

    def test_the_models_import_nothing_beyond_typing_extensions(self) -> None:
        tree = ast.parse(Path(models.__file__).read_text(encoding="utf-8"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported.add(node.module)
            elif isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
        stdlib = {"__future__", "builtins", "typing"}
        self.assertLessEqual(imported, stdlib | {"typing_extensions"})

    def test_typing_extensions_is_the_one_new_runtime_dependency(self) -> None:
        requires = importlib.metadata.requires("zakadi") or []
        names = {re.split(r"[^A-Za-z0-9._-]", r, maxsplit=1)[0] for r in requires}
        self.assertEqual(names, {"cryptography", "typing-extensions"})


if __name__ == "__main__":
    unittest.main()
