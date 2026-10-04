"""Example Local AI plugin. The app runs: python main.py <input.json> <output folder>
input.json holds the parameters the AI filled in (see "parameters" in plugin.json).
Print one line: RESULT: {json}  — the AI uses it to answer. (Return {"error": "..."} if something is wrong.)"""
import ast
import json
import math
import operator
import sys

OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
       ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos}
NAMES = {"pi": math.pi, "e": math.e}
FUNCS = {f: getattr(math, f) for f in ("sqrt", "sin", "cos", "tan", "log", "log10", "exp", "floor", "ceil")} | {"abs": abs, "round": round}


def ev(n):  # only numbers, operators and the maths functions above — nothing else can run
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        return n.value
    if isinstance(n, ast.BinOp) and type(n.op) in OPS:
        return OPS[type(n.op)](ev(n.left), ev(n.right))
    if isinstance(n, ast.UnaryOp) and type(n.op) in OPS:
        return OPS[type(n.op)](ev(n.operand))
    if isinstance(n, ast.Name) and n.id in NAMES:
        return NAMES[n.id]
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in FUNCS:
        return FUNCS[n.func.id](*[ev(a) for a in n.args])
    raise ValueError("only numbers and + - * / ** % ( ) sqrt sin cos tan log pi e are allowed")


try:
    expr = json.load(open(sys.argv[1], encoding="utf-8"))["expression"].replace("^", "**").replace(",", ".")
    value = ev(ast.parse(expr, mode="eval").body)
    print("RESULT: " + json.dumps({"expression": expr, "result": round(value, 10) if isinstance(value, float) else value}))
except Exception as e:  # noqa: BLE001
    print("RESULT: " + json.dumps({"error": str(e)}))
