"""Test per Lexer e Parser P-Like."""

from __future__ import annotations

import unittest

from plike.ast_nodes import (
    ArrayType,
    AssignStmt,
    BinaryExpr,
    ForStmt,
    IfStmt,
    PointerType,
    RecordType,
    RepeatStmt,
    SubprogramDecl,
    WhileStmt,
)
from plike.diagnostics import DiagnosticBag
from plike.lexer import Lexer
from plike.parser import Parser
from plike.tokens import TokenType


class TestLexer(unittest.TestCase):
    def test_dotted_keywords_and_numbers(self) -> None:
        src = "1..n 5. 4.e-3 x=1.OR.y=2 .TRUE. .FALSE. .AND. .NOT."
        diags = DiagnosticBag()
        toks = Lexer(src, diagnostics=diags).tokenize()
        types = [t.type for t in toks if t.type != TokenType.EOF]
        self.assertEqual(
            types,
            [
                TokenType.INT_LIT,
                TokenType.DOTDOT,
                TokenType.IDENT,
                TokenType.REAL_LIT,
                TokenType.REAL_LIT,
                TokenType.IDENT,
                TokenType.EQ,
                TokenType.INT_LIT,
                TokenType.OR,
                TokenType.IDENT,
                TokenType.EQ,
                TokenType.INT_LIT,
                TokenType.BOOL_LIT,
                TokenType.BOOL_LIT,
                TokenType.AND,
                TokenType.NOT,
            ],
        )
        self.assertEqual(toks[3].value, 5.0)
        self.assertAlmostEqual(toks[4].value, 0.004)
        self.assertEqual(len(diags.items), 0)

    def test_comments_and_unicode_and_inout(self) -> None:
        src = """
        (* commento pascal *)
        /* commento c */
        // commento linea
        procedure p(in: a; in/out: b; out: c)
        x := 2 × 3
        if (x ≠ 0) then
        """
        diags = DiagnosticBag()
        toks = Lexer(src, diagnostics=diags).tokenize()
        non_nl = [t for t in toks if t.type not in (TokenType.NEWLINE, TokenType.EOF)]
        self.assertIn(TokenType.INOUT, [t.type for t in non_nl])
        self.assertIn(TokenType.STAR, [t.type for t in non_nl])
        self.assertIn(TokenType.NEQ, [t.type for t in non_nl])
        self.assertEqual(len(diags.errors), 0)

    def test_recoverable_typo_enwhile(self) -> None:
        diags = DiagnosticBag()
        toks = Lexer("while (i < 10) do\n i := i + 1\nenwhile", diagnostics=diags).tokenize()
        self.assertIn(TokenType.ENDWHILE, [t.type for t in toks])
        self.assertEqual(len(diags.recoverables), 1)


class TestParser(unittest.TestCase):
    def _parse(self, src: str):
        diags = DiagnosticBag()
        toks = Lexer(src, diagnostics=diags).tokenize()
        ast = Parser(toks, diagnostics=diags).parse()
        return ast, diags

    def test_all_array_declaration_forms(self) -> None:
        src = """
        begin arr_forms
            var: a[10]: array of real
            var: b[1..5, 1..4]: array of integer
            var c: array [1..8] of character
            var d: array (1..2) of integer
            var: e(1..3): array of logical
            a(1) := 1.
        end arr_forms
        """
        ast, diags = self._parse(src)
        self.assertEqual(len(diags.fatals), 0)
        self.assertEqual(len(diags.errors), 0)
        self.assertIsNotNone(ast.main)
        self.assertEqual(len(ast.main.var_decls), 5)
        for vd in ast.main.var_decls:
            self.assertIsInstance(vd.type_spec, ArrayType)

    def test_record_and_pointer_type_block(self) -> None:
        src = """
        type list_pointer: *nodo_lista
             nodo_lista: record
                 info: integer
                 link: list_pointer
             end
        begin p
            var: h: list_pointer
            h := NULL
        end p
        """
        ast, diags = self._parse(src)
        self.assertEqual(len(diags.errors), 0)
        self.assertEqual(len(ast.type_decls), 2)
        self.assertIsInstance(ast.type_decls[0].type_spec, PointerType)
        self.assertIsInstance(ast.type_decls[1].type_spec, RecordType)

    def test_prefix_and_suffix_functions_and_double_end(self) -> None:
        src = """
        logical function f1(in: n)
            var: n: integer
        begin
            f1 := n > 0
        end
        end f1

        function f2(in: n): integer
            var: n: integer
        begin
            f2 := n + 1
        end f2
        """
        ast, diags = self._parse(src)
        self.assertEqual(len(diags.errors), 0)
        self.assertEqual(len(ast.subprograms), 2)
        self.assertEqual(ast.subprograms[0].name, "f1")
        self.assertEqual(ast.subprograms[1].name, "f2")

    def test_else_if_both_nested_and_flat(self) -> None:
        nested = """
        begin t1
            var: x: integer
            x := 2
            if (x = 1) then
                print 1
            else if (x = 2) then
                print 2
            else
                print 3
            endif
            endif
        end t1
        """
        flat = """
        begin t2
            var: x: integer
            x := 2
            if (x = 1) then
                print 1
            else if (x = 2) then
                print 2
            else
                print 3
            endif
        end t2
        """
        ast1, d1 = self._parse(nested)
        ast2, d2 = self._parse(flat)
        self.assertEqual(len(d1.errors) + len(d1.fatals), 0)
        self.assertEqual(len(d2.errors) + len(d2.fatals), 0)
        self.assertIsInstance(ast1.main.body[1], IfStmt)
        self.assertIsInstance(ast2.main.body[1], IfStmt)

    def test_for_variants_and_repeat(self) -> None:
        src = """
        begin loops
            var: i, s: integer
            s := 0
            for i := 10 to 1 step -2 do
                s := s + i
            endfor
            repeat
                s := s - 1
            until (s <= 0)
        end loops
        """
        ast, diags = self._parse(src)
        self.assertEqual(len(diags.errors) + len(diags.fatals), 0)
        self.assertIsInstance(ast.main.body[1], ForStmt)
        self.assertIsInstance(ast.main.body[2], RepeatStmt)


if __name__ == "__main__":
    unittest.main()
