"""Test completi per Bytecode Compiler, Virtual Machine, Transpiler Python e Transpiler C99."""

from __future__ import annotations

import io
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from plike.bytecode import CompiledProgram
from plike.driver import compile_source, run_source
from plike.vm import PLikeRuntimeError, PLikeVM


class TestVMAndCodegen(unittest.TestCase):
    def _run_vm(self, src: str, stdin_text: str = "") -> str:
        out = io.StringIO()
        res = run_source(
            src,
            napoli_mode="off",
            stdin=io.StringIO(stdin_text),
            stdout=out,
        )
        self.assertTrue(res.success, f"Compilazione fallita: {[d.format() for d in res.diagnostics.items]}")
        return out.getvalue()

    def test_pass_by_value_vs_reference(self) -> None:
        src = """
        procedure cambia(in: x; in/out: y; out: z)
            var: x, y, z: integer
        begin
            x := 999
            y := y + 10
            z := 42
        end cambia

        begin test_params
            var: a, b, c: integer
            a := 1
            b := 5
            c := 0
            cambia(a, b, c)
            print a, b, c
        end test_params
        """
        self.assertEqual(self._run_vm(src).strip(), "1 15 42")

    def test_integer_vs_real_division_and_mod(self) -> None:
        src = """
        begin test_div
            var: a, b, q, r: integer
            var: f: real
            a := 7
            b := 2
            q := a / b
            r := a mod b
            f := 7. / 2.
            print q, r, f
        end test_div
        """
        self.assertEqual(self._run_vm(src).strip(), "3 1 3.5")

    def test_read_and_repeat_until(self) -> None:
        src = """
        begin ricerca_input
            var: N, numero, elemento, i: integer
            var: trovato: logical
            read N, elemento
            trovato := .FALSE.
            i := 0
            repeat
                read numero
                i := i + 1
                if (elemento = numero) then
                    trovato := .TRUE.
                endif
            until (i = N .OR. trovato)
            print trovato, i
        end ricerca_input
        """
        self.assertEqual(self._run_vm(src, stdin_text="4 10\n2 1 10 5\n").strip(), ".TRUE. 3")

    def test_short_circuit_and_or(self) -> None:
        src = """
        begin test_sc
            var: A: array [1..3] of integer
            var: i: integer
            A(1) := 10; A(2) := 20; A(3) := 30
            i := 1
            while (i <= 3 .AND. A(i) != 99) do
                i := i + 1
            endwhile
            print i
        end test_sc
        """
        # Se non ci fosse short-circuit, A(4) esploderebbe con out-of-bounds!
        self.assertEqual(self._run_vm(src).strip(), "4")

    def test_array_bounds_error_enforced(self) -> None:
        src = """
        begin oob
            var: A: array [1..3] of integer
            A(0) := 5
        end oob
        """
        with self.assertRaises(PLikeRuntimeError):
            self._run_vm(src)

    def test_queue_adt_fifo(self) -> None:
        src = """
        begin test_queue
            var: front, rear: queue_pointer
            var: x: integer
            queue_create(front, rear)
            queue_insert(front, rear, 100)
            queue_insert(front, rear, 200)
            queue_insert(front, rear, 300)
            while (.NOT. is_queue_empty(front, rear)) do
                queue_delete(front, rear, x)
                print x
            endwhile
        end test_queue
        """
        self.assertEqual(self._run_vm(src).strip().splitlines(), ["100", "200", "300"])

    def test_nested_records_and_record_array_field(self) -> None:
        # Slide 6 e 8 di `Strutture dati-record.pdf`!
        src = """
        begin test_rec
            var: indirizzo: record
                via: record
                    strada: character
                    numero_civico: integer
                end
                cap: integer
            end
            var: vettore: record
                dimensione: array (1..2) of integer
                componente: array (1..3) of real
            end

            indirizzo.via.strada := 'Cintia'
            indirizzo.via.numero_civico := 11
            indirizzo.cap := 80126
            vettore.dimensione(1) := 3
            vettore.componente(1) := 2.5

            print indirizzo.via.strada, indirizzo.via.numero_civico, indirizzo.cap
            print vettore.dimensione(1), vettore.componente(1)
        end test_rec
        """
        lines = self._run_vm(src).strip().splitlines()
        self.assertEqual(lines, ["Cintia 11 80126", "3 2.5"])

    def test_bytecode_json_roundtrip_and_disasm(self) -> None:
        src = """
        function doppio(in: n): integer
            var: n: integer
        begin
            doppio := n * 2
        end doppio

        begin main_bc
            print doppio(21)
        end main_bc
        """
        res = compile_source(src, target="bytecode", napoli_mode="off")
        self.assertTrue(res.success)
        assert res.bytecode is not None and res.generated_code is not None
        disasm = res.bytecode.disassemble()
        self.assertIn("FUNCTION doppio", disasm)
        self.assertIn("CALL", disasm)

        reloaded = CompiledProgram.from_json(res.generated_code)
        out = io.StringIO()
        PLikeVM(reloaded, stdout=out).run()
        self.assertEqual(out.getvalue().strip(), "42")

    def test_python_and_c_transpilers(self) -> None:
        src = """
        function somma_ric(in: n): integer
            var: n: integer
        begin
            if (n = 1) then
                somma_ric := 1
            else
                somma_ric := n + somma_ric(n - 1)
            endif
        end somma_ric

        begin test_gen
            var: ris: integer
            ris := somma_ric(10)
            print 'Somma =', ris
        end test_gen
        """
        # 1. Python transpiler: esegui davvero il codice generato e confronta con la VM!
        vm_out = self._run_vm(src)
        py_res = compile_source(src, target="py", napoli_mode="off")
        self.assertTrue(py_res.success)
        assert py_res.generated_code is not None

        with tempfile.TemporaryDirectory() as td:
            py_file = Path(td) / "out.py"
            py_file.write_text(py_res.generated_code, encoding="utf-8")
            proc = subprocess.run([sys.executable, str(py_file)], capture_output=True, text=True, check=True)
            self.assertEqual(proc.stdout, vm_out)

        # 2. C99 transpiler: verifica struttura C valida
        c_res = compile_source(src, target="c", napoli_mode="off")
        self.assertTrue(c_res.success)
        assert c_res.generated_code is not None
        self.assertIn("int somma_ric(int n)", c_res.generated_code)
        self.assertIn("int main(void)", c_res.generated_code)
        self.assertIn("printf(", c_res.generated_code)


if __name__ == "__main__":
    unittest.main()
