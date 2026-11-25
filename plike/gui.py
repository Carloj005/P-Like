"""P-Like Studio — Applicazione Desktop Nativa Windows (Tkinter Dark + Tema Azzurro SSC Napoli).

Zero dipendenze esterne a runtime! Include:
- Finestra Windows nativa con barra del titolo scura (DWM Win11/10) e supporto High-DPI
- Barra live SSC Napoli con risultato partita reale, barra umore Prof. Laccetti a 5 livelli e simulatore
- Sidebar esplora esempi P-Like (funziona anche dentro l'eseguibile PyInstaller .exe!)
- Editor P-Like con syntax highlighting in tempo reale, numeri di riga e indicatori errore/perdonato
- Dock INPUT (read / stdin)
- Card Verdetto Prof. Laccetti con voto 0-30 e Lode / BOCCIATO e commento del prof
- 6 schede output: Console, Diagnostiche cliccabili (salta alla riga!), Bytecode, C99, Python, AST
- Apertura, salvataggio ed esportazione file .plike / .c / .py / .plbc con finestre di dialogo Windows native
"""

from __future__ import annotations

import ctypes
import io
import json
import os
import re
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, List, Optional, Tuple

from . import __version__
from .ast_nodes import ast_to_dict
from .codegen_c import CCodeGenerator
from .codegen_py import PythonCodeGenerator
from .driver import CompileResult, compile_source
from .napoli import LaccettiMood, MatchOutcome, NapoliMatch, fetch_latest_napoli_match
from .vm import PLikeRuntimeError, PLikeVM

# ---------------------------------------------------------------------------
# Palette Midnight Slate & Azzurro SSC Napoli
# ---------------------------------------------------------------------------

C_BG_APP = "#09111e"
C_BG_SURF = "#0e1a2d"
C_BG_ELEV = "#13233b"
C_BG_INPUT = "#0a1424"
C_BG_GUTTER = "#081120"
C_BG_ACTIVE_LINE = "#112138"
C_BORDER = "#1e3556"

C_AZZURRO = "#12a0d7"
C_AZZURRO_BRIGHT = "#38bdf8"
C_AZZURRO_DEEP = "#003c82"

C_TEXT = "#e6f0fb"
C_TEXT_MUTED = "#8aa4c5"
C_TEXT_DIM = "#5d789c"

C_OK = "#22c55e"
C_OK_LIGHT = "#86efac"
C_WARN = "#f59e0b"
C_WARN_LIGHT = "#fde68a"
C_ERR = "#ef4444"
C_ERR_LIGHT = "#fca5a5"

# Colori Syntax Highlighting
SYN_KW = "#38bdf8"
SYN_TYPE = "#a78bfa"
SYN_CONST = "#fbbf24"
SYN_NUM = "#fb923c"
SYN_STR = "#4ade80"
SYN_OP = "#f472b6"
SYN_CMT = "#64748b"

EXAMPLE_META: Dict[str, Tuple[str, str]] = {
    "esame_studente.plike": ("Esame Studente (Demo Napoli)", "Variabile Napoli"),
    "stile_non_canonico.plike": ("Stile Non Canonico (Demo Sconfitta)", "Variabile Napoli"),
    "hello.plike": ("Hello World Napoli", "Basi & Ricorsione"),
    "fattoriale.plike": ("Fattoriale & MCD Euclide", "Basi & Ricorsione"),
    "torre_di_hanoi.plike": ("Torre di Hanoi", "Basi & Ricorsione"),
    "ricerca_binaria.plike": ("Ricerca Binaria (Iter + Ric)", "Ricerca & Ordinamento"),
    "insertion_sort.plike": ("Insertion Sort", "Ricerca & Ordinamento"),
    "selection_sort.plike": ("Selection Sort", "Ricerca & Ordinamento"),
    "exchange_sort.plike": ("Exchange Sort (Bubble)", "Ricerca & Ordinamento"),
    "merge_array.plike": ("Merge tra 2 Array Ordinati", "Ricerca & Ordinamento"),
    "prodotto_matrici.plike": ("Prodotto Matrici 2D", "Calcolo Matriciale"),
    "back_substitution.plike": ("Back Substitution (step -1)", "Calcolo Matriciale"),
    "numeri_complessi.plike": ("Record: Numeri Complessi", "Record & Strutture Dinamiche"),
    "linked_list.plike": ("Linked List Ordinata Ricorsiva", "Record & Strutture Dinamiche"),
    "stack_demo.plike": ("Stack LIFO (ADT)", "Record & Strutture Dinamiche"),
}

NAPOLI_MODES: List[Tuple[str, str]] = [
    ("Live SSC Napoli (Auto)", "auto"),
    ("Goleada (Napoli 5-1 Juve)", "big-win"),
    ("Vittoria (Napoli 2-0 Torino)", "win"),
    ("Pareggio (Napoli 1-1 Lazio)", "draw"),
    ("Sconfitta (Napoli 0-1 Bologna)", "loss"),
    ("Disastro (Juve 3-0 Napoli)", "derby-loss"),
    ("Disattivata (Standard)", "off"),
]

PLIKE_TOKEN_RE = re.compile(
    r"(?P<cmt>\(\*[\s\S]*?\*\)|/\*[\s\S]*?\*/|//[^\n]*)"
    r"|(?P<str>'(?:''|[^'\n])*'|\"(?:\\.|[^\"\n])*\")"
    r"|(?P<dconst>\.(?:TRUE|FALSE)\.)"
    r"|(?P<dop>\.(?:AND|OR|NOT)\.)"
    r"|(?P<inout>\bin/out\b)"
    r"|(?P<num>\b\d+\.(?!\.)\d*(?:[eE][+-]?\d+)?|\b\d+\b)"
    r"|(?P<op>:=|!=|<>|<=|>=|\*\*|[+\-*/=<>^!])"
    r"|(?P<word>\b[A-Za-z_][A-Za-z0-9_]*\b)",
    re.IGNORECASE,
)

PLIKE_KEYWORDS = {
    "begin", "end", "var", "type", "record", "endrecord", "array", "of",
    "procedure", "endprocedure", "function", "endfunction", "return",
    "if", "then", "else", "elseif", "endif", "for", "to", "downto", "step",
    "do", "endfor", "while", "endwhile", "repeat", "until", "read", "print",
    "write", "allocate", "alloca", "deallocate", "dealloca", "free",
    "in", "out", "in/out", "input", "output", "inout", "and", "or", "not", "mod", "div",
}
PLIKE_TYPES = {
    "integer", "real", "character", "char", "string", "logical", "boolean",
    "list_pointer", "stack_pointer", "queue_pointer", "comb_pointer",
}
PLIKE_CONSTS = {"true", "false", "null", "nil"}


