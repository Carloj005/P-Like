"""Smoke test per la GUI Desktop nativa Windows (`plike/gui.py`)."""

from __future__ import annotations

import tkinter as tk
import unittest

from plike.gui import PLikeDesktopIDE, _find_examples_dir
from plike.napoli import MatchOutcome, NapoliMatch


class TestDesktopGUI(unittest.TestCase):
    def test_examples_dir_found(self) -> None:
        ex_dir = _find_examples_dir()
        self.assertIsNotNone(ex_dir)
        assert ex_dir is not None
        self.assertTrue((ex_dir / "esame_studente.plike").is_file())

    def test_gui_initializes_highlights_and_renders_verdict(self) -> None:
        try:
            root = tk.Tk()
        except tk.TclError:
            self.skipTest("Display non disponibile in questo ambiente")
            return
        root.withdraw()
        try:
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
