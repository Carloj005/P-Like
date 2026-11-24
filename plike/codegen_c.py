"""Backend Transpiler: P-Like AST -> C99 leggibile e didattico.

Nel corso di Programmazione I del Prof. Giuliano Laccetti (Federico II),
gli studenti progettano gli algoritmi in P-Like per poi tradurli in C.
Questo backend genera codice C99 pulito, commentato e pronto per gcc/clang!
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
    TypeDecl,
    TypeSpec,
    UnaryExpr,
    VarDecl,
    VarExpr,
    WhileStmt,
)
from .semantic import BUILTIN_POINTER_TYPES

C_PREAMBLE = """/* Codice C99 generato automaticamente dal compilatore P-Like (Prof. Giuliano Laccetti) */
#include <stdio.h>
#include <stdlib.h>
#include <stdbool.h>
#include <string.h>
#include <math.h>

typedef struct PLikeNode {
    int info;
    struct PLikeNode *link;
    struct PLikeNode *next;
    struct PLikeNode *prev;
} PLikeNode;

typedef PLikeNode* list_pointer;
typedef PLikeNode* stack_pointer;
typedef PLikeNode* queue_pointer;

static PLikeNode* plike_create_node(void) {
    PLikeNode *n = (PLikeNode*)calloc(1, sizeof(PLikeNode));
    return n;
}

static void plike_push(list_pointer *head, int elem) {
    PLikeNode *n = plike_create_node();
    n->info = elem;
    n->link = *head;
    n->next = *head;
    *head = n;
}

