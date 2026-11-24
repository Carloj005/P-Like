"""Pygments Lexer opzionale per evidenziare la sintassi di file `.plike`."""

from __future__ import annotations

try:
    from pygments.lexer import RegexLexer
    from pygments.token import Comment, Keyword, Name, Number, Operator, Punctuation, String, Text

    class PLikeLexer(RegexLexer):
        name = "P-Like"
        aliases = ["plike", "p-like", "pascal-like"]
        filenames = ["*.plike"]

        tokens = {
            "root": [
                (r"//.*?$", Comment.Single),
                (r"\(\*[\s\S]*?\*\)", Comment.Multiline),
                (r"/\*[\s\S]*?\*/", Comment.Multiline),
                (r"(?i)\.(?:TRUE|FALSE)\.", Keyword.Constant),
                (r"(?i)\.(?:AND|OR|NOT)\.", Operator.Word),
                (
                    r"(?i)\b(?:begin|end|var|type|record|endrecord|array|of|"
                    r"procedure|endprocedure|function|endfunction|return|"
                    r"if|then|else|elseif|endif|for|to|downto|step|do|endfor|"
                    r"while|endwhile|repeat|until|read|print|write|"
                    r"allocate|alloca|deallocate|dealloca|free|in/out|in|out)\b",
                    Keyword,
                ),
                (r"(?i)\b(?:integer|real|character|logical|list_pointer|stack_pointer|queue_pointer)\b", Keyword.Type),
                (r"(?i)\b(?:TRUE|FALSE|NULL|NIL)\b", Keyword.Constant),
                (r"(?i)\b(?:AND|OR|NOT|MOD|DIV)\b", Operator.Word),
                (r":=|!=|<>|/=|<=|>=|\*\*|[+\-*/=<>^!]", Operator),
                (r"\.\.|[()\[\],;:.]", Punctuation),
                (r"'(?:''|[^'])*'", String.Single),
                (r'"(?:\\.|[^"])*"', String.Double),
                (r"\d+\.(?!\.)\d*(?:[eE][+-]?\d+)?", Number.Float),
                (r"\d+", Number.Integer),
                (r"[A-Za-z_][A-Za-z0-9_]*", Name),
                (r"\s+", Text),
            ]
        }

except ImportError:  # pragma: no cover
    PLikeLexer = None  # type: ignore[assignment,misc]
