"""Shell interattiva (REPL) per sperimentare con il linguaggio P-Like."""

from __future__ import annotations

import sys
from typing import List

from .driver import compile_source
from .napoli import fetch_latest_napoli_match
from .vm import PLikeRuntimeError, PLikeVM


def start_repl(napoli_mode: str = "auto") -> int:
    mode = napoli_mode
    match = fetch_latest_napoli_match(mode=mode)
    print("=" * 64)
    print("  P-Like Interactive REPL  |  Prof. Giuliano Laccetti")
    print(f"  SSC Napoli: {match.scoreboard} ({match.outcome.value}) -> {match.compute_mood().value}")
    print("  Digita un programma P-Like e chiudi con una riga vuota o :run")
    print("  Comandi: :run, :clear, :napoli [auto|win|draw|loss|off], :help, :quit")
    print("=" * 64)

    buffer: List[str] = []
    while True:
        prompt = "plike> " if not buffer else "  ...> "
        try:
            line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print("\nArrivederci e Forza Napoli!")
            return 0

        cmd = line.strip()
        if cmd in (":quit", ":exit", ":q"):
            print("Arrivederci e Forza Napoli!")
            return 0
        if cmd == ":help":
            print("Comandi REPL:")
            print("  :run                 Compila ed esegue il codice nel buffer")
            print("  :clear               Svuota il buffer")
            print("  :napoli [modalita]   Mostra o cambia la modalita Napoli (auto|win|big-win|draw|loss|derby-loss|off)")
            print("  :quit                Esce dal REPL")
            print("  (Premi Invio su riga vuota per eseguire subito il buffer)")
            continue
        if cmd == ":clear":
            buffer.clear()
            print("Buffer svuotato.")
            continue
        if cmd.startswith(":napoli"):
            parts = cmd.split()
            if len(parts) > 1:
                try:
                    match = fetch_latest_napoli_match(mode=parts[1], force_refresh=(parts[1] == "auto"))
                    mode = parts[1]
                except ValueError as e:
                    print(f"Errore: {e}")
                    continue
            print(f"SSC Napoli: {match.scoreboard} ({match.outcome.value}) -> Umore: {match.compute_mood().value}")
            continue
        if cmd == ":run" or (cmd == "" and buffer):
            code = "\n".join(buffer)
            buffer.clear()
            if not code.strip():
                continue
            # Se l'utente scrive uno snippet rapido senza begin/end, avvolgilo automaticamente
            low = code.lstrip().lower()
            if not any(low.startswith(k) for k in ("begin", "procedure", "function", "type", "var", "logical", "integer", "real", "character")):
                code = f"begin repl\n{code}\nend repl\n"
            res = compile_source(code, filename="<repl>", napoli_mode=mode, match_override=match)
            if res.diagnostics.items:
                for d in res.diagnostics.items:
                    print(d.format(code.splitlines()))
            print(f"[{res.verdict.grade_label}] {res.verdict.prof_comment}")
            if res.success and res.bytecode is not None:
                try:
                    PLikeVM(res.bytecode).run()
                except PLikeRuntimeError as exc:
                    print(exc)
            continue

        buffer.append(line)
