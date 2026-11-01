"""邀请码注册的端到端验证。"""
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

PROBE = r"""
import json
from fastapi.testclient import TestClient
import api_server

c = TestClient(api_server.app)
out = {}
out["status"] = c.get("/api/auth/status").json()

out["no_code"] = c.post("/api/auth/register",
                        json={"email": "a@example.com", "password": "password123"}).status_code
out["bad_code"] = c.post("/api/auth/register",
                         json={"email": "b@example.com", "password": "password123",
                               "code": "wrong"}).status_code
out["good_code"] = c.post("/api/auth/register",
                          json={"email": "c@example.com", "password": "password123",
                                "code": "TESTCODE"}).status_code
print(json.dumps(out))
"""


class SignupCodeTest(unittest.TestCase):
    def test_code_required(self):
        with tempfile.TemporaryDirectory() as data_dir:
            env = dict(os.environ)
            env["WHATSAPP_BOT_DATA_DIR"] = data_dir
            env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
            env["WA_SIGNUP_CODE"] = "TESTCODE"

            proc = subprocess.run([sys.executable, "-c", PROBE],
                                  cwd=str(ROOT), env=env,
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            out = json.loads(proc.stdout.strip().splitlines()[-1])

            self.assertTrue(out["status"]["signup_code_required"])
            self.assertEqual(out["no_code"], 403, "没有邀请码应拒绝")
            self.assertEqual(out["bad_code"], 403, "邀请码错误应拒绝")
            self.assertEqual(out["good_code"], 200, "邀请码正确应放行")

    def test_no_code_configured(self):
        with tempfile.TemporaryDirectory() as data_dir:
            env = {k: v for k, v in os.environ.items() if k != "WA_SIGNUP_CODE"}
            env["WHATSAPP_BOT_DATA_DIR"] = data_dir
            env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")

            proc = subprocess.run([sys.executable, "-c", PROBE],
                                  cwd=str(ROOT), env=env,
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            out = json.loads(proc.stdout.strip().splitlines()[-1])
            self.assertFalse(out["status"]["signup_code_required"])
            self.assertEqual(out["no_code"], 200, "未配置邀请码时保持原行为")


if __name__ == "__main__":
    unittest.main()
