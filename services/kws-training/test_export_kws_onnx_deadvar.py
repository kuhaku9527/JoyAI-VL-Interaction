# SPDX-License-Identifier: Apache-2.0
"""Regression test for audit section 3 / F841: removed dead var must stay gone.

Guards the fix in ``services/kws-training/export_kws_onnx.py`` where the unused
``token_table = ckpt["token_table"]`` assignment was removed from ``main()``.

Uses AST parsing only (no ``torch`` import) so the test runs in the shared pytest
matrix without heavy ML dependencies, while still pinning the removal against
reintroduction.
"""

from __future__ import annotations

import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parent / "export_kws_onnx.py"


def _main_function(tree: ast.Module) -> ast.FunctionDef | None:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "main":
            return node
    return None


def test_export_main_has_no_dead_token_table_assignment():
    assert SOURCE.exists(), f"export_kws_onnx.py not found at {SOURCE}"
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    main_fn = _main_function(tree)
    assert main_fn is not None, "export_kws_onnx.py must define main()"

    dead_assigns = [
        stmt
        for stmt in main_fn.body
        if isinstance(stmt, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "token_table" for t in stmt.targets)
    ]
    assert not dead_assigns, (
        "dead variable `token_table` must not be reintroduced in "
        "export_kws_onnx.main() (audit F841)"
    )
