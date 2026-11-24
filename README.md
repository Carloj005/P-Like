# P-Like — Il Linguaggio & Compilatore del Prof. Giuliano Laccetti

Implementazione completa del linguaggio didattico **P-Like (Pascal-Like)** nato nel corso di *Programmazione I* dell'**Università degli Studi di Napoli Federico II** (Prof. Giuliano Laccetti / A. Murli), dotato di:

- **Compilatore multi-stadio reale**: Lexer, Parser a discesa ricorsiva con error recovery, Analizzatore Semantico & Type-Checker, Compilatore verso **Bytecode P-Like (`.plbc`)** + **Virtual Machine dedicata**.
- **Doppio Transpiler**: compilazione diretta da P-Like a **C99 (`.c`)** e **Python 3 (`.py`)**.
- **La Variabile "Partite del Napoli"**: fedele alla leggenda universitaria federiciana, l'esito della compilazione dipende dalle regole ufficiali del P-Like **combinate con il risultato live dell'ultima partita ufficiale dell'SSC Napoli**!
- **P-Like Studio (IDE Grafico locale)**: avvia `plike ide` per aprire un IDE moderno in stile VS Code + **tema Azzurro Napoli** nel browser (zero dipendenze esterne) con syntax highlighting live, numeri di riga, diagnostiche cliccabili, widget live SSC Napoli con barra umore Prof. Laccetti, console + input `read`, disassembler Bytecode, codice C99/Python generato, AST ed esplora-esempi!
- **Zero dipendenze esterne**: pura Python Standard Library (`Python >= 3.9`).

---

## La Variabile Napoli (Modalità Prof. Laccetti)

Come racconta la tradizione degli esami scritti alla Federico II, la severità nella correzione dipendeva sensibilmente dall'ultima partita del Napoli. Il compilatore interroga automaticamente in tempo reale il risultato dell'**ultima partita ufficiale dell'SSC Napoli** (Serie A, Champions League, Coppa Italia — con cache locale di 1 ora e fallback offline) e adatta il verdetto di compilazione:

| Risultato SSC Napoli | Umore Prof. Laccetti | Errori Fatali | Errori Recuperabili da Esame\* | Pignolerie Stilistiche\*\* | Rischio Malumore su Codice Perfetto |
|---|---|---|---|---|---|
| **Vittoria larga ($\ge 3$ gol) o vs Rivale** | `ESTASI_AZZURRA` | Fallisce | **Auto-riparati e perdonati (fino a 6!)** | Perdonate | 0% |
| **Vittoria** | `OTTIMO_UMORE` | Fallisce | **Auto-riparati e perdonati (fino a 3!)** | Perdonate | 0% |
| **Pareggio** | `NEUTRO` | Fallisce | **Fallisce** (regole standard) | Solo Warning | 0% |
| **Sconfitta** | `NERVOSO` | Fallisce | **Fallisce** | **PROMOSSE A ERRORI!** | 15% |
| **Sconfitta pesante o vs Rivale (Juve/Inter/Milan/Roma)** | `FURIA_POST_PARTITA` | Fallisce | **Fallisce** | **PROMOSSE A ERRORI!** | 30% |
| **Disattivata (`--napoli off`)** | `STANDARD` | Fallisce | **Fallisce** | Solo Warning | 0% |

> \* **Errori recuperabili tipici d'esame**: `=` al posto di `:=` in assegnazione, `then` o `do` dimenticato, variabile contatore `for` non dichiarata in `var`, `:=` al posto di `=` in una condizione, `begin`/`end` omesso in una procedure, typo `enwhile`.
>
> \*\* **Pignolerie stilistiche canoniche Laccetti/Murli**: `TRUE`/`FALSE` senza punti invece di `.TRUE.`/`.FALSE.`, `AND`/`OR`/`NOT` senza punti invece di `.AND.`/`.OR.`/`.NOT.`, indicizzazione `A[i]` invece di `A(i)`, `0` invece di `0.` assegnato a un `real`, `end` senza il nome del programma, variabili dichiarate ma mai usate.

Puoi sempre simulare qualsiasi scenario da CLI con `--napoli auto|win|big-win|draw|loss|derby-loss|off` (e disattivare il tiro casuale post-sconfitta con `--no-luck` o fissarlo con `--seed 42`).

---

## Installazione Rapida

```bash
git clone https://github.com/Carloj005/P-Like.git
cd P-Like

# Opzione 1: installazione come comando globale `plike`
pip install -e .

# Opzione 2: uso diretto senza installazione
python -m plike --help
```

---

## Utilizzo da CLI