def _resource_root() -> Path:
    """Restituisce la directory radice delle risorse (compatibile sia con sorgenti sia con PyInstaller .exe!)."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def _find_examples_dir() -> Optional[Path]:
    root = _resource_root()
    cand = root / "examples"
    if cand.is_dir():
        return cand
    return None


def _find_icon_path() -> Optional[Path]:
    root = _resource_root()
    for rel in ("assets/plike.ico", "plike.ico"):
        cand = root / rel
        if cand.is_file():
            return cand
    return None


def _enable_windows_high_dpi_and_dark_bar(window: tk.Tk) -> None:
    if sys.platform != "win32":
        return
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1)
        # DWMWA_USE_IMMERSIVE_DARK_MODE (20 su Win11/Win10 2004+, fallback 19)
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(value), ctypes.sizeof(value)
            )
    except Exception:
        pass


class PLikeDesktopIDE:
    def __init__(
        self,
        root: tk.Tk,
        initial_file: Optional[str] = None,
        default_napoli: str = "auto",
    ):
        self.root = root
        self.root.title("P-Like Studio — Prof. Giuliano Laccetti (UNINA Federico II)")
        self.root.geometry("1360x840")
        self.root.minsize(1020, 640)
        self.root.configure(bg=C_BG_APP)

        ico = _find_icon_path()
        if ico is not None:
            try:
                self.root.iconbitmap(str(ico))
            except Exception:
                pass

        self.current_file: Optional[Path] = None
        self.is_dirty: bool = False
        self.current_match: Optional[NapoliMatch] = None
        self.last_diags: List[Any] = []
        self.line_diag_markers: Dict[int, str] = {}
        self.last_artifacts: Dict[str, str] = {"bytecode_json": "", "c_code": "", "py_code": "", "ast_json": ""}
        self._highlight_after_id: Optional[str] = None
        self._example_paths: Dict[str, Path] = {}

        # Variabili Tk
        self.mode_label_to_key = {lbl: key for lbl, key in NAPOLI_MODES}
        self.mode_key_to_label = {key: lbl for lbl, key in NAPOLI_MODES}
        init_label = self.mode_key_to_label.get(default_napoli.lower(), NAPOLI_MODES[0][0])
        self.napoli_mode_var = tk.StringVar(value=init_label)
        self.no_luck_var = tk.BooleanVar(value=False)
        self.seed_var = tk.StringVar(value="")
        self.filename_var = tk.StringVar(value="esame_studente.plike")
        self.cursor_var = tk.StringVar(value="Ln 1, Col 1")
        self.status_var = tk.StringVar(value="P-Like Studio pronto — Forza Napoli!")

        self._configure_ttk_styles()
        self._build_menubar()
        self._build_topbar()
        self._build_napoli_bar()
        self._build_workbench()
        self._build_statusbar()
        self._bind_shortcuts()

        self._populate_examples()
        self._load_initial_content(initial_file)

        _enable_windows_high_dpi_and_dark_bar(self.root)
        # Avvia recupero live SSC Napoli in background
        self._refresh_napoli_async(force_refresh=False)

    # ------------------------------------------------------------------
    # Stili ttk scuri
    # ------------------------------------------------------------------

    def _configure_ttk_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except Exception:
            pass

        style.configure(".", background=C_BG_SURF, foreground=C_TEXT, font=("Segoe UI", 10))
        style.configure("TFrame", background=C_BG_SURF)
        style.configure("App.TFrame", background=C_BG_APP)
        style.configure("TPanedwindow", background=C_BORDER)
        style.configure("Sash", sashthickness=5, gripcount=0, background=C_BORDER)

        # Notebook tabs
        style.configure("Dark.TNotebook", background=C_BG_SURF, borderwidth=0, tabmargins=[2, 2, 2, 0])
        style.configure(
            "Dark.TNotebook.Tab",
            background="#0b1628",
            foreground=C_TEXT_MUTED,
            padding=[11, 6],
            borderwidth=0,
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "Dark.TNotebook.Tab",
            background=[("selected", C_BG_ELEV), ("active", "#132540")],
            foreground=[("selected", C_AZZURRO_BRIGHT), ("active", C_TEXT)],
        )

        # Treeview (Sidebar & Diagnostiche)
        style.configure(
            "Dark.Treeview",
            background=C_BG_SURF,
            fieldbackground=C_BG_SURF,
            foreground=C_TEXT,
            borderwidth=0,
            rowheight=24,
            font=("Segoe UI", 9),
        )
        style.configure(
            "Dark.Treeview.Heading",
            background=C_BG_ELEV,
            foreground=C_TEXT_MUTED,
            borderwidth=0,
            font=("Segoe UI Semibold", 9),
        )
        style.map(
            "Dark.Treeview",
            background=[("selected", "#14385c")],
            foreground=[("selected", "#ffffff")],
        )

        # Combobox
        style.configure(
            "Dark.TCombobox",
            fieldbackground=C_BG_INPUT,
            background=C_BG_ELEV,
            foreground=C_TEXT,
            arrowcolor=C_AZZURRO_BRIGHT,
            bordercolor=C_BORDER,
            lightcolor=C_BORDER,
            darkcolor=C_BORDER,
        )
        style.map(
            "Dark.TCombobox",
            fieldbackground=[("readonly", C_BG_INPUT)],
            foreground=[("readonly", C_TEXT)],
            selectbackground=[("readonly", C_BG_INPUT)],
            selectforeground=[("readonly", C_TEXT)],
        )

        # Scrollbars scure
        style.configure(
            "Dark.Vertical.TScrollbar",
            background=C_BG_ELEV,
            troughcolor=C_BG_INPUT,
            bordercolor=C_BG_INPUT,
            arrowcolor=C_TEXT_MUTED,
            relief="flat",
        )
        style.configure(
            "Dark.Horizontal.TScrollbar",
            background=C_BG_ELEV,
            troughcolor=C_BG_INPUT,
            bordercolor=C_BG_INPUT,
            arrowcolor=C_TEXT_MUTED,
            relief="flat",
        )

    # ------------------------------------------------------------------
    # Costruzione interfaccia
    # ------------------------------------------------------------------

    def _build_menubar(self) -> None:
        menubar = tk.Menu(self.root, bg=C_BG_SURF, fg=C_TEXT, activebackground=C_AZZURRO_DEEP, activeforeground="#fff")

        m_file = tk.Menu(menubar, tearoff=0, bg=C_BG_SURF, fg=C_TEXT, activebackground=C_AZZURRO_DEEP, activeforeground="#fff")
        m_file.add_command(label="Nuovo file (.plike)", accelerator="Ctrl+N", command=self.new_file)
        m_file.add_command(label="Apri file (.plike)...", accelerator="Ctrl+O", command=self.open_file)
        m_file.add_command(label="Salva", accelerator="Ctrl+S", command=self.save_file)
        m_file.add_command(label="Salva con nome...", accelerator="Ctrl+Shift+S", command=self.save_file_as)
        m_file.add_separator()
        m_file.add_command(label="Esporta Bytecode (.plbc)...", command=lambda: self.export_artifact("bytecode_json", ".plbc", "P-Like Bytecode"))
        m_file.add_command(label="Esporta C99 (.c)...", command=lambda: self.export_artifact("c_code", ".c", "Codice C99"))
        m_file.add_command(label="Esporta Python (.py)...", command=lambda: self.export_artifact("py_code", ".py", "Codice Python"))
        m_file.add_separator()
        m_file.add_command(label="Esci", command=self.root.quit)
        menubar.add_cascade(label="File", menu=m_file)

        m_run = tk.Menu(menubar, tearoff=0, bg=C_BG_SURF, fg=C_TEXT, activebackground=C_AZZURRO_DEEP, activeforeground="#fff")
        m_run.add_command(label="Compila ed Esegui", accelerator="F5 / Ctrl+Enter", command=lambda: self.run_or_check(True))
        m_run.add_command(label="Verifica compilazione e voto", accelerator="Ctrl+Shift+B", command=lambda: self.run_or_check(False))
        menubar.add_cascade(label="Esegui", menu=m_run)

        m_nap = tk.Menu(menubar, tearoff=0, bg=C_BG_SURF, fg=C_TEXT, activebackground=C_AZZURRO_DEEP, activeforeground="#fff")
        m_nap.add_command(label="Aggiorna Live SSC Napoli", command=lambda: self._refresh_napoli_async(force_refresh=True))
        m_nap.add_separator()
        for lbl, key in NAPOLI_MODES:
            m_nap.add_command(label=lbl, command=lambda l=lbl: self._select_napoli_mode_label(l))
        menubar.add_cascade(label="Variabile Napoli", menu=m_nap)

        m_help = tk.Menu(menubar, tearoff=0, bg=C_BG_SURF, fg=C_TEXT, activebackground=C_AZZURRO_DEEP, activeforeground="#fff")
        m_help.add_command(label="Guida Rapida Sintassi P-Like", command=self.show_cheatsheet)
        m_help.add_command(label="Info su P-Like Studio", command=self.show_about)
        menubar.add_cascade(label="Aiuto", menu=m_help)

        self.root.config(menu=menubar)

    def _build_topbar(self) -> None:
        bar = tk.Frame(self.root, bg="#0c182b", height=52, highlightthickness=1, highlightbackground=C_BORDER)
        bar.pack(fill=tk.X, side=tk.TOP)
        bar.pack_propagate(False)

        # Logo Azzurro Napoli
        crest_canvas = tk.Canvas(bar, width=36, height=36, bg="#0c182b", highlightthickness=0)
        crest_canvas.pack(side=tk.LEFT, padx=(12, 8), pady=8)
        crest_canvas.create_oval(2, 2, 34, 34, fill=C_AZZURRO, outline="#e0f2fe", width=2)
        crest_canvas.create_text(18, 18, text="P", fill="#ffffff", font=("Segoe UI", 14, "bold"))

        brand_box = tk.Frame(bar, bg="#0c182b")
        brand_box.pack(side=tk.LEFT)
        tk.Label(brand_box, text="P-Like Studio", bg="#0c182b", fg="#f0f9ff", font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(brand_box, text="Prof. Giuliano Laccetti · UNINA Federico II", bg="#0c182b", fg=C_TEXT_MUTED, font=("Segoe UI", 8)).pack(anchor="w")

        # Nome file attivo
        file_box = tk.Frame(bar, bg=C_BG_INPUT, highlightthickness=1, highlightbackground=C_BORDER, padx=10, pady=4)
        file_box.pack(side=tk.LEFT, padx=24)
        self.lbl_filename = tk.Label(file_box, textvariable=self.filename_var, bg=C_BG_INPUT, fg=C_TEXT, font=("Consolas", 10))
        self.lbl_filename.pack(side=tk.LEFT)

        # Pulsanti azione a destra
        actions = tk.Frame(bar, bg="#0c182b")
        actions.pack(side=tk.RIGHT, padx=12)

        self.btn_run = tk.Button(
            actions,
            text="  ▶  Esegui (F5)  ",
            bg=C_AZZURRO,
            fg="#ffffff",
            activebackground="#0284c7",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            pady=5,
            command=lambda: self.run_or_check(True),
        )
        self.btn_run.pack(side=tk.LEFT, padx=4)

        self.btn_check = tk.Button(
            actions,
            text="  ✓  Verifica  ",
            bg=C_BG_ELEV,
            fg=C_TEXT,
            activebackground="#1a3052",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=C_BORDER,
            font=("Segoe UI", 9, "bold"),
            cursor="hand2",
            pady=5,
            command=lambda: self.run_or_check(False),
        )
        self.btn_check.pack(side=tk.LEFT, padx=4)

        tk.Button(
            actions,
            text="  Salva  ",
            bg=C_BG_ELEV,
            fg=C_TEXT,
            activebackground="#1a3052",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=C_BORDER,
            font=("Segoe UI", 9),
            cursor="hand2",
            pady=5,
            command=self.save_file,
        ).pack(side=tk.LEFT, padx=4)

        tk.Button(
            actions,
            text="  ? Sintassi  ",
            bg="#0c182b",
            fg=C_TEXT_MUTED,
            activebackground=C_BG_ELEV,
            activeforeground="#ffffff",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=C_BORDER,
            font=("Segoe UI", 9),
            cursor="hand2",
            pady=5,
            command=self.show_cheatsheet,
        ).pack(side=tk.LEFT, padx=4)

    def _build_napoli_bar(self) -> None:
        self.napoli_bar = tk.Frame(self.root, bg=C_BG_SURF, pady=7, padx=12, highlightthickness=1, highlightbackground=C_BORDER)
        self.napoli_bar.pack(fill=tk.X, side=tk.TOP)

        # Sinistra: badge esito + scoreboard
        left = tk.Frame(self.napoli_bar, bg=C_BG_SURF)
        left.pack(side=tk.LEFT)
        self.napoli_left_frame = left

        self.lbl_napoli_badge = tk.Label(
            left,
            text=" NAPOLI ",
            bg=C_AZZURRO_DEEP,
            fg="#e0f2fe",
            font=("Segoe UI", 8, "bold"),
            padx=7,
            pady=4,
        )
        self.lbl_napoli_badge.pack(side=tk.LEFT, padx=(0, 10))

        score_box = tk.Frame(left, bg=C_BG_SURF)
        score_box.pack(side=tk.LEFT)
        self.napoli_score_box = score_box
        self.lbl_scoreboard = tk.Label(
            score_box,
            text="Recupero ultima partita SSC Napoli...",
            bg=C_BG_SURF,
            fg="#f8fafc",
            font=("Segoe UI", 10, "bold"),
        )
        self.lbl_scoreboard.pack(anchor="w")
        self.lbl_match_meta = tk.Label(
            score_box,
            text="Connessione live in corso",
            bg=C_BG_SURF,
            fg=C_TEXT_MUTED,
            font=("Segoe UI", 8),
        )
        self.lbl_match_meta.pack(anchor="w")

        # Centro: barra umore a 5 segmenti
        mid = tk.Frame(self.napoli_bar, bg=C_BG_SURF)
        mid.pack(side=tk.LEFT, padx=26)
        self.napoli_mid_frame = mid

        top_m = tk.Frame(mid, bg=C_BG_SURF)
        top_m.pack(fill=tk.X)
        self.napoli_top_m = top_m
        self.lbl_mood_caption = tk.Label(top_m, text="UMORE PROF:", bg=C_BG_SURF, fg=C_TEXT_MUTED, font=("Segoe UI", 8, "bold"))
        self.lbl_mood_caption.pack(side=tk.LEFT)
        self.lbl_mood_val = tk.Label(top_m, text="STANDARD", bg=C_BG_SURF, fg=C_AZZURRO_BRIGHT, font=("Segoe UI", 8, "bold"))
        self.lbl_mood_val.pack(side=tk.LEFT, padx=(6, 0))

        self.mood_canvas = tk.Canvas(mid, width=190, height=10, bg=C_BG_SURF, highlightthickness=0)
        self.mood_canvas.pack(pady=(3, 0))
        self.mood_rects = []
        for i in range(5):
            x0 = i * 38
            r = self.mood_canvas.create_rectangle(x0, 1, x0 + 34, 9, fill="#1e3556", outline="")
            self.mood_rects.append(r)

        # Destra: selettore modalità, No-Luck, Seed, Refresh
        right = tk.Frame(self.napoli_bar, bg=C_BG_SURF)
        right.pack(side=tk.RIGHT)
        self.napoli_right_frame = right

        self.lbl_mode_caption = tk.Label(right, text="Modalità:", bg=C_BG_SURF, fg=C_TEXT_MUTED, font=("Segoe UI", 9))
        self.lbl_mode_caption.pack(side=tk.LEFT, padx=(0, 4))

        self.cmb_napoli = ttk.Combobox(
            right,
            textvariable=self.napoli_mode_var,
            values=[lbl for lbl, _ in NAPOLI_MODES],
            state="readonly",
            width=25,
            style="Dark.TCombobox",
        )
        self.cmb_napoli.pack(side=tk.LEFT, padx=(0, 10))
        self.cmb_napoli.bind("<<ComboboxSelected>>", lambda _e: self._refresh_napoli_async(force_refresh=False))

        self.chk_noluck = tk.Checkbutton(
            right,
            text="No-Luck",
            variable=self.no_luck_var,
            bg=C_BG_SURF,
            fg=C_TEXT_MUTED,
            selectcolor=C_BG_INPUT,
            activebackground=C_BG_SURF,
            activeforeground=C_TEXT,
            font=("Segoe UI", 9),
        )
        self.chk_noluck.pack(side=tk.LEFT, padx=(0, 8))

        self.lbl_seed_caption = tk.Label(right, text="Seed:", bg=C_BG_SURF, fg=C_TEXT_MUTED, font=("Segoe UI", 9))
        self.lbl_seed_caption.pack(side=tk.LEFT)
        tk.Entry(
            right,
            textvariable=self.seed_var,
            width=6,
            bg=C_BG_INPUT,
            fg=C_TEXT,
            insertbackground=C_AZZURRO_BRIGHT,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=C_BORDER,
            font=("Consolas", 9),
        ).pack(side=tk.LEFT, padx=(4, 8))

        tk.Button(
            right,
            text="↻",
            bg=C_BG_ELEV,
            fg=C_AZZURRO_BRIGHT,
            activebackground="#1a3052",
            activeforeground="#ffffff",
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=C_BORDER,
            font=("Segoe UI", 10, "bold"),
            cursor="hand2",
            padx=7,
            command=lambda: self._refresh_napoli_async(force_refresh=True),
        ).pack(side=tk.LEFT)

    def _build_workbench(self) -> None:
        self.paned = ttk.Panedwindow(self.root, orient=tk.HORIZONTAL)
        self.paned.pack(fill=tk.BOTH, expand=True)

        # ---- 1. SIDEBAR ESEMPI ----
        sidebar = tk.Frame(self.paned, bg=C_BG_SURF, width=240)
        sb_hdr = tk.Frame(sidebar, bg=C_BG_ELEV, padx=8, pady=7)
        sb_hdr.pack(fill=tk.X)
        tk.Label(sb_hdr, text="ESPLORA ESEMPI P-LIKE", bg=C_BG_ELEV, fg=C_TEXT_MUTED, font=("Segoe UI", 8, "bold")).pack(anchor="w")

        sb_btns = tk.Frame(sb_hdr, bg=C_BG_ELEV)
        sb_btns.pack(fill=tk.X, pady=(6, 0))
        for txt, cmd in (("+ Nuovo", self.new_file), ("Apri...", self.open_file), ("Salva", self.save_file)):
            tk.Button(
                sb_btns,
                text=txt,
                bg=C_BG_SURF,
                fg=C_TEXT,
                activebackground=C_AZZURRO_DEEP,
                activeforeground="#fff",
                relief=tk.FLAT,
                highlightthickness=1,
                highlightbackground=C_BORDER,
                font=("Segoe UI", 8),
                cursor="hand2",
                padx=7,
                pady=2,
                command=cmd,
            ).pack(side=tk.LEFT, padx=(0, 5))

        tree_frame = tk.Frame(sidebar, bg=C_BG_SURF)
        tree_frame.pack(fill=tk.BOTH, expand=True)
        self.examples_tree = ttk.Treeview(tree_frame, show="tree", style="Dark.Treeview", selectmode="browse")
        sb_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.examples_tree.yview, style="Dark.Vertical.TScrollbar")
        self.examples_tree.configure(yscrollcommand=sb_scroll.set)
        self.examples_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.examples_tree.bind("<<TreeviewSelect>>", self._on_example_selected)

        # ---- 2. PANNELLO CENTRALE (EDITOR + STDIN) ----
        center_paned = ttk.Panedwindow(self.paned, orient=tk.VERTICAL)

        editor_frame = tk.Frame(center_paned, bg=C_BG_INPUT)
        ed_hdr = tk.Frame(editor_frame, bg=C_BG_SURF, padx=10, pady=5, highlightthickness=1, highlightbackground=C_BORDER)
        ed_hdr.pack(fill=tk.X)
        tk.Label(ed_hdr, text="● Editor P-Like", bg=C_BG_SURF, fg=C_AZZURRO_BRIGHT, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)
        tk.Label(ed_hdr, textvariable=self.cursor_var, bg=C_BG_SURF, fg=C_TEXT_MUTED, font=("Consolas", 9)).pack(side=tk.RIGHT)

        ed_body = tk.Frame(editor_frame, bg=C_BG_INPUT)
        ed_body.pack(fill=tk.BOTH, expand=True)

        self.gutter = tk.Canvas(ed_body, width=52, bg=C_BG_GUTTER, highlightthickness=0)
        self.gutter.pack(side=tk.LEFT, fill=tk.Y)

        self.editor = tk.Text(
            ed_body,
            bg=C_BG_INPUT,
            fg=C_TEXT,
            insertbackground=C_AZZURRO_BRIGHT,
            selectbackground="#184a75",
            selectforeground="#ffffff",
            font=("Consolas", 11),
            undo=True,
            maxundo=-1,
            wrap=tk.NONE,
            relief=tk.FLAT,
            padx=10,
            pady=8,
            tabs=("4c",),
        )
        ed_vscroll = ttk.Scrollbar(ed_body, orient=tk.VERTICAL, command=self._on_editor_yscroll_cmd, style="Dark.Vertical.TScrollbar")
        ed_hscroll = ttk.Scrollbar(editor_frame, orient=tk.HORIZONTAL, command=self.editor.xview, style="Dark.Horizontal.TScrollbar")
        self.editor.configure(yscrollcommand=self._on_editor_yview, xscrollcommand=ed_hscroll.set)

        self.editor.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        ed_vscroll.pack(side=tk.RIGHT, fill=tk.Y)
        ed_hscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.ed_vscroll = ed_vscroll

        # Configura tag syntax highlighting
        self.editor.tag_configure("active_line", background=C_BG_ACTIVE_LINE)
        self.editor.tag_configure("diag_line_err", background="#2d141d")
        self.editor.tag_configure("kw", foreground=SYN_KW, font=("Consolas", 11, "bold"))
        self.editor.tag_configure("type", foreground=SYN_TYPE)
        self.editor.tag_configure("const", foreground=SYN_CONST, font=("Consolas", 11, "bold"))
        self.editor.tag_configure("num", foreground=SYN_NUM)
        self.editor.tag_configure("str", foreground=SYN_STR)
        self.editor.tag_configure("op", foreground=SYN_OP)
        self.editor.tag_configure("cmt", foreground=SYN_CMT, font=("Consolas", 11, "italic"))

        self.editor.bind("<KeyRelease>", self._on_editor_change)
        self.editor.bind("<ButtonRelease-1>", lambda _e: self._update_cursor_and_gutter())
        self.editor.bind("<Configure>", lambda _e: self._redraw_gutter())
        self.editor.bind("<Tab>", self._handle_tab)
        self.editor.bind("<Shift-Tab>", self._handle_shift_tab)

        # Dock STDIN
        stdin_frame = tk.Frame(center_paned, bg=C_BG_SURF, height=110)
        st_hdr = tk.Frame(stdin_frame, bg=C_BG_SURF, padx=10, pady=4)
        st_hdr.pack(fill=tk.X)
        tk.Label(st_hdr, text="INPUT (read / stdin)", bg=C_BG_SURF, fg=C_TEXT_MUTED, font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)
        tk.Label(st_hdr, text="Valori separati da spazi o a capo prima di premere Esegui", bg=C_BG_SURF, fg=C_TEXT_DIM, font=("Segoe UI", 8)).pack(side=tk.RIGHT)

        self.stdin_text = tk.Text(
            stdin_frame,
            bg=C_BG_INPUT,
            fg=C_TEXT,
            insertbackground=C_AZZURRO_BRIGHT,
            font=("Consolas", 10),
            height=4,
            relief=tk.FLAT,
            highlightthickness=1,
            highlightbackground=C_BORDER,
            padx=8,
            pady=5,
        )
        self.stdin_text.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        center_paned.add(editor_frame, weight=5)
        center_paned.add(stdin_frame, weight=1)

        # ---- 3. PANNELLO DESTRO (VERDETTO + 6 TAB) ----
        right_pane = tk.Frame(self.paned, bg=C_BG_SURF, width=440)

        # Card Verdetto Prof. Laccetti
        self.verdict_card = tk.Frame(
            right_pane,
            bg=C_BG_ELEV,
            padx=12,
            pady=10,
            highlightthickness=2,
            highlightbackground=C_BORDER,
        )
        self.verdict_card.pack(fill=tk.X, padx=10, pady=(10, 8))

        v_top = tk.Frame(self.verdict_card, bg=C_BG_ELEV)
        v_top.pack(fill=tk.X)

        v_left = tk.Frame(v_top, bg=C_BG_ELEV)
        v_left.pack(side=tk.LEFT, fill=tk.X, expand=True)
        tk.Label(v_left, text="ESITO COMPILAZIONE & ESAME", bg=C_BG_ELEV, fg=C_TEXT_MUTED, font=("Segoe UI", 7, "bold")).pack(anchor="w")
        self.lbl_verdict_status = tk.Label(v_left, text="Pronto a compilare", bg=C_BG_ELEV, fg=C_TEXT, font=("Segoe UI", 11, "bold"))
        self.lbl_verdict_status.pack(anchor="w")

        self.lbl_grade = tk.Label(
            v_top,
            text=" --/30 ",
            bg=C_BG_INPUT,
            fg=C_TEXT,
            font=("Consolas", 11, "bold"),
            padx=8,
            pady=4,
            highlightthickness=1,
            highlightbackground=C_BORDER,
        )
        self.lbl_grade.pack(side=tk.RIGHT)

        self.lbl_prof_quote = tk.Label(
            self.verdict_card,
            text="Premi Esegui (F5 o Ctrl+Enter) per compilare con la Variabile Napoli!",
            bg=C_BG_ELEV,
            fg="#cfe0f5",
            font=("Segoe UI", 9),
            justify=tk.LEFT,
            wraplength=420,
        )
        self.lbl_prof_quote.pack(fill=tk.X, anchor="w", pady=(6, 4))

        self.lbl_verdict_stats = tk.Label(
            self.verdict_card,
            text="",
            bg=C_BG_ELEV,
            fg=C_AZZURRO_BRIGHT,
            font=("Segoe UI", 8, "bold"),
            anchor="w",
        )
        self.lbl_verdict_stats.pack(fill=tk.X)

        # Notebook a 6 schede
        self.notebook = ttk.Notebook(right_pane, style="Dark.TNotebook")
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=(0, 8))

        self.console_view = self._make_readonly_text_tab("Console")
        self.console_view.tag_configure("runtime_err", foreground=C_ERR_LIGHT)

        # Tab Diagnostiche (Treeview cliccabile!)
        diag_frame = tk.Frame(self.notebook, bg=C_BG_INPUT)
        self.notebook.add(diag_frame, text="Diagnostiche (0)")
        self.diag_tab_index = 1

        self.diag_tree = ttk.Treeview(
            diag_frame,
            columns=("tag", "loc", "msg"),
            show="headings",
            style="Dark.Treeview",
            selectmode="browse",
        )
        self.diag_tree.heading("tag", text="Stato")
        self.diag_tree.heading("loc", text="Pos.")
        self.diag_tree.heading("msg", text="Messaggio (clicca per saltare alla riga)")
        self.diag_tree.column("tag", width=125, stretch=False)
        self.diag_tree.column("loc", width=62, stretch=False)
        self.diag_tree.column("msg", width=260, stretch=True)
        self.diag_tree.tag_configure("err", foreground=C_ERR_LIGHT)
        self.diag_tree.tag_configure("forgiven", foreground=C_AZZURRO_BRIGHT)
        self.diag_tree.tag_configure("warn", foreground=C_WARN_LIGHT)

        d_scroll = ttk.Scrollbar(diag_frame, orient=tk.VERTICAL, command=self.diag_tree.yview, style="Dark.Vertical.TScrollbar")
        self.diag_tree.configure(yscrollcommand=d_scroll.set)
        self.diag_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        d_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.diag_tree.bind("<<TreeviewSelect>>", self._on_diag_clicked)

        self.bytecode_view = self._make_readonly_text_tab(
            "Bytecode",
            export_cmd=lambda: self.export_artifact("bytecode_json", ".plbc", "P-Like Bytecode"),
            export_label="Esporta .plbc",
        )
        self.c99_view = self._make_readonly_text_tab(
            "C99",
            export_cmd=lambda: self.export_artifact("c_code", ".c", "Codice C99"),
            export_label="Esporta .c",
        )
        self.python_view = self._make_readonly_text_tab(
            "Python",
            export_cmd=lambda: self.export_artifact("py_code", ".py", "Codice Python"),
            export_label="Esporta .py",
        )
        self.ast_view = self._make_readonly_text_tab("AST")

        self.paned.add(sidebar, weight=1)
        self.paned.add(center_paned, weight=4)
        self.paned.add(right_pane, weight=3)

    def _make_readonly_text_tab(
        self,
        title: str,
        export_cmd=None,
        export_label: str = "",
    ) -> tk.Text:
        frame = tk.Frame(self.notebook, bg=C_BG_INPUT)
        self.notebook.add(frame, text=title)

        bar = tk.Frame(frame, bg="#0b1526", padx=8, pady=4)
        bar.pack(fill=tk.X)
        tk.Label(bar, text=title, bg="#0b1526", fg=C_TEXT_MUTED, font=("Segoe UI", 8, "bold")).pack(side=tk.LEFT)

        txt = tk.Text(
            frame,
            bg=C_BG_INPUT,
            fg="#e2f1ff",
            font=("Consolas", 10),
            relief=tk.FLAT,
            wrap=tk.NONE,
            padx=10,
            pady=8,
            state=tk.DISABLED,
        )

        def _copy() -> None:
            self.root.clipboard_clear()
            self.root.clipboard_append(txt.get("1.0", tk.END))
            self.status_var.set(f"{title} copiato negli appunti.")

        tk.Button(
            bar,
            text="Copia",
            bg=C_BG_ELEV,
            fg=C_TEXT,
            activebackground=C_AZZURRO_DEEP,
            activeforeground="#fff",
            relief=tk.FLAT,
            font=("Segoe UI", 8),
            cursor="hand2",
            padx=8,
            command=_copy,
        ).pack(side=tk.RIGHT, padx=(4, 0))

        if export_cmd is not None:
            tk.Button(
                bar,
                text=export_label,
                bg=C_BG_ELEV,
                fg=C_AZZURRO_BRIGHT,
                activebackground=C_AZZURRO_DEEP,
                activeforeground="#fff",
                relief=tk.FLAT,
                font=("Segoe UI", 8, "bold"),
                cursor="hand2",
                padx=8,
                command=export_cmd,
            ).pack(side=tk.RIGHT, padx=(4, 0))

        body = tk.Frame(frame, bg=C_BG_INPUT)
        body.pack(fill=tk.BOTH, expand=True)
        vs = ttk.Scrollbar(body, orient=tk.VERTICAL, command=txt.yview, style="Dark.Vertical.TScrollbar")
        hs = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=txt.xview, style="Dark.Horizontal.TScrollbar")
        txt.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        txt.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vs.pack(side=tk.RIGHT, fill=tk.Y)
        hs.pack(side=tk.BOTTOM, fill=tk.X)
        return txt

    def _build_statusbar(self) -> None:
        bar = tk.Frame(self.root, bg=C_AZZURRO_DEEP, height=24, padx=10)
        bar.pack(fill=tk.X, side=tk.BOTTOM)
        bar.pack_propagate(False)
        tk.Label(bar, textvariable=self.status_var, bg=C_AZZURRO_DEEP, fg="#e0f2fe", font=("Segoe UI", 8)).pack(side=tk.LEFT)
        tk.Label(
            bar,
            text=f"P-Like v{__version__} · F5 / Ctrl+Enter: Esegui · Ctrl+Shift+B: Verifica · Ctrl+S: Salva",
            bg=C_AZZURRO_DEEP,
            fg="#bae6fd",
            font=("Segoe UI", 8),
        ).pack(side=tk.RIGHT)

    def _bind_shortcuts(self) -> None:
        self.root.bind("<F5>", lambda _e: self.run_or_check(True))
        self.root.bind("<Control-Return>", lambda _e: (self.run_or_check(True), "break")[1])
        self.root.bind("<Control-Shift-B>", lambda _e: (self.run_or_check(False), "break")[1])
        self.root.bind("<Control-Shift-b>", lambda _e: (self.run_or_check(False), "break")[1])
        self.root.bind("<Control-s>", lambda _e: (self.save_file(), "break")[1])
        self.root.bind("<Control-S>", lambda _e: (self.save_file_as(), "break")[1])
        self.root.bind("<Control-o>", lambda _e: (self.open_file(), "break")[1])
        self.root.bind("<Control-n>", lambda _e: (self.new_file(), "break")[1])

    # ------------------------------------------------------------------
    # Editor: Scroll, Numeri di Riga, Syntax Highlighting, Tab
    # ------------------------------------------------------------------

    def _on_editor_yscroll_cmd(self, *args: Any) -> None:
        self.editor.yview(*args)
        self._redraw_gutter()

    def _on_editor_yview(self, first: str, last: str) -> None:
        self.ed_vscroll.set(first, last)
        self._redraw_gutter()

    def _handle_tab(self, _event: tk.Event) -> str:
        self.editor.insert(tk.INSERT, "    ")
        self._on_editor_change()
        return "break"

    def _handle_shift_tab(self, _event: tk.Event) -> str:
        line_idx = self.editor.index("insert linestart")
        prefix = self.editor.get(line_idx, f"{line_idx}+4c")
        if prefix == "    ":
            self.editor.delete(line_idx, f"{line_idx}+4c")
            self._on_editor_change()
        return "break"

    def _on_editor_change(self, _event: Optional[tk.Event] = None) -> None:
        if not self.is_dirty:
            self.is_dirty = True
            self._update_filename_label()
        self._update_cursor_and_gutter()
        if self._highlight_after_id is not None:
            self.root.after_cancel(self._highlight_after_id)
        self._highlight_after_id = self.root.after(45, self._apply_syntax_highlighting)

    def _update_cursor_and_gutter(self) -> None:
        idx = self.editor.index(tk.INSERT)
        line_s, col_s = idx.split(".")
        self.cursor_var.set(f"Ln {line_s}, Col {int(col_s) + 1}")
        self.editor.tag_remove("active_line", "1.0", tk.END)
        self.editor.tag_add("active_line", f"{line_s}.0", f"{line_s}.end+1c")
        self._redraw_gutter()

    def _redraw_gutter(self) -> None:
        self.gutter.delete("all")
        i = self.editor.index("@0,0")
        while True:
            dline = self.editor.dlineinfo(i)
            if dline is None:
                break
            y = dline[1]
            linenum = int(str(i).split(".")[0])
            marker = self.line_diag_markers.get(linenum)
            if marker:
                col = {"err": C_ERR, "forgiven": C_AZZURRO_BRIGHT, "warn": C_WARN}.get(marker, C_WARN)
                self.gutter.create_oval(6, y + 5, 13, y + 12, fill=col, outline="")
            self.gutter.create_text(
                46,
                y + 1,
                anchor="ne",
                text=str(linenum),
                fill=C_TEXT_DIM,
                font=("Consolas", 10),
            )
            nxt = self.editor.index(f"{i}+1line")
            if nxt == i:
                break
            i = nxt

    def _apply_syntax_highlighting(self) -> None:
        self._highlight_after_id = None
        for tag in ("kw", "type", "const", "num", "str", "op", "cmt"):
            self.editor.tag_remove(tag, "1.0", tk.END)

        text = self.editor.get("1.0", "end-1c")
        for m in PLIKE_TOKEN_RE.finditer(text):
            kind = m.lastgroup
            tok = m.group()
            tag: Optional[str] = None
            if kind == "cmt":
                tag = "cmt"
            elif kind == "str":
                tag = "str"
            elif kind == "dconst":
                tag = "const"
            elif kind in ("dop", "op"):
                tag = "op"
            elif kind == "inout":
                tag = "kw"
            elif kind == "num":
                tag = "num"
            elif kind == "word":
                low = tok.lower()
                if low in PLIKE_CONSTS:
                    tag = "const"
                elif low in PLIKE_TYPES:
                    tag = "type"
                elif low in PLIKE_KEYWORDS:
                    tag = "kw"
            if tag:
                start_idx = f"1.0+{m.start()}c"
                end_idx = f"1.0+{m.end()}c"
                self.editor.tag_add(tag, start_idx, end_idx)

    # ------------------------------------------------------------------
    # Esempi e Gestione File
    # ------------------------------------------------------------------

    def _populate_examples(self) -> None:
        self.examples_tree.delete(*self.examples_tree.get_children())
        self._example_paths.clear()
        ex_dir = _find_examples_dir()
        if ex_dir is None:
            return

        order = list(EXAMPLE_META.keys())
        files = sorted(
            ex_dir.glob("*.plike"),
            key=lambda p: (order.index(p.name) if p.name in order else 999, p.name),
        )
        cat_nodes: Dict[str, str] = {}
        for p in files:
            title, cat = EXAMPLE_META.get(p.name, (p.stem.replace("_", " ").title(), "Altri Esempi"))
            if cat not in cat_nodes:
                cat_nodes[cat] = self.examples_tree.insert("", tk.END, text=f"▾ {cat}", open=True)
            item_id = self.examples_tree.insert(cat_nodes[cat], tk.END, text=f"  {title}")
            self._example_paths[item_id] = p

    def _load_initial_content(self, initial_file: Optional[str]) -> None:
        if initial_file and Path(initial_file).is_file():
            p = Path(initial_file).resolve()
            self._set_editor_content(p.read_text(encoding="utf-8-sig"), path=p)
            return
        ex_dir = _find_examples_dir()
        if ex_dir and (ex_dir / "esame_studente.plike").is_file():
            p = ex_dir / "esame_studente.plike"
            self._set_editor_content(p.read_text(encoding="utf-8-sig"), path=None, display_name=p.name)
        else:
            self.new_file()

    def _set_editor_content(self, code: str, path: Optional[Path] = None, display_name: Optional[str] = None) -> None:
        self.editor.delete("1.0", tk.END)
        self.editor.insert("1.0", code)
        self.editor.edit_reset()
        self.current_file = path
        self.is_dirty = False
        self.line_diag_markers.clear()
        self.editor.tag_remove("diag_line_err", "1.0", tk.END)
        self._display_name_override = display_name
        self._update_filename_label()
        self._apply_syntax_highlighting()
        self._update_cursor_and_gutter()

    def _update_filename_label(self) -> None:
        base = self.current_file.name if self.current_file else (getattr(self, "_display_name_override", None) or "senza_titolo.plike")
        self.filename_var.set(f"{base} *" if self.is_dirty else base)

    def _on_example_selected(self, _event: tk.Event) -> None:
        sel = self.examples_tree.selection()
        if not sel:
            return
        p = self._example_paths.get(sel[0])
        if p and p.is_file():
            self._set_editor_content(p.read_text(encoding="utf-8-sig"), path=None, display_name=p.name)
            self.status_var.set(f"Caricato esempio: {p.name}")

    def new_file(self) -> None:
        template = (
            "(* Nuovo algoritmo P-Like *)\n"
            "begin mio_programma\n"
            "    var: x: integer\n"
            "    x := 42\n"
            "    print 'Valore:', x\n"
            "end mio_programma\n"
        )
        self._set_editor_content(template, path=None, display_name="nuovo_algoritmo.plike")
        self.status_var.set("Creato nuovo file P-Like.")

    def open_file(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Apri sorgente P-Like",
            filetypes=[("File P-Like", "*.plike"), ("File di testo", "*.txt"), ("Tutti i file", "*.*")],
        )
        if not chosen:
            return
        p = Path(chosen)
        self._set_editor_content(p.read_text(encoding="utf-8-sig"), path=p)
        self.status_var.set(f"Aperto: {p}")

    def save_file(self) -> None:
        if self.current_file is None:
            self.save_file_as()
            return
        self.current_file.write_text(self.editor.get("1.0", "end-1c"), encoding="utf-8")
        self.is_dirty = False
        self._update_filename_label()
        self.status_var.set(f"Salvato: {self.current_file}")

    def save_file_as(self) -> None:
        chosen = filedialog.asksaveasfilename(
            title="Salva sorgente P-Like",
            defaultextension=".plike",
            initialfile=self.filename_var.get().replace(" *", ""),
            filetypes=[("File P-Like", "*.plike"), ("Tutti i file", "*.*")],
        )
        if not chosen:
            return
        p = Path(chosen)
        p.write_text(self.editor.get("1.0", "end-1c"), encoding="utf-8")
        self.current_file = p
        self.is_dirty = False
        self._update_filename_label()
        self.status_var.set(f"Salvato come: {p}")

    def export_artifact(self, key: str, ext: str, label: str) -> None:
        content = self.last_artifacts.get(key, "")
        if not content:
            messagebox.showinfo("Esporta", "Compila prima il programma con successo per esportare l'output.")
            return
        stem = self.filename_var.get().replace(" *", "").rsplit(".", 1)[0]
        chosen = filedialog.asksaveasfilename(
            title=f"Esporta {label}",
            defaultextension=ext,
            initialfile=f"{stem}{ext}",
            filetypes=[(label, f"*{ext}"), ("Tutti i file", "*.*")],
        )
        if not chosen:
            return
        Path(chosen).write_text(content, encoding="utf-8")
        self.status_var.set(f"Esportato {label}: {chosen}")

    # ------------------------------------------------------------------
    # Variabile Napoli live
    # ------------------------------------------------------------------

    def _current_napoli_key(self) -> str:
        return self.mode_label_to_key.get(self.napoli_mode_var.get(), "auto")

    def _select_napoli_mode_label(self, label: str) -> None:
        self.napoli_mode_var.set(label)
        self._refresh_napoli_async(force_refresh=False)

    def _safe_after(self, fn) -> None:
        try:
            if self.root.winfo_exists():
                self.root.after(0, fn)
        except (RuntimeError, tk.TclError):
            pass

    def _refresh_napoli_async(self, force_refresh: bool = False) -> None:
        mode = self._current_napoli_key()
        self.status_var.set("Aggiornamento stato SSC Napoli...")

        def worker() -> None:
            try:
                match = fetch_latest_napoli_match(mode=mode, force_refresh=force_refresh)
                self._safe_after(lambda: self._render_napoli_match(match))
            except Exception as exc:
                self._safe_after(lambda: self.status_var.set(f"Errore SSC Napoli: {exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def _render_napoli_match(self, match: NapoliMatch) -> None:
        self.current_match = match
        mood = match.compute_mood()

        if mood == LaccettiMood.ESTASI_AZZURRA:
            bg_bar, badge_bg, badge_txt, level, seg_col = "#092642", "#0ea5e9", " VITTORIA TOP ", 5, C_AZZURRO_BRIGHT
        elif mood == LaccettiMood.OTTIMO_UMORE:
            bg_bar, badge_bg, badge_txt, level, seg_col = "#0b223b", C_AZZURRO, " VITTORIA ", 4, C_AZZURRO_BRIGHT
        elif mood == LaccettiMood.NEUTRO:
            bg_bar, badge_bg, badge_txt, level, seg_col = C_BG_SURF, "#475569", " PAREGGIO ", 3, "#94a3b8"
        elif mood == LaccettiMood.NERVOSO:
            bg_bar, badge_bg, badge_txt, level, seg_col = "#2b121a", "#b91c1c", " SCONFITTA ", 2, C_ERR
        elif mood == LaccettiMood.FURIA_POST_PARTITA:
            bg_bar, badge_bg, badge_txt, level, seg_col = "#361018", "#dc2626", " DISASTRO ", 1, C_ERR
        else:
            bg_bar, badge_bg, badge_txt, level, seg_col = C_BG_SURF, C_AZZURRO_DEEP, " STANDARD ", 3, "#64748b"

        for w in (
            self.napoli_bar,
            self.napoli_left_frame,
            self.napoli_score_box,
            self.napoli_mid_frame,
            self.napoli_top_m,
            self.napoli_right_frame,
            self.lbl_scoreboard,
            self.lbl_match_meta,
            self.lbl_mood_caption,
            self.lbl_mood_val,
            self.lbl_mode_caption,
            self.lbl_seed_caption,
            self.chk_noluck,
            self.mood_canvas,
        ):
            w.configure(bg=bg_bar)

        self.lbl_napoli_badge.configure(text=badge_txt, bg=badge_bg)
        if match.outcome == MatchOutcome.DISABLED:
            self.lbl_scoreboard.configure(text="Variabile Napoli disattivata")
            self.lbl_match_meta.configure(text="Compilatore deterministico standard")
        else:
            self.lbl_scoreboard.configure(text=match.scoreboard)
            self.lbl_match_meta.configure(text=f"{match.competition} · {match.date} [{match.source}]")

        self.lbl_mood_val.configure(text=mood.value.replace("_", " "), fg=seg_col)
        for i, rect in enumerate(self.mood_rects):
            self.mood_canvas.itemconfig(rect, fill=seg_col if i < level else "#1a2a44")

        self.status_var.set(f"SSC Napoli: {match.scoreboard} ({mood.value.replace('_', ' ')})")

    # ------------------------------------------------------------------
    # Compilazione & Esecuzione
    # ------------------------------------------------------------------

    def run_or_check(self, execute: bool) -> None:
        source = self.editor.get("1.0", "end-1c")
        stdin_str = self.stdin_text.get("1.0", "end-1c")
        fname = self.filename_var.get().replace(" *", "")
        mode = self._current_napoli_key()
        allow_luck = not self.no_luck_var.get()
        raw_seed = self.seed_var.get().strip()
        seed: Optional[int] = int(raw_seed) if raw_seed.lstrip("-").isdigit() else None

        self.btn_run.configure(state=tk.DISABLED)
        self.btn_check.configure(state=tk.DISABLED)
        self.status_var.set("Compilazione ed esecuzione in corso..." if execute else "Verifica in corso...")

        def worker() -> None:
            t0 = time.perf_counter()
            res = compile_source(
                source,
                filename=fname,
                target="bytecode",
                napoli_mode=mode,
                allow_luck=allow_luck,
                seed=seed,
            )
            stdout_text = ""
            runtime_err: Optional[str] = None
            steps = 0
            disasm = ""
            bc_json = ""
            c_code = ""
            py_code = ""
            ast_json = json.dumps(ast_to_dict(res.ast), indent=2, ensure_ascii=False) if res.ast else "{}"

            if res.success and res.bytecode is not None and res.ast is not None:
                disasm = res.bytecode.disassemble()
                bc_json = res.bytecode.to_json()
                try:
                    c_code = CCodeGenerator().generate(res.ast)
                except Exception as exc:
                    c_code = f"/* Errore C99: {exc} */"
                try:
                    py_code = PythonCodeGenerator().generate(res.ast)
                except Exception as exc:
                    py_code = f"# Errore Python: {exc}"

                if execute:
                    out_buf = io.StringIO()
                    vm = PLikeVM(res.bytecode, stdin=io.StringIO(stdin_str), stdout=out_buf)
                    try:
                        vm.run()
                    except PLikeRuntimeError as exc:
                        runtime_err = str(exc)
                    stdout_text = out_buf.getvalue()
                    steps = vm.steps_executed

            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
            self._safe_after(
                lambda: self._render_compile_result(
                    res, execute, stdout_text, runtime_err, steps, elapsed_ms, disasm, bc_json, c_code, py_code, ast_json
                ),
            )

        threading.Thread(target=worker, daemon=True).start()

    def _set_readonly_text(self, widget: tk.Text, content: str, extra_err: Optional[str] = None) -> None:
        widget.configure(state=tk.NORMAL)
        widget.delete("1.0", tk.END)
        widget.insert("1.0", content)
        if extra_err:
            widget.insert(tk.END, f"\n{extra_err}\n", "runtime_err")
        widget.configure(state=tk.DISABLED)

    def _render_compile_result(
        self,
        res: CompileResult,
        executed: bool,
        stdout_text: str,
        runtime_err: Optional[str],
        steps: int,
        elapsed_ms: float,
        disasm: str,
        bc_json: str,
        c_code: str,
        py_code: str,
        ast_json: str,
    ) -> None:
        self.btn_run.configure(state=tk.NORMAL)
        self.btn_check.configure(state=tk.NORMAL)

        v = res.verdict
        self._render_napoli_match(v.match)

        # Card Verdetto
        border_col = C_AZZURRO if res.success else C_ERR
        self.verdict_card.configure(highlightbackground=border_col)
        self.lbl_verdict_status.configure(
            text=("COMPILAZIONE ED ESECUZIONE RIUSCITE" if executed else "COMPILAZIONE RIUSCITA") if res.success else "COMPILAZIONE FALLITA",
            fg=C_AZZURRO_BRIGHT if res.success else C_ERR_LIGHT,
        )
        self.lbl_grade.configure(
            text=f" {v.grade_label} ",
            fg=C_OK_LIGHT if res.success else C_ERR_LIGHT,
            highlightbackground=C_OK if res.success else C_ERR,
        )
        self.lbl_prof_quote.configure(text=v.prof_comment)

        stats_parts = [f"{elapsed_ms} ms"]
        if executed and res.success:
            stats_parts.append(f"{steps:,} passi VM")
        if v.forgiven_count > 0:
            stats_parts.append(f"{v.forgiven_count} sviste perdonate (Napoli)")
        if v.promoted_count > 0:
            stats_parts.append(f"{v.promoted_count} pignolerie promosse a errore")
        if v.bad_luck_rejection:
            stats_parts.append("Malumore post-sconfitta!")
        self.lbl_verdict_stats.configure(text=" · ".join(stats_parts))

        # Diagnostiche + Gutter markers
        self.last_diags = list(res.diagnostics.items)
        self.line_diag_markers.clear()
        self.editor.tag_remove("diag_line_err", "1.0", tk.END)
        self.diag_tree.delete(*self.diag_tree.get_children())

        for idx, d in enumerate(self.last_diags):
            if d.forgiven_by_napoli:
                tag_key, tag_label = "forgiven", f"PERDONATO {d.code}"
            elif d.promoted_by_napoli:
                tag_key, tag_label = "err", f"NAPOLI ERR {d.code}"
            elif d.severity.value in ("FATAL", "ERROR") or (d.severity.value == "RECOVERABLE" and not res.success):
                tag_key, tag_label = "err", f"{d.severity.value} {d.code}"
            else:
                tag_key, tag_label = "warn", f"{d.severity.value} {d.code}"

            prev = self.line_diag_markers.get(d.span.line)
            if not prev or tag_key == "err":
                self.line_diag_markers[d.span.line] = tag_key
            if tag_key == "err":
                self.editor.tag_add("diag_line_err", f"{d.span.line}.0", f"{d.span.line}.end+1c")

            msg = d.message + (f"  [Tip: {d.hint}]" if d.hint else "")
            self.diag_tree.insert("", tk.END, iid=str(idx), values=(tag_label, f"L{d.span.line}:{d.span.col}", msg), tags=(tag_key,))

        self.notebook.tab(self.diag_tab_index, text=f"Diagnostiche ({len(self.last_diags)})")
        self._redraw_gutter()

        # Console & schede codice
        self.last_artifacts = {
            "bytecode_json": bc_json,
            "c_code": c_code,
            "py_code": py_code,
            "ast_json": ast_json,
        }

        if not res.success:
            self._set_readonly_text(
                self.console_view,
                "",
                extra_err=f"Compilazione bloccata ({v.grade_label}).\nApri la scheda 'Diagnostiche' e clicca su un errore per saltare alla riga.",
            )
            if self.last_diags:
                self.notebook.select(self.diag_tab_index)
        elif not executed:
            self._set_readonly_text(self.console_view, "Verifica superata! Premi 'Esegui (F5)' per eseguire sulla P-Like VM.")
        else:
            self._set_readonly_text(
                self.console_view,
                stdout_text if stdout_text else "(Programma terminato senza stampare output)",
                extra_err=runtime_err,
            )
            self.notebook.select(0)

        self._set_readonly_text(self.bytecode_view, disasm or "// Compilazione fallita")
        self._set_readonly_text(self.c99_view, c_code or "/* Compilazione fallita */")
        self._set_readonly_text(self.python_view, py_code or "# Compilazione fallita")
        self._set_readonly_text(self.ast_view, ast_json)

        self.status_var.set(
            f"{'Successo' if res.success else 'Fallito'} ({v.grade_label}) in {elapsed_ms} ms — {v.match.scoreboard}"
        )

    def _on_diag_clicked(self, _event: tk.Event) -> None:
        sel = self.diag_tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(self.last_diags):
            d = self.last_diags[idx]
            target = f"{d.span.line}.{max(0, d.span.col - 1)}"
            self.editor.focus_set()
            self.editor.mark_set(tk.INSERT, target)
            self.editor.see(target)
            self._update_cursor_and_gutter()

    # ------------------------------------------------------------------
    # Finestre Guida & Info
    # ------------------------------------------------------------------

    def show_cheatsheet(self) -> None:
        win = tk.Toplevel(self.root)
        win.title("Guida Rapida Sintassi P-Like (Prof. Giuliano Laccetti)")
        win.geometry("760x560")
        win.configure(bg=C_BG_SURF)
        txt = tk.Text(win, bg=C_BG_INPUT, fg=C_TEXT, font=("Consolas", 10), relief=tk.FLAT, padx=14, pady=12)
        txt.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        guide = """=== GUIDA RAPIDA P-LIKE CANONICO (PROF. GIULIANO LACCETTI) ===

