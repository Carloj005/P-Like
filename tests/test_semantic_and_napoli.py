"""Test per Analisi Semantica e Motore 'Variabile Napoli' (Modalità Laccetti)."""

from __future__ import annotations

import io
import unittest

from plike.driver import compile_source, run_source
from plike.napoli import (
    LaccettiMood,
    MatchOutcome,
    NapoliMatch,
    _parse_espn_schedule,
    fetch_latest_napoli_match,
)


IMPERFECT_STUDENT_CODE = """
begin compito
    var: somma: integer
    var: ok: logical
    somma = 0
    ok := FALSE
    for i := 1 to 4 do
        somma := somma + i
    endfor
    if (somma = 10 AND ok = FALSE)
        ok := TRUE
        print somma, ok
    endif
end
"""

NON_CANONICAL_VALID_CODE = """
begin stile
    var: A[3]: array of real
    var: tot: real
    var: i: integer
    var: ok: logical
    A[1] := 1.5
    A[2] := 2.5
    A[3] := 1.0
    tot := 0
    ok := TRUE
    for i := 1 to 3 do
        if (ok = TRUE AND A[i] > 0.) then
            tot := tot + A[i]
        endif
    endfor
    print tot
end
"""

PERFECT_CANONICAL_CODE = """
begin perfetto
    var: a, b, s: integer
    var: ok: logical
    a := 10
    b := 20
    s := a + b
    ok := .TRUE.
    if (s = 30 .AND. ok = .TRUE.) then
        print 'Perfetto:', s
    endif
end perfetto
"""


class TestSemanticAndNapoli(unittest.TestCase):
    def test_murli_slide_197_type_mismatch_always_fails(self) -> None:
        # Slide 197: impossibile assegnare real a logical
        src = """
        begin area_rettangolo
            var: area: logical
            var: base, altezza: real
            altezza := 2.5
            base := 5.1
            area := base * altezza
        end area_rettangolo
        """
        for mode in ("win", "big-win", "draw", "loss", "off"):
            res = compile_source(src, napoli_mode=mode, allow_luck=False)
            self.assertFalse(res.success, f"Dovrebbe fallire in modalita {mode}")
            self.assertTrue(any(d.code == "SEM028" for d in res.diagnostics.items))

    def test_murli_slide_196_undefined_variable_detected(self) -> None:
        src = """
        begin perimetro
            var: lato1, lato2, lato3, somma: real
            lato1 := 3.
            lato2 := 5.
            somma := lato1 + lato2 + lato3
            print somma
        end perimetro
        """
        res_draw = compile_source(src, napoli_mode="draw")
        self.assertFalse(res_draw.success)
        self.assertTrue(any(d.code == "SEM014" for d in res_draw.diagnostics.items))

        # Col Napoli che vince, la svista recuperabile viene perdonata!
        res_win = compile_source(src, napoli_mode="win")
        self.assertTrue(res_win.success)

    def test_student_exam_passes_on_napoli_win_and_fails_on_draw_or_loss(self) -> None:
        out = io.StringIO()
        res_win = run_source(IMPERFECT_STUDENT_CODE, napoli_mode="win", stdout=out)
        self.assertTrue(res_win.success)
        self.assertEqual(res_win.verdict.mood, LaccettiMood.OTTIMO_UMORE)
        self.assertGreater(res_win.verdict.forgiven_count, 0)
        self.assertEqual(out.getvalue().strip(), "10 .TRUE.")

        res_big = compile_source(IMPERFECT_STUDENT_CODE, napoli_mode="big-win")
        self.assertTrue(res_big.success)
        self.assertEqual(res_big.verdict.mood, LaccettiMood.ESTASI_AZZURRA)

        res_draw = compile_source(IMPERFECT_STUDENT_CODE, napoli_mode="draw")
        self.assertFalse(res_draw.success)
        self.assertEqual(res_draw.verdict.mood, LaccettiMood.NEUTRO)

        res_loss = compile_source(IMPERFECT_STUDENT_CODE, napoli_mode="loss", allow_luck=False)
        self.assertFalse(res_loss.success)
        self.assertEqual(res_loss.verdict.mood, LaccettiMood.NERVOSO)

    def test_pedantic_warnings_promoted_to_errors_on_napoli_loss(self) -> None:
        res_draw = compile_source(NON_CANONICAL_VALID_CODE, napoli_mode="draw")
        self.assertTrue(res_draw.success)
        self.assertGreater(len(res_draw.diagnostics.pedantics), 0)

        res_win = compile_source(NON_CANONICAL_VALID_CODE, napoli_mode="win")
        self.assertTrue(res_win.success)

        res_loss = compile_source(NON_CANONICAL_VALID_CODE, napoli_mode="loss", allow_luck=False)
        self.assertFalse(res_loss.success)
        self.assertGreater(res_loss.verdict.promoted_count, 0)
        self.assertTrue(all(d.promoted_by_napoli for d in res_loss.diagnostics.pedantics))

    def test_perfect_code_survives_loss_without_luck_and_can_hit_bad_luck_with_seed(self) -> None:
        res_fair = compile_source(PERFECT_CANONICAL_CODE, napoli_mode="derby-loss", allow_luck=False)
        self.assertTrue(res_fair.success)

        # Verifica che con allow_luck=True in derby-loss (30% prob) su 50 seed diversi ci siano sia bocciature sia promozioni
        outcomes = [
            compile_source(PERFECT_CANONICAL_CODE, napoli_mode="derby-loss", allow_luck=True, seed=s).verdict.bad_luck_rejection
            for s in range(50)
        ]
        self.assertTrue(any(outcomes), "Ci si aspetta almeno una bocciatura per malumore su 50 tentativi in derby-loss")
        self.assertTrue(any(not x for x in outcomes), "Ci si aspetta almeno una promozione su 50 tentativi")

    def test_espn_schedule_parser_picks_latest_official_completed_match(self) -> None:
        fake_payload = {
            "events": [
                {
                    "date": "2026-12-01T19:45Z",
                    "league": {"name": "Italian Serie A"},
                    "competitions": [{"status": {"type": {"completed": False}}, "competitors": []}],
                },
                {
                    "date": "2026-11-24T20:00Z",
                    "league": {"name": "UEFA Champions League"},
                    "competitions": [
                        {
                            "status": {"type": {"completed": True}},
                            "competitors": [
                                {"homeAway": "home", "team": {"id": "382", "displayName": "Manchester City"}, "score": {"value": 1}},
                                {"homeAway": "away", "team": {"id": "114", "displayName": "Napoli"}, "score": {"value": 3}},
                            ],
                        }
                    ],
                },
                {
                    "date": "2026-11-20T19:45Z",
                    "league": {"name": "Italian Serie A"},
                    "competitions": [
                        {
                            "status": {"type": {"completed": True}},
                            "competitors": [
                                {"homeAway": "home", "team": {"id": "114", "displayName": "Napoli"}, "score": {"value": 0}},
                                {"homeAway": "away", "team": {"id": "111", "displayName": "Juventus"}, "score": {"value": 2}},
                            ],
                        }
                    ],
                },
            ]
        }
        m = _parse_espn_schedule(fake_payload)
        self.assertIsNotNone(m)
        self.assertEqual(m.date, "2026-11-24")
        self.assertEqual(m.outcome, MatchOutcome.WIN)
        self.assertEqual(m.napoli_score, 3)
        self.assertEqual(m.opponent_score, 1)


if __name__ == "__main__":
    unittest.main()
