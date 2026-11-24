"""Sistema di diagnostica per il compilatore P-Like.

Distinguere quattro livelli di gravità è fondamentale per la "Variabile Napoli":
- FATAL: errore strutturale non recuperabile (fallisce sempre, anche dopo uno Scudetto).
- ERROR: errore grave di sintassi/semantica (fallisce in modalità normale e sconfitta).
- RECOVERABLE: errore tipico da esame scritto che il compilatore riesce a riparare
  automaticamente quando il Napoli ha vinto (es. '=' al posto di ':=', 'then'/'do'
  mancante, variabile contatore non dichiarata, coercizione integer/real).
- PEDANTIC: pignoleria stilistica alla Laccetti (es. TRUE invece di .TRUE., AND
  invece di .AND., A[i] invece di A(i), 0 invece di 0. per un real, variabile
  inutilizzata, end senza nome). In modalità normale sono warning; se il Napoli
  ha perso diventano ERRORI BLOCCANTI!
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class Severity(Enum):
    FATAL = "FATAL"
    ERROR = "ERROR"
    RECOVERABLE = "RECOVERABLE"
    PEDANTIC = "PEDANTIC"
    INFO = "INFO"


@dataclass(frozen=True)
class SourceSpan:
    line: int
    col: int
    end_line: Optional[int] = None
    end_col: Optional[int] = None
    filename: str = "<input>"

    def format_loc(self) -> str:
        return f"{self.filename}:{self.line}:{self.col}"


@dataclass
class Diagnostic:
    severity: Severity
    code: str
    message: str
    span: SourceSpan
    hint: Optional[str] = None
    auto_repaired: bool = False
    promoted_by_napoli: bool = False
    forgiven_by_napoli: bool = False

    def format(self, source_lines: Optional[List[str]] = None) -> str:
        tag = self.severity.value
        if self.promoted_by_napoli:
            tag = "ERRORE (SCONFITTA NAPOLI)"
        elif self.forgiven_by_napoli:
            tag = "PERDONATO (VITTORIA NAPOLI)"
        elif self.severity == Severity.RECOVERABLE:
            tag = "ERRORE RECUPERABILE"

        out = f"[{tag} {self.code}] {self.span.format_loc()}: {self.message}"
        if source_lines and 1 <= self.span.line <= len(source_lines):
            src_line = source_lines[self.span.line - 1].rstrip("\r\n")
            caret_pos = max(0, self.span.col - 1)
            out += f"\n    {self.span.line:4d} | {src_line}"
            out += f"\n         | {' ' * caret_pos}^"
        if self.hint:
            out += f"\n    Suggerimento: {self.hint}"
        return out


@dataclass
class DiagnosticBag:
    items: List[Diagnostic] = field(default_factory=list)

    def add(
        self,
        severity: Severity,
        code: str,
        message: str,
        span: SourceSpan,
        hint: Optional[str] = None,
        auto_repaired: bool = False,
    ) -> Diagnostic:
        diag = Diagnostic(
            severity=severity,
            code=code,
            message=message,
            span=span,
            hint=hint,
            auto_repaired=auto_repaired,
        )
        self.items.append(diag)
        return diag

    def fatal(self, code: str, message: str, span: SourceSpan, hint: Optional[str] = None) -> Diagnostic:
        return self.add(Severity.FATAL, code, message, span, hint)

    def error(self, code: str, message: str, span: SourceSpan, hint: Optional[str] = None) -> Diagnostic:
        return self.add(Severity.ERROR, code, message, span, hint)

    def recoverable(
        self,
        code: str,
        message: str,
        span: SourceSpan,
        hint: Optional[str] = None,
        auto_repaired: bool = True,
    ) -> Diagnostic:
        return self.add(Severity.RECOVERABLE, code, message, span, hint, auto_repaired=auto_repaired)

    def pedantic(self, code: str, message: str, span: SourceSpan, hint: Optional[str] = None) -> Diagnostic:
        return self.add(Severity.PEDANTIC, code, message, span, hint)

    @property
    def fatals(self) -> List[Diagnostic]:
        return [d for d in self.items if d.severity == Severity.FATAL]

    @property
    def errors(self) -> List[Diagnostic]:
        return [d for d in self.items if d.severity == Severity.ERROR]

    @property
    def recoverables(self) -> List[Diagnostic]:
        return [d for d in self.items if d.severity == Severity.RECOVERABLE]

    @property
    def pedantics(self) -> List[Diagnostic]:
        return [d for d in self.items if d.severity == Severity.PEDANTIC]

    def extend(self, other: "DiagnosticBag") -> None:
        self.items.extend(other.items)
