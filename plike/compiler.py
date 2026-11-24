"""Compilatore AST -> Bytecode P-Like (.plbc)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple

from .ast_nodes import (
    AllocateExpr,
    ArrayBound,
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
from .bytecode import CompiledProgram, CompiledUnit, Instruction, OpCode, ParamSpec
from .semantic import BUILTIN_POINTER_TYPES

# Indici dei parametri passati per riferimento nelle procedure/funzioni built-in
BUILTIN_BYREF_PARAMS: Dict[str, Set[int]] = {
    "create_list": {0},
    "linked_list_create": {0},
    "list_create": {0},
    "stack_create": {0},
    "push": {0},
    "stack_insert": {0},
    "pop": {0, 1},
    "stack_delete": {0, 1},
    "list_insert": {0},
    "queue_create": {0, 1},
    "queue_insert": {0, 1},
    "queue_delete": {0, 1, 2},
    "swap": {0, 1},
}


class BytecodeCompiler:
    def __init__(self, source_name: str = "<input>"):
        self.source_name = source_name
        self.type_table: Dict[str, TypeSpec] = {}
        self.record_schemas: Dict[str, Dict[str, Any]] = {}
        self.subprogram_params: Dict[str, List[ParamSpec]] = {}
        self.current_instructions: List[Instruction] = []
        self.current_func_name: Optional[str] = None
        self.current_var_types: Dict[str, str] = {}
        self.temp_counter = 0

    def compile(self, program: Program) -> CompiledProgram:
        # 1. Raccogli tutti gli schemi record / tipi derivati
        for td in program.type_decls:
            self.type_table[td.name.lower()] = td.type_spec
        if program.main:
            for td in program.main.type_decls:
                self.type_table[td.name.lower()] = td.type_spec
        for name, tspec in self.type_table.items():
            if isinstance(tspec, RecordType):
                self.record_schemas[name] = self._describe_type(tspec)

        # 2. Registra le firme di tutti i sottoprogrammi (per pass-by-ref vs by-val!)
        for sp in program.subprograms:
            self.subprogram_params[sp.name.lower()] = [
                ParamSpec(name=p.name.lower(), mode=p.mode) for p in sp.params
            ]

        units: Dict[str, CompiledUnit] = {}
        for sp in program.subprograms:
            unit = self._compile_subprogram(sp)
            units[sp.name.lower()] = unit

        entry_unit: Optional[str] = None
        if program.main is not None:
            main_unit = self._compile_main(program.main)
            entry_key = "__main__"
            units[entry_key] = main_unit
            entry_unit = entry_key

        return CompiledProgram(
            source_name=self.source_name,
            record_schemas=self.record_schemas,
            units=units,
            entry_unit=entry_unit,
        )

    # ------------------------------------------------------------------
    # Descrizione tipi per inizializzazione runtime
    # ------------------------------------------------------------------

    def _type_tag(self, tspec: Optional[TypeSpec]) -> str:
        if tspec is None:
            return "any"
        if isinstance(tspec, PrimitiveType):
            return tspec.name.lower()
        if isinstance(tspec, ArrayType):
            return "array"
        if isinstance(tspec, RecordType):
            return "record"
        if isinstance(tspec, PointerType):
            return "pointer"
        if isinstance(tspec, NamedType):
            ln = tspec.name.lower()
            if ln in BUILTIN_POINTER_TYPES:
                return "pointer"
            if ln in self.type_table:
                return self._type_tag(self.type_table[ln])
            return "record"
        return "any"

    def _describe_type(self, tspec: Optional[TypeSpec]) -> Dict[str, Any]:
        if tspec is None:
            return {"kind": "any"}
        if isinstance(tspec, PrimitiveType):
            return {"kind": tspec.name.lower()}
        if isinstance(tspec, PointerType):
            return {"kind": "pointer", "target": tspec.target_name.lower()}
        if isinstance(tspec, NamedType):
            ln = tspec.name.lower()
            if ln in BUILTIN_POINTER_TYPES:
                return {"kind": "pointer", "target": ln}
            if ln in self.type_table:
                return self._describe_type(self.type_table[ln])
            return {"kind": "record", "type_name": ln, "fields": {}}
        if isinstance(tspec, RecordType):
            return {
                "kind": "record",
                "fields": {rf.name.lower(): self._describe_type(rf.type_spec) for rf in tspec.fields},
            }
        if isinstance(tspec, ArrayType):
            return {
                "kind": "array",
                "elem": self._describe_type(tspec.element_type),
                "ndims": len(tspec.bounds),
            }
        return {"kind": "any"}

    def _emit(self, op: OpCode, arg: Any = None, line: int = 0) -> int:
        idx = len(self.current_instructions)
        self.current_instructions.append(Instruction(op=op, arg=arg, line=line))
        return idx

    def _patch(self, idx: int, target: int) -> None:
        self.current_instructions[idx].arg = target

    def _new_temp(self, prefix: str = "tmp") -> str:
        self.temp_counter += 1
        return f"__{prefix}_{self.temp_counter}__"

    # ------------------------------------------------------------------
    # Compilazione unità
    # ------------------------------------------------------------------

    def _compile_subprogram(self, sp: SubprogramDecl) -> CompiledUnit:
        self.current_instructions = []
        self.current_func_name = sp.name.lower() if sp.kind == "function" else None
        self.current_var_types = {}

        saved_types = dict(self.type_table)
        for td in sp.type_decls:
            self.type_table[td.name.lower()] = td.type_spec
            if isinstance(td.type_spec, RecordType):
                self.record_schemas[td.name.lower()] = self._describe_type(td.type_spec)

        # Inizializza la variabile di ritorno __result__ per le function
        ret_tag = "void"
        if sp.kind == "function":
            ret_tag = self._type_tag(sp.return_type)
            self._emit(
                OpCode.INIT_VAR,
                {"name": "__result__", "type": self._describe_type(sp.return_type), "is_param_redecl": False},
                line=sp.span.line,
            )

        param_names = {p.name.lower() for p in sp.params}
        for p in sp.params:
            if p.type_spec:
                self.current_var_types[p.name.lower()] = self._type_tag(p.type_spec)

        for vd in sp.var_decls:
            self._compile_var_decl(vd, param_names)

        for st in sp.body:
            self._compile_stmt(st)

        if sp.kind == "function":
            self._emit(OpCode.LOAD_VAR, "__result__", line=sp.span.line)
            self._emit(OpCode.RET, None, line=sp.span.line)
        else:
            self._emit(OpCode.RET_VOID, None, line=sp.span.line)

        self.type_table = saved_types
        self.current_func_name = None

        return CompiledUnit(
            name=sp.name,
            kind=sp.kind,
            params=[ParamSpec(name=p.name.lower(), mode=p.mode) for p in sp.params],
            return_type=ret_tag,
            instructions=self.current_instructions,
        )

    def _compile_main(self, main: MainProgram) -> CompiledUnit:
        self.current_instructions = []
        self.current_func_name = None
        self.current_var_types = {}

        for vd in main.var_decls:
            self._compile_var_decl(vd, set())

        for st in main.body:
            self._compile_stmt(st)

        self._emit(OpCode.HALT, None, line=main.span.line)

        return CompiledUnit(
            name=main.name or "main",
            kind="main",
            params=[],
            return_type="void",
            instructions=self.current_instructions,
        )

    def _compile_var_decl(self, vd: VarDecl, param_names: Set[str]) -> None:
        for item in vd.items:
            vname = item.name.lower()
            is_param = vname in param_names
            tdesc = self._describe_type(vd.type_spec)
            bounds: Optional[List[ArrayBound]] = None

            if isinstance(vd.type_spec, ArrayType):
                bounds = item.inline_bounds if item.inline_bounds else vd.type_spec.bounds
                tdesc["ndims"] = len(bounds)
                self.current_var_types[vname] = "array"
            elif item.inline_bounds:
                bounds = item.inline_bounds
                tdesc = {"kind": "array", "elem": tdesc, "ndims": len(bounds)}
                self.current_var_types[vname] = "array"
            else:
                self.current_var_types[vname] = self._type_tag(vd.type_spec)

            # Inizializza la variabile (se è parametro già bindato, INIT_VAR non lo sovrascrive ma può adattare array out!)
            # Per i bounds statici (es. [1..10]), li passiamo come costanti se valutabili staticamente;
            # i bounds con variabili non ancora lette (es. A[m, n] prima di `read m, n`) diventano dinamici!
            static_bounds: List[Tuple[int, Optional[int]]] = []
            if bounds:
                for b in bounds:
                    low_val = self._try_eval_const_int(b.low) if b.low is not None else 1
                    high_val = self._try_eval_const_int(b.high) if b.high is not None else None
                    static_bounds.append((low_val if low_val is not None else 1, high_val))

            tdesc["static_bounds"] = static_bounds
            self._emit(
                OpCode.INIT_VAR,
                {"name": vname, "type": tdesc, "is_param_redecl": is_param},
                line=(item.span or vd.span).line,
            )

            if item.init_expr is not None:
                self._compile_expr(item.init_expr)
                self._emit(OpCode.STORE_VAR, vname, line=(item.span or vd.span).line)

    def _try_eval_const_int(self, expr: Optional[Expr]) -> Optional[int]:
        if expr is None:
            return None
        if isinstance(expr, IntLiteral):
            return expr.value
        if isinstance(expr, UnaryExpr) and expr.op == "-":
            inner = self._try_eval_const_int(expr.operand)
            return -inner if inner is not None else None
        if isinstance(expr, BinaryExpr):
            l = self._try_eval_const_int(expr.left)
            r = self._try_eval_const_int(expr.right)
            if l is not None and r is not None:
                if expr.op == "+":
                    return l + r
                if expr.op == "-":
                    return l - r
                if expr.op == "*":
                    return l * r
        return None

    # ------------------------------------------------------------------
    # Statements
    # ------------------------------------------------------------------

    def _compile_stmt(self, stmt: Stmt) -> None:
        line = stmt.span.line

        if isinstance(stmt, InlineVarStmt):
            self._compile_var_decl(stmt.decl, set())
            return

        if isinstance(stmt, AssignStmt):
            self._compile_assign(stmt.target, stmt.value, line)
            return

        if isinstance(stmt, ReadStmt):
            for t in stmt.targets:
                self._compile_ref(t)
                hint_type = t.inferred_type or "any"
                self._emit(OpCode.READ_REF, hint_type, line=line)
            return

        if isinstance(stmt, PrintStmt):
            for e in stmt.expressions:
                self._compile_expr(e)
            self._emit(OpCode.PRINT, len(stmt.expressions), line=line)
            return

        if isinstance(stmt, CallStmt):
            self._compile_call(stmt.callee, stmt.args, expect_return=False, line=line)
            return

        if isinstance(stmt, IfStmt):
            end_jumps: List[int] = []
            for br in stmt.branches:
                self._compile_expr(br.condition)
                jmp_false = self._emit(OpCode.JMP_IF_FALSE, -1, line=br.span.line)
                for s in br.body:
                    self._compile_stmt(s)
                end_jumps.append(self._emit(OpCode.JMP, -1, line=br.span.line))
                self._patch(jmp_false, len(self.current_instructions))
            for s in stmt.else_body:
                self._compile_stmt(s)
            end_ip = len(self.current_instructions)
            for j in end_jumps:
                self._patch(j, end_ip)
            return

        if isinstance(stmt, ForStmt):
            vname = stmt.var_name.lower()
            end_var = self._new_temp("for_end")
            step_var = self._new_temp("for_step")

            # Valuta start, end, step una sola volta
            self._compile_expr(stmt.start)
            self._emit(OpCode.STORE_VAR, vname, line=line)

            self._compile_expr(stmt.end)
            self._emit(OpCode.STORE_VAR, end_var, line=line)

            if stmt.step is not None:
                self._compile_expr(stmt.step)
            else:
                self._emit(OpCode.LOAD_CONST, -1 if stmt.downto else 1, line=line)
            self._emit(OpCode.STORE_VAR, step_var, line=line)

            loop_start = len(self.current_instructions)

            # Controllo condizione: se step >= 0 -> vname <= end_var; altrimenti vname >= end_var
            self._emit(OpCode.LOAD_VAR, step_var, line=line)
            self._emit(OpCode.LOAD_CONST, 0, line=line)
            self._emit(OpCode.BINARY_OP, ">=", line=line)
            jmp_neg_step = self._emit(OpCode.JMP_IF_FALSE, -1, line=line)

            # Caso step >= 0
            self._emit(OpCode.LOAD_VAR, vname, line=line)
            self._emit(OpCode.LOAD_VAR, end_var, line=line)
            self._emit(OpCode.BINARY_OP, "<=", line=line)
            jmp_body_from_pos = self._emit(OpCode.JMP, -1, line=line)

            # Caso step < 0
            self._patch(jmp_neg_step, len(self.current_instructions))
            self._emit(OpCode.LOAD_VAR, vname, line=line)
            self._emit(OpCode.LOAD_VAR, end_var, line=line)
            self._emit(OpCode.BINARY_OP, ">=", line=line)

            self._patch(jmp_body_from_pos, len(self.current_instructions))
            jmp_exit = self._emit(OpCode.JMP_IF_FALSE, -1, line=line)

            for s in stmt.body:
                self._compile_stmt(s)

            # Incrementa: vname := vname + step_var
            self._emit(OpCode.LOAD_VAR, vname, line=line)
            self._emit(OpCode.LOAD_VAR, step_var, line=line)
            self._emit(OpCode.BINARY_OP, "+", line=line)
            self._emit(OpCode.STORE_VAR, vname, line=line)
            self._emit(OpCode.JMP, loop_start, line=line)

            self._patch(jmp_exit, len(self.current_instructions))
            return

        if isinstance(stmt, WhileStmt):
            loop_start = len(self.current_instructions)
            self._compile_expr(stmt.condition)
            jmp_exit = self._emit(OpCode.JMP_IF_FALSE, -1, line=line)
            for s in stmt.body:
                self._compile_stmt(s)
            self._emit(OpCode.JMP, loop_start, line=line)
            self._patch(jmp_exit, len(self.current_instructions))
            return

        if isinstance(stmt, RepeatStmt):
            loop_start = len(self.current_instructions)
            for s in stmt.body:
                self._compile_stmt(s)
            self._compile_expr(stmt.condition)
            # repeat ... until cond -> ripeti finché cond è FALSA!
            self._emit(OpCode.JMP_IF_FALSE, loop_start, line=line)
            return

        if isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                self._compile_expr(stmt.value)
                self._emit(OpCode.RET, None, line=line)
            elif self.current_func_name is not None:
                self._emit(OpCode.LOAD_VAR, "__result__", line=line)
                self._emit(OpCode.RET, None, line=line)
            else:
                self._emit(OpCode.RET_VOID, None, line=line)
            return

        if isinstance(stmt, DeallocateStmt):
            self._compile_expr(stmt.target)
            self._emit(OpCode.FREE_NODE, None, line=line)
            return

    def _compile_assign(self, target: Expr, value: Expr, line: int) -> None:
        if isinstance(target, VarExpr):
            vname = target.name.lower()
            if self.current_func_name and vname == self.current_func_name:
                vname = "__result__"
            self._compile_expr(value)
            self._emit(OpCode.STORE_VAR, vname, line=line)
            return

        if isinstance(target, IndexExpr):
            self._compile_expr(target.target)
            for idx in target.indices:
                self._compile_expr(idx)
            self._compile_expr(value)
            self._emit(OpCode.STORE_INDEX, len(target.indices), line=line)
            return

        if isinstance(target, CallOrIndexExpr):
            self._compile_expr(target.target)
            for a in target.args:
                self._compile_expr(a.expr)
            self._compile_expr(value)
            self._emit(OpCode.STORE_INDEX, len(target.args), line=line)
            return

        if isinstance(target, FieldAccessExpr):
            self._compile_expr(target.target)
            self._compile_expr(value)
            self._emit(OpCode.STORE_FIELD, target.field_name.lower(), line=line)
            return

        raise RuntimeError(f"Target di assegnazione non supportato: {type(target).__name__}")

    def _compile_ref(self, expr: Expr) -> None:
        """Emette bytecode che lascia sullo stack un oggetto Ref (.get() / .set()) per passaggio per riferimento o read."""
        line = expr.span.line
        if isinstance(expr, VarExpr):
            vname = expr.name.lower()
            if self.current_func_name and vname == self.current_func_name:
                vname = "__result__"
            self._emit(OpCode.LOAD_VAR_REF, vname, line=line)
            return
        if isinstance(expr, FieldAccessExpr):
            self._compile_expr(expr.target)
            self._emit(OpCode.LOAD_FIELD_REF, expr.field_name.lower(), line=line)
            return
        if isinstance(expr, IndexExpr):
            self._compile_expr(expr.target)
            for idx in expr.indices:
                self._compile_expr(idx)
            self._emit(OpCode.LOAD_INDEX_REF, len(expr.indices), line=line)
            return
        if isinstance(expr, CallOrIndexExpr):
            self._compile_expr(expr.target)
            for a in expr.args:
                self._compile_expr(a.expr)
            self._emit(OpCode.LOAD_INDEX_REF, len(expr.args), line=line)
            return
        # Fallback: espressione non l-value passata per valore
        self._compile_expr(expr)

    # ------------------------------------------------------------------
    # Espressioni
    # ------------------------------------------------------------------

    def _compile_expr(self, expr: Expr) -> None:
        line = expr.span.line

        if isinstance(expr, IntLiteral):
            self._emit(OpCode.LOAD_CONST, expr.value, line=line)
            return

        if isinstance(expr, RealLiteral):
            self._emit(OpCode.LOAD_CONST, expr.value, line=line)
            return

        if isinstance(expr, StringLiteral):
            self._emit(OpCode.LOAD_CONST, expr.value, line=line)
            return

        if isinstance(expr, BoolLiteral):
            self._emit(OpCode.LOAD_CONST, expr.value, line=line)
            return

        if isinstance(expr, NullLiteral):
            self._emit(OpCode.LOAD_CONST, None, line=line)
            return

        if isinstance(expr, AllocateExpr):
            tname = expr.type_name.lower() if expr.type_name else None
            self._emit(OpCode.ALLOC_NODE, tname, line=line)
            return

        if isinstance(expr, VarExpr):
            vname = expr.name.lower()
            if self.current_func_name and vname == self.current_func_name:
                vname = "__result__"
            self._emit(OpCode.LOAD_VAR, vname, line=line)
            return

        if isinstance(expr, UnaryExpr):
            self._compile_expr(expr.operand)
            self._emit(OpCode.UNARY_OP, expr.op, line=line)
            return

        if isinstance(expr, BinaryExpr):
            # Corto-circuito per .AND. e .OR.!
            if expr.op == "and":
                self._compile_expr(expr.left)
                jmp_short = self._emit(OpCode.JMP_IF_FALSE_PEEK, -1, line=line)
                self._emit(OpCode.POP, None, line=line)
                self._compile_expr(expr.right)
                self._patch(jmp_short, len(self.current_instructions))
                return

            if expr.op == "or":
                self._compile_expr(expr.left)
                jmp_short = self._emit(OpCode.JMP_IF_TRUE_PEEK, -1, line=line)
                self._emit(OpCode.POP, None, line=line)
                self._compile_expr(expr.right)
                self._patch(jmp_short, len(self.current_instructions))
                return

            self._compile_expr(expr.left)
            self._compile_expr(expr.right)
            self._emit(OpCode.BINARY_OP, expr.op, line=line)
            return

        if isinstance(expr, FieldAccessExpr):
            self._compile_expr(expr.target)
            self._emit(OpCode.LOAD_FIELD, expr.field_name.lower(), line=line)
            return

        if isinstance(expr, IndexExpr):
            self._compile_expr(expr.target)
            for idx in expr.indices:
                self._compile_expr(idx)
            self._emit(OpCode.LOAD_INDEX, len(expr.indices), line=line)
            return

        if isinstance(expr, CallOrIndexExpr):
            if expr.resolved_kind == "call" and isinstance(expr.target, VarExpr):
                self._compile_call(expr.target.name, expr.args, expect_return=True, line=line)
            else:
                self._compile_expr(expr.target)
                for a in expr.args:
                    self._compile_expr(a.expr)
                self._emit(OpCode.LOAD_INDEX, len(expr.args), line=line)
            return

        raise RuntimeError(f"Espressione non compilabile: {type(expr).__name__}")

    def _compile_call(self, callee: str, args: List[CallArg], expect_return: bool, line: int) -> None:
        key = callee.lower()
        params = self.subprogram_params.get(key)
        builtin_refs = BUILTIN_BYREF_PARAMS.get(key, set())

        for idx, arg in enumerate(args):
            is_ref = False
            if params is not None and idx < len(params):
                is_ref = params[idx].mode in ("out", "in/out", "default")
            elif key in BUILTIN_BYREF_PARAMS:
                is_ref = idx in builtin_refs
            elif arg.mode_hint in ("out", "in/out"):
                is_ref = True

            if is_ref and isinstance(arg.expr, (VarExpr, FieldAccessExpr, IndexExpr, CallOrIndexExpr)):
                self._compile_ref(arg.expr)
            else:
                self._compile_expr(arg.expr)

        self._emit(OpCode.CALL, (key, len(args), expect_return), line=line)
