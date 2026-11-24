"""Virtual Machine a stack per l'esecuzione del Bytecode P-Like (.plbc).

Caratteristiche fedeli al corso del Prof. Giuliano Laccetti:
- Array 1-based di default (o con limiti arbitrari `low..high`), 1D / 2D / N-D
- Passaggio di parametri per valore (`in:`) e per riferimento (`out:`, `in/out:`, default),
  incluso il passaggio per riferimento di campi record come `head.link` (slide 20 Strutture Dati Dinamiche!)
- Divisione intera `integer / integer` troncata verso zero (come `mediano := (primo+ultimo)/2`)
  e divisione reale se almeno un operando è `real`
- Record annidati e puntatori dinamici (`allocate`, `dealloca`, `NULL`) con controllo use-after-free
- Libreria standard integrata: ADT Linked List, Stack, Queue e funzioni matematiche di base
"""

from __future__ import annotations

import copy
import io
import math
import sys
from typing import Any, Dict, List, Optional, TextIO, Tuple

from .bytecode import CompiledProgram, CompiledUnit, OpCode


class PLikeRuntimeError(Exception):
    def __init__(self, message: str, line: int = 0):
        super().__init__(f"[ERRORE RUNTIME L{line}] {message}" if line else f"[ERRORE RUNTIME] {message}")
        self.line = line


# ---------------------------------------------------------------------------
# Tipi runtime: Ref, Array, Record/Node
# ---------------------------------------------------------------------------

class Ref:
    def get(self) -> Any:
        raise NotImplementedError

    def set(self, value: Any) -> None:
        raise NotImplementedError


class VarCell(Ref):
    __slots__ = ("value",)

    def __init__(self, value: Any = None):
        self.value = value

    def get(self) -> Any:
        return self.value

    def set(self, value: Any) -> None:
        self.value = value


class FieldRef(Ref):
    __slots__ = ("obj", "field")

    def __init__(self, obj: "PLikeRecord", field: str):
        self.obj = obj
        self.field = field

    def get(self) -> Any:
        return self.obj.get_field(self.field)

    def set(self, value: Any) -> None:
        self.obj.set_field(self.field, value)


class IndexRef(Ref):
    __slots__ = ("arr", "indices")

    def __init__(self, arr: "PLikeArray", indices: Tuple[int, ...]):
        self.arr = arr
        self.indices = indices

    def get(self) -> Any:
        return self.arr.get(self.indices)

    def set(self, value: Any) -> None:
        self.arr.set(self.indices, value)


class PLikeArray:
    """Array P-Like N-dimensionale con indicizzazione 1-based (o limiti personalizzati)."""

    def __init__(
        self,
        elem_desc: Dict[str, Any],
        bounds: List[Tuple[int, Optional[int]]],
        record_schemas: Dict[str, Dict[str, Any]],
    ):
        self.elem_desc = elem_desc
        self.bounds = bounds  # [(low1, high1_or_None), ...]
        self.record_schemas = record_schemas
        self.data: Dict[Tuple[int, ...], Any] = {}

    def _check_and_norm(self, indices: Tuple[int, ...]) -> Tuple[int, ...]:
        norm = tuple(int(i) for i in indices)
        if self.bounds and len(norm) != len(self.bounds):
            raise PLikeRuntimeError(
                f"Numero di indici errato: attesi {len(self.bounds)}, forniti {len(norm)}."
            )
        for dim, idx in enumerate(norm):
            if dim < len(self.bounds):
                low, high = self.bounds[dim]
                if idx < low:
                    raise PLikeRuntimeError(
                        f"Indice fuori dai limiti (dimensione {dim + 1}): {idx} < limite inferiore {low} "
                        "(ricorda: in P-Like gli array partono da 1!)."
                    )
                if high is not None and idx > high:
                    raise PLikeRuntimeError(
                        f"Indice fuori dai limiti (dimensione {dim + 1}): {idx} > limite superiore {high}."
                    )
        return norm

    def get(self, indices: Tuple[int, ...]) -> Any:
        key = self._check_and_norm(indices)
        if key not in self.data:
            self.data[key] = _default_value(self.elem_desc, self.record_schemas)
        return self.data[key]

    def set(self, indices: Tuple[int, ...], value: Any) -> None:
        key = self._check_and_norm(indices)
        self.data[key] = value

    def deep_copy(self) -> "PLikeArray":
        clone = PLikeArray(self.elem_desc, list(self.bounds), self.record_schemas)
        for k, v in self.data.items():
            if isinstance(v, PLikeArray):
                clone.data[k] = v.deep_copy()
            elif isinstance(v, PLikeRecord) and not v.is_heap_node:
                clone.data[k] = v.deep_copy()
            else:
                clone.data[k] = v
        return clone


