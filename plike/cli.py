"""Interfaccia a riga di comando (CLI) del compilatore P-Like (Prof. Giuliano Laccetti)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from . import __version__
from .ast_nodes import ast_to_dict
from .bytecode import CompiledProgram
from .driver import CompileResult, compile_source
from .ide import launch_ide
from .napoli import LaccettiMood, NapoliMatch, fetch_latest_napoli_match
from .repl import start_repl
from .vm import PLikeRuntimeError, PLikeVM


def _ensure_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


def _mood_badge(mood: LaccettiMood) -> str:
    return {
        LaccettiMood.ESTASI_AZZURRA: "[ESTASI AZZURRA - MANICA LARGHISSIMA]",
        LaccettiMood.OTTIMO_UMORE: "[OTTIMO UMORE - COMPILATORE INDULGENTE]",
        LaccettiMood.NEUTRO: "[UMORE NEUTRO - REGOLE STANDARD]",
        LaccettiMood.NERVOSO: "[NERVOSO - MODALITA PIGNOLA]",
        LaccettiMood.FURIA_POST_PARTITA: "[FURIA POST-PARTITA - BOCCIATURA FACILE]",
        LaccettiMood.STANDARD: "[MODALITA STANDARD - VARIABILE NAPOLI OFF]",
    }[mood]


def _print_napoli_banner(match: NapoliMatch, out=None) -> None:
    stream = out if out is not None else sys.stderr
    mood = match.compute_mood()
    stream.write("=" * 68 + "\n")
    stream.write("  P-LIKE COMPILER  |  Prof. Giuliano Laccetti (UNINA Federico II)\n")
    stream.write("=" * 68 + "\n")
    if mood == LaccettiMood.STANDARD:
        stream.write("  Variabile Napoli : DISATTIVATA (--napoli off)\n")
    else:
        stream.write(f"  Ultima SSC Napoli: {match.scoreboard} ({match.competition}, {match.date}) [{match.source}]\n")
        stream.write(f"  Esito Partita    : {match.outcome.value}\n")
    stream.write(f"  Umore Professore : {_mood_badge(mood)}\n")
    stream.write("-" * 68 + "\n")


def _print_compile_report(res: CompileResult, source: str, quiet: bool = False) -> None:
    source_lines = source.splitlines()
    if not quiet:
        _print_napoli_banner(res.verdict.match, out=sys.stderr)

    if res.diagnostics.items and (not quiet or not res.success):
        for d in res.diagnostics.items:
            sys.stderr.write(d.format(source_lines) + "\n")
        sys.stderr.write("-" * 68 + "\n")

    if not quiet or not res.success:
        status = "COMPILAZIONE RIUSCITA" if res.success else "COMPILAZIONE FALLITA"
        sys.stderr.write(f"  Verdetto : {status}  |  Voto: {res.verdict.grade_label}\n")
        sys.stderr.write(f"  Prof.    : {res.verdict.prof_comment}\n")
        sys.stderr.write("=" * 68 + "\n")


def _add_napoli_args(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--napoli",
        default="auto",
        help="Modalita Variabile Napoli: auto (live SSC Napoli), win, big-win, draw, loss, derby-loss, off",
    )
    p.add_argument(
        "--refresh-napoli",
        action="store_true",
        help="Ignora la cache locale e riscarica live l'ultima partita del Napoli",
    )
    p.add_argument(
        "--no-luck",
        action="store_true",
        help="Disattiva il rischio casuale di bocciatura per malumore su codice perfetto dopo una sconfitta",
    )
    p.add_argument(
        "--seed",
        type=int,
        default=None,
        help="Seed deterministico per eventuali valutazioni casuali da malumore post-partita",
    )
    p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Mostra solo l'output del programma (e gli errori in caso di fallimento)",
    )


def _read_source_file(path_str: str) -> tuple[str, str]:
    p = Path(path_str)
    if not p.exists():
        sys.stderr.write(f"Errore: file non trovato: {path_str}\n")
        sys.exit(2)
    return p.read_text(encoding="utf-8-sig"), str(p)


def cmd_run(args: argparse.Namespace) -> int:
    source, fname = _read_source_file(args.file)
    res = compile_source(
        source,
        filename=fname,
        target="bytecode",
        napoli_mode=args.napoli,
        refresh_napoli=args.refresh_napoli,
        allow_luck=not args.no_luck,
        seed=args.seed,
    )
    _print_compile_report(res, source, quiet=args.quiet)
    if not res.success or res.bytecode is None:
        return 1

    try:
        vm = PLikeVM(res.bytecode)
        vm.run()
    except PLikeRuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


def cmd_compile(args: argparse.Namespace) -> int:
    source, fname = _read_source_file(args.file)
    res = compile_source(
        source,
        filename=fname,
        target=args.target,
        napoli_mode=args.napoli,
        refresh_napoli=args.refresh_napoli,
        allow_luck=not args.no_luck,
        seed=args.seed,
    )
    _print_compile_report(res, source, quiet=args.quiet)
    if not res.success or res.generated_code is None:
        return 1

    ext_map = {"bytecode": ".plbc", "c": ".c", "py": ".py"}
    out_path = Path(args.output) if args.output else Path(args.file).with_suffix(ext_map[res.target])
    out_path.write_text(res.generated_code, encoding="utf-8")
    if not args.quiet:
        sys.stderr.write(f"File compilato scritto in: {out_path}\n")
    return 0


def cmd_run_bc(args: argparse.Namespace) -> int:
    p = Path(args.file)
    if not p.exists():
        sys.stderr.write(f"Errore: file bytecode non trovato: {args.file}\n")
        return 2
    bc = CompiledProgram.from_json(p.read_text(encoding="utf-8"))
    try:
        PLikeVM(bc).run()
    except PLikeRuntimeError as exc:
        sys.stderr.write(f"{exc}\n")
        return 1
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    source, fname = _read_source_file(args.file)
    res = compile_source(
        source,
        filename=fname,
        target="bytecode",
        napoli_mode=args.napoli,
        refresh_napoli=args.refresh_napoli,
        allow_luck=not args.no_luck,
        seed=args.seed,
    )
    _print_compile_report(res, source, quiet=args.quiet)
    return 0 if res.success else 1


def cmd_disasm(args: argparse.Namespace) -> int:
    p = Path(args.file)
    if not p.exists():
        sys.stderr.write(f"Errore: file non trovato: {args.file}\n")
        return 2
    if p.suffix.lower() == ".plbc":
        bc = CompiledProgram.from_json(p.read_text(encoding="utf-8"))
        print(bc.disassemble())
        return 0

    source, fname = _read_source_file(args.file)
    res = compile_source(
        source,
        filename=fname,
        target="bytecode",
        napoli_mode=args.napoli,
        refresh_napoli=args.refresh_napoli,
        allow_luck=not args.no_luck,
        seed=args.seed,
    )
    _print_compile_report(res, source, quiet=args.quiet)
    if not res.success or res.bytecode is None:
        return 1
    print(res.bytecode.disassemble())
    return 0


def cmd_ast(args: argparse.Namespace) -> int:
    source, fname = _read_source_file(args.file)
    res = compile_source(source, filename=fname, napoli_mode="off")
    if res.ast is None:
        sys.stderr.write("Impossibile costruire l'AST.\n")
        return 1
    print(json.dumps(ast_to_dict(res.ast), indent=2, ensure_ascii=False))
    return 0


def cmd_napoli(args: argparse.Namespace) -> int:
    match = fetch_latest_napoli_match(mode=args.mode, force_refresh=args.refresh)
    _print_napoli_banner(match, out=sys.stdout)
    mood = match.compute_mood()
    rules = {
        LaccettiMood.ESTASI_AZZURRA: "Fino a 6 errori recuperabili perdonati e auto-corretti; warning ignorati.",
        LaccettiMood.OTTIMO_UMORE: "Fino a 3 errori recuperabili perdonati e auto-corretti; warning ignorati.",
        LaccettiMood.NEUTRO: "Regole standard P-Like: errori bloccanti, warning solo informativi.",
        LaccettiMood.NERVOSO: "Tutte le pignolerie stilistiche Laccetti diventano ERRORI + 15% malumore!",
        LaccettiMood.FURIA_POST_PARTITA: "Tutte le pignolerie diventano ERRORI + 30% rischio bocciatura arbitraria!",
        LaccettiMood.STANDARD: "Variabile Napoli disattivata: compilatore deterministico standard.",
    }[mood]
    print(f"  Effetto sul compilatore: {rules}")
    print("=" * 68)
    return 0


def cmd_gui(args: argparse.Namespace) -> int:
    try:
        from .gui import launch_gui
    except ImportError as exc:
        sys.stderr.write(
            f"Errore: impossibile avviare la GUI Desktop ({exc}).\n"
            "Su Linux installa Tkinter con il package manager della tua distribuzione:\n"
            "  Ubuntu / Debian / Mint / Pop!_OS : sudo apt install python3-tk\n"
            "  Fedora / RHEL / Rocky            : sudo dnf install python3-tkinter\n"
            "  Arch / Manjaro / EndeavourOS     : sudo pacman -S tk\n"
            "  openSUSE                         : sudo zypper install python3-tk\n"
            "  Alpine Linux                     : sudo apk add py3-tkinter\n"
            "In alternativa avvia il Web IDE (non richiede Tkinter): plike ide\n"
        )
        return 1
    return launch_gui(initial_file=args.file, default_napoli=args.napoli)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="plike",
        description="Compilatore e Virtual Machine per il linguaggio didattico P-Like (Prof. Giuliano Laccetti - UNINA Federico II).",
    )
    parser.add_argument("-V", "--version", action="version", version=f"P-Like Compiler {__version__}")
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="Compila (con Variabile Napoli) ed esegue un file .plike sulla P-Like VM")
    p_run.add_argument("file", help="Percorso del file sorgente .plike")
    _add_napoli_args(p_run)
    p_run.set_defaults(func=cmd_run)

    p_comp = sub.add_parser("compile", help="Compila un file .plike verso Bytecode (.plbc), C99 (.c) o Python (.py)")
    p_comp.add_argument("file", help="Percorso del file sorgente .plike")
    p_comp.add_argument("-t", "--target", choices=["bytecode", "c", "py"], default="bytecode", help="Target di compilazione (default: bytecode)")
    p_comp.add_argument("-o", "--output", default=None, help="Percorso del file di output")
    _add_napoli_args(p_comp)
    p_comp.set_defaults(func=cmd_compile)

    p_runbc = sub.add_parser("run-bc", help="Esegue un file bytecode .plbc precedentemente compilato")
    p_runbc.add_argument("file", help="Percorso del file .plbc")
    p_runbc.set_defaults(func=cmd_run_bc)

    p_chk = sub.add_parser("check", help="Analizza e valuta un file .plike (stile esame scritto Laccetti) senza eseguirlo")
    p_chk.add_argument("file", help="Percorso del file sorgente .plike")
    _add_napoli_args(p_chk)
    p_chk.set_defaults(func=cmd_check)

    p_dis = sub.add_parser("disasm", help="Mostra il disassemblato del bytecode P-Like (.plike o .plbc)")
    p_dis.add_argument("file", help="Percorso del file .plike o .plbc")
    _add_napoli_args(p_dis)
    p_dis.set_defaults(func=cmd_disasm)

    p_ast = sub.add_parser("ast", help="Stampa l'Abstract Syntax Tree (JSON) di un file .plike")
    p_ast.add_argument("file", help="Percorso del file sorgente .plike")
    p_ast.set_defaults(func=cmd_ast)

    p_nap = sub.add_parser("napoli", help="Mostra l'ultima partita live dell'SSC Napoli e l'umore del compilatore")
    p_nap.add_argument("--mode", default="auto", help="auto (default), win, big-win, draw, loss, derby-loss, off")
    p_nap.add_argument("--refresh", action="store_true", help="Forza aggiornamento live dalla rete")
    p_nap.set_defaults(func=cmd_napoli)

    p_repl = sub.add_parser("repl", help="Avvia la shell interattiva P-Like")
    p_repl.add_argument("--napoli", default="auto", help="Modalita Variabile Napoli iniziale (default: auto)")
    p_repl.set_defaults(func=lambda a: start_repl(napoli_mode=a.napoli))

    p_ide = sub.add_parser("ide", help="Avvia P-Like Studio, il Web IDE locale con tema Azzurro Napoli")
    p_ide.add_argument("file", nargs="?", default=None, help="File .plike opzionale da aprire (e salvare su disco)")
    p_ide.add_argument("--port", type=int, default=8765, help="Porta HTTP locale (default: 8765)")
    p_ide.add_argument("--no-browser", action="store_true", help="Non aprire automaticamente il browser")
    p_ide.add_argument("--napoli", default="auto", help="Modalita Variabile Napoli iniziale (default: auto)")
    p_ide.set_defaults(
        func=lambda a: launch_ide(
            port=a.port,
            open_browser=not a.no_browser,
            initial_file=a.file,
            default_napoli=a.napoli,
        )
    )

    p_gui = sub.add_parser("gui", help="Avvia P-Like Studio come App Desktop nativa Windows/Linux (Tkinter)")
    p_gui.add_argument("file", nargs="?", default=None, help="File .plike opzionale da aprire")
    p_gui.add_argument("--napoli", default="auto", help="Modalita Variabile Napoli iniziale (default: auto)")
    p_gui.set_defaults(func=cmd_gui)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    _ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not hasattr(args, "func"):
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
