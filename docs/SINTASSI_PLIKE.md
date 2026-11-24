# Specifica Formale del Linguaggio P-Like (Prof. Giuliano Laccetti)

Questa specifica sintetizza le regole ufficiali del linguaggio didattico **P-Like (Pascal-Like)** insegnato nel corso di *Programmazione I* (Università degli Studi di Napoli Federico II, Prof. Giuliano Laccetti / A. Murli) e implementato in questo compilatore.

---

## 1. Lessico e Convenzioni

- **Case-insensitivity**: tutte le parole chiave e gli identificatori sono insensibili a maiuscole/minuscole (`Begin` = `begin`, `A(I,J)` = `a(i,j)`).
- **Commenti**:
  - `(* commento multi-riga stile Pascal *)`
  - `/* commento multi-riga stile C (usato nelle slide di ricorsione e merge) */`
  - `// commento su singola riga`
- **Separazione istruzioni**: nuova riga oppure `;` per più istruzioni sulla stessa riga.

### Costanti (Letterali)
| Tipo | Forma canonica Laccetti/Murli | Forme tollerate (segnalate se pignolo) |
|---|---|---|
| Intero (`integer`) | `0`, `42`, `-15` | — |
| Reale (`real`) | `3.14`, `5.`, `0.`, `95.6e4`, `4.e-3` | Intero assegnato a `real` (avviso `PED017`) |
| Alfanumerico (`character`) | `'Napoli'`, `'s'`, `'l''array'` | `"doppia virgoletta"` |
| Logico (`logical`) | `.TRUE.`, `.FALSE.` | `TRUE`, `FALSE` (avviso `PED015`) |
| Puntatore nullo | `NULL` | `null`, `nil` |

---

## 2. Tipi di Dato e Dichiarazioni

### Tipi Primitivi
- `integer` — intero con segno (default `0`)
- `real` — virgola mobile in doppia precisione (default `0.0`)
- `character` — stringa / dato alfanumerico (default `''`)
- `logical` — booleano `.TRUE.` / `.FALSE.` (default `.FALSE.`)

### Dichiarazione Variabili
```plike
var: R, C: real
var: i, j, n: integer
var: nome: character
var: trovato: logical
```
(I due punti dopo `var` sono opzionali come nelle slide Laccetti: `var i, j: integer`.)

### Array (Indicizzazione 1-based di default!)
Tutte le forme presenti nelle slide sono supportate:
```plike
var: A: array [1..n] of real
var: B: array [1..m, 1..n] of integer
var: V[100]: array of real
var: M[4, 3]: array of integer
var: D(1..10): array of character
```
- L'indicizzazione canonica usa le **parentesi tonde**: `A(i)`, `M(i, j)`.
- Le parentesi quadre `A[i]`, `M[i, j]` sono supportate ma generano l'avviso pedante `PED009` (bloccante se il Napoli ha perso!).

### Record e Tipi Derivati (`type` / `record`)
```plike
type complex: record
    Re: real
    Im: real
end

var: x, y, z: complex
```
Oppure inline (anche annidati e con campi array):
```plike
var: data: record
    giorno: integer
    mese: character
    anno: integer
end
```
Accesso ai campi tramite punto: `z.Re := x.Re + y.Re`.

### Puntatori e Strutture Dati Dinamiche
```plike
type list_pointer: *nodo_lista
     nodo_lista: record
         info: integer
         link: list_pointer
     end

var: head, newnode: list_pointer
```
Sono disponibili di default i tipi puntatore `list_pointer`, `stack_pointer`, `queue_pointer`, le operazioni `allocate` / `create_node()` / `dealloca` (o `deallocate` / `free`), e le primitive ADT delle slide Laccetti:
- `create_list(head)` / `linked_list_create(head)` / `stack_create(head)`
- `push(head, elem)` / `stack_insert(head, elem)`
- `pop(head, elem)` / `stack_delete(head, elem)` (anche come funzione `x := pop(head)`)
- `is_stack_empty(head)`, `is_list_empty(head)`
- `list_insert(head, nodo_dopo_cui, elem)`, `list_visualize(head)`
- `queue_create(front, rear)`, `queue_insert(front, rear, elem)`, `queue_delete(front, rear, elem)`, `is_queue_empty(front, rear)`

