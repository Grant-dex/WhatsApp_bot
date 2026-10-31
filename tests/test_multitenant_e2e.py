"""多租户端到端测试：走真实 HTTP 层（TestClient），在子进程里跑，

避免污染其它测试模块的 config / database 全局状态。

覆盖：未登录拦截 → 初始化管理员 → 注册第二个用户 → 数据隔离 → webhook 租户归属。
运行： PYTHONPATH=src python -m unittest tests.test_multitenant_e2e -v
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
import api_server

app = api_server.app
# 模拟来自本机的 bridge 回调
anon = TestClient(app, client=("127.0.0.1", 50000))

out = {}
out["anon_home"] = anon.get("/", follow_redirects=False).status_code
out["anon_api"] = anon.get("/admin/api/customers").status_code

# 1) 管理员
admin = TestClient(app, client=("127.0.0.1", 50001))
boot = admin.post("/api/auth/bootstrap",
                  json={"email": "owner@example.com", "password": "password123"})
out["bootstrap"] = boot.status_code
out["home_after_login"] = admin.get("/").status_code
out["admin_me"] = admin.get("/api/auth/me").json()

# 2) 第二个用户
other = TestClient(app, client=("127.0.0.1", 50002))
reg = other.post("/api/auth/register",
                 json={"email": "user2@example.com", "password": "password123"})
out["register"] = reg.status_code
out["other_me"] = other.get("/api/auth/me").json()

# 3) 数据隔离：管理员写入一条客户
token = out["admin_me"]["user_id"]
from database import get_connection
import tenancy
from pathlib import Path
owner = __import__("accounts").get_user(token)
tenancy.set_current(tenancy.Tenant(owner["id"], owner["email"], Path(owner["data_dir"])))
conn = get_connection()
conn.execute("INSERT INTO customers(phone,name) VALUES('+15550009999','OWNER ONLY')")
conn.commit()
tenancy.reset_current(tenancy.set_current(None))

out["admin_customers"] = admin.get("/admin/api/customers").json()["total"]
out["other_customers"] = other.get("/admin/api/customers").json()["total"]

# 4) 二维码按租户归属
other_id = out["other_me"]["user_id"]
anon.post("/webhook/qr", json={"qr_text": "2@OTHER"}, headers={"X-Tenant-Id": other_id})
out["other_qr"] = other.get("/admin/api/qr").json()
out["admin_qr"] = admin.get("/admin/api/qr").json()

# 5) 退出
out["logout"] = admin.post("/api/auth/logout").status_code
out["after_logout"] = admin.get("/", follow_redirects=False).status_code

print(json.dumps(out))
"""


class MultiTenantEndToEndTest(unittest.TestCase):
    def test_full_flow(self):
        with tempfile.TemporaryDirectory() as data_dir:
            env = dict(os.environ)
            env["WHATSAPP_BOT_DATA_DIR"] = data_dir
            env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")

            proc = subprocess.run(
                [sys.executable, "-c", PROBE],
                cwd=str(ROOT), env=env,
                capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr[-2000:])
            out = json.loads(proc.stdout.strip().splitlines()[-1])

            self.assertEqual(out["anon_home"], 302, "未登录访问首页应跳转")
            self.assertEqual(out["anon_api"], 401, "未登录访问 API 应 401")

            self.assertEqual(out["bootstrap"], 200)
            self.assertEqual(out["home_after_login"], 200)
            self.assertEqual(out["admin_me"]["email"], "owner@example.com")

            self.assertEqual(out["register"], 200)
            self.assertEqual(out["other_me"]["email"], "user2@example.com")

            self.assertEqual(out["admin_customers"], 1, "管理员应看到自己的客户")
            self.assertEqual(out["other_customers"], 0, "第二个用户不应看到别人的客户")

            self.assertEqual(out["other_qr"]["qr_text"], "2@OTHER")
            self.assertEqual(out["admin_qr"]["status"], "none", "二维码不能串租户")

            self.assertEqual(out["logout"], 200)
            self.assertEqual(out["after_logout"], 302)


if __name__ == "__main__":
    unittest.main()
