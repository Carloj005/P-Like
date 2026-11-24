"""Backend Transpiler: P-Like AST -> Python 3 eseguibile standalone.

Genera codice Python leggibile e completo di micro-runtime (array 1-based,
celle per pass-by-reference, divisione intera P-Like, record, puntatori, ADT)
così che `python output.py` produca lo stesso identico comportamento della P-Like VM.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Set

from .ast_nodes import (
    AllocateExpr,
    ArrayType,
    AssignStmt,
    BinaryExpr,
    BoolLiteral,
    CallArg,
    CallOrIndexExpr,
    CallStmt,
    DeallocateStmt,
    Expr,
    FieldAccessExpr,
    ForStmt,
    IfStmt,
    IndexExpr,
    InlineVarStmt,
    IntLiteral,
    MainProgram,
    NamedType,
    NullLiteral,
    PointerType,
    PrimitiveType,
    PrintStmt,
    Program,
    ReadStmt,
    RealLiteral,
    RecordType,
    RepeatStmt,
    ReturnStmt,
    Stmt,
    StringLiteral,
    SubprogramDecl,
    TypeSpec,
    UnaryExpr,
    VarDecl,
    VarExpr,
    WhileStmt,
)
from .compiler import BUILTIN_BYREF_PARAMS

PY_PREAMBLE = '''"""Codice Python generato automaticamente dal compilatore P-Like (Prof. Giuliano Laccetti)."""
import math
import sys

class _Ref:
    def get(self): raise NotImplementedError
    def set(self, v): raise NotImplementedError

class _Cell(_Ref):
    def __init__(self, v=0): self.v = v
    def get(self): return self.v
    def set(self, v): self.v = v

class _FieldRef(_Ref):
    def __init__(self, obj, field): self.obj, self.field = obj, field
    def get(self): return self.obj.get_field(self.field)
    def set(self, v): self.obj.set_field(self.field, v)

class _IdxRef(_Ref):
    def __init__(self, arr, idxs): self.arr, self.idxs = arr, idxs
    def get(self): return self.arr.get(self.idxs)
    def set(self, v): self.arr.set(self.idxs, v)

class _PLikeArray:
    def __init__(self, default_fn=lambda: 0):
        self.default_fn = default_fn
        self.data = {}
    def get(self, idxs):
        key = tuple(int(i) for i in idxs)
        if key not in self.data:
            self.data[key] = self.default_fn()
        return self.data[key]
    def set(self, idxs, v):
        self.data[tuple(int(i) for i in idxs)] = v
    def copy(self):
        c = _PLikeArray(self.default_fn)
        c.data = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in self.data.items()}
        return c

class _PLikeRecord:
    def __init__(self, fields=None):
        self.fields = dict(fields) if fields else {}
    def get_field(self, f):
        return self.fields.get(f, None if f in ("link", "next", "prev") else 0)
    def set_field(self, f, v):
        self.fields[f] = v

def _plike_div(a, b):
    if isinstance(a, int) and not isinstance(a, bool) and isinstance(b, int) and not isinstance(b, bool):
        return int(a / b)
    return float(a) / float(b)

def _plike_fmt(v):
    if isinstance(v, bool): return ".TRUE." if v else ".FALSE."
    if v is None: return "NULL"
    if isinstance(v, float): return f"{v:g}" if abs(v - round(v)) > 1e-12 else f"{v:.1f}"
    return str(v)

def _plike_print(*vals):
    print(" ".join(_plike_fmt(v) for v in vals))

_IN_TOKENS = []
def _plike_read(ref, kind="any"):
    while not _IN_TOKENS:
        line = sys.stdin.readline()
        if line == "": raise EOFError("Fine input durante read")
        if kind == "character":
            s = line.rstrip("\\r\\n")
            if not s: continue
            parts = s.split()
            _IN_TOKENS.extend(parts if len(parts) > 1 else [s])
        else:
            _IN_TOKENS.extend(line.replace(",", " ").split())
    tok = _IN_TOKENS.pop(0)
    if kind == "integer": ref.set(int(float(tok)))
    elif kind == "real": ref.set(float(tok))
    elif kind == "logical": ref.set(tok.strip().lower().strip(".") in ("true", "vero", "1", "t", "s"))
    elif kind == "character": ref.set(tok)
    else:
        try: ref.set(int(tok))
        except ValueError:
            try: ref.set(float(tok))
            except ValueError: ref.set(tok)

def _plike_create_node(*_): return _PLikeRecord({"info": 0, "link": None, "next": None, "prev": None})
def _plike_create_list(h): h.set(None); return None
def _plike_push(h, elem):
    n = _plike_create_node()
    n.set_field("info", elem); n.set_field("link", h.get()); n.set_field("next", h.get())
    h.set(n); return n
def _plike_pop(h, out=None):
    n = h.get(); val = n.get_field("info"); h.set(n.get_field("link"))
    if isinstance(out, _Ref): out.set(val)
    return val
def _plike_swap(a, b):
    t = a.get(); a.set(b.get()); b.set(t)
def _plike_is_odd(n): return int(n) % 2 != 0
def _plike_is_even(n): return int(n) % 2 == 0
'''


class PythonCodeGenerator:
    def __init__(self) -> None:
        self.lines: List[str] = []
        self.indent = 0
        self.subprogram_modes: Dict[str, List[str]] = {}
        self.current_func: Optional[str] = None
        self.type_table: Dict[str, TypeSpec] = {}

    def generate(self, program: Program) -> str:
        self.lines = [PY_PREAMBLE]
        for td in program.type_decls:
            self.type_table[td.name.lower()] = td.type_spec
        if program.main:
            for td in program.main.type_decls:
                self.type_table[td.name.lower()] = td.type_spec

        for sp in program.subprograms:
            self.subprogram_modes[sp.name.lower()] = [p.mode for p in sp.params]

        for sp in program.subprograms:
            self._gen_subprogram(sp)
            self.lines.append("")

        if program.main:
            self._gen_main(program.main)
            self.lines.append("")
            self.lines.append('if __name__ == "__main__":')
            self.lines.append("    _plike_main()")

        return "\n".join(self.lines) + "\n"

    def _w(self, text: str) -> None:
        self.lines.append("    " * self.indent + text)

    def _safe_id(self, name: str) -> str:
        low = name.lower()
        if self.current_func and low == self.current_func:
            return "_result"
        return f"v_{low}"

    def _default_py_expr(self, tspec: Optional[TypeSpec]) -> str:
        if tspec is None:
            return "0"
        if isinstance(tspec, PrimitiveType):
            return {"integer": "0", "real": "0.0", "character": "''", "logical": "False"}.get(tspec.name.lower(), "0")
        if isinstance(tspec, PointerType):
            return "None"
        if isinstance(tspec, ArrayType):
            return f"_PLikeArray(lambda: {self._default_py_expr(tspec.element_type)})"
        if isinstance(tspec, RecordType):
            pairs = ", ".join(f"{rf.name.lower()!r}: {self._default_py_expr(rf.type_spec)}" for rf in tspec.fields)
            return f"_PLikeRecord({{{pairs}}})"
        if isinstance(tspec, NamedType):
            ln = tspec.name.lower()
            if ln in self.type_table:
                return self._default_py_expr(self.type_table[ln])
            return "None"
        return "0"

    def _gen_subprogram(self, sp: SubprogramDecl) -> None:
        self.current_func = sp.name.lower() if sp.kind == "function" else None
        params_str = ", ".join(f"p_{p.name.lower()}" for p in sp.params)
        self._w(f"def fn_{sp.name.lower()}({params_str}):")
        self.indent += 1

        param_set: Set[str] = set()
        for p in sp.params:
            pn = p.name.lower()
            param_set.add(pn)
            if p.mode in ("out", "in/out", "default"):
                self._w(f"v_{pn} = p_{pn} if isinstance(p_{pn}, _Ref) else _Cell(p_{pn})")
            else:
                self._w(
                    f"_raw_{pn} = p_{pn}.get() if isinstance(p_{pn}, _Ref) else p_{pn}"
                )
                self._w(
                    f"v_{pn} = _Cell(_raw_{pn}.copy() if isinstance(_raw_{pn}, _PLikeArray) else _raw_{pn})"
                )

        if sp.kind == "function":
            self._w(f"_result = _Cell({self._default_py_expr(sp.return_type)})")

        for vd in sp.var_decls:
            self._gen_var_decl(vd, param_set)

        if not sp.body:
            self._w("pass")
        else:
            for st in sp.body:
                self._gen_stmt(st)

        if sp.kind == "function":
            self._w("return _result.get()")

        self.indent -= 1
        self.current_func = None

    def _gen_main(self, main: MainProgram) -> None:
        self.current_func = None
        self._w("def _plike_main():")
        self.indent += 1
        for vd in main.var_decls:
            self._gen_var_decl(vd, set())
        if not main.body:
            self._w("pass")
        else:
            for st in main.body:
                self._gen_stmt(st)
        self.indent -= 1

    def _gen_var_decl(self, vd: VarDecl, param_set: Set[str]) -> None:
        for item in vd.items:
            ln = item.name.lower()
            if ln in param_set:
                if item.init_expr:
                    self._w(f"v_{ln}.set({self._gen_expr(item.init_expr)})")
                continue
            if item.init_expr:
                init = self._gen_expr(item.init_expr)
            elif item.inline_bounds and not isinstance(vd.type_spec, ArrayType):
                init = f"_PLikeArray(lambda: {self._default_py_expr(vd.type_spec)})"
            else:
                init = self._default_py_expr(vd.type_spec)
            self._w(f"v_{ln} = _Cell({init})")

    def _gen_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, InlineVarStmt):
            self._gen_var_decl(stmt.decl, set())
            return
        if isinstance(stmt, AssignStmt):
            val = self._gen_expr(stmt.value)
            self._w(f"{self._gen_ref(stmt.target)}.set({val})")
            return
        if isinstance(stmt, ReadStmt):
            for t in stmt.targets:
                kind = t.inferred_type or "any"
                self._w(f"_plike_read({self._gen_ref(t)}, {kind!r})")
            return
        if isinstance(stmt, PrintStmt):
            args = ", ".join(self._gen_expr(e) for e in stmt.expressions)
            self._w(f"_plike_print({args})")
            return
        if isinstance(stmt, CallStmt):
            self._w(self._gen_call_expr(stmt.callee, stmt.args))
            return
        if isinstance(stmt, IfStmt):
            for idx, br in enumerate(stmt.branches):
                kw = "if" if idx == 0 else "elif"
                self._w(f"{kw} {self._gen_expr(br.condition)}:")
                self.indent += 1
                if not br.body:
                    self._w("pass")
                else:
                    for s in br.body:
                        self._gen_stmt(s)
                self.indent -= 1
            if stmt.else_body:
                self._w("else:")
                self.indent += 1
                for s in stmt.else_body:
                    self._gen_stmt(s)
                self.indent -= 1
            return
        if isinstance(stmt, ForStmt):
            vn = self._safe_id(stmt.var_name)
            st = self._gen_expr(stmt.start)
            en = self._gen_expr(stmt.end)
            sp = self._gen_expr(stmt.step) if stmt.step else ("-1" if stmt.downto else "1")
            self._w(f"if {vn!r} not in locals(): {vn} = _Cell(0)")
            self._w(f"{vn}.set({st})")
            self._w(f"_for_end = {en}; _for_step = {sp}")
            self._w(f"while ({vn}.get() <= _for_end if _for_step >= 0 else {vn}.get() >= _for_end):")
            self.indent += 1
            for s in stmt.body:
                self._gen_stmt(s)
            self._w(f"{vn}.set({vn}.get() + _for_step)")
            self.indent -= 1
            return
        if isinstance(stmt, WhileStmt):
            self._w(f"while {self._gen_expr(stmt.condition)}:")
            self.indent += 1
            if not stmt.body:
                self._w("pass")
            else:
                for s in stmt.body:
                    self._gen_stmt(s)
            self.indent -= 1
            return
        if isinstance(stmt, RepeatStmt):
            self._w("while True:")
            self.indent += 1
            for s in stmt.body:
                self._gen_stmt(s)
            self._w(f"if {self._gen_expr(stmt.condition)}: break")
            self.indent -= 1
            return
        if isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                self._w(f"return {self._gen_expr(stmt.value)}")
            elif self.current_func:
                self._w("return _result.get()")
            else:
                self._w("return")
            return
        if isinstance(stmt, DeallocateStmt):
            self._w(f"pass  # dealloca {self._gen_expr(stmt.target)}")

    def _gen_ref(self, expr: Expr) -> str:
        if isinstance(expr, VarExpr):
            return self._safe_id(expr.name)
        if isinstance(expr, FieldAccessExpr):
            return f"_FieldRef({self._gen_expr(expr.target)}, {expr.field_name.lower()!r})"
        if isinstance(expr, IndexExpr):
            idxs = ", ".join(self._gen_expr(i) for i in expr.indices)
            return f"_IdxRef({self._gen_expr(expr.target)}, ({idxs},))"
        if isinstance(expr, CallOrIndexExpr):
            idxs = ", ".join(self._gen_expr(a.expr) for a in expr.args)
            return f"_IdxRef({self._gen_expr(expr.target)}, ({idxs},))"
        return f"_Cell({self._gen_expr(expr)})"

    def _gen_expr(self, expr: Expr) -> str:
        if isinstance(expr, IntLiteral):
            return repr(expr.value)
        if isinstance(expr, RealLiteral):
            return repr(expr.value)
        if isinstance(expr, StringLiteral):
            return repr(expr.value)
        if isinstance(expr, BoolLiteral):
            return "True" if expr.value else "False"
        if isinstance(expr, NullLiteral):
            return "None"
        if isinstance(expr, AllocateExpr):
            return "_plike_create_node()"
        if isinstance(expr, VarExpr):
            return f"{self._safe_id(expr.name)}.get()"
        if isinstance(expr, UnaryExpr):
            if expr.op == "not":
                return f"(not ({self._gen_expr(expr.operand)}))"
            return f"({expr.op}({self._gen_expr(expr.operand)}))"
        if isinstance(expr, BinaryExpr):
            l = self._gen_expr(expr.left)
            r = self._gen_expr(expr.right)
            if expr.op == "/":
                return f"_plike_div({l}, {r})"
            if expr.op == "div":
                return f"int(int({l}) / int({r}))"
            if expr.op == "mod":
                return f"(int({l}) % int({r}))"
            op_map = {"=": "==", "!=": "!=", "and": "and", "or": "or"}
            py_op = op_map.get(expr.op, expr.op)
            return f"({l} {py_op} {r})"
        if isinstance(expr, FieldAccessExpr):
            return f"({self._gen_expr(expr.target)}).get_field({expr.field_name.lower()!r})"
        if isinstance(expr, IndexExpr):
            idxs = ", ".join(self._gen_expr(i) for i in expr.indices)
            return f"({self._gen_expr(expr.target)}).get(({idxs},))"
        if isinstance(expr, CallOrIndexExpr):
            if expr.resolved_kind == "call" and isinstance(expr.target, VarExpr):
                return self._gen_call_expr(expr.target.name, expr.args)
            idxs = ", ".join(self._gen_expr(a.expr) for a in expr.args)
            return f"({self._gen_expr(expr.target)}).get(({idxs},))"
        return "0"

    def _gen_call_expr(self, callee: str, args: List[CallArg]) -> str:
        key = callee.lower()
        builtin_map = {
            "abs": "abs",
            "sqrt": "math.sqrt",
            "int": "int",
            "trunc": "int",
            "floor": "math.floor",
            "ceil": "math.ceil",
            "real": "float",
            "min": "min",
            "max": "max",
            "is_odd": "_plike_is_odd",
            "is_even": "_plike_is_even",
            "create_node": "_plike_create_node",
            "create_list": "_plike_create_list",
            "linked_list_create": "_plike_create_list",
            "list_create": "_plike_create_list",
            "stack_create": "_plike_create_list",
            "push": "_plike_push",
            "stack_insert": "_plike_push",
            "pop": "_plike_pop",
            "stack_delete": "_plike_pop",
            "swap": "_plike_swap",
        }
        modes = self.subprogram_modes.get(key)
        brefs = BUILTIN_BYREF_PARAMS.get(key, set())
        rendered: List[str] = []
        for idx, a in enumerate(args):
            is_ref = False
            if modes is not None and idx < len(modes):
                is_ref = modes[idx] in ("out", "in/out", "default")
            elif key in BUILTIN_BYREF_PARAMS:
                is_ref = idx in brefs
            if is_ref and isinstance(a.expr, (VarExpr, FieldAccessExpr, IndexExpr, CallOrIndexExpr)):
                rendered.append(self._gen_ref(a.expr))
            else:
                rendered.append(self._gen_expr(a.expr))
        fn_name = builtin_map.get(key, f"fn_{key}")
        return f"{fn_name}({', '.join(rendered)})"
