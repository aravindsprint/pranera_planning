"""Guard: a function that calls frappe's translation helper `_()` must never also assign
to `_` (e.g. `allowed, *_ = ...` or `for (_, x) in ...`). Python then treats `_` as a local
for the WHOLE function, so every `_("...")` call crashes — and since the Stock Entry check
lets entries through when it crashes, the protection silently disappears.

Pure AST scan: runs anywhere, no frappe needed.
"""
import ast
import pathlib
import unittest

APP = pathlib.Path(__file__).resolve().parents[1]


def _own_nodes(fn):
    """Nodes in fn's own scope — not inside nested functions, lambdas or comprehensions."""
    todo = list(ast.iter_child_nodes(fn))
    while todo:
        node = todo.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda,
                             ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            continue
        yield node
        todo.extend(ast.iter_child_nodes(node))


class TestNoTranslationShadowing(unittest.TestCase):
    def test_no_function_assigns_and_calls_underscore(self):
        offenders = []
        for path in APP.rglob("*.py"):
            tree = ast.parse(path.read_text())
            for fn in ast.walk(tree):
                if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                nodes = list(_own_nodes(fn))
                assigns = any(isinstance(n, ast.Name) and n.id == "_" and isinstance(n.ctx, ast.Store) for n in nodes)
                calls = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_" for n in nodes)
                if assigns and calls:
                    offenders.append(f"{path.relative_to(APP)}:{fn.lineno} {fn.name}")
        self.assertEqual(offenders, [], "functions that shadow _() — rename the throwaway variable")


if __name__ == "__main__":
    unittest.main()
