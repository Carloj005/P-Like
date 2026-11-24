"""Driver principale della pipeline di compilazione ed esecuzione P-Like.

Pipeline completa:
    Sorgente (.plike)
      -> Lexer (Tokenizzazione)
      -> Parser (Costruzione AST + recupero errori d'esame)
      -> SemanticAnalyzer (Type-checking, disambiguazione, Laccetti Style Audit)
      -> NapoliMoodEngine (Valutazione risultato SSC Napoli + Verdetto Laccetti)
      -> Backend scelto:
           - 'bytecode' -> BytecodeCompiler (.plbc) -> PLikeVM
           - 'c'        -> CCodeGenerator (.c)
           - 'py'       -> PythonCodeGenerator (.py)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, TextIO

from .ast_nodes import Program
from .bytecode import CompiledProgram
from .codegen_c import CCodeGenerator
from .codegen_py import PythonCodeGenerator
from .compiler import BytecodeCompiler
from .diagnostics import DiagnosticBag
from .lexer import Lexer
from .napoli import CompilationVerdict, NapoliMatch, evaluate_compilation_verdict, fetch_latest_napoli_match
from .parser import Parser
from .semantic import SemanticAnalyzer
from .vm import PLikeVM


@dataclass
class CompileResult:
    success: bool
    verdict: CompilationVerdict
    diagnostics: DiagnosticBag
    ast: Optional[Program] = None
    bytecode: Optional[CompiledProgram] = None
    generated_code: Optional[str] = None
    target: str = "bytecode"


def compile_source(
    source: str,
    *,
    filename: str = "<input>",
    target: str = "bytecode",
    napoli_mode: str = "auto",
    refresh_napoli: bool = False,
    allow_luck: bool = True,
    seed: Optional[int] = None,
    match_override: Optional[NapoliMatch] = None,
) -> CompileResult:
    """Esegue l'intera pipeline di compilazione P-Like (con Variabile Napoli!)."""
    diags = DiagnosticBag()

    # Fase 1: Lexing
    lexer = Lexer(source, filename=filename, diagnostics=diags)
    tokens = lexer.tokenize()

    # Fase 2: Parsing
    parser = Parser(tokens, diagnostics=diags)
    ast = parser.parse()

    # Fase 3: Analisi semantica (solo se non ci sono errori fatali di sintassi)
    if not diags.fatals:
        analyzer = SemanticAnalyzer(diags)
        analyzer.analyze(ast)

    # Fase 4: Variabile Napoli & Verdetto Laccetti
    match = match_override if match_override is not None else fetch_latest_napoli_match(
        mode=napoli_mode,
        force_refresh=refresh_napoli,
    )
    verdict = evaluate_compilation_verdict(
        diags,
        match,
        allow_luck=allow_luck,
        seed=seed,
    )

    if not verdict.passed:
        return CompileResult(
            success=False,
            verdict=verdict,
            diagnostics=diags,
            ast=ast,
            target=target,
        )

    # Fase 5: Generazione codice (Bytecode / C99 / Python)
    t = target.lower()
    if t in ("bytecode", "bc", "plbc"):
        bc = BytecodeCompiler(source_name=filename).compile(ast)
        return CompileResult(
            success=True,
            verdict=verdict,
            diagnostics=diags,
            ast=ast,
            bytecode=bc,
            generated_code=bc.to_json(),
            target="bytecode",
        )
    if t == "c":
        c_code = CCodeGenerator().generate(ast)
        return CompileResult(
            success=True,
            verdict=verdict,
            diagnostics=diags,
            ast=ast,
            generated_code=c_code,
            target="c",
        )
    if t in ("py", "python"):
        py_code = PythonCodeGenerator().generate(ast)
        return CompileResult(
            success=True,
            verdict=verdict,
            diagnostics=diags,
            ast=ast,
            generated_code=py_code,
            target="py",
        )
    raise ValueError(f"Target di compilazione non supportato: {target!r}. Usa 'bytecode', 'c' o 'py'.")


def run_source(
    source: str,
    *,
    filename: str = "<input>",
    napoli_mode: str = "auto",
    refresh_napoli: bool = False,
    allow_luck: bool = True,
    seed: Optional[int] = None,
    match_override: Optional[NapoliMatch] = None,
    stdin: Optional[TextIO] = None,
    stdout: Optional[TextIO] = None,
) -> CompileResult:
    """Compila (valutando la Variabile Napoli) ed esegue immediatamente il programma sulla P-Like VM."""
    res = compile_source(
        source,
        filename=filename,
        target="bytecode",
        napoli_mode=napoli_mode,
        refresh_napoli=refresh_napoli,
        allow_luck=allow_luck,
        seed=seed,
        match_override=match_override,
    )
    if res.success and res.bytecode is not None:
        vm = PLikeVM(res.bytecode, stdin=stdin, stdout=stdout)
        vm.run()
    return res
