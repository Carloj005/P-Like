"""Test end-to-end del backend HTTP di P-Like Studio (IDE Grafico)."""

from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path

from plike.ide.server import create_ide_server


class TestPLikeStudioIDE(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.test_file = Path(self.tmpdir.name) / "mio_esame.plike"
        self.test_file.write_text("begin test\n    print 'Ciao IDE'\nend test\n", encoding="utf-8")

        self.server, self.port = create_ide_server(
            host="127.0.0.1",
            port=0,
            initial_file=self.test_file,
            default_napoli="win",
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.tmpdir.cleanup()

    def _get(self, path: str):
        with urllib.request.urlopen(self.base_url + path, timeout=5) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()

    def _post_json(self, path: str, body: dict):
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_static_assets_and_path_traversal_blocked(self) -> None:
        st, ctype, html = self._get("/")
        self.assertEqual(st, 200)
        self.assertIn("text/html", ctype)
        self.assertIn(b"P-Like Studio", html)

        st_css, _, css = self._get("/static/style.css")
        self.assertEqual(st_css, 200)
        self.assertIn(b"--azzurro", css)

        st_js, _, js = self._get("/static/app.js")
        self.assertEqual(st_js, 200)
        self.assertIn(b"highlightPLike", js)

        with self.assertRaises(urllib.error.HTTPError) as ctx:
            self._get("/static/../server.py")
        self.assertEqual(ctx.exception.code, 404)

    def test_info_and_examples_and_napoli_endpoints(self) -> None:
        st, _, raw = self._get("/api/info")
        self.assertEqual(st, 200)
        info = json.loads(raw.decode("utf-8"))
        self.assertEqual(info["default_napoli"], "win")
        self.assertEqual(info["initial_file"]["filename"], "mio_esame.plike")

        st2, _, raw2 = self._get("/api/examples")
        self.assertEqual(st2, 200)
        exs = json.loads(raw2.decode("utf-8"))["examples"]
        self.assertGreaterEqual(len(exs), 10)
        self.assertTrue(any(e["filename"] == "esame_studente.plike" for e in exs))

        st3, _, raw3 = self._get("/api/napoli?mode=big-win")
        self.assertEqual(st3, 200)
        match = json.loads(raw3.decode("utf-8"))["match"]
        self.assertEqual(match["mood"], "ESTASI_AZZURRA")
        self.assertEqual(match["outcome"], "WIN")

    def test_run_endpoint_with_stdin_and_all_backends(self) -> None:
        code = """
        begin somma_ide
            var: a, b: integer
            read a, b
            print 'Totale:', a + b
        end somma_ide
        """
        st, res = self._post_json(
            "/api/run",
            {"code": code, "filename": "somma_ide.plike", "stdin": "17 25\n", "napoli_mode": "win"},
        )
        self.assertEqual(st, 200)
        self.assertTrue(res["success"])
        self.assertEqual(res["stdout"].strip(), "Totale: 42")
        self.assertIn("PRINT", res["disasm"])
        self.assertIn("int main(void)", res["c_code"])
        self.assertIn("def _plike_main():", res["py_code"])
        self.assertIn("MainProgram", res["ast_json"])

    def test_napoli_verdict_win_vs_loss_via_api(self) -> None:
        imperfect = """
        begin esame
            var: s: integer
            s = 5
            if (s = 5 AND TRUE)
                print s
            endif
        end
        """
        _, res_win = self._post_json("/api/run", {"code": imperfect, "napoli_mode": "win"})
        self.assertTrue(res_win["success"])
        self.assertEqual(res_win["stdout"].strip(), "5")
        self.assertGreater(res_win["verdict"]["forgiven_count"], 0)

        _, res_loss = self._post_json("/api/check", {"code": imperfect, "napoli_mode": "loss", "allow_luck": False})
        self.assertFalse(res_loss["success"])
        self.assertGreater(res_loss["verdict"]["promoted_count"], 0)

    def test_save_local_file_endpoint(self) -> None:
        new_code = "begin aggiornato\n    print 'Salvato da IDE!'\nend aggiornato\n"
        st, res = self._post_json("/api/save-local", {"code": new_code})
        self.assertEqual(st, 200)
        self.assertTrue(res["saved"])
        self.assertEqual(self.test_file.read_text(encoding="utf-8"), new_code)


if __name__ == "__main__":
    unittest.main()
