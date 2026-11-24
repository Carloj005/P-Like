"""Test end-to-end su tutti i programmi di esempio in `examples/`."""

from __future__ import annotations

import io
import unittest
from pathlib import Path

from plike.driver import compile_source, run_source

EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"


class TestExamples(unittest.TestCase):
    def _run_example(self, filename: str, napoli_mode: str = "loss", allow_luck: bool = False) -> tuple[bool, str]:
        src = (EXAMPLES_DIR / filename).read_text(encoding="utf-8")
        out = io.StringIO()
        res = run_source(src, filename=filename, napoli_mode=napoli_mode, allow_luck=allow_luck, stdout=out)
        if not res.success:
            return False, "\n".join(d.format(src.splitlines()) for d in res.diagnostics.items)
        return True, out.getvalue().strip()

    def test_all_canonical_examples_pass_even_on_napoli_loss(self) -> None:
        expected_snippets = {
            "hello.plike": "Giuliano Laccetti",
            "fattoriale.plike": ["720", "MCD(66, 48) = 6"],
            "ricerca_binaria.plike": ["trovato = .TRUE. posizione = 6", "posizione = 8", "trovato = .FALSE. posizione = -1"],
            "insertion_sort.plike": ["1.0", "3.0", "4.0", "5.0", "11.0", "17.0", "21.0"],
            "selection_sort.plike": ["Ordinato prima: .FALSE.", "Ordinato dopo: .TRUE.", "1.0", "12.5"],
            "exchange_sort.plike": ["1.0", "2.0", "3.0", "4.0", "5.0", "11.0"],
            "merge_array.plike": ["1", "2", "7", "11", "15", "19"],
            "prodotto_matrici.plike": ["58.0", "64.0", "139.0", "154.0"],
            "back_substitution.plike": ["x( 3 ) = 1.0", "x( 2 ) = -0.428571", "x( 1 ) = 0.928571"],
            "torre_di_hanoi.plike": ["Sposta disco 3 da A a C"],
            "numeri_complessi.plike": ["4.5 + i * -2.0", "12.5 + i * -9.0"],
            "linked_list.plike": ["5 -> 10 -> 25 -> 30 -> NULL", "Somma dei campi info: 70"],
            "stack_demo.plike": ["Popped: 30", "Popped: 20", "Popped: 10"],
        }

        for fname, checks in expected_snippets.items():
            ok, out = self._run_example(fname, napoli_mode="loss", allow_luck=False)
            self.assertTrue(ok, f"Esempio canonico '{fname}' fallito in modalita Napoli Loss:\n{out}")
            if isinstance(checks, str):
                checks = [checks]
            for snippet in checks:
                self.assertIn(snippet, out, f"Output inatteso per {fname}:\n{out}")

    def test_esame_studente_depends_on_napoli_match(self) -> None:
        ok_win, out_win = self._run_example("esame_studente.plike", napoli_mode="win")
        self.assertTrue(ok_win, out_win)
        self.assertIn("15", out_win)

        ok_draw, _ = self._run_example("esame_studente.plike", napoli_mode="draw")
        self.assertFalse(ok_draw)

        ok_loss, _ = self._run_example("esame_studente.plike", napoli_mode="loss", allow_luck=False)
        self.assertFalse(ok_loss)

    def test_stile_non_canonico_depends_on_napoli_match(self) -> None:
        ok_win, out_win = self._run_example("stile_non_canonico.plike", napoli_mode="win")
        self.assertTrue(ok_win, out_win)
        self.assertIn("7.0", out_win)

        ok_draw, out_draw = self._run_example("stile_non_canonico.plike", napoli_mode="draw")
        self.assertTrue(ok_draw, out_draw)

        ok_loss, _ = self._run_example("stile_non_canonico.plike", napoli_mode="loss", allow_luck=False)
        self.assertFalse(ok_loss)


if __name__ == "__main__":
    unittest.main()
