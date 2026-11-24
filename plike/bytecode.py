"""Definizione del set di istruzioni Bytecode P-Like (.plbc), serializzazione e disassembler."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class OpCode(Enum):
    # Costanti e stack
    LOAD_CONST = "LOAD_CONST"
    POP = "POP"
    DUP = "DUP"

    # Variabili e riferimenti (first-class Ref per in/out e out!)
    INIT_VAR = "INIT_VAR"          # arg: dict spec {name, type_tag, dims, elem_type, record_fields, ...}
    LOAD_VAR = "LOAD_VAR"          # arg: var_name (lowercase)
    LOAD_VAR_REF = "LOAD_VAR_REF"  # arg: var_name (lowercase)
    STORE_VAR = "STORE_VAR"        # arg: var_name (lowercase)

    # Array (1-based o bounds personalizzati)
    MAKE_ARRAY = "MAKE_ARRAY"      # arg: (elem_type, ndims) -> pops 2*ndims values (low1, high1, ...)
    LOAD_INDEX = "LOAD_INDEX"      # arg: ndims -> pops target + ndims indices -> pushes value
    LOAD_INDEX_REF = "LOAD_INDEX_REF"  # arg: ndims -> pops target + ndims indices -> pushes IndexRef
    STORE_INDEX = "STORE_INDEX"    # arg: ndims -> pops value, indices, target -> writes element

    # Record e puntatori dinamici
    LOAD_FIELD = "LOAD_FIELD"          # arg: field_name
    LOAD_FIELD_REF = "LOAD_FIELD_REF"  # arg: field_name
    STORE_FIELD = "STORE_FIELD"        # arg: field_name
    ALLOC_NODE = "ALLOC_NODE"          # arg: type_name (optional)
    FREE_NODE = "FREE_NODE"            # pops pointer

    # Operazioni aritmetiche, relazionali e logiche
    BINARY_OP = "BINARY_OP"        # arg: '+', '-', '*', '/', 'div', 'mod', '**', '=', '!=', '<', '<=', '>', '>='
    UNARY_OP = "UNARY_OP"          # arg: '-', '+', 'not'

    # Salti e corto-circuito
    JMP = "JMP"                        # arg: target_ip
    JMP_IF_FALSE = "JMP_IF_FALSE"      # arg: target_ip (consuma top)
    JMP_IF_TRUE = "JMP_IF_TRUE"        # arg: target_ip (consuma top)
    JMP_IF_FALSE_PEEK = "JMP_IF_FALSE_PEEK"  # corto-circuito AND
    JMP_IF_TRUE_PEEK = "JMP_IF_TRUE_PEEK"    # corto-circuito OR

    # Chiamate e ritorni
    CALL = "CALL"          # arg: (callee_lower, arg_count, expect_return)
    RET = "RET"            # pops value and returns
    RET_VOID = "RET_VOID"  # returns None

    # I/O
    READ_REF = "READ_REF"  # arg: expected_type_tag -> pops Ref, reads value
    PRINT = "PRINT"        # arg: count -> pops count values and prints

    HALT = "HALT"


@dataclass
class Instruction:
    op: OpCode
    arg: Any = None
    line: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"op": self.op.value, "arg": self.arg, "line": self.line}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Instruction":
        return cls(op=OpCode(d["op"]), arg=d.get("arg"), line=d.get("line", 0))


@dataclass
class ParamSpec:
    name: str
    mode: str  # 'in', 'out', 'in/out', 'default'

    def to_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "mode": self.mode}

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ParamSpec":
        return cls(name=d["name"], mode=d["mode"])


@dataclass
class CompiledUnit:
    name: str
    kind: str  # 'main', 'procedure', 'function'
    params: List[ParamSpec] = field(default_factory=list)
    return_type: str = "void"
    instructions: List[Instruction] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "params": [p.to_dict() for p in self.params],
            "return_type": self.return_type,
            "instructions": [ins.to_dict() for ins in self.instructions],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "CompiledUnit":
        return cls(
            name=d["name"],
            kind=d["kind"],
            params=[ParamSpec.from_dict(p) for p in d.get("params", [])],
            return_type=d.get("return_type", "void"),
            instructions=[Instruction.from_dict(i) for i in d.get("instructions", [])],
        )


@dataclass
class CompiledProgram:
    format_version: str = "plbc-1.0"
    source_name: str = "<input>"
    record_schemas: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    units: Dict[str, CompiledUnit] = field(default_factory=dict)
    entry_unit: Optional[str] = None

    def to_json(self) -> str:
        payload = {
            "format_version": self.format_version,
            "source_name": self.source_name,
            "record_schemas": self.record_schemas,
            "entry_unit": self.entry_unit,
            "units": {k: u.to_dict() for k, u in self.units.items()},
        }
        return json.dumps(payload, indent=2, ensure_ascii=False)

    @classmethod
    def from_json(cls, text: str) -> "CompiledProgram":
        d = json.loads(text)
        return cls(
            format_version=d.get("format_version", "plbc-1.0"),
            source_name=d.get("source_name", "<input>"),
            record_schemas=d.get("record_schemas", {}),
            entry_unit=d.get("entry_unit"),
            units={k: CompiledUnit.from_dict(v) for k, v in d.get("units", {}).items()},
        )

    def disassemble(self) -> str:
        lines: List[str] = [
            f"; P-Like Bytecode ({self.format_version}) - sorgente: {self.source_name}",
            f"; Entry point: {self.entry_unit or '<nessuno>'}",
            "",
        ]
        for key, unit in self.units.items():
            param_s = ", ".join(f"{p.mode}:{p.name}" for p in unit.params)
            lines.append(f"=== {unit.kind.upper()} {unit.name}({param_s}) -> {unit.return_type} ===")
            for idx, ins in enumerate(unit.instructions):
                arg_str = "" if ins.arg is None else f" {ins.arg!r}"
                lines.append(f"  {idx:04d}  [L{ins.line:03d}]  {ins.op.value:<18}{arg_str}")
            lines.append("")
        return "\n".join(lines)