class PLikeRecord:
    """Record P-Like o nodo dinamico allocato sullo heap (per linked list / stack / queue)."""

    def __init__(
        self,
        fields: Optional[Dict[str, Any]] = None,
        type_name: str = "record",
        is_heap_node: bool = False,
    ):
        self.fields: Dict[str, Any] = fields if fields is not None else {}
        self.type_name = type_name
        self.is_heap_node = is_heap_node
        self.freed = False

    def get_field(self, name: str) -> Any:
        if self.freed:
            raise PLikeRuntimeError(f"Accesso a nodo già deallocato (campo '.{name}').")
        key = name.lower()
        if key not in self.fields:
            # Per nodi generici (list_pointer/stack_pointer), inizializza campi standard a None/0
            if key in ("link", "next", "prev", "linkc", "linkl"):
                self.fields[key] = None
            else:
                self.fields[key] = 0
        return self.fields[key]

    def set_field(self, name: str, value: Any) -> None:
        if self.freed:
            raise PLikeRuntimeError(f"Scrittura su nodo già deallocato (campo '.{name}').")
        self.fields[name.lower()] = value

    def deep_copy(self) -> "PLikeRecord":
        cloned_fields: Dict[str, Any] = {}
        for k, v in self.fields.items():
            if isinstance(v, PLikeArray):
                cloned_fields[k] = v.deep_copy()
            elif isinstance(v, PLikeRecord) and not v.is_heap_node:
                cloned_fields[k] = v.deep_copy()
            else:
                cloned_fields[k] = v
        return PLikeRecord(cloned_fields, self.type_name, is_heap_node=self.is_heap_node)

    def __repr__(self) -> str:
        return f"<{self.type_name} {self.fields}>"


def _default_value(tdesc: Dict[str, Any], schemas: Dict[str, Dict[str, Any]]) -> Any:
    kind = tdesc.get("kind", "any")
    if kind == "integer":
        return 0
    if kind == "real":
        return 0.0
    if kind == "character":
        return ""
    if kind == "logical":
        return False
    if kind == "pointer":
        return None
    if kind == "array":
        raw_bounds = tdesc.get("static_bounds") or []
        bounds = [(b[0], b[1]) for b in raw_bounds]
        return PLikeArray(tdesc.get("elem", {"kind": "any"}), bounds, schemas)
    if kind == "record":
        fspecs = tdesc.get("fields", {})
        if not fspecs and tdesc.get("type_name") in schemas:
            fspecs = schemas[tdesc["type_name"]].get("fields", {})
        fields = {fn: _default_value(fs, schemas) for fn, fs in fspecs.items()}
        return PLikeRecord(fields, type_name=tdesc.get("type_name", "record"), is_heap_node=False)
    return 0


def format_plike_value(val: Any) -> str:
    if isinstance(val, bool):
        return ".TRUE." if val else ".FALSE."
    if val is None:
        return "NULL"
    if isinstance(val, float):
        # Evita rumore tipo 3.0000000000000004
        return f"{val:g}" if abs(val - round(val)) > 1e-12 else f"{val:.1f}"
    return str(val)


# ---------------------------------------------------------------------------
# Virtual Machine
# ---------------------------------------------------------------------------

