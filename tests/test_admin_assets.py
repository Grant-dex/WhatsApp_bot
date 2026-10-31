"""Regression test: the admin panel must be served in source mode.

``GET /`` used to answer 500 "Admin panel not found" when the backend ran from
source, because ``admin.html`` was resolved through ``config.get_bundle_dir()``
— which returns the repo root in source mode — while the file actually lives in
``src/static/``. A perfectly healthy backend therefore looked broken whenever it
was started without PyInstaller.

The probe runs in a subprocess so this test never inherits config/database
global state from the other unittest modules.

Run from the repository root:
    PYTHONPATH=src python -m unittest tests.test_admin_assets -v
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

# Creates the app with a throwaway data dir and reports the three routes the
# desktop window depends on. Mocked nowhere: this is the real routing layer.
PROBE = r"""
import json
from fastapi.testclient import TestClient
import api_server

client = TestClient(api_server.app)
out = {}
for path in ("/health", "/", "/admin/api/dashboard", "/admin/api/activity?lines=10", "/assets/common.js", "/assets/workspace.css", "/design-reference/dashboard-preview.html"):
    response = client.get(path)
    out[path] = {
        "status": response.status_code,
        "content_type": response.headers.get("content-type", ""),
        "body": response.text[:400],
    }
print(json.dumps(out))
"""


class AdminAssetsTest(unittest.TestCase):
    def _probe(self) -> dict:
        with tempfile.TemporaryDirectory() as data_dir:
            log_dir = Path(data_dir) / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            (log_dir / "backend.log").write_text(
                "2026-10-23 20:00:00,000 [INFO] test marker: backend started\n",
                encoding="utf-8",
            )
            env = dict(os.environ)
            env["WHATSAPP_BOT_DATA_DIR"] = data_dir
            # Keep the caller's dependency path (e.g. a temporary pip target or
            # virtualenv) while ensuring src/ is importable.
            existing = [p for p in env.get("PYTHONPATH", "").split(os.pathsep)
                        if p and p != str(SRC)]
            env["PYTHONPATH"] = os.pathsep.join([str(SRC), *existing])
            env.pop("PYTHONHOME", None)
            proc = subprocess.run(
                [sys.executable, "-c", PROBE],
                cwd=str(ROOT),
                env=env,
                capture_output=True,
                text=True,
                timeout=180,
            )
        self.assertEqual(
            proc.returncode, 0,
            f"probe failed:\nstdout={proc.stdout[-2000:]}\nstderr={proc.stderr[-2000:]}",
        )
        # FastAPI's TestClient emits a deprecation warning on stderr; only the
        # last stdout line is the JSON payload.
        return json.loads(proc.stdout.strip().splitlines()[-1])

    def test_admin_panel_is_served_from_source(self):
        payload = self._probe()

        self.assertEqual(payload["/health"]["status"], 200)

        root = payload["/"]
        self.assertEqual(root["status"], 200, root["body"])
        self.assertIn("text/html", root["content_type"])
        self.assertIn("<!DOCTYPE html>", root["body"])
        self.assertNotIn("Admin panel not found", root["body"])

    def test_split_assets_and_private_references(self):
        payload = self._probe()
        self.assertEqual(payload["/assets/common.js"]["status"], 200)
        self.assertIn("javascript", payload["/assets/common.js"]["content_type"])
        self.assertEqual(payload["/assets/workspace.css"]["status"], 200)
        self.assertEqual(payload["/design-reference/dashboard-preview.html"]["status"], 404)

    def test_dashboard_api_works_on_an_empty_database(self):
        payload = self._probe()
        self.assertEqual(payload["/admin/api/dashboard"]["status"], 200)

    def test_activity_log_reads_the_actual_data_dir_log(self):
        payload = self._probe()
        activity = payload["/admin/api/activity?lines=10"]
        self.assertEqual(activity["status"], 200)
        self.assertIn("backend.log", activity["body"])
        self.assertIn("test marker", activity["body"])


if __name__ == "__main__":
    unittest.main()