static int plike_pop(list_pointer *head, int *out_elem) {
    if (*head == NULL) return 0;
    PLikeNode *tmp = *head;
    int val = tmp->info;
    *head = tmp->link;
    free(tmp);
    if (out_elem) *out_elem = val;
    return val;
}
"""


class CCodeGenerator:
    def __init__(self) -> None:
        self.lines: List[str] = []
        self.indent = 0
        self.subprogram_sigs: Dict[str, SubprogramDecl] = {}
        self.ref_params: Set[str] = set()
        self.array_vars: Dict[str, int] = {}  # var_name -> ndims
        self.var_types: Dict[str, str] = {}
        self.current_func: Optional[str] = None

    def generate(self, program: Program) -> str:
        self.lines = [C_PREAMBLE]

        # 1. Typedef / struct per i tipi definiti dall'utente
        for td in program.type_decls:
            self._gen_typedef(td)
        if program.main:
            for td in program.main.type_decls:
                self._gen_typedef(td)

        # 2. Prototipi
        for sp in program.subprograms:
            self.subprogram_sigs[sp.name.lower()] = sp
        for sp in program.subprograms:
            self._w(self._subprogram_header(sp) + ";")
        if program.subprograms:
            self.lines.append("")

        # 3. Definizioni procedure/function
        for sp in program.subprograms:
            self._gen_subprogram(sp)
            self.lines.append("")

        # 4. Main
        if program.main:
            self._gen_main(program.main)

        return "\n".join(self.lines) + "\n"

    def _w(self, text: str) -> None:
        self.lines.append("    " * self.indent + text)

    def _c_type(self, tspec: Optional[TypeSpec]) -> str:
        if tspec is None:
            return "int"
        if isinstance(tspec, PrimitiveType):
            return {
                "integer": "int",
                "real": "double",
                "character": "char*",
                "logical": "bool",
            }.get(tspec.name.lower(), "int")
        if isinstance(tspec, PointerType):
            return f"struct {tspec.target_name}*"
        if isinstance(tspec, NamedType):
            ln = tspec.name.lower()
            if ln in BUILTIN_POINTER_TYPES:
                return ln
            return tspec.name
        if isinstance(tspec, ArrayType):
            return self._c_type(tspec.element_type)
        if isinstance(tspec, RecordType):
            return "struct"
        return "int"

    def _gen_typedef(self, td: TypeDecl) -> None:
        if isinstance(td.type_spec, RecordType):
            self._w(f"typedef struct {td.name} {{")
            self.indent += 1
            for rf in td.type_spec.fields:
                if isinstance(rf.type_spec, ArrayType):
                    ct = self._c_type(rf.type_spec.element_type)
                    self._w(f"{ct} {rf.name}[101];")
                else:
                    self._w(f"{self._c_type(rf.type_spec)} {rf.name};")
            self.indent -= 1
            self._w(f"}} {td.name};\n")
        elif isinstance(td.type_spec, PointerType):
            self._w(f"struct {td.type_spec.target_name};")
            self._w(f"typedef struct {td.type_spec.target_name}* {td.name};\n")

    def _param_type_from_vars(self, sp: SubprogramDecl, pname: str) -> Optional[TypeSpec]:
        low = pname.lower()
        for vd in sp.var_decls:
            for item in vd.items:
                if item.name.lower() == low:
                    if item.inline_bounds and not isinstance(vd.type_spec, ArrayType):
                        return ArrayType(span=vd.span, bounds=item.inline_bounds, element_type=vd.type_spec)
                    return vd.type_spec
        return None

    def _subprogram_header(self, sp: SubprogramDecl) -> str:
        ret_c = "void" if sp.kind == "procedure" else self._c_type(sp.return_type)
        c_params: List[str] = []
        for p in sp.params:
            tspec = p.type_spec or self._param_type_from_vars(sp, p.name)
            if isinstance(tspec, ArrayType):
                et = self._c_type(tspec.element_type)
                nd = max(1, len(tspec.bounds))
                if nd == 2:
                    c_params.append(f"{et} {p.name}[][101]")
                else:
                    c_params.append(f"{et} {p.name}[]")
            else:
                ct = self._c_type(tspec)
                if p.mode in ("out", "in/out", "default") and sp.kind == "procedure":
                    c_params.append(f"{ct} *{p.name}")
                else:
                    c_params.append(f"{ct} {p.name}")
        return f"{ret_c} {sp.name}({', '.join(c_params) if c_params else 'void'})"

    def _gen_subprogram(self, sp: SubprogramDecl) -> None:
        self.current_func = sp.name.lower() if sp.kind == "function" else None
        self.ref_params = set()
        self.array_vars = {}
        self.var_types = {}

        param_set = {p.name.lower() for p in sp.params}
        for p in sp.params:
            tspec = p.type_spec or self._param_type_from_vars(sp, p.name)
            if isinstance(tspec, ArrayType):
                self.array_vars[p.name.lower()] = max(1, len(tspec.bounds))
                self.var_types[p.name.lower()] = "array"
            else:
                if p.mode in ("out", "in/out", "default") and sp.kind == "procedure":
                    self.ref_params.add(p.name.lower())
                self.var_types[p.name.lower()] = self._c_type(tspec)

        self._w(self._subprogram_header(sp) + " {")
        self.indent += 1

        if sp.kind == "function":
            self._w(f"{self._c_type(sp.return_type)} _result = 0;")

        for vd in sp.var_decls:
            self._gen_var_decl(vd, param_set)

        for st in sp.body:
            self._gen_stmt(st)

        if sp.kind == "function":
            self._w("return _result;")

        self.indent -= 1
        self._w("}")
        self.current_func = None

    def _gen_main(self, main: MainProgram) -> None:
        self.current_func = None
        self.ref_params = set()
        self.array_vars = {}
        self.var_types = {}

        self._w("int main(void) {")
        self.indent += 1
        for vd in main.var_decls:
            self._gen_var_decl(vd, set())
        for st in main.body:
            self._gen_stmt(st)
        self._w("return 0;")
        self.indent -= 1
        self._w("}")

    def _gen_var_decl(self, vd: VarDecl, param_set: Set[str]) -> None:
        for item in vd.items:
            ln = item.name.lower()
            if ln in param_set:
                continue
            if isinstance(vd.type_spec, ArrayType) or item.inline_bounds:
                et = self._c_type(vd.type_spec.element_type if isinstance(vd.type_spec, ArrayType) else vd.type_spec)
                bounds = item.inline_bounds if item.inline_bounds else (vd.type_spec.bounds if isinstance(vd.type_spec, ArrayType) else [])
                nd = max(1, len(bounds))
                self.array_vars[ln] = nd
                self.var_types[ln] = "array"
                dims = "".join("[101]" for _ in range(nd))
                self._w(f"{et} {item.name}{dims} = {{0}}; /* 1-based P-Like array */")
            elif isinstance(vd.type_spec, RecordType):
                self._w("struct {")
                self.indent += 1
                for rf in vd.type_spec.fields:
                    self._w(f"{self._c_type(rf.type_spec)} {rf.name};")
                self.indent -= 1
                self._w(f"}} {item.name};")
                self.var_types[ln] = "record"
            else:
                ct = self._c_type(vd.type_spec)
                self.var_types[ln] = ct
                init = f" = {self._gen_expr(item.init_expr)}" if item.init_expr else (" = NULL" if "*" in ct or "pointer" in ct else " = 0")
                self._w(f"{ct} {item.name}{init};")

    def _gen_stmt(self, stmt: Stmt) -> None:
        if isinstance(stmt, InlineVarStmt):
            self._gen_var_decl(stmt.decl, set())
            return
        if isinstance(stmt, AssignStmt):
            lhs = self._gen_lvalue(stmt.target)
            rhs = self._gen_expr(stmt.value)
            self._w(f"{lhs} = {rhs};")
            return
        if isinstance(stmt, ReadStmt):
            for t in stmt.targets:
                lv = self._gen_lvalue(t)
                tt = t.inferred_type or "integer"
                fmt = {"integer": "%d", "real": "%lf", "character": "%s"}.get(tt, "%d")
                addr = lv if tt == "character" else f"&({lv})"
                self._w(f'scanf("{fmt}", {addr});')
            return
        if isinstance(stmt, PrintStmt):
            parts: List[str] = []
            args: List[str] = []
            for e in stmt.expressions:
                if isinstance(e, StringLiteral):
                    parts.append(e.value.replace("%", "%%").replace('"', '\\"'))
                else:
                    et = e.inferred_type or "integer"
                    if et == "real":
                        parts.append("%g")
                        args.append(self._gen_expr(e))
                    elif et == "logical":
                        parts.append("%s")
                        args.append(f"({self._gen_expr(e)} ? \".TRUE.\" : \".FALSE.\")")
                    elif et == "character":
                        parts.append("%s")
                        args.append(self._gen_expr(e))
                    else:
                        parts.append("%d")
                        args.append(f"(int)({self._gen_expr(e)})")
            fmt_str = " ".join(parts) + "\\n"
            if args:
                self._w(f'printf("{fmt_str}", {", ".join(args)});')
            else:
                self._w(f'printf("{fmt_str}");')
            return
        if isinstance(stmt, CallStmt):
            self._w(self._gen_call(stmt.callee, stmt.args) + ";")
            return
        if isinstance(stmt, IfStmt):
            for idx, br in enumerate(stmt.branches):
                kw = "if" if idx == 0 else "else if"
                self._w(f"{kw} ({self._gen_expr(br.condition)}) {{")
                self.indent += 1
                for s in br.body:
                    self._gen_stmt(s)
                self.indent -= 1
                self._w("}")
            if stmt.else_body:
                self._w("else {")
                self.indent += 1
                for s in stmt.else_body:
                    self._gen_stmt(s)
                self.indent -= 1
                self._w("}")
            return
        if isinstance(stmt, ForStmt):
            vn = stmt.var_name
            st = self._gen_expr(stmt.start)
            en = self._gen_expr(stmt.end)
            if stmt.step:
                sp = self._gen_expr(stmt.step)
                cmp_op = ">=" if (isinstance(stmt.step, UnaryExpr) and stmt.step.op == "-") else "<="
                self._w(f"for ({vn} = {st}; {vn} {cmp_op} {en}; {vn} += ({sp})) {{")
            elif stmt.downto:
                self._w(f"for ({vn} = {st}; {vn} >= {en}; {vn}--) {{")
            else:
                self._w(f"for ({vn} = {st}; {vn} <= {en}; {vn}++) {{")
            self.indent += 1
            for s in stmt.body:
                self._gen_stmt(s)
            self.indent -= 1
            self._w("}")
            return
        if isinstance(stmt, WhileStmt):
            self._w(f"while ({self._gen_expr(stmt.condition)}) {{")
            self.indent += 1
            for s in stmt.body:
                self._gen_stmt(s)
            self.indent -= 1
            self._w("}")
            return
        if isinstance(stmt, RepeatStmt):
            self._w("do {")
            self.indent += 1
            for s in stmt.body:
                self._gen_stmt(s)
            self.indent -= 1
            self._w(f"}} while (!({self._gen_expr(stmt.condition)}));")
            return
        if isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                self._w(f"return {self._gen_expr(stmt.value)};")
            elif self.current_func:
                self._w("return _result;")
            else:
                self._w("return;")
            return
        if isinstance(stmt, DeallocateStmt):
            self._w(f"free({self._gen_expr(stmt.target)});")

    def _gen_lvalue(self, expr: Expr) -> str:
        if isinstance(expr, VarExpr):
            ln = expr.name.lower()
            if self.current_func and ln == self.current_func:
                return "_result"
            if ln in self.ref_params:
                return f"(*{expr.name})"
            return expr.name
        if isinstance(expr, IndexExpr):
            base = self._gen_expr(expr.target)
            idxs = "".join(f"[{self._gen_expr(i)}]" for i in expr.indices)
            return f"{base}{idxs}"
        if isinstance(expr, CallOrIndexExpr):
            base = self._gen_expr(expr.target)
            idxs = "".join(f"[{self._gen_expr(a.expr)}]" for a in expr.args)
            return f"{base}{idxs}"
        if isinstance(expr, FieldAccessExpr):
            t_str = self._gen_expr(expr.target)
            is_ptr = expr.target.inferred_type == "pointer"
            op = "->" if is_ptr else "."
            return f"({t_str}){op}{expr.field_name}"
        return self._gen_expr(expr)

    def _gen_expr(self, expr: Expr) -> str:
        if isinstance(expr, IntLiteral):
            return str(expr.value)
        if isinstance(expr, RealLiteral):
            return repr(expr.value)
        if isinstance(expr, StringLiteral):
            esc = expr.value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{esc}"'
        if isinstance(expr, BoolLiteral):
            return "true" if expr.value else "false"
        if isinstance(expr, NullLiteral):
            return "NULL"
        if isinstance(expr, AllocateExpr):
            return "plike_create_node()"
        if isinstance(expr, VarExpr):
            ln = expr.name.lower()
            if self.current_func and ln == self.current_func:
                return "_result"
            if ln in self.ref_params:
                return f"(*{expr.name})"
            return expr.name
        if isinstance(expr, UnaryExpr):
            op = "!" if expr.op == "not" else expr.op
            return f"({op}({self._gen_expr(expr.operand)}))"
        if isinstance(expr, BinaryExpr):
            l = self._gen_expr(expr.left)
            r = self._gen_expr(expr.right)
            if expr.op == "**":
                return f"pow({l}, {r})"
            op_map = {"=": "==", "!=": "!=", "and": "&&", "or": "||", "mod": "%", "div": "/"}
            cop = op_map.get(expr.op, expr.op)
            return f"({l} {cop} {r})"
        if isinstance(expr, FieldAccessExpr):
            t_str = self._gen_expr(expr.target)
            op = "->" if expr.target.inferred_type == "pointer" else "."
            return f"({t_str}){op}{expr.field_name}"
        if isinstance(expr, IndexExpr):
            base = self._gen_expr(expr.target)
            idxs = "".join(f"[{self._gen_expr(i)}]" for i in expr.indices)
            return f"{base}{idxs}"
        if isinstance(expr, CallOrIndexExpr):
            if expr.resolved_kind == "call" and isinstance(expr.target, VarExpr):
                return self._gen_call(expr.target.name, expr.args)
            base = self._gen_expr(expr.target)
            idxs = "".join(f"[{self._gen_expr(a.expr)}]" for a in expr.args)
            return f"{base}{idxs}"
        return "0"

    def _gen_call(self, callee: str, args: List[CallArg]) -> str:
        key = callee.lower()
        if key == "create_node":
            return "plike_create_node()"
        if key in ("push", "stack_insert") and len(args) == 2:
            return f"plike_push(&({self._gen_lvalue(args[0].expr)}), {self._gen_expr(args[1].expr)})"
        if key in ("pop", "stack_delete"):
            a0 = f"&({self._gen_lvalue(args[0].expr)})"
            a1 = f"&({self._gen_lvalue(args[1].expr)})" if len(args) >= 2 else "NULL"
            return f"plike_pop({a0}, {a1})"
        if key in ("create_list", "linked_list_create", "list_create", "stack_create") and args:
            return f"({self._gen_lvalue(args[0].expr)} = NULL)"

        sp = self.subprogram_sigs.get(key)
        c_args: List[str] = []
        for idx, a in enumerate(args):
            if sp is not None and idx < len(sp.params):
                p = sp.params[idx]
                tspec = p.type_spec or self._param_type_from_vars(sp, p.name)
                if not isinstance(tspec, ArrayType) and p.mode in ("out", "in/out", "default") and sp.kind == "procedure":
                    c_args.append(f"&({self._gen_lvalue(a.expr)})")
                    continue
            c_args.append(self._gen_expr(a.expr))
        return f"{callee}({', '.join(c_args)})"
