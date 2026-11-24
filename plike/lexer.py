"""Lexer (analizzatore lessicale) completo per il linguaggio P-Like.

Supporta fedelmente tutte le convenzioni delle slide del Prof. Giuliano Laccetti
(e dei testi Murli/Giunta/Laccetti) più le varianti usate negli esami:
- Case-insensitive per keyword e identificatori
- Costanti logiche canoniche `.TRUE.` / `.FALSE.` (e `TRUE` / `FALSE` con flag non-canonico)
- Operatori logici canonici `.AND.` / `.OR.` / `.NOT.` (e `AND` / `OR` / `NOT` / `!`)
- Reali con punto finale (`5.`, `0.`, `4.e-3`) disambiguati correttamente da `..` e da `.OR.`/`.AND.`
- Commenti `(* ... *)`, `/* ... */` e `// ...`
- Stringhe/caratteri tra apici singoli `'...'` (canonico) e doppi `"..."` (e virgolette tipografiche)
- Operatori `:=`, `=`, `==`, `!=`, `<>`, `/=`, `≠`, `×`, `in/out`
"""

from __future__ import annotations

from typing import List, Tuple

from .diagnostics import DiagnosticBag, SourceSpan
from .tokens import KEYWORDS, RECOVERABLE_TYPOS, Token, TokenType

DOTTED_KEYWORDS = {
    ".true.": (TokenType.BOOL_LIT, True),
    ".false.": (TokenType.BOOL_LIT, False),
    ".and.": (TokenType.AND, "and"),
    ".or.": (TokenType.OR, "or"),
    ".not.": (TokenType.NOT, "not"),
}