```bash
# Controlla in tempo reale l'ultima partita del Napoli e l'umore del compilatore
plike napoli

# Compila ed esegue un programma P-Like sulla Virtual Machine (usa il risultato LIVE del Napoli!)
plike run examples/fattoriale.plike

# Prova lo stesso compito d'esame con piccole sviste nei 3 scenari del Napoli:
plike run examples/esame_studente.plike --napoli win     # COMPILA E GIRA! (Auto-riparato)
plike run examples/esame_studente.plike --napoli draw    # BOCCIATO (Regole standard)
plike run examples/esame_studente.plike --napoli loss    # BOCCIATURA BRUTALE

# Compila verso Bytecode (.plbc), C99 (.c) o Python (.py)
plike compile examples/ricerca_binaria.plike --target bytecode -o ricerca.plbc
plike run-bc ricerca.plbc

plike compile examples/insertion_sort.plike --target c -o insertion_sort.c
plike compile examples/prodotto_matrici.plike --target py -o prodotto_matrici.py

# Ispeziona il Bytecode disassemblato o l'AST JSON
plike disasm examples/fattoriale.plike --napoli off
plike ast examples/hello.plike

# Valuta un file senza eseguirlo (modalità correzione compito scritto)
plike check examples/stile_non_canonico.plike --napoli draw
plike check examples/stile_non_canonico.plike --napoli loss

# Avvia P-Like Studio — IDE grafico locale nel browser!
plike ide
plike ide examples/esame_studente.plike --napoli win

# Shell interattiva (REPL)
plike repl
```

---

## Esempio di Codice P-Like Canonico

```plike
(* Ricerca binaria ricorsiva - dalle slide del Prof. Giuliano Laccetti *)
function trova_pos(in: elenco, primo, ultimo, chiave): integer
    var: elenco: array [1..100] of integer
    var: primo, ultimo, chiave, mediano: integer
begin
    if (primo > ultimo) then
        trova_pos := 0
    else
        mediano := (primo + ultimo) / 2
        if (chiave = elenco(mediano)) then
            trova_pos := mediano
        else if (chiave < elenco(mediano)) then
            trova_pos := trova_pos(elenco, primo, mediano - 1, chiave)
        else
            trova_pos := trova_pos(elenco, mediano + 1, ultimo, chiave)
        endif
        endif
    endif
end trova_pos

begin test_ricerca_binaria
    var: A: array [1..6] of integer
    var: pos: integer

    A(1) := 3
    A(2) := 7
    A(3) := 12
    A(4) := 19
    A(5) := 25
    A(6) := 42

    pos := trova_pos(A, 1, 6, 19)
    print 'Elemento 19 trovato in posizione:', pos
end test_ricerca_binaria
```

---

## Architettura del Compilatore

```text
  file.plike
      │
      ▼
  [1. Lexer]           plike/lexer.py        Tokenizzazione case-insensitive (.TRUE., .AND., 5., .., (* *), /* */, //)
      │
      ▼
  [2. Parser]          plike/parser.py       Discesa ricorsiva -> AST tipizzato + classificazione RECOVERABLE / PEDANTIC
      │
      ▼
  [3. Semantic]        plike/semantic.py     Scope, Type-checking, disambiguazione A(i) vs f(i), definite-assignment
      │
      ▼
  [4. Napoli Engine]   plike/napoli.py       API live SSC Napoli + cache -> Verdetto Laccetti (voto 0-30L, perdono/promozione)
      │
      ├──► [5a. Bytecode Compiler + VM]  plike/compiler.py + plike/vm.py     (.plbc, pass-by-ref Ref, array 1-based, ADT)
      ├──► [5b. C99 Transpiler]          plike/codegen_c.py                  Genera codice C99 didattico standalone
      └──► [5c. Python Transpiler]       plike/codegen_py.py                 Genera script Python 3 eseguibile
```

---

## Documentazione & Esempi

- Specifica completa della sintassi e delle regole del linguaggio: [docs/SINTASSI_PLIKE.md](docs/SINTASSI_PLIKE.md)
- Programmi di esempio pronti da eseguire in [`examples/`](examples/):
  - `hello.plike` — Hello World canonico
  - `fattoriale.plike` — Fattoriale iterativo e ricorsivo + MCD di Euclide
  - `ricerca_binaria.plike` — Ricerca binaria iterativa (`procedure`) e ricorsiva (`function`)
  - `insertion_sort.plike` — Insertion Sort su array 1-based
  - `selection_sort.plike` — Selection Sort con `procedure` e parametri `in:` / `in/out:`
  - `exchange_sort.plike` — Exchange Sort (Bubble Sort ottimizzato con flag `ordinato`)
  - `merge_array.plike` — Merge tra 2 array ordinati (dalle slide Laccetti)
  - `prodotto_matrici.plike` — Prodotto matrice-matrice 2D $C = A \cdot B$
  - `back_substitution.plike` — Risoluzione sistema triangolare superiore $Ux = b$ con `step -1`
  - `torre_di_hanoi.plike` — Torre di Hanoi ricorsiva
  - `numeri_complessi.plike` — Tipo derivato `type complex: record` e `procedure somma_complex`
  - `linked_list.plike` — Lista concatenata con `allocate`, `list_pointer`, inserimento ordinato ricorsivo per riferimento su `head.link`!
  - `stack_demo.plike` — Stack LIFO con `stack_create`, `push`, `pop`, `is_stack_empty`
  - `esame_studente.plike` — Compito d'esame con tipiche sviste (mostra la differenza tra `--napoli win`, `draw`, `loss`)
  - `stile_non_canonico.plike` — Codice valido ma non pignolo (passa col pareggio, bocciato con la sconfitta del Napoli!)

---

## Test Suite

```bash
python -m unittest discover -s tests -v
```

---

## Licenza

Distribuito sotto licenza [MIT](LICENSE).