1. STRUTTURA & VARIABILI
   begin nome_programma
       var: i, n: integer
       var: media: real
       var: ok: logical
       var: testo: character
       var: A: array [1..100] of real
       var: M: array [1..10, 1..10] of integer
       ...
   end nome_programma

2. COSTANTI & OPERATORI CANONICI
   x := a + b            (* Assegnazione canonica *)
   5.   0.   4.e-3       (* Reali con punto decimale! *)
   .TRUE.   .FALSE.      (* Costanti logiche *)
   .AND.  .OR.  .NOT.    (* Operatori logici con corto-circuito *)
   =  !=  <  <=  >  >=   (* Confronti *)
   a / b                 (* Divisione intera se entrambi integer *)
   a mod b   a div b     (* Resto e quoziente intero *)

3. CONTROLLO DI FLUSSO
   if (condizione) then
       ...
   elseif (altra) then
       ...
   else
       ...
   endif

   for i := 1 to n do ... endfor
   for i := n - 1 to 1 step -1 do ... endfor
   while (condizione) do ... endwhile
   repeat ... until (condizione)

4. PROCEDURE, FUNCTION, RECORD & PUNTATORI
   procedure scambia(in/out: a, b)
       var: a, b, tmp: integer
   begin
       tmp := a; a := b; b := tmp
   end scambia

   function fatt(in: n): integer
       var: n: integer
   begin
       if (n <= 1) then fatt := 1 else fatt := n * fatt(n - 1) endif
   end fatt

   type complex: record
       Re: real
       Im: real
   end

   type list_pointer: *nodo_lista
        nodo_lista: record
            info: integer
            link: list_pointer
        end
"""
        txt.insert("1.0", guide)
        txt.configure(state=tk.DISABLED)

    def show_about(self) -> None:
        messagebox.showinfo(
            "P-Like Studio",
            f"P-Like Studio v{__version__}\n\n"
            "Compilatore, Bytecode VM, Transpiler C99/Python e IDE Windows\n"
            "per il linguaggio didattico P-Like del Prof. Giuliano Laccetti\n"
            "(Università degli Studi di Napoli Federico II).\n\n"
            "Include la Variabile Live 'Partite dell'SSC Napoli'!\n"
            "Repo: https://github.com/Carloj005/P-Like",
        )


def launch_gui(initial_file: Optional[str] = None, default_napoli: str = "auto") -> int:
    """Avvia l'applicazione desktop Windows nativa P-Like Studio."""
    if sys.platform == "win32":
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass

    root = tk.Tk()
    PLikeDesktopIDE(root, initial_file=initial_file, default_napoli=default_napoli)
    root.mainloop()
    return 0
