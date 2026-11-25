"""Smoke test per la GUI Desktop cross-platform (`plike/gui.py`) e il packaging Linux."""

from __future__ import annotations

import tkinter as tk
import unittest
from pathlib import Path

from plike.gui import PLikeDesktopIDE, _find_examples_dir, _find_png_icon_path, _resolve_fonts
from plike.napoli import MatchOutcome, NapoliMatch

ROOT = Path(__file__).resolve().parent.parent


class TestDesktopGUI(unittest.TestCase):
    def test_examples_dir_and_png_icon_found(self) -> None:
        ex_dir = _find_examples_dir()
        self.assertIsNotNone(ex_dir)
        assert ex_dir is not None
        self.assertTrue((ex_dir / "esame_studente.plike").is_file())

        png = _find_png_icon_path()
        self.assertIsNotNone(png)
        assert png is not None
        self.assertTrue(png.is_file())
        self.assertGreater(png.stat().st_size, 500)

    def test_linux_packaging_files_present_and_lf(self) -> None:
        pkg_dir = ROOT / "packaging" / "linux"
        desktop = pkg_dir / "p-like-studio.desktop"
        mime = pkg_dir / "plike-mime.xml"
        self.assertTrue(desktop.is_file())
        self.assertTrue(mime.is_file())
        self.assertIn("StartupWMClass=P-Like-Studio", desktop.read_text(encoding="utf-8"))
        self.assertIn("text/x-plike", mime.read_text(encoding="utf-8"))

        for script_name in ("install.sh", "uninstall.sh", "install-from-source.sh"):
            script = pkg_dir / script_name
            self.assertTrue(script.is_file(), f"Manca {script}")
            raw = script.read_bytes()
            self.assertTrue(raw.startswith(b"#!/usr/bin/env bash\n"), f"{script} deve iniziare con shebang bash LF")
            self.assertNotIn(b"\r\n", raw, f"{script} non deve contenere CRLF")

    def test_gui_initializes_highlights_and_renders_verdict(self) -> None:
        try:
            root = tk.Tk(className="P-Like-Studio")
        except tk.TclError:
            self.skipTest("Display non disponibile in questo ambiente")
            return
        root.withdraw()
        try:
            ui_font, mono_font = _resolve_fonts(root)
            self.assertTrue(bool(ui_font))
            self.assertTrue(bool(mono_font))

            app = PLikeDesktopIDE(root, default_napoli="win")
            app._apply_syntax_highlighting()
            match = NapoliMatch(
                date="2026-11-24",
                competition="Serie A",
                home_team="Napoli",
                away_team="Juventus",
                home_score=3,
                away_score=0,
                napoli_is_home=True,
                outcome=MatchOutcome.WIN,
                source="simulated",
            )
            app._render_napoli_match(match)
            self.assertIn("Napoli 3 - 0 Juventus", app.lbl_scoreboard.cget("text"))
            self.assertIn("ESTASI AZZURRA", app.lbl_mood_val.cget("text"))
        finally:
            root.destroy()


if __name__ == "__main__":
    unittest.main()