class Lexer:
    def __init__(self, source: str, filename: str = "<input>", diagnostics: DiagnosticBag | None = None):
        self.source = source
        self.filename = filename
        self.diagnostics = diagnostics if diagnostics is not None else DiagnosticBag()
        self.pos = 0
        self.line = 1
        self.col = 1
        self.length = len(source)

    def _peek(self, offset: int = 0) -> str:
        idx = self.pos + offset
        if idx >= self.length:
            return "\0"
        return self.source[idx]

    def _advance(self) -> str:
        ch = self.source[self.pos]
        self.pos += 1
        if ch == "\n":
            self.line += 1
            self.col = 1
        else:
            self.col += 1
        return ch

    def _match(self, expected: str) -> bool:
        if self._peek() == expected:
            self._advance()
            return True
        return False

    def _span(self, start_line: int, start_col: int) -> SourceSpan:
        return SourceSpan(
            line=start_line,
            col=start_col,
            end_line=self.line,
            end_col=self.col,
            filename=self.filename,
        )

    def _peek_dotted_keyword(self) -> Tuple[str, TokenType, object] | None:
        if self._peek() != ".":
            return None
        rest = self.source[self.pos:self.pos + 8].lower()
        for kw, (tt, val) in DOTTED_KEYWORDS.items():
            if rest.startswith(kw):
                return kw, tt, val
        return None

    def tokenize(self) -> List[Token]:
        tokens: List[Token] = []

        while self.pos < self.length:
            ch = self._peek()

            # Spazi orizzontali
            if ch in (" ", "\t", "\r"):
                self._advance()
                continue

            # Fine riga (significativa per separare istruzioni in P-Like)
            if ch == "\n":
                sl, sc = self.line, self.col
                self._advance()
                if tokens and tokens[-1].type != TokenType.NEWLINE:
                    tokens.append(Token(TokenType.NEWLINE, "\n", "\n", self._span(sl, sc)))
                continue

            # Commento // ...
            if ch == "/" and self._peek(1) == "/":
                while self.pos < self.length and self._peek() != "\n":
                    self._advance()
                continue

            # Commento /* ... */
            if ch == "/" and self._peek(1) == "*":
                sl, sc = self.line, self.col
                self._advance()
                self._advance()
                closed = False
                while self.pos < self.length:
                    if self._peek() == "*" and self._peek(1) == "/":
                        self._advance()
                        self._advance()
                        closed = True
                        break
                    self._advance()
                if not closed:
                    self.diagnostics.error(
                        "LEX001",
                        "Commento /* ... */ non chiuso prima della fine del file.",
                        self._span(sl, sc),
                    )
                continue

            # Commento (* ... *)
            if ch == "(" and self._peek(1) == "*":
                sl, sc = self.line, self.col
                self._advance()
                self._advance()
                closed = False
                while self.pos < self.length:
                    if self._peek() == "*" and self._peek(1) == ")":
                        self._advance()
                        self._advance()
                        closed = True
                        break
                    self._advance()
                if not closed:
                    self.diagnostics.error(
                        "LEX002",
                        "Commento (* ... *) non chiuso prima della fine del file.",
                        self._span(sl, sc),
                    )
                continue

            sl, sc = self.line, self.col

            # Stringhe / costanti alfanumeriche
            if ch in ("'", '"', "‘", "“"):
                tokens.append(self._lex_string())
                continue

            # Numeri interi e reali
            if ch.isdigit():
                tokens.append(self._lex_number())
                continue

            # Punto, `..`, o keyword puntata (.TRUE., .FALSE., .AND., .OR., .NOT.)
            if ch == ".":
                dotted = self._peek_dotted_keyword()
                if dotted is not None:
                    kw, tt, val = dotted
                    raw = self.source[self.pos:self.pos + len(kw)]
                    for _ in range(len(kw)):
                        self._advance()
                    tokens.append(Token(tt, raw, val, self._span(sl, sc), canonical=True))
                    continue
                if self._peek(1) == ".":
                    self._advance()
                    self._advance()
                    # Gestisci anche '...' elisione -> se tre punti, avvisa o consuma
                    tokens.append(Token(TokenType.DOTDOT, "..", "..", self._span(sl, sc)))
                    continue
                # Reale che inizia con punto es. `.5`
                if self._peek(1).isdigit():
                    tokens.append(self._lex_number())
                    continue
                self._advance()
                tokens.append(Token(TokenType.DOT, ".", ".", self._span(sl, sc)))
                continue

            # Identificatori e parole chiave
            if ch.isalpha() or ch == "_":
                tokens.append(self._lex_ident_or_keyword())
                continue

            # Operatori e punteggiatura
            if ch == ":":
                self._advance()
                if self._match("="):
                    tokens.append(Token(TokenType.ASSIGN, ":=", ":=", self._span(sl, sc)))
                else:
                    tokens.append(Token(TokenType.COLON, ":", ":", self._span(sl, sc)))
                continue

            if ch == "=":
                self._advance()
                if self._match("="):
                    self.diagnostics.pedantic(
                        "PED001",
                        "Operatore '==' stile C usato al posto del canonico '=' di P-Like.",
                        self._span(sl, sc),
                        hint="In P-Like l'uguaglianza si scrive '=' e l'assegnazione ':='.",
                    )
                    tokens.append(Token(TokenType.EQ, "==", "=", self._span(sl, sc), canonical=False))
                else:
                    tokens.append(Token(TokenType.EQ, "=", "=", self._span(sl, sc)))
                continue

            if ch == "!":
                self._advance()
                if self._match("="):
                    tokens.append(Token(TokenType.NEQ, "!=", "!=", self._span(sl, sc)))
                else:
                    self.diagnostics.pedantic(
                        "PED002",
                        "Operatore '!' stile C usato al posto di '.NOT.' / 'NOT'.",
                        self._span(sl, sc),
                        hint="Usa '.NOT.' secondo la sintassi canonica P-Like.",
                    )
                    tokens.append(Token(TokenType.NOT, "!", "not", self._span(sl, sc), canonical=False))
                continue

            if ch == "<":
                self._advance()
                if self._match("="):
                    tokens.append(Token(TokenType.LTE, "<=", "<=", self._span(sl, sc)))
                elif self._match(">"):
                    tokens.append(Token(TokenType.NEQ, "<>", "!=", self._span(sl, sc)))
                else:
                    tokens.append(Token(TokenType.LT, "<", "<", self._span(sl, sc)))
                continue

            if ch == ">":
                self._advance()
                if self._match("="):
                    tokens.append(Token(TokenType.GTE, ">=", ">=", self._span(sl, sc)))
                else:
                    tokens.append(Token(TokenType.GT, ">", ">", self._span(sl, sc)))
                continue

            if ch == "/":
                self._advance()
                if self._match("="):
                    tokens.append(Token(TokenType.NEQ, "/=", "!=", self._span(sl, sc)))
                else:
                    tokens.append(Token(TokenType.SLASH, "/", "/", self._span(sl, sc)))
                continue

            if ch == "*":
                self._advance()
                if self._match("*"):
                    tokens.append(Token(TokenType.POWER, "**", "**", self._span(sl, sc)))
                else:
                    tokens.append(Token(TokenType.STAR, "*", "*", self._span(sl, sc)))
                continue

            if ch == "×":
                self._advance()
                tokens.append(Token(TokenType.STAR, "×", "*", self._span(sl, sc)))
                continue

            if ch == "≠":
                self._advance()
                tokens.append(Token(TokenType.NEQ, "≠", "!=", self._span(sl, sc)))
                continue

            if ch in ("–", "−"):  # en-dash / minus unicode copiati dai PDF delle slide!
                self._advance()
                tokens.append(Token(TokenType.MINUS, ch, "-", self._span(sl, sc)))
                continue

            single_map = {
                "+": TokenType.PLUS,
                "-": TokenType.MINUS,
                "^": TokenType.CARET,
                "(": TokenType.LPAREN,
                ")": TokenType.RPAREN,
                "[": TokenType.LBRACKET,
                "]": TokenType.RBRACKET,
                ",": TokenType.COMMA,
                ";": TokenType.SEMICOLON,
                "%": TokenType.MOD,
            }
            if ch in single_map:
                self._advance()
                tt = single_map[ch]
                val = "mod" if ch == "%" else ch
                if ch == "%":
                    self.diagnostics.pedantic(
                        "PED003",
                        "Operatore '%' stile C usato al posto di 'mod'.",
                        self._span(sl, sc),
                        hint="In P-Like il resto della divisione intera si scrive 'mod'.",
                    )
                tokens.append(Token(tt, ch, val, self._span(sl, sc), canonical=(ch != "%")))
                continue

            # Carattere sconosciuto
            self._advance()
            self.diagnostics.error(
                "LEX003",
                f"Carattere non riconosciuto: {ch!r}.",
                self._span(sl, sc),
            )

        tokens.append(Token(TokenType.EOF, "", None, SourceSpan(self.line, self.col, filename=self.filename)))
        return tokens

    def _lex_string(self) -> Token:
        sl, sc = self.line, self.col
        open_q = self._advance()
        close_map = {"'": "'", '"': '"', "‘": "’", "“": "”"}
        close_q = close_map[open_q]
        chars: List[str] = []
        closed = False

        while self.pos < self.length:
            ch = self._peek()
            if ch == "\n":
                break
            if ch == "\\" and self._peek(1) in (close_q, "\\", "n", "t"):
                self._advance()
                esc = self._advance()
                chars.append({"n": "\n", "t": "\t"}.get(esc, esc))
                continue
            if ch == close_q:
                self._advance()
                # Escape Pascal '' dentro '...'
                if open_q == "'" and self._peek() == "'":
                    self._advance()
                    chars.append("'")
                    continue
                closed = True
                break
            # Gestione chiusura ASCII su apertura smart-quote
            if open_q == "‘" and ch == "'":
                self._advance()
                closed = True
                break
            if open_q == "“" and ch == '"':
                self._advance()
                closed = True
                break
            chars.append(self._advance())

        if not closed:
            self.diagnostics.error(
                "LEX004",
                "Costante alfanumerica (stringa) non terminata sulla riga.",
                self._span(sl, sc),
            )

        val = "".join(chars)
        canonical = open_q == "'"
        if open_q == '"':
            # I doppi apici sono comuni ma le slide Murli/Laccetti definiscono gli apici singoli come canonici
            pass
        return Token(TokenType.STRING_LIT, f"{open_q}{val}{close_q}", val, self._span(sl, sc), canonical=canonical)

    def _lex_number(self) -> Token:
        sl, sc = self.line, self.col
        start = self.pos
        is_real = False

        while self.pos < self.length and self._peek().isdigit():
            self._advance()

        # Controlla se c'è un punto decimale (MA NON '..' né '.AND.' / '.OR.' / '.NOT.' / '.TRUE.' / '.FALSE.')
        if self._peek() == "." and self._peek(1) != "." and self._peek_dotted_keyword() is None:
            is_real = True
            self._advance()  # consuma '.'
            while self.pos < self.length and self._peek().isdigit():
                self._advance()

        # Notazione esponenziale es. 95.6e4, 4.e-3, 1e5
        if self._peek() in ("e", "E"):
            nxt = self._peek(1)
            nxt2 = self._peek(2)
            if nxt.isdigit() or (nxt in ("+", "-", "–", "−") and nxt2.isdigit()):
                is_real = True
                self._advance()
                if self._peek() in ("+", "-", "–", "−"):
                    self._advance()
                while self.pos < self.length and self._peek().isdigit():
                    self._advance()

        lexeme = self.source[start:self.pos]
        norm = lexeme.replace("–", "-").replace("−", "-")
        if is_real:
            return Token(TokenType.REAL_LIT, lexeme, float(norm), self._span(sl, sc))
        return Token(TokenType.INT_LIT, lexeme, int(norm), self._span(sl, sc))

    def _lex_ident_or_keyword(self) -> Token:
        sl, sc = self.line, self.col
        start = self.pos

        while self.pos < self.length and (self._peek().isalnum() or self._peek() == "_"):
            self._advance()

        lexeme = self.source[start:self.pos]
        lower = lexeme.lower()

        # Caso speciale: `in/out` (modalità parametro P-Like!)
        if lower == "in" and self._peek() == "/" and self.source[self.pos + 1:self.pos + 4].lower() == "out":
            after = self.source[self.pos + 4:self.pos + 5]
            if not (after.isalnum() or after == "_"):
                for _ in range(4):
                    self._advance()
                full = self.source[start:self.pos]
                return Token(TokenType.INOUT, full, "in/out", self._span(sl, sc))

        # Typo noti nelle slide / compiti d'esame (es. `enwhile` in slide 228!)
        if lower in RECOVERABLE_TYPOS:
            tt = RECOVERABLE_TYPOS[lower]
            self.diagnostics.recoverable(
                "LEX005",
                f"Errore di battitura nella parola chiave '{lexeme}' (intendevi '{tt.name.lower()}'?).",
                self._span(sl, sc),
                hint=f"Correggi '{lexeme}' in '{tt.name.lower()}'.",
            )
            return Token(tt, lexeme, tt.name.lower(), self._span(sl, sc), canonical=False)

        if lower in KEYWORDS:
            tt = KEYWORDS[lower]
            canonical = True
            val: object = lower
            if tt == TokenType.BOOL_LIT:
                val = lower == "true"
                canonical = False  # Canonico in Laccetti è .TRUE. / .FALSE.
            elif tt in (TokenType.AND, TokenType.OR, TokenType.NOT):
                canonical = False  # Canonico in Laccetti è .AND. / .OR. / .NOT.
            elif tt == TokenType.NULL_LIT:
                val = None
            return Token(tt, lexeme, val, self._span(sl, sc), canonical=canonical)

        return Token(TokenType.IDENT, lexeme, lexeme, self._span(sl, sc))