---

## 3. Operatori e Semantica

- **Assegnazione**: `:=` (usare `=` in un'assegnazione è un errore `RECOVERABLE`, perdonato solo quando il Napoli vince!).
- **Aritmetici**: `+`, `-`, `*` (`×`), `/`, `div`, `mod`, `**` (`^`).
  - **Divisione**: `integer / integer` esegue la **divisione intera troncata verso zero** (come in `mediano := (primo + ultimo) / 2` e `inc := inc / 2`); se almeno un operando è `real` esegue la divisione reale in virgola mobile.
- **Relazionali**: `=` (uguaglianza), `!=` / `<>` / `/=` / `≠`, `<`, `<=`, `>`, `>=`.
- **Logici** (con valutazione in corto-circuito):
  - Canonici: `.AND.`, `.OR.`, `.NOT.`
  - Tollerati (avviso pedante se il Napoli perde): `AND`, `OR`, `NOT`, `!`

---

## 4. Strutture di Controllo

### Selezione
```plike
if (condizione) then
    istruzioni
elseif (altra_condizione) then
    istruzioni
else
    istruzioni
endif
```
Supporta anche `else if (...) then` (sia con singolo `endif` sia con `endif` annidati come nelle slide di Laccetti).

### Ciclo `for` (iterazione definita)
```plike
for i := 1 to n do
    istruzioni
endfor

for i := n - 1 to 1 step -1 do
    istruzioni
endfor
```
Supporta anche `downto` e la forma storica Murli `for i = 1, N do` (segnalata come pedante).

### Ciclo `while` (pre-condizionale)
```plike
while (condizione) do
    istruzioni
endwhile
```

### Ciclo `repeat ... until` (post-condizionale)
```plike
repeat
    istruzioni
until (condizione)
```
Esegue il corpo almeno una volta e termina quando `condizione` diventa `.TRUE.`.

---

## 5. Procedure e Function

### Procedure
```plike
procedure somma_complex (in: x, y; out: z)
    var: x, y, z: complex
begin
    z.Re := x.Re + y.Re
    z.Im := x.Im + y.Im
end somma_complex
```
- `in:` — passaggio **per valore** (non modifica il chiamante).
- `out:` e `in/out:` (e parametri senza modalità nelle `procedure`) — passaggio **per riferimento** (supporta anche il passaggio per riferimento di elementi di array `A(i)` e campi puntatore come `head.link`!).
- I parametri vengono ridefiniti nel blocco `var` locale per specificarne il tipo, esattamente come nel P-Like di Laccetti.

### Function
Supporta entrambe le intestazioni canoniche:
```plike
function fatt_ricorsivo (in: n): integer
    var: n: integer
begin
    if (n <= 1) then
        fatt_ricorsivo := 1
    else
        fatt_ricorsivo := fatt_ricorsivo(n - 1) * n
    endif
end fatt_ricorsivo
```
oppure:
```plike
logical function sequential_search (in: n, A, x)
    ...
end sequential_search
```
Il valore di ritorno si assegna al **nome stesso della function** (oppure tramite `return valore`).

---

## 6. Input / Output e Funzioni Built-in

- `read x, y` oppure `read A(i)` oppure `read(n)`
- `print 'Risultato:', x` oppure `print ('Valore:', x)`
- Funzioni matematiche/utility built-in: `abs(x)`, `sqrt(x)`, `int(x)`, `trunc(x)`, `floor(x)`, `ceil(x)`, `real(x)`, `mod(a, b)`, `min(a, b)`, `max(a, b)`, `length(s)`, `is_odd(n)`, `is_even(n)`, `swap(a, b)`.
