"""Motore 'Variabile Napoli' (Modalità Prof. Giuliano Laccetti).

Recupera in tempo reale il risultato dell'ultima partita ufficiale dell'SSC Napoli
(Serie A, Champions League, Coppa Italia, ecc.) tramite l'API pubblica ESPN con cache
locale, e determina l'umore del Prof. Laccetti e l'esito finale della compilazione:

- VITTORIA (e ancor più GOLEADA / VITTORIA VS RIVALI):
  Compilazione INDULGENTE! Gli errori recuperabili tipici da compito scritto
  (es. '=' invece di ':=', 'then'/'do' mancante, variabile indice non dichiarata)
  vengono automaticamente perdonati e auto-riparati!
- PAREGGIO:
  Compilazione STANDARD. Valgono le normali regole del P-Like (gli errori falliscono,
  le pignolerie stilistiche sono solo warning).
- SCONFITTA (e ancor più SCONFITTA PESANTE / CONTRO JUVENTUS, INTER, MILAN, ROMA):
  Compilazione SEVERISSIMA! Tutte le pignolerie stilistiche Laccetti (TRUE senza punti,
  AND senza punti, A[i] invece di A(i), 0 invece di 0. per un real, variabile inutilizzata,
  end senza nome) vengono PROMOSSE A ERRORI BLOCCANTI, e persino un codice perfetto
  rischia la "bocciatura da malumore post-partita" (disattivabile con --no-luck o
  riproducibile con --seed)!
"""

from __future__ import annotations

import json
import os
import random
import time
import urllib.request
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import List, Optional, Tuple

from .diagnostics import DiagnosticBag, Severity

ESPN_NAPOLI_ALL_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams/114/schedule"
ESPN_NAPOLI_SERIEA_URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/ita.1/teams/114/schedule"
NAPOLI_TEAM_ID = "114"
CACHE_TTL_SECONDS = 3600  # 1 ora

RIVAL_KEYWORDS = ("juventus", "inter", "internazionale", "milan", "ac milan", "roma", "lazio", "atalanta")


class MatchOutcome(Enum):
    WIN = "WIN"
    DRAW = "DRAW"
    LOSS = "LOSS"
    DISABLED = "DISABLED"


class LaccettiMood(Enum):
    ESTASI_AZZURRA = "ESTASI_AZZURRA"         # Vittoria larga (>=3 gol) o contro grande rivale
    OTTIMO_UMORE = "OTTIMO_UMORE"             # Vittoria normale
    NEUTRO = "NEUTRO"                         # Pareggio
    NERVOSO = "NERVOSO"                       # Sconfitta di misura
    FURIA_POST_PARTITA = "FURIA_POST_PARTITA" # Sconfitta pesante o contro rivale (es. Juve!)
    STANDARD = "STANDARD"                     # Modalità Napoli disattivata (--napoli off)


@dataclass
class NapoliMatch:
    date: str
    competition: str
    home_team: str
    away_team: str
    home_score: int
    away_score: int
    napoli_is_home: bool
    outcome: MatchOutcome
    source: str = "live"  # 'live', 'cache', 'simulated', 'fallback'

    @property
    def napoli_score(self) -> int:
        return self.home_score if self.napoli_is_home else self.away_score

    @property
    def opponent_score(self) -> int:
        return self.away_score if self.napoli_is_home else self.home_score

    @property
    def opponent(self) -> str:
        return self.away_team if self.napoli_is_home else self.home_team

    @property
    def goal_diff(self) -> int:
        return self.napoli_score - self.opponent_score

    @property
    def against_rival(self) -> bool:
        opp = self.opponent.lower()
        return any(r in opp for r in RIVAL_KEYWORDS)

    @property
    def scoreboard(self) -> str:
        return f"{self.home_team} {self.home_score} - {self.away_score} {self.away_team}"

    def compute_mood(self) -> LaccettiMood:
        if self.outcome == MatchOutcome.DISABLED:
            return LaccettiMood.STANDARD
        if self.outcome == MatchOutcome.WIN:
            if self.goal_diff >= 3 or self.against_rival:
                return LaccettiMood.ESTASI_AZZURRA
            return LaccettiMood.OTTIMO_UMORE
        if self.outcome == MatchOutcome.DRAW:
            return LaccettiMood.NEUTRO
        # LOSS
        if self.goal_diff <= -2 or self.against_rival:
            return LaccettiMood.FURIA_POST_PARTITA
        return LaccettiMood.NERVOSO


