"""Server HTTP locale per P-Like Studio (Web IDE).

Usa esclusivamente la libreria standard Python (`http.server`, `threading`, `webbrowser`)
e si lega solo su `127.0.0.1` per sicurezza.
"""

from __future__ import annotations

import io
import json
import mimetypes
import socket
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import __version__
from ..ast_nodes import ast_to_dict
from ..codegen_c import CCodeGenerator
from ..codegen_py import PythonCodeGenerator
from ..compiler import BytecodeCompiler
from ..driver import compile_source
from ..napoli import fetch_latest_napoli_match
from ..vm import PLikeRuntimeError, PLikeVM

STATIC_DIR = Path(__file__).resolve().parent / "static"
REPO_EXAMPLES_DIR = Path(__file__).resolve().parent.parent.parent / "examples"

EXAMPLE_METADATA: Dict[str, Tuple[str, str, str]] = {
    # filename: (titolo, categoria, stdin_suggerito)
    "esame_studente.plike": ("Esame Studente (Demo Napoli)", "Variabile Napoli", ""),
    "stile_non_canonico.plike": ("Stile Non Canonico (Demo Sconfitta)", "Variabile Napoli", ""),
    "hello.plike": ("Hello World Napoli", "Basi & Ricorsione", ""),
    "fattoriale.plike": ("Fattoriale & MCD Euclide", "Basi & Ricorsione", ""),
    "torre_di_hanoi.plike": ("Torre di Hanoi", "Basi & Ricorsione", ""),
    "ricerca_binaria.plike": ("Ricerca Binaria (Iter + Ric)", "Ricerca & Ordinamento", ""),
    "insertion_sort.plike": ("Insertion Sort", "Ricerca & Ordinamento", ""),
    "selection_sort.plike": ("Selection Sort", "Ricerca & Ordinamento", ""),
    "exchange_sort.plike": ("Exchange Sort (Bubble)", "Ricerca & Ordinamento", ""),
    "merge_array.plike": ("Merge tra 2 Array Ordinati", "Ricerca & Ordinamento", ""),
    "prodotto_matrici.plike": ("Prodotto Matrici 2D", "Calcolo Matriciale", ""),
    "back_substitution.plike": ("Back Substitution (step -1)", "Calcolo Matriciale", ""),
    "numeri_complessi.plike": ("Record: Numeri Complessi", "Record & Strutture Dinamiche", ""),
    "linked_list.plike": ("Linked List Ordinata Ricorsiva", "Record & Strutture Dinamiche", ""),
    "stack_demo.plike": ("Stack LIFO (ADT)", "Record & Strutture Dinamiche", ""),
}


def _serialize_match(match) -> Dict[str, Any]:
    mood = match.compute_mood()
    return {
        "date": match.date,
        "competition": match.competition,
        "home_team": match.home_team,
        "away_team": match.away_team,
        "home_score": match.home_score,
        "away_score": match.away_score,
        "napoli_is_home": match.napoli_is_home,
        "scoreboard": match.scoreboard,
        "outcome": match.outcome.value,
        "source": match.source,
        "against_rival": match.against_rival,
        "goal_diff": match.goal_diff,
        "mood": mood.value,
    }


def _serialize_diag(d, source_lines: List[str]) -> Dict[str, Any]:
    src_line = ""
    if 1 <= d.span.line <= len(source_lines):
        src_line = source_lines[d.span.line - 1].rstrip("\r\n")
    return {
        "severity": d.severity.value,
        "code": d.code,
        "message": d.message,
        "line": d.span.line,
        "col": d.span.col,
        "hint": d.hint,
        "source_line": src_line,
        "forgiven_by_napoli": d.forgiven_by_napoli,
        "promoted_by_napoli": d.promoted_by_napoli,
    }


def _list_examples() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if not REPO_EXAMPLES_DIR.exists():
        return items

    order = list(EXAMPLE_METADATA.keys())
    files = sorted(
        REPO_EXAMPLES_DIR.glob("*.plike"),
        key=lambda p: (order.index(p.name) if p.name in order else 999, p.name),
    )
    for p in files:
        title, category, default_stdin = EXAMPLE_METADATA.get(
            p.name, (p.stem.replace("_", " ").title(), "Altri Esempi", "")
        )
        items.append(
            {
                "filename": p.name,
                "title": title,
                "category": category,
                "default_stdin": default_stdin,
                "code": p.read_text(encoding="utf-8-sig"),
            }
        )
    return items


