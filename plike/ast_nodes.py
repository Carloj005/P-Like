"""Nodi dell'Abstract Syntax Tree (AST) per il linguaggio P-Like."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .diagnostics import SourceSpan


# ---------------------------------------------------------------------------
# Tipi
# ---------------------------------------------------------------------------

@dataclass
class TypeSpec:
    span: SourceSpan


@dataclass
class PrimitiveType(TypeSpec):
    name: str  # 'integer', 'real', 'character', 'logical'


@dataclass
class NamedType(TypeSpec):
    name: str  # nome di un tipo definito con `type` o builtin pointer (es. list_pointer)


@dataclass
class PointerType(TypeSpec):
    target_name: str  # es. *nodo_lista o ^Nodo


@dataclass
class ArrayBound:
    low: Optional["Expr"]  # None -> default 1
    high: Optional["Expr"]  # None -> array dinamico / non dimensionato
    span: SourceSpan


@dataclass
class ArrayType(TypeSpec):
    bounds: List[ArrayBound]
    element_type: TypeSpec


@dataclass
class RecordField:
    name: str
    type_spec: TypeSpec
    span: SourceSpan


@dataclass
class RecordType(TypeSpec):
    fields: List[RecordField]


# ---------------------------------------------------------------------------
# Dichiarazioni
# ---------------------------------------------------------------------------

@dataclass
class Node:
    span: SourceSpan


@dataclass
class TypeDecl(Node):
    name: str
    type_spec: TypeSpec


@dataclass
class VarItem:
    name: str
    inline_bounds: Optional[List[ArrayBound]] = None
    init_expr: Optional["Expr"] = None
    span: Optional[SourceSpan] = None


@dataclass
class VarDecl(Node):
    items: List[VarItem]
    type_spec: TypeSpec


@dataclass
class SubprogramForwardDecl(Node):
    """Es. `var: sequential_search(n, A, x): logical function` o `var: del_testa: procedure`."""
    names: List[str]
    kind: str  # 'function' o 'procedure'
    return_type: Optional[TypeSpec] = None


@dataclass
class ParamDecl:
    name: str
    mode: str  # 'in', 'out', 'in/out', 'default'
    type_spec: Optional[TypeSpec] = None
    span: Optional[SourceSpan] = None


@dataclass
class SubprogramDecl(Node):
    kind: str  # 'procedure' o 'function'
    name: str
    params: List[ParamDecl]
    return_type: Optional[TypeSpec]
    type_decls: List[TypeDecl] = field(default_factory=list)
    var_decls: List[VarDecl] = field(default_factory=list)
    forward_decls: List[SubprogramForwardDecl] = field(default_factory=list)
    body: List["Stmt"] = field(default_factory=list)
    end_name: Optional[str] = None


@dataclass
class MainProgram(Node):
    name: Optional[str]
    type_decls: List[TypeDecl] = field(default_factory=list)
    var_decls: List[VarDecl] = field(default_factory=list)
    forward_decls: List[SubprogramForwardDecl] = field(default_factory=list)
    body: List["Stmt"] = field(default_factory=list)
    end_name: Optional[str] = None


@dataclass
class Program(Node):
    type_decls: List[TypeDecl] = field(default_factory=list)
    subprograms: List[SubprogramDecl] = field(default_factory=list)
    main: Optional[MainProgram] = None


# ---------------------------------------------------------------------------
# Espressioni
# ---------------------------------------------------------------------------

@dataclass
class Expr(Node):
    inferred_type: Optional[str] = field(default=None, init=False, repr=False)


@dataclass
class IntLiteral(Expr):
    value: int


@dataclass
class RealLiteral(Expr):
    value: float


@dataclass
class StringLiteral(Expr):
    value: str


@dataclass
class BoolLiteral(Expr):
    value: bool
    canonical: bool = True


@dataclass
class NullLiteral(Expr):
    pass


@dataclass
class VarExpr(Expr):
    name: str


@dataclass
class UnaryExpr(Expr):
    op: str  # '-', '+', 'not'
    operand: Expr


@dataclass
class BinaryExpr(Expr):
    op: str  # '+', '-', '*', '/', 'div', 'mod', '**', '=', '!=', '<', '<=', '>', '>=', 'and', 'or'
    left: Expr
    right: Expr


@dataclass
class FieldAccessExpr(Expr):
    target: Expr
    field_name: str


@dataclass
class IndexExpr(Expr):
    target: Expr
    indices: List[Expr]
    bracket_style: str = "paren"  # 'paren' -> A(i), 'square' -> A[i]


@dataclass
class CallArg:
    expr: Expr
    mode_hint: Optional[str] = None  # opzionale es. merge(in: head1; out: head3)


@dataclass
class CallExpr(Expr):
    callee: str
    args: List[CallArg]


@dataclass
class CallOrIndexExpr(Expr):
    """Espressione `target(e1, e2, ...)` che l'analisi semantica disambigua tra chiamata a function o accesso ad array."""
    target: Expr
    args: List[CallArg]
    resolved_kind: Optional[str] = field(default=None, init=False)  # 'call' o 'index'


@dataclass
class AllocateExpr(Expr):
    type_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Istruzioni (Statements)
# ---------------------------------------------------------------------------

@dataclass
class Stmt(Node):
    pass


@dataclass
class AssignStmt(Stmt):
    target: Expr
    value: Expr
    used_equals_sign: bool = False  # True se scritto '=' invece di ':='


@dataclass
class CallStmt(Stmt):
    callee: str
    args: List[CallArg]


@dataclass
class ReadStmt(Stmt):
    targets: List[Expr]


@dataclass
class PrintStmt(Stmt):
    expressions: List[Expr]


@dataclass
class IfBranch:
    condition: Expr
    body: List[Stmt]
    span: SourceSpan


@dataclass
class IfStmt(Stmt):
    branches: List[IfBranch]
    else_body: List[Stmt] = field(default_factory=list)


@dataclass
class ForStmt(Stmt):
    var_name: str
    start: Expr
    end: Expr
    step: Optional[Expr]
    downto: bool
    body: List[Stmt]


@dataclass
class WhileStmt(Stmt):
    condition: Expr
    body: List[Stmt]


@dataclass
class RepeatStmt(Stmt):
    body: List[Stmt]
    condition: Expr


@dataclass
class ReturnStmt(Stmt):
    value: Optional[Expr] = None


@dataclass
class DeallocateStmt(Stmt):
    target: Expr


@dataclass
class InlineVarStmt(Stmt):
    """Dichiarazione var trovata nel corpo (permessa in stile Yappetti / C-like, segnalata se pedantic)."""
    decl: VarDecl


def ast_to_dict(obj: object) -> object:
    """Converte un nodo AST in struttura serializzabile JSON/stampa."""
    if obj is None or isinstance(obj, (int, float, str, bool)):
        return obj
    if isinstance(obj, SourceSpan):
        return f"{obj.line}:{obj.col}"
    if isinstance(obj, list):
        return [ast_to_dict(x) for x in obj]
    if isinstance(obj, tuple):
        return [ast_to_dict(x) for x in obj]
    if hasattr(obj, "__dataclass_fields__"):
        res: Dict[str, object] = {"_node": type(obj).__name__}
        for k in obj.__dataclass_fields__:
            if k == "span":
                continue
            val = getattr(obj, k)
            if val is not None and val != []:
                res[k] = ast_to_dict(val)
        return res
    return str(obj)