@dataclass
class CompilationVerdict:
    passed: bool
    mood: LaccettiMood
    match: NapoliMatch
    grade_numeric: int       # 0..31 (31 = 30 e Lode)
    grade_label: str         # es. "30 e Lode", "27/30", "BOCCIATO (15/30)"
    prof_comment: str
    forgiven_count: int = 0
    promoted_count: int = 0
    bad_luck_rejection: bool = False


def _cache_path() -> Path:
    return Path.home() / ".plike_napoli_cache.json"


def _simulated_match(mode: str) -> NapoliMatch:
    m = mode.lower().strip()
    if m in ("off", "none", "disabled", "standard"):
        return NapoliMatch(
            date="N/A",
            competition="Modalità Standard",
            home_team="Napoli",
            away_team="N/A",
            home_score=0,
            away_score=0,
            napoli_is_home=True,
            outcome=MatchOutcome.DISABLED,
            source="disabled",
        )
    if m in ("big-win", "goleada", "scudetto"):
        return NapoliMatch(
            date="Simulata",
            competition="Serie A (Simulazione)",
            home_team="Napoli",
            away_team="Juventus",
            home_score=5,
            away_score=1,
            napoli_is_home=True,
            outcome=MatchOutcome.WIN,
            source="simulated",
        )
    if m in ("win", "vittoria", "v"):
        return NapoliMatch(
            date="Simulata",
            competition="Serie A (Simulazione)",
            home_team="Napoli",
            away_team="Torino",
            home_score=2,
            away_score=0,
            napoli_is_home=True,
            outcome=MatchOutcome.WIN,
            source="simulated",
        )
    if m in ("draw", "pareggio", "p", "x"):
        return NapoliMatch(
            date="Simulata",
            competition="Serie A (Simulazione)",
            home_team="Napoli",
            away_team="Lazio",
            home_score=1,
            away_score=1,
            napoli_is_home=True,
            outcome=MatchOutcome.DRAW,
            source="simulated",
        )
    if m in ("derby-loss", "disastro", "juve-loss"):
        return NapoliMatch(
            date="Simulata",
            competition="Serie A (Simulazione)",
            home_team="Juventus",
            away_team="Napoli",
            home_score=3,
            away_score=0,
            napoli_is_home=False,
            outcome=MatchOutcome.LOSS,
            source="simulated",
        )
    if m in ("loss", "sconfitta", "l", "s"):
        return NapoliMatch(
            date="Simulata",
            competition="Serie A (Simulazione)",
            home_team="Napoli",
            away_team="Bologna",
            home_score=0,
            away_score=1,
            napoli_is_home=True,
            outcome=MatchOutcome.LOSS,
            source="simulated",
        )
    raise ValueError(
        f"Modalità Napoli sconosciuta: {mode!r}. "
        "Valori ammessi: auto, win, big-win, draw, loss, derby-loss, off."
    )


def _parse_espn_schedule(data: dict) -> Optional[NapoliMatch]:
    events = data.get("events", [])
    completed: List[dict] = []
    for ev in events:
        comps = ev.get("competitions", [])
        if not comps:
            continue
        status_type = comps[0].get("status", {}).get("type", {})
        if status_type.get("completed"):
            completed.append(ev)

    if not completed:
        return None

    # Ordina dalla partita più recente alla meno recente
    completed.sort(key=lambda e: e.get("date", ""), reverse=True)

    # Preferisci partite ufficiali rispetto alle amichevoli se disponibili
    official = [e for e in completed if "friendly" not in e.get("league", {}).get("name", "").lower()]
    chosen = official[0] if official else completed[0]

    comp = chosen["competitions"][0]
    competitors = comp.get("competitors", [])
    if len(competitors) < 2:
        return None

    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

    home_name = home.get("team", {}).get("displayName", "Home")
    away_name = away.get("team", {}).get("displayName", "Away")

    def _score_int(c: dict) -> int:
        s = c.get("score", {})
        if isinstance(s, dict):
            raw = s.get("value", s.get("displayValue", 0))
        else:
            raw = s
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return 0

    hs = _score_int(home)
    as_ = _score_int(away)
    napoli_is_home = (
        str(home.get("team", {}).get("id", "")) == NAPOLI_TEAM_ID
        or "napoli" in home_name.lower()
    )

    nap_s = hs if napoli_is_home else as_
    opp_s = as_ if napoli_is_home else hs
    if nap_s > opp_s:
        outcome = MatchOutcome.WIN
    elif nap_s < opp_s:
        outcome = MatchOutcome.LOSS
    else:
        outcome = MatchOutcome.DRAW

    date_str = chosen.get("date", "")[:10]
    league_name = chosen.get("league", {}).get("name", "Competizione Ufficiale")

    return NapoliMatch(
        date=date_str,
        competition=league_name,
        home_team=home_name,
        away_team=away_name,
        home_score=hs,
        away_score=as_,
        napoli_is_home=napoli_is_home,
        outcome=outcome,
        source="live",
    )


