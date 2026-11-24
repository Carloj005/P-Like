"""Analizzatore semantico, type-checker e Laccetti Style Auditor per P-Like.

Esegue:
1. Risoluzione dei tipi derivati (`type ... : record`, puntatori `*T` / `^T`, builtin `list_pointer` / `stack_pointer` / `queue_pointer`).
2. Costruzione della tabella dei simboli case-insensitive per programma principale, procedure e function.
3. Fusione delle dichiarazioni `var` con i parametri di procedure/function (regola tipica P-Like).
4. Disambiguazione di `CallOrIndexExpr` (`A(i)` vs `fun(i)`).
5. Controllo dei tipi statici, compatibilità delle assegnazioni (slide Murli 197),
   condizioni logiche, modalità `in:` / `out:` / `in/out:`, uso di variabili non definite (slide Murli 196).
6. Raccolta di diagnostiche `RECOVERABLE` (riparabili con la vittoria del Napoli!) e `PEDANTIC`
   (warning in modalità normale, errori fatali se il Napoli ha perso!).
"""

from __future__ import annotations

from dataclasses import dataclass, field
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
    ParamDecl,
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
from .diagnostics import DiagnosticBag, SourceSpan


BUILTIN_POINTER_TYPES = {"list_pointer", "stack_pointer", "queue_pointer", "comb_pointer", "list"}

# Funzioni e procedure della libreria standard P-Like (ADT Laccetti + matematica di base)
BUILTIN_FUNCTIONS: Dict[str, tuple[str, int, int]] = {
    # nome: (tipo_ritorno, min_args, max_args)
    "abs": ("numeric", 1, 1),
    "sqrt": ("real", 1, 1),
    "int": ("integer", 1, 1),
    "trunc": ("integer", 1, 1),
    "floor": ("integer", 1, 1),
    "ceil": ("integer", 1, 1),
    "real": ("real", 1, 1),
    "mod": ("integer", 2, 2),
    "min": ("numeric", 2, 2),
    "max": ("numeric", 2, 2),
    "length": ("integer", 1, 1),
    "is_odd": ("logical", 1, 1),
    "is_even": ("logical", 1, 1),
    "create_node": ("pointer", 0, 1),
    "create_list": ("pointer", 0, 1),
    "list_create": ("pointer", 0, 1),
    "linked_list_create": ("pointer", 0, 1),
    "is_stack_empty": ("logical", 1, 1),
    "is_list_empty": ("logical", 1, 1),
    "is_queue_empty": ("logical", 2, 2),
    "pop": ("any", 1, 2),
}

BUILTIN_PROCEDURES: Dict[str, tuple[int, int]] = {
    "create_list": (1, 1),
    "linked_list_create": (1, 1),
    "list_create": (1, 1),
    "stack_create": (1, 1),
    "push": (2, 2),
    "stack_insert": (2, 2),
    "pop": (2, 2),
    "stack_delete": (2, 2),
    "list_insert": (3, 3),
    "list_visualize": (1, 1),
    "queue_create": (2, 2),
    "queue_insert": (3, 3),
    "queue_delete": (3, 3),
    "swap": (2, 2),
}


@dataclass
class SymbolInfo:
    name: str
    type_tag: str  # 'integer', 'real', 'character', 'logical', 'array', 'record', 'pointer', 'any'
    type_spec: Optional[TypeSpec] = None
    is_param: bool = False
    param_mode: str = "local"  # 'local', 'in', 'out', 'in/out', 'default'
    defined: bool = False
    used: bool = False
    span: Optional[SourceSpan] = None
    array_dims: int = 0
    array_elem_type: str = "any"
    record_fields: Dict[str, "SymbolInfo"] = field(default_factory=dict)


@dataclass
class SubprogramSignature:
    kind: str  # 'procedure' o 'function'
    name: str
    params: List[ParamDecl]
    return_type_tag: str  # 'void' per procedure