class PLikeIDEState:
    def __init__(self, initial_file: Optional[Path] = None, default_napoli: str = "auto"):
        self.initial_file: Optional[Path] = initial_file.resolve() if initial_file else None
        self.default_napoli = default_napoli


def _make_handler(state: PLikeIDEState):
    class PLikeIDEHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args: Any) -> None:
            # Silenzia log HTTP rumorosi in console
            return

        def _send_bytes(self, status: int, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status: int, payload: Dict[str, Any]) -> None:
            raw = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send_bytes(status, "application/json; charset=utf-8", raw)

        def _read_json_body(self) -> Dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return {}
            if length <= 0 or length > 2_000_000:
                return {}
            raw = self.rfile.read(length)
            try:
                return json.loads(raw.decode("utf-8"))
            except json.JSONDecodeError:
                return {}

        def do_GET(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            qs = urllib.parse.parse_qs(parsed.query)

            if path == "/" or path == "/index.html":
                html_path = STATIC_DIR / "index.html"
                self._send_bytes(HTTPStatus.OK, "text/html; charset=utf-8", html_path.read_bytes())
                return

            if path.startswith("/static/"):
                rel = path[len("/static/"):]
                # Previene path traversal
                target = (STATIC_DIR / rel).resolve()
                if STATIC_DIR.resolve() not in target.parents or not target.is_file():
                    self._send_json(HTTPStatus.NOT_FOUND, {"error": "Risorsa non trovata"})
                    return
                ctype, _ = mimetypes.guess_type(str(target))
                ctype = ctype or "application/octet-stream"
                if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
                    ctype += "; charset=utf-8"
                self._send_bytes(HTTPStatus.OK, ctype, target.read_bytes())
                return

            if path == "/api/info":
                init_payload: Optional[Dict[str, Any]] = None
                if state.initial_file and state.initial_file.is_file():
                    init_payload = {
                        "filename": state.initial_file.name,
                        "full_path": str(state.initial_file),
                        "can_save_disk": True,
                        "code": state.initial_file.read_text(encoding="utf-8-sig"),
                    }
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "version": __version__,
                        "default_napoli": state.default_napoli,
                        "initial_file": init_payload,
                    },
                )
                return

            if path == "/api/examples":
                self._send_json(HTTPStatus.OK, {"examples": _list_examples()})
                return

            if path == "/api/napoli":
                mode = (qs.get("mode") or [state.default_napoli])[0]
                refresh = (qs.get("refresh") or ["0"])[0] in ("1", "true", "yes")
                try:
                    match = fetch_latest_napoli_match(mode=mode, force_refresh=refresh)
                except ValueError as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return
                self._send_json(HTTPStatus.OK, {"match": _serialize_match(match)})
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Endpoint non trovato"})

        def do_POST(self) -> None:
            parsed = urllib.parse.urlparse(self.path)
            path = parsed.path
            data = self._read_json_body()

            if path in ("/api/run", "/api/check"):
                execute = path == "/api/run"
                source = str(data.get("code", ""))
                filename = str(data.get("filename", "programma.plike"))
                stdin_text = str(data.get("stdin", ""))
                napoli_mode = str(data.get("napoli_mode", state.default_napoli))
                refresh_napoli = bool(data.get("refresh_napoli", False))
                allow_luck = bool(data.get("allow_luck", True))
                raw_seed = data.get("seed", None)
                seed: Optional[int] = None
                if raw_seed not in (None, ""):
                    try:
                        seed = int(raw_seed)
                    except (TypeError, ValueError):
                        seed = None

                t0 = time.perf_counter()
                try:
                    res = compile_source(
                        source,
                        filename=filename,
                        target="bytecode",
                        napoli_mode=napoli_mode,
                        refresh_napoli=refresh_napoli,
                        allow_luck=allow_luck,
                        seed=seed,
                    )
                except ValueError as exc:
                    self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})
                    return

                source_lines = source.splitlines()
                stdout_text = ""
                runtime_error: Optional[str] = None
                steps = 0
                disasm = ""
                bytecode_json = ""
                c_code = ""
                py_code = ""
                ast_json = json.dumps(ast_to_dict(res.ast), indent=2, ensure_ascii=False) if res.ast else ""

                if res.success and res.bytecode is not None and res.ast is not None:
                    disasm = res.bytecode.disassemble()
                    bytecode_json = res.bytecode.to_json()
                    try:
                        c_code = CCodeGenerator().generate(res.ast)
                    except Exception as exc:
                        c_code = f"/* Errore generazione C99: {exc} */"
                    try:
                        py_code = PythonCodeGenerator().generate(res.ast)
                    except Exception as exc:
                        py_code = f"# Errore generazione Python: {exc}"

                    if execute:
                        out_buf = io.StringIO()
                        in_buf = io.StringIO(stdin_text)
                        vm = PLikeVM(res.bytecode, stdin=in_buf, stdout=out_buf)
                        try:
                            vm.run()
                        except PLikeRuntimeError as exc:
                            runtime_error = str(exc)
                        stdout_text = out_buf.getvalue()
                        steps = vm.steps_executed

                elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
                v = res.verdict
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "success": res.success,
                        "executed": execute and res.success,
                        "elapsed_ms": elapsed_ms,
                        "steps": steps,
                        "stdout": stdout_text,
                        "runtime_error": runtime_error,
                        "verdict": {
                            "passed": v.passed,
                            "mood": v.mood.value,
                            "grade_numeric": v.grade_numeric,
                            "grade_label": v.grade_label,
                            "prof_comment": v.prof_comment,
                            "forgiven_count": v.forgiven_count,
                            "promoted_count": v.promoted_count,
                            "bad_luck_rejection": v.bad_luck_rejection,
                            "match": _serialize_match(v.match),
                        },
                        "diagnostics": [_serialize_diag(d, source_lines) for d in res.diagnostics.items],
                        "disasm": disasm,
                        "bytecode_json": bytecode_json,
                        "c_code": c_code,
                        "py_code": py_code,
                        "ast_json": ast_json,
                    },
                )
                return

            if path == "/api/save-local":
                if state.initial_file is None:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        {"error": "Nessun file locale aperto da CLI; usa il download dal browser."},
                    )
                    return
                code = str(data.get("code", ""))
                state.initial_file.write_text(code, encoding="utf-8")
                self._send_json(HTTPStatus.OK, {"saved": True, "path": str(state.initial_file)})
                return

            self._send_json(HTTPStatus.NOT_FOUND, {"error": "Endpoint non trovato"})

    return PLikeIDEHandler


