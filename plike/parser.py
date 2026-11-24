"""Parser a discesa ricorsiva per il linguaggio P-Like (Prof. Giuliano Laccetti).

Supporta sia la sintassi canonica delle slide Laccetti/Murli sia il recupero
degli errori tipici da compito scritto d'esame (marcati come RECOVERABLE o PEDANTIC
così che la Variabile Napoli possa perdonarli o bocciarli!).
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .ast_nodes import (
    AllocateExpr,
    ArrayBound,
    ArrayType,
    AssignStmt,
    BinaryExpr,
    BoolLiteral,
    CallArg,
    CallOrIndexExpr,
    CallStmt,
    DeallocateStmt,
    Expr,
    FieldAccessExpr,
    ForStmt,
    IfBranch,
    IfStmt,
    IndexExpr,
    InlineVarStmt,
    IntLiteral,
    MainProgram,
    NamedType,
    NullLiteral,
    ParamDecl,
    PointerType,
    PrimitiveType,
    PrintStmt,
    Program,
    ReadStmt,
    RealLiteral,
    RecordField,
    RecordType,
    RepeatStmt,
    ReturnStmt,
    Stmt,
    StringLiteral,
    SubprogramDecl,
    SubprogramForwardDecl,
    TypeDecl,
    TypeSpec,
    UnaryExpr,
    VarDecl,
    VarExpr,
    VarItem,
    WhileStmt,
)
from .diagnostics import DiagnosticBag, SourceSpan
from .tokens import Token, TokenType

PRIMITIVE_TOKENS = {
    TokenType.INTEGER: "integer",
    TokenType.REAL: "real",
    TokenType.CHARACTER: "character",
    TokenType.LOGICAL: "logical",
}

BLOCK_END_TOKENS = {
    TokenType.END,
    TokenType.ENDIF,
    TokenType.ELSE,
    TokenType.ELSEIF,
    TokenType.ENDFOR,
    TokenType.ENDWHILE,
    TokenType.UNTIL,
    TokenType.ENDPROCEDURE,
    TokenType.ENDFUNCTION,
    TokenType.EOF,
}

STMT_START_KEYWORDS = {
    TokenType.IF,
    TokenType.FOR,
    TokenType.WHILE,
    TokenType.REPEAT,
    TokenType.READ,
    TokenType.PRINT,
    TokenType.RETURN,
    TokenType.DEALLOCATE,
    TokenType.ALLOCATE,
    TokenType.VAR,
    TokenType.TYPE,
}


class Parser:
    def __init__(self, tokens: List[Token], diagnostics: DiagnosticBag | None = None):
        self.tokens = tokens
        self.diagnostics = diagnostics if diagnostics is not None else DiagnosticBag()
        self.pos = 0

    # ------------------------------------------------------------------
    # Utility sui token
    # ------------------------------------------------------------------

    def _peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        if idx >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[idx]

    def _peek_non_nl(self, start_offset: int = 0) -> Token:
        i = self.pos + start_offset
        while i < len(self.tokens) and self.tokens[i].type == TokenType.NEWLINE:
            i += 1
        if i >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[i]

    def _at_eof(self) -> bool:
        return self._peek().type == TokenType.EOF

    def _advance(self) -> Token:
        tok = self._peek()
        if tok.type != TokenType.EOF:
            self.pos += 1
        return tok

    def _check(self, *types: TokenType) -> bool:
        return self._peek().type in types

    def _match(self, *types: TokenType) -> Optional[Token]:
        if self._peek().type in types:
            return self._advance()
        return None

    def _skip_newlines(self) -> None:
        while self._check(TokenType.NEWLINE, TokenType.SEMICOLON):
            self._advance()

    def _skip_only_newlines(self) -> None:
        while self._check(TokenType.NEWLINE):
            self._advance()

    def _expect(self, tt: TokenType, code: str, msg: str, recoverable: bool = False) -> Optional[Token]:
        if self._check(tt):
            return self._advance()
        tok = self._peek()
        if recoverable:
            self.diagnostics.recoverable(code, f"{msg} (trovato {tok.lexeme!r})", tok.span)
        else:
            self.diagnostics.error(code, f"{msg} (trovato {tok.lexeme!r})", tok.span)
        return None

    def _is_end_keyword_pair(self, second: TokenType) -> bool:
        """Controlla forme a due parole come `end if`, `end for`, `end while`, `end procedure`, `end function`, `end record`."""
        return (
            self._peek(0).type == TokenType.END
            and self._peek(1).type == second
            and self._peek(0).span.line == self._peek(1).span.line
        )

    def _is_return_type_function_header(self) -> bool:
        """Riconosce `<tipo> function <nome>...` es. `logical function seq(...)` o `list_pointer function costr(...)`."""
        t0 = self._peek(0)
        t1 = self._peek(1)
        if t1.type == TokenType.FUNCTION and (t0.type in PRIMITIVE_TOKENS or t0.type == TokenType.IDENT):
            return True
        if t0.type in (TokenType.STAR, TokenType.CARET) and t1.type == TokenType.IDENT and self._peek(2).type == TokenType.FUNCTION:
            return True
        return False

    def _is_chiamante_label(self) -> bool:
        """Riconosce l'etichetta opzionale `Chiamante:` o `Main:` usata nei file d'esame."""
        t0 = self._peek(0)
        t1 = self._peek(1)
        return (
            t0.type == TokenType.IDENT
            and t0.lexeme.lower() in ("chiamante", "main", "programma")
            and t1.type == TokenType.COLON
        )

    # ------------------------------------------------------------------
    # Entry point: Program
    # ------------------------------------------------------------------

    def parse(self) -> Program:
        start_span = self._peek().span
        type_decls: List[TypeDecl] = []
        subprograms: List[SubprogramDecl] = []
        pre_main_vars: List[VarDecl] = []
        pre_main_forwards: List[SubprogramForwardDecl] = []
        main_prog: Optional[MainProgram] = None

        self._skip_newlines()
        while not self._at_eof():
            self._skip_newlines()
            if self._at_eof():
                break

            if self._is_chiamante_label():
                self._advance()
                self._advance()
                self._skip_newlines()
                continue

            if self._check(TokenType.TYPE):
                type_decls.extend(self._parse_type_block())
                continue

            if self._check(TokenType.PROCEDURE):
                subprograms.append(self._parse_subprogram())
                continue

            if self._check(TokenType.FUNCTION) or self._is_return_type_function_header():
                # Distingui tra definizione e dichiarazione prototipo (es. `logical function f(..)`)
                if self._is_prototype_only():
                    pre_main_forwards.append(self._parse_bare_prototype())
                else:
                    subprograms.append(self._parse_subprogram())
                continue

            if self._check(TokenType.VAR):
                v_or_f = self._parse_var_decl_or_forward()
                if isinstance(v_or_f, VarDecl):
                    pre_main_vars.append(v_or_f)
                elif isinstance(v_or_f, SubprogramForwardDecl):
                    pre_main_forwards.append(v_or_f)
                continue

            if self._check(TokenType.BEGIN):
                if main_prog is not None:
                    self.diagnostics.error(
                        "PAR001",
                        "Trovato un secondo blocco 'begin' principale nello stesso file.",
                        self._peek().span,
                    )
                main_prog = self._parse_main_program(pre_main_vars, pre_main_forwards)
                pre_main_vars = []
                pre_main_forwards = []
                continue

            # Istruzioni top-level senza 'begin' (modalità script/estratto slide!)
            tok = self._peek()
            if tok.type in STMT_START_KEYWORDS or tok.type == TokenType.IDENT:
                self.diagnostics.recoverable(
                    "PAR002",
                    "Istruzioni principali fuori da un blocco 'begin ... end'.",
                    tok.span,
                    hint="Racchiudi il programma principale tra 'begin <nome>' e 'end <nome>'.",
                )
                body = self._parse_stmt_list(stop_at_top_decls=True)
                if main_prog is None:
                    main_prog = MainProgram(
                        span=tok.span,
                        name=None,
                        var_decls=pre_main_vars,
                        forward_decls=pre_main_forwards,
                        body=body,
                    )
                    pre_main_vars = []
                    pre_main_forwards = []
                else:
                    main_prog.body.extend(body)
                continue

            # Token inatteso a top-level
            self.diagnostics.fatal(
                "PAR003",
                f"Token inatteso a livello principale: {tok.lexeme!r}.",
                tok.span,
            )
            self._advance()

        # Se c'erano solo var globali senza begin
        if main_prog is None and (pre_main_vars or pre_main_forwards):
            main_prog = MainProgram(
                span=start_span,
                name=None,
                var_decls=pre_main_vars,
                forward_decls=pre_main_forwards,
                body=[],
            )

        return Program(
            span=start_span,
            type_decls=type_decls,
            subprograms=subprograms,
            main=main_prog,
        )

    def _is_prototype_only(self) -> bool:
        """Riconosce prototipi tipo `logical function sequential_search (..)` prima di `begin`."""
        save = self.pos
        try:
            if self._peek().type in (TokenType.STAR, TokenType.CARET):
                self._advance()
            if self._peek().type != TokenType.FUNCTION:
                self._advance()
            if not self._check(TokenType.FUNCTION):
                return False
            self._advance()
            if not self._check(TokenType.IDENT):
                return False
            self._advance()
            if self._check(TokenType.LPAREN):
                self._advance()
                if self._check(TokenType.DOTDOT):
                    return True
            return False
        finally:
            self.pos = save

    def _parse_bare_prototype(self) -> SubprogramForwardDecl:
        span = self._peek().span
        ret_type: Optional[TypeSpec] = None
        if not self._check(TokenType.FUNCTION):
            ret_type = self._parse_type_spec()
        self._expect(TokenType.FUNCTION, "PAR004", "Atteso 'function' nel prototipo")
        name_tok = self._expect(TokenType.IDENT, "PAR005", "Atteso nome funzione nel prototipo")
        if self._match(TokenType.LPAREN):
            depth = 1
            while not self._at_eof() and depth > 0:
                if self._check(TokenType.LPAREN):
                    depth += 1
                elif self._check(TokenType.RPAREN):
                    depth -= 1
                self._advance()
        if self._match(TokenType.COLON):
            ret_type = self._parse_type_spec()
        return SubprogramForwardDecl(
            span=span,
            names=[name_tok.lexeme] if name_tok else [],
            kind="function",
            return_type=ret_type,
        )

    # ------------------------------------------------------------------
    # Dichiarazioni `type` e `record`
    # ------------------------------------------------------------------

    def _parse_type_block(self) -> List[TypeDecl]:
        """Supporta sia singolo `type T: record ... end` sia il blocco Laccetti:
        type list_pointer : *nodo_lista
             nodo_lista : record
                 info : integer
                 link : list_pointer
             end
        """
        self._expect(TokenType.TYPE, "PAR010", "Atteso 'type'")
        decls: List[TypeDecl] = []

        while True:
            self._skip_newlines()
            if not self._check(TokenType.IDENT):
                break
            # Se siamo dopo la prima dichiarazione, verifica che sia `ident : ...` o `ident = ...`
            if decls and self._peek(1).type not in (TokenType.COLON, TokenType.EQ):
                break
            span = self._peek().span
            name_tok = self._advance()
            if not self._match(TokenType.COLON, TokenType.EQ):
                self.diagnostics.error(
                    "PAR011",
                    f"Atteso ':' o '=' dopo il nome del tipo '{name_tok.lexeme}'.",
                    self._peek().span,
                )
                break
            tspec = self._parse_type_spec()
            decls.append(TypeDecl(span=span, name=name_tok.lexeme, type_spec=tspec))
            self._skip_newlines()
            # Continua nel blocco type solo se la prossima riga è un altro `<ident> : record|*...`
            if not (
                self._check(TokenType.IDENT)
                and self._peek(1).type in (TokenType.COLON, TokenType.EQ)
                and self._peek(2).type in (TokenType.RECORD, TokenType.STAR, TokenType.CARET, TokenType.ARRAY, *PRIMITIVE_TOKENS)
            ):
                break

        return decls

    def _parse_type_spec(self) -> TypeSpec:
        tok = self._peek()
        span = tok.span

        # Puntatore: `*nodo_lista` o `^Nodo`
        if self._match(TokenType.STAR, TokenType.CARET):
            target = self._expect(TokenType.IDENT, "PAR012", "Atteso nome del tipo puntato dopo '*'/'^'")
            return PointerType(span=span, target_name=target.lexeme if target else "unknown")

        # Record inline o dentro `type`
        if self._match(TokenType.RECORD):
            fields: List[RecordField] = []
            self._skip_newlines()
            while not self._at_eof():
                if self._check(TokenType.ENDRECORD):
                    self._advance()
                    break
                if self._is_end_keyword_pair(TokenType.RECORD):
                    self._advance()
                    self._advance()
                    break
                if self._check(TokenType.END):
                    self._advance()
                    break
                # `campo1, campo2 : tipo`
                f_span = self._peek().span
                f_names: List[Token] = []
                if not self._check(TokenType.IDENT):
                    self.diagnostics.error(
                        "PAR013",
                        f"Atteso nome del campo nel record (trovato {self._peek().lexeme!r}).",
                        self._peek().span,
                    )
                    self._advance()
                    self._skip_newlines()
                    continue
                f_names.append(self._advance())
                while self._match(TokenType.COMMA):
                    if self._check(TokenType.IDENT):
                        f_names.append(self._advance())
                self._expect(TokenType.COLON, "PAR014", "Atteso ':' dopo il nome del campo nel record", recoverable=True)
                f_type = self._parse_type_spec()
                for fn in f_names:
                    fields.append(RecordField(name=fn.lexeme, type_spec=f_type, span=f_span))
                self._skip_newlines()
            return RecordType(span=span, fields=fields)

        # Array: `array [1..n] of real`, `array (1..2) of integer`, `array of integer`
        if self._match(TokenType.ARRAY):
            bounds: List[ArrayBound] = []
            if self._check(TokenType.LBRACKET, TokenType.LPAREN):
                bounds = self._parse_array_bounds()
            self._expect(TokenType.OF, "PAR015", "Atteso 'of' nella dichiarazione di array", recoverable=True)
            elem_type = self._parse_type_spec()
            return ArrayType(span=span, bounds=bounds, element_type=elem_type)

        # Tipi primitivi
        if tok.type in PRIMITIVE_TOKENS:
            self._advance()
            return PrimitiveType(span=span, name=PRIMITIVE_TOKENS[tok.type])

        # Tipo nominato (record definito dall'utente o list_pointer/stack_pointer/queue_pointer)
        if tok.type == TokenType.IDENT:
            self._advance()
            return NamedType(span=span, name=tok.lexeme)

        self.diagnostics.error("PAR016", f"Tipo non valido: {tok.lexeme!r}.", span)
        return PrimitiveType(span=span, name="integer")

    def _parse_array_bounds(self) -> List[ArrayBound]:
        open_tok = self._advance()  # '[' o '('
        close_tt = TokenType.RBRACKET if open_tok.type == TokenType.LBRACKET else TokenType.RPAREN
        bounds: List[ArrayBound] = []

        if not self._check(close_tt):
            while True:
                b_span = self._peek().span
                first = self._parse_expr()
                if self._match(TokenType.DOTDOT):
                    high = self._parse_expr()
                    bounds.append(ArrayBound(low=first, high=high, span=b_span))
                else:
                    bounds.append(ArrayBound(low=None, high=first, span=b_span))
                if not self._match(TokenType.COMMA):
                    break

        self._expect(close_tt, "PAR017", f"Attesa parentesi di chiusura dell'intervallo array", recoverable=True)
        return bounds

    # ------------------------------------------------------------------
    # Dichiarazioni `var`
    # ------------------------------------------------------------------

    def _parse_var_decl_or_forward(self) -> Optional[VarDecl | SubprogramForwardDecl]:
        """Supporta tutte le forme Laccetti/Murli:
        - `var: R, C: real`
        - `var i, j, n : integer`
        - `var: A[1..n]: array of integer`
        - `var: A[m, n], B[m, n]: array of integer`
        - `var: A(1..n): array of integer`
        - `var A : array [1..n] of real`
        - `var: Max_weight := 0, Flag := 0: integer`
        - `var: sequential_search(n, A, x): logical function`
        - `var: del_testa, del_mezzo: procedure`
        """
        span = self._advance().span  # consuma `var`
        self._match(TokenType.COLON)  # `:` dopo `var` è opzionale (Murli lo mette, Laccetti spesso no!)

        items: List[VarItem] = []
        looks_like_forward_sig = False

        while True:
            if not self._check(TokenType.IDENT):
                break
            item_tok = self._advance()
            inline_bounds: Optional[List[ArrayBound]] = None
            init_expr: Optional[Expr] = None

            # Controlla `nome[...]` o `nome(...)`
            if self._check(TokenType.LBRACKET):
                inline_bounds = self._parse_array_bounds()
            elif self._check(TokenType.LPAREN):
                # Può essere `A(1..n)` OPPURE forward declaration `seq_search(n, A, x): logical function` o `seq_search(..)`
                save = self.pos
                self._advance()  # '('
                if self._check(TokenType.DOTDOT):
                    looks_like_forward_sig = True
                    while not self._at_eof() and not self._check(TokenType.RPAREN):
                        self._advance()
                    self._match(TokenType.RPAREN)
                else:
                    # Guarda avanti dopo ')' se segue `: <tipo> function` o `: procedure`
                    depth = 1
                    while not self._at_eof() and depth > 0:
                        if self._check(TokenType.LPAREN):
                            depth += 1
                        elif self._check(TokenType.RPAREN):
                            depth -= 1
                        self._advance()
                    after_close = self.pos
                    if self._check(TokenType.COLON):
                        t1 = self._peek(1).type
                        t2 = self._peek(2).type
                        if t1 == TokenType.PROCEDURE or t2 == TokenType.FUNCTION or t1 == TokenType.FUNCTION:
                            looks_like_forward_sig = True
                    if not looks_like_forward_sig:
                        self.pos = save
                        inline_bounds = self._parse_array_bounds()
                    else:
                        self.pos = after_close

            # Inizializzazione inline opzionale: `Max_weight := 0`
            if self._match(TokenType.ASSIGN):
                init_expr = self._parse_expr()
                self.diagnostics.pedantic(
                    "PED004",
                    f"Inizializzazione inline nella dichiarazione 'var' per '{item_tok.lexeme}'.",
                    item_tok.span,
                    hint="Nel P-Like canonico le variabili si dichiarano in 'var' e si inizializzano dopo 'begin'.",
                )

            items.append(VarItem(name=item_tok.lexeme, inline_bounds=inline_bounds, init_expr=init_expr, span=item_tok.span))

            if self._match(TokenType.COMMA):
                # Tollera virgola finale accidentale come nelle slide di Laccetti: `var i, j, n, : integer`!
                if self._check(TokenType.COLON):
                    self.diagnostics.pedantic(
                        "PED005",
                        "Virgola superflua prima di ':' nella dichiarazione 'var'.",
                        self._peek().span,
                    )
                    break
                continue
            break

        if not items:
            self.diagnostics.error("PAR018", "Dichiarazione 'var' senza nomi di variabili.", span)
            return None

        # `:` prima del tipo (recuperabile se dimenticato come `var: C[M,N] array of integer`)
        if not self._match(TokenType.COLON):
            self.diagnostics.recoverable(
                "PAR019",
                f"Manca ':' prima del tipo nella dichiarazione di '{items[-1].name}'.",
                self._peek().span,
                hint="Scrivi `var: nome: tipo`.",
            )

        # Forward declaration: `... : procedure` o `... : <tipo> function`
        if self._check(TokenType.PROCEDURE):
            self._advance()
            return SubprogramForwardDecl(span=span, names=[it.name for it in items], kind="procedure")

        if self._check(TokenType.FUNCTION):
            self._advance()
            return SubprogramForwardDecl(span=span, names=[it.name for it in items], kind="function")

        if looks_like_forward_sig or (
            self._peek().type in (*PRIMITIVE_TOKENS, TokenType.IDENT)
            and self._peek(1).type == TokenType.FUNCTION
        ):
            ret_type = self._parse_type_spec()
            if self._match(TokenType.FUNCTION):
                return SubprogramForwardDecl(
                    span=span,
                    names=[it.name for it in items],
                    kind="function",
                    return_type=ret_type,
                )
            # Altrimenti è un normale tipo
            tspec = ret_type
        else:
            tspec = self._parse_type_spec()

        # Se `var: A[m, n]: array of integer`, trasferisci i bounds inline sull'ArrayType
        # (se tutti gli items hanno inline_bounds e tspec è ArrayType senza bounds, li teniamo su ogni item!)
        self._match(TokenType.SEMICOLON)
        return VarDecl(span=span, items=items, type_spec=tspec)

    # ------------------------------------------------------------------
    # Procedure & Function
    # ------------------------------------------------------------------

    def _parse_subprogram(self) -> SubprogramDecl:
        span = self._peek().span
        prefix_return_type: Optional[TypeSpec] = None

        if self._check(TokenType.PROCEDURE):
            kind = "procedure"
            self._advance()
        elif self._check(TokenType.FUNCTION):
            kind = "function"
            self._advance()
        else:
            # Forma `<tipo> function <nome>(...)`
            prefix_return_type = self._parse_type_spec()
            self._expect(TokenType.FUNCTION, "PAR020", "Atteso 'function'")
            kind = "function"

        name_tok = self._expect(TokenType.IDENT, "PAR021", f"Atteso nome della {kind}")
        name = name_tok.lexeme if name_tok else "<anon>"

        params: List[ParamDecl] = []
        if self._match(TokenType.LPAREN):
            params = self._parse_param_list()
            self._expect(TokenType.RPAREN, "PAR022", f"Attesa ')' dopo i parametri di '{name}'", recoverable=True)

        return_type = prefix_return_type
        # Permetti `: <tipo>` anche sulla riga successiva (vedi slide 22 `Ricorsione`)
        save = self.pos
        self._skip_only_newlines()
        if kind == "function" and self._match(TokenType.COLON):
            return_type = self._parse_type_spec()
        else:
            self.pos = save

        if kind == "function" and return_type is None:
            self.diagnostics.recoverable(
                "PAR023",
                f"La function '{name}' non specifica il tipo di ritorno.",
                span,
                hint=f"Usa `function {name}(...): integer` oppure `integer function {name}(...)`.",
            )

        type_decls: List[TypeDecl] = []
        var_decls: List[VarDecl] = []
        forward_decls: List[SubprogramForwardDecl] = []

        self._skip_newlines()
        while self._check(TokenType.TYPE, TokenType.VAR):
            if self._check(TokenType.TYPE):
                type_decls.extend(self._parse_type_block())
            else:
                vf = self._parse_var_decl_or_forward()
                if isinstance(vf, VarDecl):
                    var_decls.append(vf)
                elif isinstance(vf, SubprogramForwardDecl):
                    forward_decls.append(vf)
            self._skip_newlines()

        # `begin` opzionale (in Laccetti c'è quasi sempre, ma alcune slide/studenti lo omettono!)
        if self._match(TokenType.BEGIN):
            # In caso di `begin <nome>` opzionale
            if self._check(TokenType.IDENT) and self._peek().lexeme.lower() == name.lower():
                self._advance()
        else:
            self.diagnostics.recoverable(
                "PAR024",
                f"Manca 'begin' all'inizio del corpo di {kind} '{name}'.",
                self._peek().span,
                hint="Nel P-Like canonico il corpo di procedure e function inizia con 'begin'.",
            )

        body = self._parse_stmt_list(stop_at_subprogram_end=True)

        end_name = self._consume_subprogram_end(kind, name, span)

        return SubprogramDecl(
            span=span,
            kind=kind,
            name=name,
            params=params,
            return_type=return_type,
            type_decls=type_decls,
            var_decls=var_decls,
            forward_decls=forward_decls,
            body=body,
            end_name=end_name,
        )

    def _parse_param_list(self) -> List[ParamDecl]:
        """Supporta tutte le convenzioni di parametri:
        - `(in: a, b; out: c; in/out: d)`
        - `(in: A, B, n, m out: C)` (senza `;`!)
        - `(in x, y; out: z)` (senza `:` dopo `in`!)
        - `(a, b, c)` (senza modalità -> default by-ref!)
        - `(var head: ^Nodo, valore: integer)` (stile Pascal tipizzato!)
        - `(input: head: list_pointer, peso: integer)`
        """
        params: List[ParamDecl] = []
        current_mode = "default"

        while not self._at_eof() and not self._check(TokenType.RPAREN):
            self._skip_only_newlines()
            if self._check(TokenType.RPAREN):
                break

            # Cambio modalità: `in:`, `out:`, `in/out:`, `var`
            if self._check(TokenType.IN, TokenType.OUT, TokenType.INOUT):
                mtok = self._advance()
                if mtok.type == TokenType.IN:
                    current_mode = "in"
                elif mtok.type == TokenType.OUT:
                    current_mode = "out"
                else:
                    current_mode = "in/out"
                self._match(TokenType.COLON)
                continue

            if self._match(TokenType.VAR):
                current_mode = "in/out"
                continue

            # Ignora separatori `;` o `,`
            if self._match(TokenType.SEMICOLON, TokenType.COMMA):
                continue

            if self._check(TokenType.IDENT):
                # Typo comune nei file esame: `ou:` invece di `out:`
                if self._peek().lexeme.lower() == "ou" and self._peek(1).type == TokenType.COLON:
                    self.diagnostics.recoverable(
                        "PAR025",
                        "Modalità parametro 'ou:' scritta male (intendevi 'out:'?).",
                        self._peek().span,
                    )
                    self._advance()
                    self._advance()
                    current_mode = "out"
                    continue

                ptok = self._advance()
                ptype: Optional[TypeSpec] = None
                if self._match(TokenType.COLON):
                    ptype = self._parse_type_spec()
                params.append(ParamDecl(name=ptok.lexeme, mode=current_mode, type_spec=ptype, span=ptok.span))
                self._match(TokenType.COMMA)
                continue

            # Elisione o token strano dentro param list
            self.diagnostics.error("PAR026", f"Token inatteso nella lista parametri: {self._peek().lexeme!r}.", self._peek().span)
            self._advance()

        return params

    def _consume_subprogram_end(self, kind: str, name: str, start_span: SourceSpan) -> Optional[str]:
        end_name: Optional[str] = None
        expected_kw = TokenType.PROCEDURE if kind == "procedure" else TokenType.FUNCTION
        expected_single = TokenType.ENDPROCEDURE if kind == "procedure" else TokenType.ENDFUNCTION

        if self._check(expected_single):
            self._advance()
            end_name = kind
            return end_name

        if self._check(TokenType.END):
            end_tok = self._advance()
            if self._check(expected_kw) and self._peek().span.line == end_tok.span.line:
                self._advance()
                end_name = kind
            elif self._check(TokenType.IDENT) and self._peek().span.line == end_tok.span.line:
                end_name = self._advance().lexeme
            else:
                # Controlla il doppio `end` tipico di Laccetti:
                #   end
                #   end selection_sort   (oppure `end procedure` / `end function`)
                save = self.pos
                self._skip_newlines()
                if self._check(expected_single):
                    self._advance()
                    end_name = kind
                elif self._check(TokenType.END):
                    e2 = self._advance()
                    if self._check(expected_kw) and self._peek().span.line == e2.span.line:
                        self._advance()
                        end_name = kind
                    elif (
                        self._check(TokenType.IDENT)
                        and self._peek().span.line == e2.span.line
                        and self._peek().lexeme.lower() == name.lower()
                    ):
                        end_name = self._advance().lexeme
                    else:
                        self.pos = save
                else:
                    self.pos = save
            return end_name

        self.diagnostics.recoverable(
            "PAR027",
            f"Manca 'end' di chiusura per {kind} '{name}'.",
            self._peek().span,
            hint=f"Termina {kind} '{name}' con `end` o `end {name}`.",
        )
        return end_name

    # ------------------------------------------------------------------
    # Programma principale (`begin [nome] ... end [nome]`)
    # ------------------------------------------------------------------

    def _parse_main_program(
        self,
        pre_vars: List[VarDecl],
        pre_forwards: List[SubprogramForwardDecl],
    ) -> MainProgram:
        begin_tok = self._advance()  # `begin`
        prog_name: Optional[str] = None

        # Nome programma sulla stessa riga di `begin`, solo se NON è l'inizio di un'istruzione
        # (es. `begin circonf` sì, `begin var: ...` o `begin a := 1` no!)
        if (
            self._check(TokenType.IDENT)
            and self._peek().span.line == begin_tok.span.line
            and self._peek(1).type in (TokenType.NEWLINE, TokenType.EOF)
        ):
            prog_name = self._advance().lexeme

        type_decls: List[TypeDecl] = []
        var_decls: List[VarDecl] = list(pre_vars)
        forward_decls: List[SubprogramForwardDecl] = list(pre_forwards)

        self._skip_newlines()
        while self._check(TokenType.TYPE, TokenType.VAR):
            if self._check(TokenType.TYPE):
                type_decls.extend(self._parse_type_block())
            else:
                vf = self._parse_var_decl_or_forward()
                if isinstance(vf, VarDecl):
                    var_decls.append(vf)
                elif isinstance(vf, SubprogramForwardDecl):
                    forward_decls.append(vf)
            self._skip_newlines()

        body = self._parse_stmt_list(stop_at_main_end=True)

        end_name: Optional[str] = None
        if self._check(TokenType.END):
            end_tok = self._advance()
            if self._check(TokenType.IDENT) and self._peek().span.line == end_tok.span.line:
                end_name = self._advance().lexeme
                if prog_name and end_name.lower() != prog_name.lower():
                    self.diagnostics.recoverable(
                        "PAR028",
                        f"Il nome dopo 'end' ('{end_name}') non coincide con 'begin {prog_name}'.",
                        end_tok.span,
                        hint=f"Usa 'end {prog_name}'.",
                    )
            elif prog_name:
                self.diagnostics.pedantic(
                    "PED006",
                    f"Chiusura 'end' senza il nome del programma '{prog_name}'.",
                    end_tok.span,
                    hint=f"In P-Like canonico si chiude con 'end {prog_name}'.",
                )
        else:
            self.diagnostics.recoverable(
                "PAR029",
                "Manca 'end' di chiusura del programma principale.",
                self._peek().span,
                hint="Aggiungi 'end' alla fine del programma.",
            )

        return MainProgram(
            span=begin_tok.span,
            name=prog_name,
            type_decls=type_decls,
            var_decls=var_decls,
            forward_decls=forward_decls,
            body=body,
            end_name=end_name,
        )

    # ------------------------------------------------------------------
    # Istruzioni (Statements)
    # ------------------------------------------------------------------

    def _parse_stmt_list(
        self,
        stop_tokens: Tuple[TokenType, ...] = (),
        stop_at_subprogram_end: bool = False,
        stop_at_main_end: bool = False,
        stop_at_top_decls: bool = False,
    ) -> List[Stmt]:
        stmts: List[Stmt] = []
        while True:
            self._skip_newlines()
            tok = self._peek()
            if tok.type == TokenType.EOF:
                break
            if tok.type in stop_tokens:
                break
            if tok.type == TokenType.END:
                # Controlla se è `end if`, `end for`, `end while` che appartiene al blocco esterno
                if TokenType.ENDIF in stop_tokens and self._is_end_keyword_pair(TokenType.IF):
                    break
                if TokenType.ENDFOR in stop_tokens and self._is_end_keyword_pair(TokenType.FOR):
                    break
                if TokenType.ENDWHILE in stop_tokens and self._is_end_keyword_pair(TokenType.WHILE):
                    break
                if stop_at_subprogram_end or stop_at_main_end:
                    break
                # `end` imprevisto dentro un blocco interno -> probabilmente manca endif/endfor/endwhile!
                break
            if stop_at_subprogram_end and tok.type in (TokenType.ENDPROCEDURE, TokenType.ENDFUNCTION):
                break
            if (stop_at_subprogram_end or stop_at_top_decls) and (
                tok.type in (TokenType.PROCEDURE, TokenType.FUNCTION, TokenType.BEGIN)
                or self._is_return_type_function_header()
                or self._is_chiamante_label()
            ):
                break

            stmt = self._parse_stmt()
            if stmt is not None:
                stmts.append(stmt)
        return stmts

    def _parse_stmt(self) -> Optional[Stmt]:
        tok = self._peek()

        if tok.type == TokenType.IF:
            return self._parse_if()
        if tok.type == TokenType.FOR:
            return self._parse_for()
        if tok.type == TokenType.WHILE:
            return self._parse_while()
        if tok.type == TokenType.REPEAT:
            return self._parse_repeat()
        if tok.type == TokenType.READ:
            return self._parse_read()
        if tok.type == TokenType.PRINT:
            return self._parse_print()
        if tok.type == TokenType.RETURN:
            return self._parse_return()
        if tok.type == TokenType.DEALLOCATE:
            return self._parse_deallocate()
        if tok.type == TokenType.ALLOCATE:
            return self._parse_allocate_stmt()
        if tok.type == TokenType.VAR:
            vf = self._parse_var_decl_or_forward()
            if isinstance(vf, VarDecl):
                self.diagnostics.pedantic(
                    "PED007",
                    "Dichiarazione 'var' nel mezzo del corpo del programma.",
                    tok.span,
                    hint="In P-Like canonico tutte le variabili vanno dichiarate prima del corpo eseguibile.",
                )
                return InlineVarStmt(span=tok.span, decl=vf)
            return None

        # Pseudocodice stringa isolata nelle slide (es. "alloca head" in listaPeso.plike)
        if tok.type == TokenType.STRING_LIT:
            self._advance()
            self.diagnostics.pedantic(
                "PED008",
                f"Nota testuale isolata {tok.lexeme} ignorata come commento di pseudocodice.",
                tok.span,
                hint="Usa commenti (* ... *) o /* ... */ invece di stringhe isolate.",
            )
            return None

        if tok.type == TokenType.IDENT:
            return self._parse_assign_or_call()

        # Token non valido come inizio istruzione -> errore e avanza per evitare loop infinito
        self.diagnostics.fatal(
            "PAR030",
            f"Istruzione non valida a partire da {tok.lexeme!r}.",
            tok.span,
        )
        self._advance()
        return None

    def _parse_assign_or_call(self) -> Stmt:
        span = self._peek().span
        lhs = self._parse_lvalue_or_call()

        # Assegnazione canonica `:=`
        if self._match(TokenType.ASSIGN):
            val = self._parse_expr()
            # Permetti assegnazioni multiple separate da virgola sulla stessa riga (es. `i:=1, j:=i`)
            self._match(TokenType.COMMA)
            return AssignStmt(span=span, target=lhs, value=val, used_equals_sign=False)

        # Assegnazione con `=` (errore classico da esame scritto / vecchie slide Murli!)
        if self._match(TokenType.EQ):
            self.diagnostics.recoverable(
                "PAR031",
                "Usato '=' invece dell'operatore di assegnazione ':='.",
                span,
                hint="In P-Like l'assegnazione si scrive ':=' ('=' è riservato al confronto di uguaglianza).",
            )
            val = self._parse_expr()
            self._match(TokenType.COMMA)
            return AssignStmt(span=span, target=lhs, value=val, used_equals_sign=True)

        # Chiamata a procedura: `nome(arg1, arg2)`
        if isinstance(lhs, CallOrIndexExpr) and isinstance(lhs.target, VarExpr):
            return CallStmt(span=span, callee=lhs.target.name, args=lhs.args)

        # Chiamata a procedura senza parentesi? (raro ma possibile)
        if isinstance(lhs, VarExpr):
            self.diagnostics.error(
                "PAR032",
                f"Identificatore isolato '{lhs.name}' non seguito da ':=' o '(...)'.",
                span,
                hint="Se intendevi un'assegnazione usa `:=`, se una procedura aggiungi `()`.",
            )
            return CallStmt(span=span, callee=lhs.name, args=[])

        self.diagnostics.error("PAR033", "Atteso ':=' dopo l'espressione a sinistra.", self._peek().span)
        return AssignStmt(span=span, target=lhs, value=IntLiteral(span=span, value=0))

    def _parse_lvalue_or_call(self) -> Expr:
        """Parsa una catena `ident(.field | (args) | [indices])*`."""
        tok = self._advance()
        expr: Expr = VarExpr(span=tok.span, name=tok.lexeme)

        while True:
            if self._match(TokenType.DOT):
                field_tok = self._expect(TokenType.IDENT, "PAR034", "Atteso nome del campo dopo '.'")
                fname = field_tok.lexeme if field_tok else "<err>"
                expr = FieldAccessExpr(span=expr.span, target=expr, field_name=fname)
            elif self._check(TokenType.LBRACKET):
                self.diagnostics.pedantic(
                    "PED009",
                    "Indicizzazione array con parentesi quadre `[...]` invece delle canoniche tonde `(...)`.",
                    self._peek().span,
                    hint="Nelle slide P-Like di Laccetti gli elementi di un array si indicizzano con `A(i)` o `A(i, j)`.",
                )
                indices = self._parse_bracket_indices()
                expr = IndexExpr(span=expr.span, target=expr, indices=indices, bracket_style="square")
            elif self._check(TokenType.LPAREN) and self._peek().span.line == tok.span.line:
                args = self._parse_call_args()
                expr = CallOrIndexExpr(span=expr.span, target=expr, args=args)
            else:
                break
        return expr

    def _parse_bracket_indices(self) -> List[Expr]:
        self._expect(TokenType.LBRACKET, "PAR035", "Atteso '['")
        indices: List[Expr] = []
        if not self._check(TokenType.RBRACKET):
            indices.append(self._parse_expr())
            while self._match(TokenType.COMMA):
                indices.append(self._parse_expr())
        self._expect(TokenType.RBRACKET, "PAR036", "Atteso ']' dopo gli indici dell'array", recoverable=True)
        return indices

    def _parse_call_args(self) -> List[CallArg]:
        self._expect(TokenType.LPAREN, "PAR037", "Atteso '('")
        args: List[CallArg] = []
        mode_hint: Optional[str] = None
        if not self._check(TokenType.RPAREN):
            while not self._at_eof() and not self._check(TokenType.RPAREN):
                if self._check(TokenType.IN, TokenType.OUT, TokenType.INOUT):
                    mtok = self._advance()
                    mode_hint = "in" if mtok.type == TokenType.IN else ("out" if mtok.type == TokenType.OUT else "in/out")
                    self._match(TokenType.COLON)
                    continue
                if self._match(TokenType.SEMICOLON, TokenType.COMMA):
                    continue
                expr = self._parse_expr()
                args.append(CallArg(expr=expr, mode_hint=mode_hint))
                self._match(TokenType.COMMA)
        self._expect(TokenType.RPAREN, "PAR038", "Attesa ')' di chiusura degli argomenti", recoverable=True)
        return args

    # ------------------------------------------------------------------
    # If / ElseIf / Else / EndIf
    # ------------------------------------------------------------------

    def _parse_if(self) -> IfStmt:
        if_tok = self._advance()  # `if`
        cond = self._parse_expr()
        if not self._match(TokenType.THEN):
            self.diagnostics.recoverable(
                "PAR040",
                "Manca la parola chiave 'then' dopo la condizione dell'if.",
                self._peek().span,
                hint="Scrivi `if (condizione) then`.",
            )

        branches: List[IfBranch] = []
        else_body: List[Stmt] = []
        first_body = self._parse_stmt_list(stop_tokens=(TokenType.ELSEIF, TokenType.ELSE, TokenType.ENDIF))
        branches.append(IfBranch(condition=cond, body=first_body, span=if_tok.span))

        same_line_else_if_count = 0

        while True:
            if self._check(TokenType.ELSEIF):
                etok = self._advance()
                econd = self._parse_expr()
                if not self._match(TokenType.THEN):
                    self.diagnostics.recoverable(
                        "PAR041",
                        "Manca 'then' dopo 'elseif (condizione)'.",
                        self._peek().span,
                    )
                ebody = self._parse_stmt_list(stop_tokens=(TokenType.ELSEIF, TokenType.ELSE, TokenType.ENDIF))
                branches.append(IfBranch(condition=econd, body=ebody, span=etok.span))
                continue

            if self._check(TokenType.ELSE):
                else_tok = self._advance()
                # `else if (...)` sulla STESSA riga: gestiamo sia lo stile flat (1 endif) sia Laccetti nested (N+1 endif)
                if self._check(TokenType.IF) and self._peek().span.line == else_tok.span.line:
                    same_line_else_if_count += 1
                    self._advance()  # consuma `if`
                    econd = self._parse_expr()
                    if not self._match(TokenType.THEN):
                        self.diagnostics.recoverable(
                            "PAR042",
                            "Manca 'then' dopo 'else if (condizione)'.",
                            self._peek().span,
                        )
                    ebody = self._parse_stmt_list(stop_tokens=(TokenType.ELSEIF, TokenType.ELSE, TokenType.ENDIF))
                    branches.append(IfBranch(condition=econd, body=ebody, span=else_tok.span))
                    continue
                else:
                    else_body = self._parse_stmt_list(stop_tokens=(TokenType.ENDIF,))
                    break
            break

        # Consuma `endif` o `end if`
        self._consume_endif(if_tok.span)

        # Se c'erano `else if` sulla stessa riga, consuma eventuali `endif` extra (stile slide Laccetti `sorted` / `ricerca_binaria`)
        for _ in range(same_line_else_if_count):
            save = self.pos
            self._skip_newlines()
            if self._check(TokenType.ENDIF):
                self._advance()
            elif self._is_end_keyword_pair(TokenType.IF):
                self._advance()
                self._advance()
            else:
                self.pos = save
                break

        return IfStmt(span=if_tok.span, branches=branches, else_body=else_body)

    def _consume_endif(self, if_span: SourceSpan) -> None:
        if self._match(TokenType.ENDIF):
            return
        if self._is_end_keyword_pair(TokenType.IF):
            self._advance()
            self._advance()
            return
        self.diagnostics.recoverable(
            "PAR043",
            f"Manca 'endif' per chiudere l'if iniziato alla riga {if_span.line}.",
            self._peek().span,
            hint="Chiudi ogni blocco `if` con `endif`.",
        )

    # ------------------------------------------------------------------
    # For / While / Repeat
    # ------------------------------------------------------------------

    def _parse_for(self) -> ForStmt:
        for_tok = self._advance()  # `for`
        var_tok = self._expect(TokenType.IDENT, "PAR044", "Atteso nome della variabile indice dopo 'for'")
        var_name = var_tok.lexeme if var_tok else "_i"

        if self._match(TokenType.ASSIGN):
            pass
        elif self._match(TokenType.EQ):
            # In Murli (`for i = 1, N do`) era usato `=`, mentre Laccetti preferisce `:=`
            self.diagnostics.pedantic(
                "PED010",
                "Usato '=' nell'intestazione del ciclo 'for' invece di ':='.",
                self._peek().span,
                hint="Usa `for i := 1 to n do` secondo lo stile Laccetti.",
            )
        else:
            self.diagnostics.recoverable("PAR045", "Atteso ':=' nell'intestazione del ciclo 'for'.", self._peek().span)

        start_expr = self._parse_expr()
        downto = False
        if self._match(TokenType.TO):
            downto = False
        elif self._match(TokenType.DOWNTO):
            downto = True
        elif self._match(TokenType.COMMA):
            # Forma storica Murli: `for i = 1, N do`
            downto = False
            self.diagnostics.pedantic(
                "PED011",
                "Usata virgola nel ciclo 'for' (stile Murli) invece di 'to'.",
                self._peek().span,
                hint="Preferisci `for i := 1 to N do`.",
            )
        else:
            self.diagnostics.recoverable("PAR046", "Atteso 'to' nel ciclo 'for'.", self._peek().span)

        end_expr = self._parse_expr()
        step_expr: Optional[Expr] = None

        # Opzionale `, step s` oppure `step s`
        self._match(TokenType.COMMA)
        if self._match(TokenType.STEP):
            step_expr = self._parse_expr()

        if not self._match(TokenType.DO):
            self.diagnostics.recoverable(
                "PAR047",
                "Manca la parola chiave 'do' nell'intestazione del ciclo 'for'.",
                self._peek().span,
                hint="Scrivi `for i := 1 to n do`.",
            )
        # Tollera `do:` stile Python (visto in Yappetti/Array_Settimana.plike!)
        if self._match(TokenType.COLON):
            self.diagnostics.recoverable(
                "PAR048",
                "Due punti ':' superflui dopo 'do' (stile Python non valido in P-Like).",
                self._peek().span,
            )

        body = self._parse_stmt_list(stop_tokens=(TokenType.ENDFOR,))

        if self._match(TokenType.ENDFOR):
            pass
        elif self._is_end_keyword_pair(TokenType.FOR):
            self._advance()
            self._advance()
        else:
            self.diagnostics.recoverable(
                "PAR049",
                f"Manca 'endfor' per chiudere il ciclo 'for' iniziato alla riga {for_tok.span.line}.",
                self._peek().span,
            )

        return ForStmt(
            span=for_tok.span,
            var_name=var_name,
            start=start_expr,
            end=end_expr,
            step=step_expr,
            downto=downto,
            body=body,
        )

    def _parse_while(self) -> WhileStmt:
        w_tok = self._advance()  # `while`
        cond = self._parse_expr()
        if not self._match(TokenType.DO):
            self.diagnostics.recoverable(
                "PAR050",
                "Manca la parola chiave 'do' dopo la condizione del ciclo 'while'.",
                self._peek().span,
                hint="Scrivi `while (condizione) do`.",
            )
        if self._match(TokenType.COLON):
            self.diagnostics.recoverable("PAR051", "Due punti ':' superflui dopo 'do'.", self._peek().span)

        body = self._parse_stmt_list(stop_tokens=(TokenType.ENDWHILE,))

        if self._match(TokenType.ENDWHILE):
            pass
        elif self._is_end_keyword_pair(TokenType.WHILE):
            self._advance()
            self._advance()
        else:
            self.diagnostics.recoverable(
                "PAR052",
                f"Manca 'endwhile' per chiudere il ciclo 'while' iniziato alla riga {w_tok.span.line}.",
                self._peek().span,
            )

        return WhileStmt(span=w_tok.span, condition=cond, body=body)

    def _parse_repeat(self) -> RepeatStmt:
        r_tok = self._advance()  # `repeat`
        body = self._parse_stmt_list(stop_tokens=(TokenType.UNTIL,))
        self._expect(TokenType.UNTIL, "PAR053", f"Atteso 'until' per chiudere il 'repeat' della riga {r_tok.span.line}", recoverable=True)
        cond = self._parse_expr()
        return RepeatStmt(span=r_tok.span, body=body, condition=cond)

    # ------------------------------------------------------------------
    # Read / Print / Return / Allocate / Deallocate
    # ------------------------------------------------------------------

    def _parse_read(self) -> ReadStmt:
        r_tok = self._advance()  # `read`
        targets: List[Expr] = []
        wrapped = self._match(TokenType.LPAREN) is not None

        while not self._at_eof():
            if wrapped and self._check(TokenType.RPAREN):
                break
            if not wrapped and self._check(TokenType.NEWLINE, TokenType.SEMICOLON, *BLOCK_END_TOKENS):
                break
            if self._check(TokenType.IDENT):
                targets.append(self._parse_lvalue_or_call())
                if not self._match(TokenType.COMMA):
                    if wrapped and not self._check(TokenType.RPAREN):
                        continue
                    break
            else:
                break

        if wrapped:
            self._expect(TokenType.RPAREN, "PAR054", "Attesa ')' di chiusura per 'read(...)'", recoverable=True)

        if not targets:
            self.diagnostics.error("PAR055", "Istruzione 'read' senza variabili di destinazione.", r_tok.span)

        return ReadStmt(span=r_tok.span, targets=targets)

    def _parse_print(self) -> PrintStmt:
        p_tok = self._advance()  # `print`
        exprs: List[Expr] = []

        # Caso speciale: `print ('il numero', x, 'e presente')` o `print ("da" arrivo "a" origine)`
        # Attenzione: `print (a + b) * 2` NON è una lista parentesizzata ma un'espressione che inizia con `(`!
        if self._check(TokenType.LPAREN) and self._looks_like_paren_print_list():
            self._advance()  # '('
            while not self._at_eof() and not self._check(TokenType.RPAREN):
                exprs.append(self._parse_expr())
                self._match(TokenType.COMMA)
            self._expect(TokenType.RPAREN, "PAR056", "Attesa ')' dopo la lista di 'print(...)'", recoverable=True)
            return PrintStmt(span=p_tok.span, expressions=exprs)

        while not self._at_eof():
            tok = self._peek()
            if tok.type in (TokenType.NEWLINE, TokenType.SEMICOLON, *BLOCK_END_TOKENS):
                break
            if tok.span.line != p_tok.span.line and not exprs:
                break
            if tok.span.line != p_tok.span.line:
                break
            exprs.append(self._parse_expr())
            self._match(TokenType.COMMA)

        return PrintStmt(span=p_tok.span, expressions=exprs)

    def _looks_like_paren_print_list(self) -> bool:
        """Verifica se `print (...)` contiene più elementi (separati da `,` o giustapposti) anziché una singola espressione aritmetica."""
        save = self.pos
        try:
            self._advance()  # '('
            depth = 1
            while not self._at_eof() and depth > 0:
                t = self._peek()
                if t.type == TokenType.LPAREN:
                    depth += 1
                elif t.type == TokenType.RPAREN:
                    depth -= 1
                    if depth == 0:
                        self._advance()
                        # Se dopo ')' c'è un operatore binario, allora '(' fa parte di un'espressione!
                        if self._peek().type in (
                            TokenType.PLUS, TokenType.MINUS, TokenType.STAR, TokenType.SLASH,
                            TokenType.MOD, TokenType.DIV, TokenType.POWER, TokenType.EQ,
                            TokenType.NEQ, TokenType.LT, TokenType.LTE, TokenType.GT, TokenType.GTE,
                            TokenType.AND, TokenType.OR,
                        ):
                            return False
                        return True
                elif depth == 1 and t.type == TokenType.COMMA:
                    return True
                self._advance()
            return False
        finally:
            self.pos = save

    def _parse_return(self) -> ReturnStmt:
        r_tok = self._advance()
        val: Optional[Expr] = None
        if not self._check(TokenType.NEWLINE, TokenType.SEMICOLON, *BLOCK_END_TOKENS) and self._peek().span.line == r_tok.span.line:
            val = self._parse_expr()
        return ReturnStmt(span=r_tok.span, value=val)

    def _parse_deallocate(self) -> DeallocateStmt:
        d_tok = self._advance()
        wrapped = self._match(TokenType.LPAREN) is not None
        target = self._parse_expr()
        if wrapped:
            self._expect(TokenType.RPAREN, "PAR057", "Attesa ')' dopo dealloca(...)", recoverable=True)
        return DeallocateStmt(span=d_tok.span, target=target)

    def _parse_allocate_stmt(self) -> AssignStmt:
        """Supporta `alloca(head)` o `alloca head` come statement -> `head := allocate`."""
        a_tok = self._advance()
        wrapped = self._match(TokenType.LPAREN) is not None
        target = self._parse_lvalue_or_call()
        if wrapped:
            self._expect(TokenType.RPAREN, "PAR058", "Attesa ')' dopo alloca(...)", recoverable=True)
        return AssignStmt(span=a_tok.span, target=target, value=AllocateExpr(span=a_tok.span, type_name=None))

    # ------------------------------------------------------------------
    # Espressioni (Precedenza operatori completa)
    # ------------------------------------------------------------------

    def _parse_expr(self) -> Expr:
        return self._parse_or()

    def _parse_or(self) -> Expr:
        left = self._parse_and()
        while self._check(TokenType.OR):
            op_tok = self._advance()
            if not op_tok.canonical:
                self.diagnostics.pedantic(
                    "PED012",
                    f"Operatore logico '{op_tok.lexeme}' senza punti (forma canonica Laccetti: '.OR.').",
                    op_tok.span,
                    hint="Usa '.OR.' per massima aderenza alle slide del Prof. Laccetti.",
                )
            right = self._parse_and()
            left = BinaryExpr(span=op_tok.span, op="or", left=left, right=right)
        return left

    def _parse_and(self) -> Expr:
        left = self._parse_not()
        while self._check(TokenType.AND):
            op_tok = self._advance()
            if not op_tok.canonical:
                self.diagnostics.pedantic(
                    "PED013",
                    f"Operatore logico '{op_tok.lexeme}' senza punti (forma canonica Laccetti: '.AND.').",
                    op_tok.span,
                    hint="Usa '.AND.' per massima aderenza alle slide del Prof. Laccetti.",
                )
            right = self._parse_not()
            left = BinaryExpr(span=op_tok.span, op="and", left=left, right=right)
        return left

    def _parse_not(self) -> Expr:
        if self._check(TokenType.NOT):
            op_tok = self._advance()
            if not op_tok.canonical and op_tok.lexeme != "!":
                self.diagnostics.pedantic(
                    "PED014",
                    f"Operatore logico '{op_tok.lexeme}' senza punti (forma canonica Laccetti: '.NOT.').",
                    op_tok.span,
                    hint="Usa '.NOT.' per massima aderenza alle slide del Prof. Laccetti.",
                )
            operand = self._parse_not()
            return UnaryExpr(span=op_tok.span, op="not", operand=operand)
        return self._parse_comparison()

    def _parse_comparison(self) -> Expr:
        left = self._parse_additive()
        if self._check(TokenType.EQ, TokenType.NEQ, TokenType.LT, TokenType.LTE, TokenType.GT, TokenType.GTE):
            op_tok = self._advance()
            op_map = {
                TokenType.EQ: "=",
                TokenType.NEQ: "!=",
                TokenType.LT: "<",
                TokenType.LTE: "<=",
                TokenType.GT: ">",
                TokenType.GTE: ">=",
            }
            right = self._parse_additive()
            return BinaryExpr(span=op_tok.span, op=op_map[op_tok.type], left=left, right=right)
        # Recupera errore da esame scritto: `if (cont1 := cont2)` o `while (controllo := .TRUE.)`!
        if self._check(TokenType.ASSIGN):
            op_tok = self._advance()
            self.diagnostics.recoverable(
                "PAR060",
                "Usato ':=' al posto di '=' in una condizione di confronto!",
                op_tok.span,
                hint="Nelle condizioni usa '=' per confrontare, non ':='.",
            )
            right = self._parse_additive()
            return BinaryExpr(span=op_tok.span, op="=", left=left, right=right)
        return left

    def _parse_additive(self) -> Expr:
        left = self._parse_multiplicative()
        while self._check(TokenType.PLUS, TokenType.MINUS):
            op_tok = self._advance()
            op = "+" if op_tok.type == TokenType.PLUS else "-"
            right = self._parse_multiplicative()
            left = BinaryExpr(span=op_tok.span, op=op, left=left, right=right)
        return left

    def _parse_multiplicative(self) -> Expr:
        left = self._parse_unary()
        while self._check(TokenType.STAR, TokenType.SLASH, TokenType.MOD, TokenType.DIV):
            op_tok = self._advance()
            op_map = {
                TokenType.STAR: "*",
                TokenType.SLASH: "/",
                TokenType.MOD: "mod",
                TokenType.DIV: "div",
            }
            right = self._parse_unary()
            left = BinaryExpr(span=op_tok.span, op=op_map[op_tok.type], left=left, right=right)
        return left

    def _parse_unary(self) -> Expr:
        if self._check(TokenType.MINUS, TokenType.PLUS):
            op_tok = self._advance()
            op = "-" if op_tok.type == TokenType.MINUS else "+"
            operand = self._parse_unary()
            return UnaryExpr(span=op_tok.span, op=op, operand=operand)
        return self._parse_power()

    def _parse_power(self) -> Expr:
        base = self._parse_postfix()
        if self._check(TokenType.POWER, TokenType.CARET):
            op_tok = self._advance()
            exp = self._parse_unary()
            return BinaryExpr(span=op_tok.span, op="**", left=base, right=exp)
        return base

    def _parse_postfix(self) -> Expr:
        expr = self._parse_primary()
        while True:
            if self._match(TokenType.DOT):
                field_tok = self._expect(TokenType.IDENT, "PAR061", "Atteso nome campo dopo '.'")
                fname = field_tok.lexeme if field_tok else "<err>"
                expr = FieldAccessExpr(span=expr.span, target=expr, field_name=fname)
            elif self._check(TokenType.LBRACKET):
                self.diagnostics.pedantic(
                    "PED009",
                    "Indicizzazione array con parentesi quadre `[...]` invece delle canoniche tonde `(...)`.",
                    self._peek().span,
                    hint="In P-Like gli elementi di un array si indicizzano con `A(i)` o `A(i, j)`.",
                )
                indices = self._parse_bracket_indices()
                expr = IndexExpr(span=expr.span, target=expr, indices=indices, bracket_style="square")
            elif self._check(TokenType.LPAREN) and self._peek().span.line == expr.span.line:
                args = self._parse_call_args()
                expr = CallOrIndexExpr(span=expr.span, target=expr, args=args)
            else:
                break
        return expr

    def _parse_primary(self) -> Expr:
        tok = self._peek()

        if tok.type == TokenType.INT_LIT:
            self._advance()
            return IntLiteral(span=tok.span, value=tok.value)

        if tok.type == TokenType.REAL_LIT:
            self._advance()
            return RealLiteral(span=tok.span, value=tok.value)

        if tok.type == TokenType.STRING_LIT:
            self._advance()
            return StringLiteral(span=tok.span, value=tok.value)

        if tok.type == TokenType.BOOL_LIT:
            self._advance()
            if not tok.canonical:
                self.diagnostics.pedantic(
                    "PED015",
                    f"Costante logica '{tok.lexeme}' senza punti (forma canonica Laccetti: '.{tok.lexeme.upper()}.').",
                    tok.span,
                    hint="Nelle slide di Murli/Laccetti le costanti logiche sono `.TRUE.` e `.FALSE.`.",
                )
            return BoolLiteral(span=tok.span, value=bool(tok.value), canonical=tok.canonical)

        if tok.type == TokenType.NULL_LIT:
            self._advance()
            return NullLiteral(span=tok.span)

        if tok.type == TokenType.ALLOCATE:
            self._advance()
            type_name: Optional[str] = None
            if self._match(TokenType.LPAREN):
                if self._check(TokenType.IDENT):
                    type_name = self._advance().lexeme
                self._expect(TokenType.RPAREN, "PAR062", "Attesa ')' dopo allocate(...)", recoverable=True)
            elif self._check(TokenType.IDENT) and self._peek().span.line == tok.span.line:
                type_name = self._advance().lexeme
            return AllocateExpr(span=tok.span, type_name=type_name)

        if tok.type == TokenType.IDENT:
            self._advance()
            return VarExpr(span=tok.span, name=tok.lexeme)

        if tok.type == TokenType.LPAREN:
            self._advance()
            inner = self._parse_expr()
            self._expect(TokenType.RPAREN, "PAR063", "Attesa ')' di chiusura dell'espressione", recoverable=True)
            return inner

        self.diagnostics.fatal(
            "PAR064",
            f"Espressione inattesa: trovato {tok.lexeme!r}.",
            tok.span,
        )
        if not self._at_eof():
            self._advance()
        return IntLiteral(span=tok.span, value=0)
