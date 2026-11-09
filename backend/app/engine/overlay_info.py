"""오버레이 폴더를 실행하지 않고(ast) 무엇을 고쳤는지 읽는다 — 화면 표시용."""

from __future__ import annotations

import ast
from pathlib import Path


def overlay_summary(overlay: Path) -> list[dict]:
    out = []
    for p in sorted(overlay.glob("*.py")):
        if p.name.startswith("_"):
            continue
        tree = ast.parse(p.read_text(encoding="utf-8"))
        doc_first = ((ast.get_docstring(tree) or "").strip().splitlines() or [""])[0]
        fixes: dict = {"preprocess_raw": doc_first}
        for node in tree.body:
            if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "FIXES" for t in node.targets):
                try:
                    fixes = ast.literal_eval(node.value)
                except ValueError:
                    fixes = {}
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and (node.name.startswith("REME_") or node.name == "preprocess_raw"):
                out.append(
                    {
                        "file": p.name,
                        "function": node.name,
                        "rule": node.name.replace("_", "-", 1) if node.name.startswith("REME_") else None,
                        "note": fixes.get(node.name, ""),
                        "line": node.lineno,
                    }
                )
    return out
