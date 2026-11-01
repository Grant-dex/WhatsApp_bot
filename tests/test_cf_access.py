"""Cloudflare Access 单点登录测试。

在子进程里跑，避免污染其它模块的全局状态。真实的身份校验调用被替换成
桩函数，只验证"拿到邮箱之后"的自动开通与登录逻辑。
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

PROBE = r"""
import json
from fastapi.testclient import TestClient

import cf_access
# 只替换掉"向 Cloudflare 校验 cookie"这一步
cf_access.identity_email = lambda token: "sso@example.com" if token == "good-token" else None

import api_server
app = api_server.app

out = {}

anon = TestClient(app, client=("127.0.0.1", 50010))
out["no_cookie"] = anon.get("/", follow_redirects=False).status_code

user = TestClient(app, client=("127.0.0.1", 50011),
                  cookies={"CF_Authorization": "good-token"})
out["with_cookie_home"] = user.get("/").status_code
out["me"] = user.get("/api/auth/me").json()

bad = TestClient(app, client=("127.0.0.1", 50012),
                 cookies={"CF_Authorization": "bad-token"})
out["bad_cookie"] = bad.get("/", follow_redirects=False).status_code

print(json.dumps(out))
"""


class CloudflareAccessTest(unittest.TestCase):
    def test_auto_provision_and_login(self):
        with tempfile.TemporaryDirectory() as data_dir:
            env = dict(os.environ)
            env["WHATSAPP_BOT_DATA_DIR"] = data_dir
            env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
            env["CF_ACCESS_TEAM_DOMAIN"] = "https://demo.cloudflareaccess.com"
            env["CF_ACCESS_AUTO_LOGIN"] = "1"

            proc = subprocess.run([sys.executable, "-c", PROBE],
                                  cwd=str(ROOT), env=env,
                                  capture_output=True, text=True, timeout=120)
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            out = json.loads(proc.stdout.strip().splitlines()[-1])

            self.assertEqual(out["no_cookie"], 302, "没有 CF cookie 时仍应跳登录页")
            self.assertEqual(out["with_cookie_home"], 200, "CF 验证通过应直接进控制台")
            self.assertEqual(out["me"]["email"], "sso@example.com")
            self.assertEqual(out["bad_cookie"], 302, "无效 cookie 不应放行")

    def test_disabled_by_default(self):
        import importlib

        old = os.environ.pop("CF_ACCESS_TEAM_DOMAIN", None)
        try:
            import cf_access
            importlib.reload(cf_access)
            self.assertFalse(cf_access.enabled())
            self.assertIsNone(cf_access.identity_email("anything"))
        finally:
            if old is not None:
                os.environ["CF_ACCESS_TEAM_DOMAIN"] = old


if __name__ == "__main__":
    unittest.main()