def fetch_latest_napoli_match(
    mode: str = "auto",
    force_refresh: bool = False,
    timeout: float = 5.0,
) -> NapoliMatch:
    """Recupera l'ultima partita dell'SSC Napoli (o restituisce una partita simulata)."""
    if mode.lower() != "auto":
        return _simulated_match(mode)

    # 1. Prova la cache locale
    cpath = _cache_path()
    if not force_refresh and cpath.exists():
        try:
            cached = json.loads(cpath.read_text(encoding="utf-8"))
            if time.time() - cached.get("fetched_at", 0) < CACHE_TTL_SECONDS:
                m = cached["match"]
                return NapoliMatch(
                    date=m["date"],
                    competition=m["competition"],
                    home_team=m["home_team"],
                    away_team=m["away_team"],
                    home_score=m["home_score"],
                    away_score=m["away_score"],
                    napoli_is_home=m["napoli_is_home"],
                    outcome=MatchOutcome(m["outcome"]),
                    source="cache",
                )
        except Exception:
            pass

    # 2. Interroga API pubblica ESPN (tutte le competizioni, poi fallback Serie A)
    for url in (ESPN_NAPOLI_ALL_URL, ESPN_NAPOLI_SERIEA_URL):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "PLike-Laccetti-Compiler/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            match = _parse_espn_schedule(data)
            if match is not None:
                try:
                    payload = {
                        "fetched_at": time.time(),
                        "match": {
                            **asdict(match),
                            "outcome": match.outcome.value,
                        },
                    }
                    cpath.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                except Exception:
                    pass
                return match
        except Exception:
            continue

    # 3. Fallback offline se non c'è rete (usa eventuale cache scaduta oppure pareggio neutro)
    if cpath.exists():
        try:
            cached = json.loads(cpath.read_text(encoding="utf-8"))
            m = cached["match"]
            return NapoliMatch(
                date=m["date"],
                competition=m["competition"],
                home_team=m["home_team"],
                away_team=m["away_team"],
                home_score=m["home_score"],
                away_score=m["away_score"],
                napoli_is_home=m["napoli_is_home"],
                outcome=MatchOutcome(m["outcome"]),
                source="cache-stale",
            )
        except Exception:
            pass

    return NapoliMatch(
        date="Offline",
        competition="Connessione assente (modalità neutra)",
        home_team="Napoli",
        away_team="Avversario",
        home_score=1,
        away_score=1,
        napoli_is_home=True,
        outcome=MatchOutcome.DRAW,
        source="fallback",
    )


# ---------------------------------------------------------------------------
# Valutazione dell'esito di compilazione ("Esame scritto di Programmazione I")
# ---------------------------------------------------------------------------

