"""Definizioni dei token del linguaggio P-Like."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Dict

from .diagnostics import SourceSpan


class TokenType(Enum):
    # Strutturali
    NEWLINE = auto()
    EOF = auto()

    # Letterali & Identificatori
    IDENT = auto()
    INT_LIT = auto()
    REAL_LIT = auto()
    STRING_LIT = auto()
    BOOL_LIT = auto()
    NULL_LIT = auto()

    # Parole chiave di struttura
    BEGIN = auto()
    END = auto()
    VAR = auto()
    TYPE = auto()
    RECORD = auto()
    ENDRECORD = auto()
    ARRAY = auto()
    OF = auto()
    PROCEDURE = auto()
    ENDPROCEDURE = auto()
    FUNCTION = auto()
    ENDFUNCTION = auto()
    RETURN = auto()

    # Controllo di flusso
    IF = auto()
    THEN = auto()
    ELSE = auto()
    ELSEIF = auto()
    ENDIF = auto()
    FOR = auto()
    TO = auto()
    DOWNTO = auto()
    STEP = auto()
    DO = auto()
    ENDFOR = auto()
    WHILE = auto()
    ENDWHILE = auto()
    REPEAT = auto()
    UNTIL = auto()

    # I/O e memoria dinamica
    READ = auto()
    PRINT = auto()
    ALLOCATE = auto()
    DEALLOCATE = auto()

    # Tipi primitivi
    INTEGER = auto()
    REAL = auto()
    CHARACTER = auto()
    LOGICAL = auto()

    # Modalità parametri
    IN = auto()
    OUT = auto()
    INOUT = auto()

    # Operatori logici e aritmetici parola-chiave
    AND = auto()
    OR = auto()
    NOT = auto()
    MOD = auto()
    DIV = auto()

    # Operatori simbolici
    ASSIGN = auto()      # :=
    EQ = auto()          # = o ==
    NEQ = auto()         # !=, <>, /=, ≠
    LT = auto()          # <
    LTE = auto()         # <=
    GT = auto()          # >
    GTE = auto()         # >=
    PLUS = auto()        # +
    MINUS = auto()       # -
    STAR = auto()        # * o ×
    SLASH = auto()       # /
    POWER = auto()       # ** o ^
    CARET = auto()       # ^ (puntatore o potenza a seconda del contesto)
    BANG = auto()        # !

    # Punteggiatura
    LPAREN = auto()      # (
    RPAREN = auto()      # )
    LBRACKET = auto()    # [
    RBRACKET = auto()    # ]
    COMMA = auto()       # ,
    COLON = auto()       # :
    SEMICOLON = auto()   # ;
    DOT = auto()         # .
    DOTDOT = auto()      # ..


KEYWORDS: Dict[str, TokenType] = {
    "begin": TokenType.BEGIN,
    "end": TokenType.END,
    "var": TokenType.VAR,
    "type": TokenType.TYPE,
    "record": TokenType.RECORD,
    "endrecord": TokenType.ENDRECORD,
    "array": TokenType.ARRAY,
    "of": TokenType.OF,
    "procedure": TokenType.PROCEDURE,
    "endprocedure": TokenType.ENDPROCEDURE,
    "function": TokenType.FUNCTION,
    "endfunction": TokenType.ENDFUNCTION,
    "return": TokenType.RETURN,
    "if": TokenType.IF,
    "then": TokenType.THEN,
    "else": TokenType.ELSE,
    "elseif": TokenType.ELSEIF,
    "endif": TokenType.ENDIF,
    "for": TokenType.FOR,
    "to": TokenType.TO,
    "downto": TokenType.DOWNTO,
    "step": TokenType.STEP,
    "do": TokenType.DO,
    "endfor": TokenType.ENDFOR,
    "while": TokenType.WHILE,
    "endwhile": TokenType.ENDWHILE,
    "repeat": TokenType.REPEAT,
    "until": TokenType.UNTIL,
    "read": TokenType.READ,
    "print": TokenType.PRINT,
    "write": TokenType.PRINT,
    "allocate": TokenType.ALLOCATE,
    "alloca": TokenType.ALLOCATE,
    "deallocate": TokenType.DEALLOCATE,
    "dealloca": TokenType.DEALLOCATE,
    "free": TokenType.DEALLOCATE,
    "integer": TokenType.INTEGER,
    "real": TokenType.REAL,
    "character": TokenType.CHARACTER,
    "char": TokenType.CHARACTER,
    "string": TokenType.CHARACTER,
    "logical": TokenType.LOGICAL,
    "boolean": TokenType.LOGICAL,
    "in": TokenType.IN,
    "input": TokenType.IN,
    "out": TokenType.OUT,
    "output": TokenType.OUT,
    "inout": TokenType.INOUT,
    "and": TokenType.AND,
    "or": TokenType.OR,
    "not": TokenType.NOT,
    "mod": TokenType.MOD,
    "div": TokenType.DIV,
    "true": TokenType.BOOL_LIT,
    "false": TokenType.BOOL_LIT,
    "null": TokenType.NULL_LIT,
    "nil": TokenType.NULL_LIT,
}

# Tipi di typo tollerati nelle slide di Murli/Laccetti e negli esami studenti
RECOVERABLE_TYPOS: Dict[str, TokenType] = {
    "enwhile": TokenType.ENDWHILE,
    "endwhille": TokenType.ENDWHILE,
    "whille": TokenType.WHILE,
    "funcion": TokenType.FUNCTION,
    "endfuncion": TokenType.ENDFUNCTION,
}


@dataclass(frozen=True)
class Token:
    type: TokenType
    lexeme: str
    value: Any
    span: SourceSpan
    canonical: bool = True  # False per forme non canoniche (es. TRUE senza punti, AND senza punti, ==)

    def __repr__(self) -> str:
        return f"Token({self.type.name}, {self.lexeme!r}, {self.span.line}:{self.span.col})"