def create_ide_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    initial_file: Optional[Path] = None,
    default_napoli: str = "auto",
) -> Tuple[ThreadingHTTPServer, int]:
    """Crea un ThreadingHTTPServer (se la porta richiesta è occupata, cerca la prima libera)."""
    state = PLikeIDEState(initial_file=initial_file, default_napoli=default_napoli)
    handler = _make_handler(state)

    if port == 0:
        srv = ThreadingHTTPServer((host, 0), handler)
        return srv, int(srv.server_address[1])

    last_err: Optional[OSError] = None
    for candidate in range(port, port + 20):
        try:
            srv = ThreadingHTTPServer((host, candidate), handler)
            return srv, candidate
        except OSError as exc:
            last_err = exc
    raise last_err or OSError(f"Impossibile aprire una porta a partire da {port}")


def launch_ide(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    initial_file: Optional[str] = None,
    default_napoli: str = "auto",
) -> int:
    init_path = Path(initial_file) if initial_file else None
    if init_path is not None and not init_path.exists():
        print(f"Errore: file iniziale non trovato: {initial_file}")
        return 2

    srv, actual_port = create_ide_server(
        host=host,
        port=port,
        initial_file=init_path,
        default_napoli=default_napoli,
    )
    url = f"http://{host}:{actual_port}/"
    print("=" * 64)
    print(f"  P-Like Studio (IDE) avviato su: {url}")
    print("  Prof. Giuliano Laccetti | UNINA Federico II | Forza Napoli!")
    print("  Premi Ctrl+C nel terminale per chiudere il server.")
    print("=" * 64)

    if open_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()

    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nP-Like Studio chiuso. Forza Napoli!")
    finally:
        srv.server_close()
    return 0