def evaluate_compilation_verdict(
    diagnostics: DiagnosticBag,
    match: NapoliMatch,
    *,
    allow_luck: bool = True,
    seed: Optional[int] = None,
) -> CompilationVerdict:
    """Applica le regole del P-Like combinate con la Variabile Napoli!"""
    mood = match.compute_mood()
    fatals = diagnostics.fatals
    hard_errors = diagnostics.errors
    recoverables = diagnostics.recoverables
    pedantics = diagnostics.pedantics

    rng = random.Random(seed)

    # Errori FATAL bloccano sempre la compilazione (AST inutilizzabile)
    if fatals:
        return CompilationVerdict(
            passed=False,
            mood=mood,
            match=match,
            grade_numeric=8,
            grade_label="INSUFFICIENTE (8/30)",
            prof_comment=(
                "Guagliò, qua non si capisce proprio niente! Nemmeno se il Napoli "
                "vincesse la Champions 5-0 potrei compilare questo codice."
            ),
        )

    # ------------------------------------------------------------------
    # MODALITÀ STANDARD (--napoli off)
    # ------------------------------------------------------------------
    if mood == LaccettiMood.STANDARD:
        passed = len(hard_errors) == 0 and len(recoverables) == 0
        grade = 30 if passed and not pedantics else (max(18, 29 - len(pedantics)) if passed else max(10, 17 - len(hard_errors) - len(recoverables)))
        return CompilationVerdict(
            passed=passed,
            mood=mood,
            match=match,
            grade_numeric=grade,
            grade_label=f"{grade}/30" if passed else f"NON SUPERATO ({grade}/30)",
            prof_comment=(
                "Compilazione completata in modalità standard (Variabile Napoli disattivata)."
                if passed
                else "Compilazione fallita: correggi gli errori P-Like segnalati."
            ),
        )

    # ------------------------------------------------------------------
    # VITTORIA DEL NAPOLI (ESTASI_AZZURRA / OTTIMO_UMORE)
    # ------------------------------------------------------------------
    if mood in (LaccettiMood.ESTASI_AZZURRA, LaccettiMood.OTTIMO_UMORE):
        max_forgive = 6 if mood == LaccettiMood.ESTASI_AZZURRA else 3
        # In Estasi Azzurra (es. vittoria larga / vs Juventus), perfino 1 errore semantico non fatale
        # viene perdonato se c'è margine, e fino a 6 errori recuperabili sono auto-corretti!
        if len(hard_errors) == 0 and len(recoverables) <= max_forgive:
            for d in recoverables:
                d.forgiven_by_napoli = True
            for d in pedantics:
                d.forgiven_by_napoli = True

            if len(recoverables) == 0 and len(pedantics) <= 1:
                grade_num = 31
                grade_lbl = "30 e Lode!"
            else:
                bonus = 3 if mood == LaccettiMood.ESTASI_AZZURRA else 1
                grade_num = min(30, max(22, 30 + bonus - len(recoverables) * 2 - len(pedantics) // 2))
                grade_lbl = f"{grade_num}/30"

            if mood == LaccettiMood.ESTASI_AZZURRA:
                comment = (
                    f"FORZA NAPOLI! Dopo '{match.scoreboard}' ({match.competition}) oggi passiamo tutti! "
                    + (
                        f"Ti ho persino perdonato e auto-corretto {len(recoverables)} svista/e da esame scritto. Vai a festeggiare!"
                        if recoverables
                        else "Algoritmo impeccabile, 30 e Lode meritato... e sempre Forza Napoli!"
                    )
                )
            else:
                comment = (
                    f"Il Napoli ha vinto ({match.scoreboard}) e oggi sono di ottimo umore! "
                    + (
                        f"Chiudo un occhio su {len(recoverables)} imprecisione/i P-Like e te lo compilo lo stesso."
                        if recoverables
                        else "Ottimo P-Like, promosso a pieni voti!"
                    )
                )

            return CompilationVerdict(
                passed=True,
                mood=mood,
                match=match,
                grade_numeric=grade_num,
                grade_label=grade_lbl,
                prof_comment=comment,
                forgiven_count=len(recoverables) + len(pedantics),
            )

        # Troppi errori anche per una vittoria del Napoli
        grade_num = max(12, 17 - len(hard_errors) - max(0, len(recoverables) - max_forgive))
        return CompilationVerdict(
            passed=False,
            mood=mood,
            match=match,
            grade_numeric=grade_num,
            grade_label=f"BOCCIATO ({grade_num}/30)",
            prof_comment=(
                f"Pure col Napoli vittorioso ({match.scoreboard}) ci hai messo troppi errori "
                f"({len(hard_errors)} gravi, {len(recoverables)} recuperabili). Dai, un minimo di P-Like!"
            ),
        )

    # ------------------------------------------------------------------
    # PAREGGIO DEL NAPOLI (NEUTRO)
    # ------------------------------------------------------------------
    if mood == LaccettiMood.NEUTRO:
        passed = len(hard_errors) == 0 and len(recoverables) == 0
        if passed:
            grade_num = 30 if not pedantics else max(21, 30 - len(pedantics))
            comment = (
                f"Il Napoli ha pareggiato ({match.scoreboard}): valutazione regolare e imparziale. "
                + (
                    "Codice pulito, promosso!"
                    if not pedantics
                    else f"Promosso, ma occhio ai {len(pedantics)} dettagli di stile P-Like."
                )
            )
            return CompilationVerdict(
                passed=True,
                mood=mood,
                match=match,
                grade_numeric=grade_num,
                grade_label=f"{grade_num}/30",
                prof_comment=comment,
            )
        grade_num = max(11, 17 - len(hard_errors) - len(recoverables))
        return CompilationVerdict(
            passed=False,
            mood=mood,
            match=match,
            grade_numeric=grade_num,
            grade_label=f"BOCCIATO ({grade_num}/30)",
            prof_comment=(
                f"Col pareggio del Napoli ({match.scoreboard}) non faccio sconti: "
                "correggi gli errori di sintassi/semantica e ripresentati!"
            ),
        )

    # ------------------------------------------------------------------
    # SCONFITTA DEL NAPOLI (NERVOSO / FURIA_POST_PARTITA)
    # ------------------------------------------------------------------
    # Tutte le pignolerie PEDANTIC diventano ERRORI BLOCCANTI!
    for d in pedantics:
        d.promoted_by_napoli = True

    total_issues = len(hard_errors) + len(recoverables) + len(pedantics)
    if total_issues > 0:
        grade_num = max(8, 16 - total_issues)
        if mood == LaccettiMood.FURIA_POST_PARTITA:
            comment = (
                f"MA COME SI FA?! Il Napoli ha perso '{match.scoreboard}' e tu vieni all'esame "
                f"con {total_issues} errori/imprecisioni (anche le pignolerie oggi sono bocciatura immediata)! "
                "Ci vediamo al prossimo appello!"
            )
        else:
            comment = (
                f"Il Napoli ha perso ({match.scoreboard}) e oggi non si perdona NULLA: "
                f"anche {len(pedantics)} imprecisioni di stile P-Like ti fanno saltare la compilazione. "
                "Studia le slide sulla sintassi canonica!"
            )
        return CompilationVerdict(
            passed=False,
            mood=mood,
            match=match,
            grade_numeric=grade_num,
            grade_label=f"BOCCIATO ({grade_num}/30)",
            prof_comment=comment,
            promoted_count=len(pedantics),
        )

    # Codice formalmente perfetto durante una sconfitta del Napoli -> rischio "malumore post-partita"!
    rejection_prob = 0.30 if mood == LaccettiMood.FURIA_POST_PARTITA else 0.15
    if allow_luck and rng.random() < rejection_prob:
        excuses = [
            "Il codice compila formalmente, ma dopo questa sconfitta del Napoli non mi convince la complessità asintotica. Ritenta al prossimo appello!",
            "Sintassi corretta, sì... ma la Leading Dimension mi fa venire il mal di testa oggi dopo la partita del Napoli. Rimandato!",
            "Troppo elegante per il mio umore dopo la sconfitta del Napoli: ci rivediamo all'orale straordinario (compilazione rifiutata)!",
        ]
        return CompilationVerdict(
            passed=False,
            mood=mood,
            match=match,
            grade_numeric=17,
            grade_label="BOCCIATO PER MALUMORE (17/30)",
            prof_comment=f"[{match.scoreboard}] " + rng.choice(excuses),
            bad_luck_rejection=True,
        )

    # Sopravvissuto all'appello post-sconfitta!
    grade_num = 24 if mood == LaccettiMood.FURIA_POST_PARTITA else 27
    return CompilationVerdict(
        passed=True,
        mood=mood,
        match=match,
        grade_numeric=grade_num,
        grade_label=f"{grade_num}/30 (Sopravvissuto!)",
        prof_comment=(
            f"Nonostante la sconfitta del Napoli ({match.scoreboard}), il tuo P-Like è così "
            "canonico e impeccabile che non ho trovato un solo appiglio per bocciarti. Bravo!"
        ),
    )