class PLikeVM:
    def __init__(
        self,
        program: CompiledProgram,
        stdin: Optional[TextIO] = None,
        stdout: Optional[TextIO] = None,
        max_steps: int = 2_000_000,
        max_call_depth: int = 500,
    ):
        self.program = program
        self.stdin = stdin if stdin is not None else sys.stdin
        self.stdout = stdout if stdout is not None else sys.stdout
        self.max_steps = max_steps
        self.max_call_depth = max_call_depth
        self._input_tokens: List[str] = []
        self.steps_executed = 0

    def run(self) -> None:
        if not self.program.entry_unit:
            raise PLikeRuntimeError(
                "Questo file contiene solo procedure/function e nessun blocco 'begin ... end' eseguibile."
            )
        entry = self.program.units[self.program.entry_unit]
        self._exec_unit(entry, args=[], depth=0)

    def call_unit(self, name: str, args: List[Any]) -> Any:
        """Invoca direttamente una function o procedure compilata (utile nei test e nel REPL!)."""
        key = name.lower()
        if key not in self.program.units:
            raise PLikeRuntimeError(f"Sottoprogramma '{name}' non trovato nel bytecode.")
        return self._exec_unit(self.program.units[key], args=args, depth=0)

    def _read_token(self, expected_type: str, line: int) -> Any:
        while not self._input_tokens:
            raw_line = self.stdin.readline()
            if raw_line == "":
                raise PLikeRuntimeError("Fine input (EOF) raggiunta durante l'istruzione 'read'.", line)
            if expected_type == "character":
                stripped = raw_line.rstrip("\r\n")
                if stripped == "":
                    continue
                # Se l'utente inserisce più caratteri/parole separati da spazi, o una riga intera
                parts = stripped.split()
                if len(parts) > 1:
                    self._input_tokens.extend(parts)
                else:
                    self._input_tokens.append(stripped)
            else:
                # Permetti sia spazi sia virgole tra i valori inseriti
                cleaned = raw_line.replace(",", " ").split()
                self._input_tokens.extend(cleaned)

        tok = self._input_tokens.pop(0)

        if expected_type == "integer":
            try:
                return int(tok)
            except ValueError:
                try:
                    return int(float(tok))
                except ValueError:
                    raise PLikeRuntimeError(f"Input non valido per variabile integer: {tok!r}.", line)
        if expected_type == "real":
            try:
                return float(tok)
            except ValueError:
                raise PLikeRuntimeError(f"Input non valido per variabile real: {tok!r}.", line)
        if expected_type == "logical":
            low = tok.strip().lower().strip(".")
            if low in ("true", "vero", "1", "t", "s"):
                return True
            if low in ("false", "falso", "0", "f", "n"):
                return False
            raise PLikeRuntimeError(f"Input non valido per variabile logical: {tok!r}.", line)
        if expected_type == "character":
            return tok

        # Tipo generico ('any'): inferisci automaticamente
        low = tok.strip().lower()
        if low in (".true.", "true"):
            return True
        if low in (".false.", "false"):
            return False
        try:
            return int(tok)
        except ValueError:
            try:
                return float(tok)
            except ValueError:
                return tok

    def _exec_unit(self, unit: CompiledUnit, args: List[Any], depth: int) -> Any:
        if depth > self.max_call_depth:
            raise PLikeRuntimeError(f"Superata profondità massima di ricorsione ({self.max_call_depth}) in '{unit.name}'.")

        env: Dict[str, Ref] = {}

        # Bind parametri formali
        for idx, pspec in enumerate(unit.params):
            raw = args[idx] if idx < len(args) else None
            if pspec.mode in ("out", "in/out", "default") and isinstance(raw, Ref):
                env[pspec.name] = raw
            else:
                val = raw.get() if isinstance(raw, Ref) else raw
                if pspec.mode == "in":
                    if isinstance(val, PLikeArray):
                        val = val.deep_copy()
                    elif isinstance(val, PLikeRecord) and not val.is_heap_node:
                        val = val.deep_copy()
                env[pspec.name] = VarCell(val)

        stack: List[Any] = []
        ip = 0
        ins_list = unit.instructions
        n_ins = len(ins_list)

        while ip < n_ins:
            self.steps_executed += 1
            if self.steps_executed > self.max_steps:
                raise PLikeRuntimeError(
                    f"Limite massimo di istruzioni ({self.max_steps}) superato: probabile ciclo infinito!",
                    ins_list[ip].line,
                )

            ins = ins_list[ip]
            op = ins.op
            arg = ins.arg
            line = ins.line
            ip += 1

            if op == OpCode.LOAD_CONST:
                stack.append(arg)

            elif op == OpCode.POP:
                if stack:
                    stack.pop()

            elif op == OpCode.DUP:
                stack.append(stack[-1])

            elif op == OpCode.INIT_VAR:
                vname = arg["name"]
                tdesc = arg["type"]
                is_param_redecl = arg.get("is_param_redecl", False)
                if is_param_redecl and vname in env:
                    # Non sovrascrivere un parametro già passato, ma se era un array non inizializzato (None/0) crealo!
                    cur = env[vname].get()
                    if tdesc.get("kind") == "array" and not isinstance(cur, PLikeArray):
                        env[vname].set(_default_value(tdesc, self.program.record_schemas))
                else:
                    env[vname] = VarCell(_default_value(tdesc, self.program.record_schemas))

            elif op == OpCode.LOAD_VAR:
                if arg not in env:
                    env[arg] = VarCell(0)
                stack.append(env[arg].get())

            elif op == OpCode.LOAD_VAR_REF:
                if arg not in env:
                    env[arg] = VarCell(0)
                stack.append(env[arg])

            elif op == OpCode.STORE_VAR:
                val = stack.pop()
                if arg not in env:
                    env[arg] = VarCell(val)
                else:
                    env[arg].set(val)

            elif op == OpCode.LOAD_INDEX:
                ndims = int(arg)
                indices = tuple(stack.pop() for _ in range(ndims))[::-1]
                arr = stack.pop()
                if not isinstance(arr, PLikeArray):
                    if isinstance(arr, str) and ndims == 1:
                        i1 = int(indices[0])
                        if 1 <= i1 <= len(arr):
                            stack.append(arr[i1 - 1])
                            continue
                        raise PLikeRuntimeError(f"Indice stringa fuori dai limiti: {i1}.", line)
                    raise PLikeRuntimeError(f"Tentativo di indicizzare un oggetto non-array ({type(arr).__name__}).", line)
                stack.append(arr.get(indices))

            elif op == OpCode.LOAD_INDEX_REF:
                ndims = int(arg)
                indices = tuple(stack.pop() for _ in range(ndims))[::-1]
                arr = stack.pop()
                if not isinstance(arr, PLikeArray):
                    raise PLikeRuntimeError("Tentativo di ottenere riferimento indicizzato su oggetto non-array.", line)
                stack.append(IndexRef(arr, tuple(int(i) for i in indices)))

            elif op == OpCode.STORE_INDEX:
                ndims = int(arg)
                val = stack.pop()
                indices = tuple(stack.pop() for _ in range(ndims))[::-1]
                arr = stack.pop()
                if not isinstance(arr, PLikeArray):
                    raise PLikeRuntimeError("Tentativo di scrivere in un oggetto non-array.", line)
                arr.set(indices, val)

            elif op == OpCode.LOAD_FIELD:
                obj = stack.pop()
                if obj is None:
                    raise PLikeRuntimeError(f"Dereferenziazione di puntatore NULL sul campo '.{arg}'!", line)
                if not isinstance(obj, PLikeRecord):
                    raise PLikeRuntimeError(f"Accesso al campo '.{arg}' su valore non-record ({obj!r}).", line)
                stack.append(obj.get_field(arg))

            elif op == OpCode.LOAD_FIELD_REF:
                obj = stack.pop()
                if obj is None:
                    raise PLikeRuntimeError(f"Dereferenziazione di puntatore NULL sul campo '.{arg}'!", line)
                if not isinstance(obj, PLikeRecord):
                    raise PLikeRuntimeError(f"Accesso al campo '.{arg}' su valore non-record.", line)
                stack.append(FieldRef(obj, arg))

            elif op == OpCode.STORE_FIELD:
                val = stack.pop()
                obj = stack.pop()
                if obj is None:
                    raise PLikeRuntimeError(f"Scrittura su puntatore NULL nel campo '.{arg}'!", line)
                if not isinstance(obj, PLikeRecord):
                    raise PLikeRuntimeError(f"Scrittura del campo '.{arg}' su valore non-record.", line)
                obj.set_field(arg, val)

            elif op == OpCode.ALLOC_NODE:
                node = self._alloc_node(arg)
                stack.append(node)

            elif op == OpCode.FREE_NODE:
                node = stack.pop()
                if isinstance(node, PLikeRecord):
                    node.freed = True

            elif op == OpCode.UNARY_OP:
                v = stack.pop()
                if arg == "-":
                    stack.append(-v)
                elif arg == "+":
                    stack.append(+v)
                elif arg == "not":
                    stack.append(not bool(v))
                else:
                    raise PLikeRuntimeError(f"Operatore unario sconosciuto: {arg!r}", line)

            elif op == OpCode.BINARY_OP:
                r = stack.pop()
                l = stack.pop()
                stack.append(self._eval_binary(arg, l, r, line))

            elif op == OpCode.JMP:
                ip = int(arg)

            elif op == OpCode.JMP_IF_FALSE:
                cond = stack.pop()
                if not bool(cond):
                    ip = int(arg)

            elif op == OpCode.JMP_IF_TRUE:
                cond = stack.pop()
                if bool(cond):
                    ip = int(arg)

            elif op == OpCode.JMP_IF_FALSE_PEEK:
                if not bool(stack[-1]):
                    ip = int(arg)

            elif op == OpCode.JMP_IF_TRUE_PEEK:
                if bool(stack[-1]):
                    ip = int(arg)

            elif op == OpCode.CALL:
                callee, argc, expect_ret = arg
                call_args = [stack.pop() for _ in range(argc)][::-1]
                res = self._invoke(callee, call_args, depth, line)
                if expect_ret:
                    stack.append(res)

            elif op == OpCode.RET:
                return stack.pop() if stack else None

            elif op == OpCode.RET_VOID:
                return None

            elif op == OpCode.READ_REF:
                ref = stack.pop()
                val = self._read_token(arg, line)
                if isinstance(ref, Ref):
                    ref.set(val)
                else:
                    raise PLikeRuntimeError("Destinazione di 'read' non scrivibile.", line)

            elif op == OpCode.PRINT:
                cnt = int(arg)
                vals = [stack.pop() for _ in range(cnt)][::-1]
                text = " ".join(format_plike_value(v) for v in vals)
                self.stdout.write(text + "\n")

            elif op == OpCode.HALT:
                return None

            else:
                raise PLikeRuntimeError(f"OpCode sconosciuto: {op}", line)

        return None

    def _alloc_node(self, type_name: Optional[str]) -> PLikeRecord:
        if type_name and type_name in self.program.record_schemas:
            schema = self.program.record_schemas[type_name]
            fields = {fn: _default_value(fs, self.program.record_schemas) for fn, fs in schema.get("fields", {}).items()}
            return PLikeRecord(fields, type_name=type_name, is_heap_node=True)
        return PLikeRecord({"info": 0, "link": None, "next": None, "prev": None}, type_name=type_name or "nodo", is_heap_node=True)

    def _eval_binary(self, op: str, l: Any, r: Any, line: int) -> Any:
        try:
            if op == "+":
                if isinstance(l, str) or isinstance(r, str):
                    return str(l) + str(r)
                return l + r
            if op == "-":
                return l - r
            if op == "*":
                return l * r
            if op == "/":
                if r == 0:
                    raise PLikeRuntimeError("Divisione per zero!", line)
                # Regola P-Like (Laccetti/C/Fortran): int/int -> divisione intera troncata verso 0!
                if isinstance(l, int) and not isinstance(l, bool) and isinstance(r, int) and not isinstance(r, bool):
                    return int(l / r)
                return float(l) / float(r)
            if op == "div":
                if r == 0:
                    raise PLikeRuntimeError("Divisione intera (div) per zero!", line)
                return int(int(l) / int(r))
            if op == "mod":
                if r == 0:
                    raise PLikeRuntimeError("Operazione modulo (mod) per zero!", line)
                return int(l) % int(r)
            if op == "**":
                return l ** r
            if op == "=":
                return l == r
            if op == "!=":
                return l != r
            if op == "<":
                return l < r
            if op == "<=":
                return l <= r
            if op == ">":
                return l > r
            if op == ">=":
                return l >= r
        except PLikeRuntimeError:
            raise
        except Exception as exc:
            raise PLikeRuntimeError(f"Errore nell'operazione '{op}' tra {l!r} e {r!r}: {exc}", line) from exc
        raise PLikeRuntimeError(f"Operatore binario sconosciuto: {op!r}", line)

    def _invoke(self, callee: str, args: List[Any], depth: int, line: int) -> Any:
        # 1. Sottoprogramma definito dall'utente
        if callee in self.program.units:
            return self._exec_unit(self.program.units[callee], args, depth + 1)

        # 2. Libreria standard P-Like & ADT Laccetti
        def _val(x: Any) -> Any:
            return x.get() if isinstance(x, Ref) else x

        if callee == "abs":
            return abs(_val(args[0]))
        if callee == "sqrt":
            v = float(_val(args[0]))
            if v < 0:
                raise PLikeRuntimeError("Radice quadrata di un numero negativo!", line)
            return math.sqrt(v)
        if callee in ("int", "trunc"):
            return int(_val(args[0]))
        if callee == "floor":
            return math.floor(_val(args[0]))
        if callee == "ceil":
            return math.ceil(_val(args[0]))
        if callee == "real":
            return float(_val(args[0]))
        if callee == "mod":
            return int(_val(args[0])) % int(_val(args[1]))
        if callee == "min":
            return min(_val(args[0]), _val(args[1]))
        if callee == "max":
            return max(_val(args[0]), _val(args[1]))
        if callee == "length":
            v = _val(args[0])
            if isinstance(v, str):
                return len(v)
            if isinstance(v, PLikeArray):
                return len(v.data)
            return 0
        if callee == "is_odd":
            return int(_val(args[0])) % 2 != 0
        if callee == "is_even":
            return int(_val(args[0])) % 2 == 0

        if callee == "swap":
            a_ref, b_ref = args[0], args[1]
            if not (isinstance(a_ref, Ref) and isinstance(b_ref, Ref)):
                raise PLikeRuntimeError("swap richiede due variabili/elementi modificabili.", line)
            tmp = a_ref.get()
            a_ref.set(b_ref.get())
            b_ref.set(tmp)
            return None

        # --- ADT Dinamici Laccetti (Linked List, Stack, Queue) ---
        if callee == "create_node":
            tname = _val(args[0]) if args else None
            return self._alloc_node(str(tname).lower() if tname else None)

        if callee in ("create_list", "linked_list_create", "list_create", "stack_create"):
            if args and isinstance(args[0], Ref):
                args[0].set(None)
            return None

        if callee in ("is_stack_empty", "is_list_empty"):
            return _val(args[0]) is None

        if callee == "is_queue_empty":
            return _val(args[0]) is None and _val(args[1]) is None

        if callee in ("push", "stack_insert"):
            head_ref = args[0]
            elem = _val(args[1])
            node = self._alloc_node(None)
            node.set_field("info", elem)
            node.set_field("link", head_ref.get())
            node.set_field("next", head_ref.get())
            head_ref.set(node)
            return node

        if callee in ("pop", "stack_delete"):
            head_ref = args[0]
            head = head_ref.get()
            if head is None:
                raise PLikeRuntimeError("Pop su stack/lista vuota (head = NULL)!", line)
            val = head.get_field("info")
            nxt = head.get_field("link")
            head.freed = True
            head_ref.set(nxt)
            if len(args) >= 2 and isinstance(args[1], Ref):
                args[1].set(val)
            return val

        if callee == "list_insert":
            head_ref, after_node, elem = args[0], _val(args[1]), _val(args[2])
            node = self._alloc_node(None)
            node.set_field("info", elem)
            if after_node is None:
                node.set_field("link", head_ref.get())
                head_ref.set(node)
            else:
                node.set_field("link", after_node.get_field("link"))
                after_node.set_field("link", node)
            return None

        if callee == "list_visualize":
            curr = _val(args[0])
            items: List[str] = []
            guard = 0
            while curr is not None and guard < 10_000:
                items.append(format_plike_value(curr.get_field("info")))
                curr = curr.get_field("link")
                guard += 1
            self.stdout.write(" -> ".join(items + ["NULL"]) + "\n")
            return None

        if callee == "queue_create":
            args[0].set(None)
            args[1].set(None)
            return None

        if callee == "queue_insert":
            front_ref, rear_ref, elem = args[0], args[1], _val(args[2])
            node = self._alloc_node(None)
            node.set_field("info", elem)
            node.set_field("link", None)
            if front_ref.get() is None:
                front_ref.set(node)
                rear_ref.set(node)
            else:
                rear_ref.get().set_field("link", node)
                rear_ref.set(node)
            return None

        if callee == "queue_delete":
            front_ref, rear_ref, out_ref = args[0], args[1], args[2]
            front = front_ref.get()
            if front is None:
                raise PLikeRuntimeError("Estrazione (queue_delete) da coda vuota!", line)
            val = front.get_field("info")
            if front is rear_ref.get():
                front_ref.set(None)
                rear_ref.set(None)
            else:
                front_ref.set(front.get_field("link"))
            front.freed = True
            if isinstance(out_ref, Ref):
                out_ref.set(val)
            return val

        raise PLikeRuntimeError(f"Funzione o procedura sconosciuta a runtime: '{callee}'.", line)