class SemanticAnalyzer:
    def __init__(self, diagnostics: DiagnosticBag):
        self.diagnostics = diagnostics
        self.type_table: Dict[str, TypeSpec] = {}
        self.subprograms: Dict[str, SubprogramSignature] = {}
        self.current_subprogram: Optional[SubprogramDecl] = None
        self.scope: Dict[str, SymbolInfo] = {}

    def analyze(self, program: Program) -> None:
        # 1. Registra tipi globali
        for td in program.type_decls:
            self.type_table[td.name.lower()] = td.type_spec
        if program.main:
            for td in program.main.type_decls:
                self.type_table[td.name.lower()] = td.type_spec

        # 2. Registra firme di tutte le procedure e function
        for sp in program.subprograms:
            key = sp.name.lower()
            if key in self.subprograms:
                self.diagnostics.error(
                    "SEM001",
                    f"Sottoprogramma '{sp.name}' già definito in precedenza.",
                    sp.span,
                )
            ret_tag = "void" if sp.kind == "procedure" else self._type_tag(sp.return_type)
            self.subprograms[key] = SubprogramSignature(
                kind=sp.kind,
                name=sp.name,
                params=sp.params,
                return_type_tag=ret_tag,
            )

        # 3. Analizza ciascun sottoprogramma
        for sp in program.subprograms:
            self._analyze_subprogram(sp)

        # 4. Analizza il programma principale
        if program.main is not None:
            self._analyze_main(program.main)

    # ------------------------------------------------------------------
    # Risoluzione tipi
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
            lname = tspec.name.lower()
            if lname in BUILTIN_POINTER_TYPES:
                return "pointer"
            if lname in self.type_table:
                return self._type_tag(self.type_table[lname])
            return "record"  # tipo utente (o record/pointer forward)
        return "any"

    def _resolve_record_fields(self, tspec: Optional[TypeSpec], _seen: Optional[Set[str]] = None) -> Dict[str, SymbolInfo]:
        if tspec is None:
            return {}
        seen = set() if _seen is None else _seen
        if isinstance(tspec, RecordType):
            res: Dict[str, SymbolInfo] = {}
            for rf in tspec.fields:
                res[rf.name.lower()] = self._make_symbol(rf.name, rf.type_spec, span=rf.span, defined=True, _seen=seen)
            return res
        if isinstance(tspec, PointerType):
            tname = tspec.target_name.lower()
            if tname in seen:
                return {}
            target = self.type_table.get(tname)
            if target is not None:
                return self._resolve_record_fields(target, seen | {tname})
            return {}
        if isinstance(tspec, NamedType):
            tname = tspec.name.lower()
            if tname in seen:
                return {}
            target = self.type_table.get(tname)
            if target is not None:
                return self._resolve_record_fields(target, seen | {tname})
        return {}

    def _make_symbol(
        self,
        name: str,
        tspec: Optional[TypeSpec],
        inline_bounds=None,
        span: Optional[SourceSpan] = None,
        is_param: bool = False,
        param_mode: str = "local",
        defined: bool = False,
        _seen: Optional[Set[str]] = None,
    ) -> SymbolInfo:
        tag = self._type_tag(tspec)
        dims = 0
        elem_tag = "any"
        if isinstance(tspec, ArrayType):
            tag = "array"
            bounds = inline_bounds if inline_bounds else tspec.bounds
            dims = len(bounds)
            elem_tag = self._type_tag(tspec.element_type)
        elif inline_bounds:
            tag = "array"
            dims = len(inline_bounds)
            elem_tag = self._type_tag(tspec)

        # Per i record/puntatori risolviamo i campi a un livello senza loop infiniti sui tipi ricorsivi
        rec_fields = self._resolve_record_fields(tspec, _seen) if _seen is None else {}
        return SymbolInfo(
            name=name,
            type_tag=tag,
            type_spec=tspec,
            is_param=is_param,
            param_mode=param_mode,
            defined=defined,
            span=span,
            array_dims=dims,
            array_elem_type=elem_tag,
            record_fields=rec_fields,
        )

    # ------------------------------------------------------------------
    # Analisi sottoprogramma e main
    # ------------------------------------------------------------------

    def _analyze_subprogram(self, sp: SubprogramDecl) -> None:
        self.current_subprogram = sp
        saved_types = dict(self.type_table)
        for td in sp.type_decls:
            self.type_table[td.name.lower()] = td.type_spec

        self.scope = {}

        # Registra i parametri formali
        for p in sp.params:
            key = p.name.lower()
            defined = p.mode in ("in", "in/out", "default")
            self.scope[key] = self._make_symbol(
                p.name,
                p.type_spec,
                span=p.span,
                is_param=True,
                param_mode=p.mode,
                defined=defined,
            )

        # Registra la variabile implicita di ritorno per le function (stesso nome della function!)
        ret_key = sp.name.lower()
        if sp.kind == "function":
            self.scope[ret_key] = self._make_symbol(
                sp.name,
                sp.return_type,
                span=sp.span,
                is_param=False,
                param_mode="return",
                defined=False,
            )

        # Registra dichiarazioni var locali (fondendole con i parametri se omonimi!)
        for vd in sp.var_decls:
            self._register_var_decl(vd)

        # Analizza il corpo
        has_return = False
        for st in sp.body:
            if self._analyze_stmt(st):
                has_return = True

        # Verifica che la function abbia assegnato un valore di ritorno
        if sp.kind == "function":
            ret_sym = self.scope.get(ret_key)
            if not has_return and (ret_sym is None or not ret_sym.defined):
                self.diagnostics.recoverable(
                    "SEM002",
                    f"La function '{sp.name}' potrebbe non assegnare mai il valore di ritorno '{sp.name} := ...'.",
                    sp.span,
                    hint=f"Assegna il risultato a `{sp.name} := <valore>` o usa `return <valore>`.",
                )

        # Audit variabili locali inutilizzate (PEDANTIC!)
        self._check_unused_vars()

        self.type_table = saved_types
        self.current_subprogram = None

    def _analyze_main(self, main: MainProgram) -> None:
        self.current_subprogram = None
        self.scope = {}
        for vd in main.var_decls:
            self._register_var_decl(vd)

        for st in main.body:
            self._analyze_stmt(st)

        self._check_unused_vars()

    def _register_var_decl(self, vd: VarDecl) -> None:
        for item in vd.items:
            key = item.name.lower()
            # Valida eventuali espressioni nei bounds dell'array (senza esigere che siano già definite a compile-time!)
            if item.inline_bounds:
                for b in item.inline_bounds:
                    if b.low:
                        self._analyze_expr(b.low, check_defined=False)
                    if b.high:
                        self._analyze_expr(b.high, check_defined=False)
            if isinstance(vd.type_spec, ArrayType):
                for b in vd.type_spec.bounds:
                    if b.low:
                        self._analyze_expr(b.low, check_defined=False)
                    if b.high:
                        self._analyze_expr(b.high, check_defined=False)

            if key in self.scope and self.scope[key].is_param:
                # Regola canonica P-Like: `var` specifica il tipo di un parametro formale!
                existing = self.scope[key]
                updated = self._make_symbol(
                    item.name,
                    vd.type_spec,
                    inline_bounds=item.inline_bounds,
                    span=item.span or vd.span,
                    is_param=True,
                    param_mode=existing.param_mode,
                    defined=existing.defined or (item.init_expr is not None),
                )
                self.scope[key] = updated
            else:
                if key in self.scope and self.scope[key].param_mode != "return":
                    self.diagnostics.recoverable(
                        "SEM003",
                        f"Variabile '{item.name}' dichiarata più volte nello stesso blocco.",
                        item.span or vd.span,
                    )
                sym = self._make_symbol(
                    item.name,
                    vd.type_spec,
                    inline_bounds=item.inline_bounds,
                    span=item.span or vd.span,
                    defined=(item.init_expr is not None or self._type_tag(vd.type_spec) in ("array", "record")),
                )
                self.scope[key] = sym

            if item.init_expr is not None:
                val_type = self._analyze_expr(item.init_expr)
                self._check_assignment_compat(self.scope[key].type_tag, val_type, item.init_expr, item.span or vd.span)

    def _check_unused_vars(self) -> None:
        for sym in self.scope.values():
            if sym.is_param or sym.param_mode == "return":
                continue
            if not sym.used and not sym.defined:
                self.diagnostics.pedantic(
                    "PED016",
                    f"Variabile '{sym.name}' dichiarata ma mai utilizzata.",
                    sym.span or SourceSpan(1, 1),
                    hint=f"Rimuovi la dichiarazione inutilizzata di '{sym.name}'.",
                )

    # ------------------------------------------------------------------
    # Analisi Statement
    # ------------------------------------------------------------------

    def _analyze_stmt(self, stmt: Stmt) -> bool:
        """Restituisce True se lo statement contiene un `return` esplicito."""
        if isinstance(stmt, InlineVarStmt):
            self._register_var_decl(stmt.decl)
            return False

        if isinstance(stmt, AssignStmt):
            val_type = self._analyze_expr(stmt.value)
            target_type = self._analyze_lvalue(stmt.target, mark_defined=True)
            self._check_assignment_compat(target_type, val_type, stmt.value, stmt.span)
            return False

        if isinstance(stmt, ReadStmt):
            for t in stmt.targets:
                self._analyze_lvalue(t, mark_defined=True)
            return False

        if isinstance(stmt, PrintStmt):
            for e in stmt.expressions:
                self._analyze_expr(e)
            return False

        if isinstance(stmt, CallStmt):
            self._analyze_call_args(stmt.callee, stmt.args, is_proc=True, span=stmt.span)
            return False

        if isinstance(stmt, IfStmt):
            has_ret = False
            for br in stmt.branches:
                ct = self._analyze_expr(br.condition)
                self._check_logical_cond(ct, br.span, "if")
                for s in br.body:
                    if self._analyze_stmt(s):
                        has_ret = True
            for s in stmt.else_body:
                if self._analyze_stmt(s):
                    has_ret = True
            return has_ret

        if isinstance(stmt, ForStmt):
            st_t = self._analyze_expr(stmt.start)
            en_t = self._analyze_expr(stmt.end)
            if st_t not in ("integer", "any"):
                self.diagnostics.recoverable(
                    "SEM004",
                    f"L'estremo iniziale del ciclo 'for' dovrebbe essere integer (trovato {st_t}).",
                    stmt.start.span,
                )
            if en_t not in ("integer", "any"):
                self.diagnostics.recoverable(
                    "SEM005",
                    f"L'estremo finale del ciclo 'for' dovrebbe essere integer (trovato {en_t}).",
                    stmt.end.span,
                )
            if stmt.step:
                sp_t = self._analyze_expr(stmt.step)
                if sp_t not in ("integer", "any"):
                    self.diagnostics.recoverable(
                        "SEM006",
                        f"Lo 'step' del ciclo 'for' dovrebbe essere integer (trovato {sp_t}).",
                        stmt.step.span,
                    )
            vkey = stmt.var_name.lower()
            if vkey not in self.scope:
                self.diagnostics.recoverable(
                    "SEM007",
                    f"Variabile indice '{stmt.var_name}' del ciclo 'for' non dichiarata in 'var'.",
                    stmt.span,
                    hint=f"Aggiungi `var: {stmt.var_name}: integer`.",
                )
                self.scope[vkey] = SymbolInfo(name=stmt.var_name, type_tag="integer", defined=True, used=True, span=stmt.span)
            else:
                self.scope[vkey].defined = True
                self.scope[vkey].used = True
            has_ret = False
            for s in stmt.body:
                if self._analyze_stmt(s):
                    has_ret = True
            return has_ret

        if isinstance(stmt, WhileStmt):
            ct = self._analyze_expr(stmt.condition)
            self._check_logical_cond(ct, stmt.span, "while")
            has_ret = False
            for s in stmt.body:
                if self._analyze_stmt(s):
                    has_ret = True
            return has_ret

        if isinstance(stmt, RepeatStmt):
            has_ret = False
            for s in stmt.body:
                if self._analyze_stmt(s):
                    has_ret = True
            ct = self._analyze_expr(stmt.condition)
            self._check_logical_cond(ct, stmt.span, "until")
            return has_ret

        if isinstance(stmt, ReturnStmt):
            if stmt.value is not None:
                vt = self._analyze_expr(stmt.value)
                if self.current_subprogram and self.current_subprogram.kind == "function":
                    ret_sym = self.scope.get(self.current_subprogram.name.lower())
                    if ret_sym:
                        ret_sym.defined = True
                        self._check_assignment_compat(ret_sym.type_tag, vt, stmt.value, stmt.span)
            return True

        if isinstance(stmt, DeallocateStmt):
            self._analyze_expr(stmt.target)
            return False

        return False

    def _analyze_lvalue(self, target: Expr, mark_defined: bool = True) -> str:
        if isinstance(target, VarExpr):
            key = target.name.lower()
            sym = self.scope.get(key)
            if sym is None:
                self.diagnostics.recoverable(
                    "SEM008",
                    f"Variabile '{target.name}' utilizzata senza dichiarazione 'var'.",
                    target.span,
                    hint=f"Dichiara '{target.name}' nella sezione `var:`.",
                )
                sym = SymbolInfo(name=target.name, type_tag="any", defined=mark_defined, used=True, span=target.span)
                self.scope[key] = sym
            else:
                if mark_defined:
                    sym.defined = True
                sym.used = True
            target.inferred_type = sym.type_tag
            return sym.type_tag

        if isinstance(target, CallOrIndexExpr):
            # In posizione L-value `A(i)` è SEMPRE un accesso ad array!
            target.resolved_kind = "index"
            arr_type = self._analyze_lvalue(target.target, mark_defined=False)
            for arg in target.args:
                it = self._analyze_expr(arg.expr)
                if it not in ("integer", "any"):
                    self.diagnostics.recoverable(
                        "SEM010",
                        f"Indice di array non intero ({it}).",
                        arg.expr.span,
                    )
            elem_type = self._lookup_array_elem_type(target.target)
            target.inferred_type = elem_type
            return elem_type

        if isinstance(target, IndexExpr):
            self._analyze_lvalue(target.target, mark_defined=False)
            for idx in target.indices:
                it = self._analyze_expr(idx)
                if it not in ("integer", "any"):
                    self.diagnostics.recoverable("SEM010", f"Indice di array non intero ({it}).", idx.span)
            elem_type = self._lookup_array_elem_type(target.target)
            target.inferred_type = elem_type
            return elem_type

        if isinstance(target, FieldAccessExpr):
            self._analyze_expr(target.target, check_defined=False)
            ftype = self._lookup_field_type(target.target, target.field_name, target.span)
            target.inferred_type = ftype
            return ftype

        self.diagnostics.error("SEM011", "Destinazione di assegnazione non valida.", target.span)
        return "any"

    def _lookup_array_elem_type(self, target: Expr) -> str:
        if isinstance(target, VarExpr):
            sym = self.scope.get(target.name.lower())
            if sym and sym.type_tag == "array":
                return sym.array_elem_type
        if isinstance(target, FieldAccessExpr):
            fsym = self._lookup_field_symbol(target.target, target.field_name)
            if fsym and fsym.type_tag == "array":
                return fsym.array_elem_type
        return "any"

    def _lookup_field_symbol(self, target: Expr, field_name: str) -> Optional[SymbolInfo]:
        if isinstance(target, VarExpr):
            sym = self.scope.get(target.name.lower())
            if sym:
                fields = sym.record_fields or self._resolve_record_fields(sym.type_spec)
                return fields.get(field_name.lower())
        elif isinstance(target, FieldAccessExpr):
            parent = self._lookup_field_symbol(target.target, target.field_name)
            if parent:
                fields = parent.record_fields or self._resolve_record_fields(parent.type_spec)
                return fields.get(field_name.lower())
        return None

    def _lookup_field_type(self, target: Expr, field_name: str, span: SourceSpan) -> str:
        # Se il target ha un tipo record esplicito con campi definiti, controlliamo che il campo esista!
        if isinstance(target, VarExpr):
            sym = self.scope.get(target.name.lower())
            if sym:
                fields = sym.record_fields or self._resolve_record_fields(sym.type_spec)
                if fields:
                    fsym = fields.get(field_name.lower())
                    if fsym is None:
                        self.diagnostics.error(
                            "SEM012",
                            f"Il record '{target.name}' non possiede il campo '.{field_name}'.",
                            span,
                        )
                        return "any"
                    return fsym.type_tag
        elif isinstance(target, FieldAccessExpr):
            parent = self._lookup_field_symbol(target.target, target.field_name)
            if parent:
                fields = parent.record_fields or self._resolve_record_fields(parent.type_spec)
                if fields:
                    fsym = fields.get(field_name.lower())
                    if fsym is None:
                        self.diagnostics.error(
                            "SEM012",
                            f"Il campo '.{target.field_name}' non possiede il sottocampo '.{field_name}'.",
                            span,
                        )
                        return "any"
                    return fsym.type_tag
        return "any"

    # ------------------------------------------------------------------
    # Analisi Espressioni
    # ------------------------------------------------------------------

    def _analyze_expr(self, expr: Expr, check_defined: bool = True) -> str:
        if isinstance(expr, IntLiteral):
            expr.inferred_type = "integer"
            return "integer"

        if isinstance(expr, RealLiteral):
            expr.inferred_type = "real"
            return "real"

        if isinstance(expr, StringLiteral):
            expr.inferred_type = "character"
            return "character"

        if isinstance(expr, BoolLiteral):
            expr.inferred_type = "logical"
            return "logical"

        if isinstance(expr, NullLiteral):
            expr.inferred_type = "pointer"
            return "pointer"

        if isinstance(expr, AllocateExpr):
            expr.inferred_type = "pointer"
            return "pointer"

        if isinstance(expr, VarExpr):
            key = expr.name.lower()
            sym = self.scope.get(key)
            if sym is None:
                self.diagnostics.recoverable(
                    "SEM013",
                    f"Variabile '{expr.name}' non dichiarata.",
                    expr.span,
                    hint=f"Dichiara '{expr.name}' nella sezione `var:`.",
                )
                sym = SymbolInfo(name=expr.name, type_tag="any", defined=True, used=True, span=expr.span)
                self.scope[key] = sym
            else:
                sym.used = True
                if check_defined and not sym.defined and sym.type_tag not in ("array", "record"):
                    # Slide Murli 196: "ERRATO!!!! tutte le variabili devono essere definite prima di essere utilizzate"
                    self.diagnostics.recoverable(
                        "SEM014",
                        f"Variabile '{expr.name}' utilizzata prima di essere stata definita (inizializzata o letta con 'read').",
                        expr.span,
                        hint=f"Inizializza '{expr.name}' con `:=` o leggila con `read {expr.name}` prima di usarla.",
                    )
            expr.inferred_type = sym.type_tag
            return sym.type_tag

        if isinstance(expr, UnaryExpr):
            ot = self._analyze_expr(expr.operand, check_defined=check_defined)
            if expr.op == "not":
                if ot not in ("logical", "any"):
                    self.diagnostics.recoverable("SEM015", f"Operatore NOT applicato a tipo '{ot}' invece di 'logical'.", expr.span)
                expr.inferred_type = "logical"
                return "logical"
            if ot not in ("integer", "real", "any"):
                self.diagnostics.error("SEM016", f"Operatore unario '{expr.op}' non valido per tipo '{ot}'.", expr.span)
            expr.inferred_type = ot
            return ot

        if isinstance(expr, BinaryExpr):
            lt = self._analyze_expr(expr.left, check_defined=check_defined)
            rt = self._analyze_expr(expr.right, check_defined=check_defined)

            if expr.op in ("and", "or"):
                if lt not in ("logical", "any") or rt not in ("logical", "any"):
                    self.diagnostics.recoverable(
                        "SEM017",
                        f"Operatore logico '{expr.op.upper()}' richiede operandi 'logical' (trovati {lt}, {rt}).",
                        expr.span,
                    )
                expr.inferred_type = "logical"
                return "logical"

            if expr.op in ("=", "!=", "<", "<=", ">", ">="):
                expr.inferred_type = "logical"
                return "logical"

            if expr.op in ("mod", "div"):
                if lt not in ("integer", "any") or rt not in ("integer", "any"):
                    self.diagnostics.recoverable(
                        "SEM018",
                        f"Operatore '{expr.op}' richiede operandi 'integer' (trovati {lt}, {rt}).",
                        expr.span,
                    )
                expr.inferred_type = "integer"
                return "integer"

            if expr.op in ("+", "-", "*", "/", "**"):
                if expr.op == "+" and (lt == "character" or rt == "character"):
                    expr.inferred_type = "character"
                    return "character"
                if "real" in (lt, rt):
                    expr.inferred_type = "real"
                    return "real"
                if lt == "integer" and rt == "integer":
                    expr.inferred_type = "integer"
                    return "integer"
                expr.inferred_type = "any"
                return "any"

            expr.inferred_type = "any"
            return "any"

        if isinstance(expr, FieldAccessExpr):
            self._analyze_expr(expr.target, check_defined=check_defined)
            ftype = self._lookup_field_type(expr.target, expr.field_name, expr.span)
            expr.inferred_type = ftype
            return ftype

        if isinstance(expr, IndexExpr):
            self._analyze_expr(expr.target, check_defined=False)
            for idx in expr.indices:
                it = self._analyze_expr(idx, check_defined=check_defined)
                if it not in ("integer", "any"):
                    self.diagnostics.recoverable("SEM010", f"Indice di array non intero ({it}).", idx.span)
            elem_type = self._lookup_array_elem_type(expr.target)
            expr.inferred_type = elem_type
            return elem_type

        if isinstance(expr, CallOrIndexExpr):
            return self._disambiguate_call_or_index(expr, check_defined=check_defined)

        return "any"

    def _disambiguate_call_or_index(self, expr: CallOrIndexExpr, check_defined: bool = True) -> str:
        # Se target è un FieldAccess (es. `vettore.dimensione(1)`), è un accesso ad array!
        if not isinstance(expr.target, VarExpr):
            expr.resolved_kind = "index"
            self._analyze_expr(expr.target, check_defined=False)
            for a in expr.args:
                self._analyze_expr(a.expr, check_defined=check_defined)
            et = self._lookup_array_elem_type(expr.target)
            expr.inferred_type = et
            return et

        name = expr.target.name
        key = name.lower()
        sym = self.scope.get(key)

        # 1. È una variabile array nel corrente scope?
        if sym is not None and sym.type_tag == "array":
            expr.resolved_kind = "index"
            sym.used = True
            if sym.array_dims and len(expr.args) != sym.array_dims:
                self.diagnostics.error(
                    "SEM019",
                    f"L'array '{name}' ha {sym.array_dims} dimensioni ma viene indicizzato con {len(expr.args)} indici.",
                    expr.span,
                )
            for a in expr.args:
                it = self._analyze_expr(a.expr, check_defined=check_defined)
                if it not in ("integer", "any"):
                    self.diagnostics.recoverable("SEM010", f"Indice di array non intero ({it}).", a.expr.span)
            expr.inferred_type = sym.array_elem_type
            return sym.array_elem_type

        # 2. È una function definita dall'utente o builtin?
        if key in self.subprograms:
            expr.resolved_kind = "call"
            sig = self.subprograms[key]
            if sig.kind == "procedure":
                self.diagnostics.error(
                    "SEM020",
                    f"La procedure '{name}' non restituisce un valore e non può essere usata in un'espressione.",
                    expr.span,
                )
            self._analyze_call_args(name, expr.args, is_proc=False, span=expr.span)
            expr.inferred_type = sig.return_type_tag
            return sig.return_type_tag

        if key in BUILTIN_FUNCTIONS:
            expr.resolved_kind = "call"
            ret_tag, min_a, max_a = BUILTIN_FUNCTIONS[key]
            if not (min_a <= len(expr.args) <= max_a):
                self.diagnostics.error(
                    "SEM021",
                    f"La funzione built-in '{name}' richiede da {min_a} a {max_a} argomenti (passati {len(expr.args)}).",
                    expr.span,
                )
            arg_types = [self._analyze_expr(a.expr, check_defined=check_defined) for a in expr.args]
            if ret_tag == "numeric":
                ret_tag = "real" if "real" in arg_types else ("integer" if arg_types else "real")
            expr.inferred_type = ret_tag
            return ret_tag

        # 3. Se sym esiste ma ha tipo 'any' (es. array non tipizzato), trattalo come array!
        if sym is not None:
            expr.resolved_kind = "index"
            sym.used = True
            for a in expr.args:
                self._analyze_expr(a.expr, check_defined=check_defined)
            expr.inferred_type = "any"
            return "any"

        # 4. Sconosciuto: errore semantico
        expr.resolved_kind = "call"
        for a in expr.args:
            self._analyze_expr(a.expr, check_defined=check_defined)
        self.diagnostics.error(
            "SEM022",
            f"Funzione o array '{name}' non dichiarato.",
            expr.span,
            hint=f"Dichiara '{name}' come array in `var:` oppure definisci `function {name}(...)`.",
        )
        expr.inferred_type = "any"
        return "any"

    def _analyze_call_args(self, callee: str, args: List[CallArg], is_proc: bool, span: SourceSpan) -> None:
        key = callee.lower()
        sig = self.subprograms.get(key)

        if sig is not None:
            if len(args) != len(sig.params):
                self.diagnostics.error(
                    "SEM023",
                    f"'{callee}' richiede {len(sig.params)} parametri ma ne sono stati passati {len(args)}.",
                    span,
                )
            for idx, arg in enumerate(args):
                mode = sig.params[idx].mode if idx < len(sig.params) else "in"
                if mode == "out":
                    self._analyze_lvalue(arg.expr, mark_defined=True)
                elif mode in ("in/out", "default"):
                    if isinstance(arg.expr, (VarExpr, FieldAccessExpr, IndexExpr, CallOrIndexExpr)):
                        # Permetti di passare anche variabili appena create come output
                        self._analyze_expr(arg.expr, check_defined=False)
                        if isinstance(arg.expr, VarExpr) and arg.expr.name.lower() in self.scope:
                            self.scope[arg.expr.name.lower()].defined = True
                    else:
                        self._analyze_expr(arg.expr)
                else:
                    self._analyze_expr(arg.expr)
            return

        if key in BUILTIN_PROCEDURES:
            min_a, max_a = BUILTIN_PROCEDURES[key]
            if not (min_a <= len(args) <= max_a):
                self.diagnostics.error(
                    "SEM024",
                    f"La procedure built-in '{callee}' richiede da {min_a} a {max_a} argomenti (passati {len(args)}).",
                    span,
                )
            for arg in args:
                if isinstance(arg.expr, VarExpr) and arg.expr.name.lower() in self.scope:
                    self.scope[arg.expr.name.lower()].defined = True
                    self.scope[arg.expr.name.lower()].used = True
                else:
                    self._analyze_expr(arg.expr, check_defined=False)
            return

        if key in BUILTIN_FUNCTIONS:
            for arg in args:
                self._analyze_expr(arg.expr)
            return

        for arg in args:
            self._analyze_expr(arg.expr, check_defined=False)
        self.diagnostics.error(
            "SEM025",
            f"Procedura o funzione '{callee}' non definita.",
            span,
            hint=f"Definisci `procedure {callee}(...)` prima o nello stesso file.",
        )

    def _check_logical_cond(self, cond_type: str, span: SourceSpan, construct: str) -> None:
        if cond_type not in ("logical", "any"):
            self.diagnostics.recoverable(
                "SEM026",
                f"La condizione di '{construct}' deve essere di tipo 'logical' (trovato '{cond_type}').",
                span,
            )

    def _check_assignment_compat(self, target_type: str, val_type: str, val_expr: Expr, span: SourceSpan) -> None:
        if target_type == "any" or val_type == "any":
            return
        if target_type == val_type:
            return
        # Widening integer -> real: ammesso, MA Murli/Laccetti sono fissati sul punto decimale (`0.` invece di `0`)!
        if target_type == "real" and val_type == "integer":
            if isinstance(val_expr, IntLiteral):
                self.diagnostics.pedantic(
                    "PED017",
                    f"Costante intera '{val_expr.value}' assegnata a variabile 'real' senza punto decimale.",
                    span,
                    hint=f"Nelle slide Murli/Laccetti le costanti reali hanno il punto decimale: scrivi `{val_expr.value}.`.",
                )
            return
        # Narrowing real -> integer: errore recuperabile (troncamento)
        if target_type == "integer" and val_type == "real":
            self.diagnostics.recoverable(
                "SEM027",
                "Assegnazione di un valore 'real' a una variabile 'integer' (perdita di precisione).",
                span,
                hint="Usa `int(...)` o `trunc(...)` per convertire esplicitamente.",
            )
            return
        # Slide Murli 197: "ERRATO!!!! Il valore dell'espressione deve essere dello stesso tipo della variabile!"
        self.diagnostics.error(
            "SEM028",
            f"Incompatibilità di tipo nell'assegnazione: impossibile assegnare '{val_type}' a una variabile di tipo '{target_type}'.",
            span,
            hint="In P-Like il valore dell'espressione deve avere lo stesso tipo della variabile destinataria.",
        )
