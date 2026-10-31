"""多租户认证与隔离的单元测试。

运行：
    PYTHONPATH=src .venv/bin/python -m unittest tests.test_auth -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import accounts  # noqa: E402
import config as config_module  # noqa: E402
import database  # noqa: E402
import tenancy  # noqa: E402
from tenancy import Tenant  # noqa: E402


def _write_config(path: Path, company: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "app:\n  name: {c}\nbusiness:\n  company_name: {c}\n"
        "database:\n  path: ./data/customers.db\n".format(c=company),
        encoding="utf-8",
    )


class PasswordTests(unittest.TestCase):
    def test_roundtrip(self):
        stored = accounts.hash_password("supersecret1")
        self.assertTrue(stored.startswith("scrypt$"))
        self.assertTrue(accounts.verify_password("supersecret1", stored))

    def test_wrong_password(self):
        stored = accounts.hash_password("supersecret1")
        self.assertFalse(accounts.verify_password("supersecret2", stored))
        self.assertFalse(accounts.verify_password("", stored))
        self.assertFalse(accounts.verify_password("x", "garbage"))

    def test_salt_is_random(self):
        a = accounts.hash_password("samepassword")
        b = accounts.hash_password("samepassword")
        self.assertNotEqual(a, b)
        self.assertTrue(accounts.verify_password("samepassword", a))
        self.assertTrue(accounts.verify_password("samepassword", b))

    def test_min_length(self):
        with self.assertRaises(ValueError):
            accounts.hash_password("short")


class TenantIsolationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wa-tenant-"))
        self._old_env = os.environ.get("WHATSAPP_BOT_DATA_DIR")
        os.environ["WHATSAPP_BOT_DATA_DIR"] = str(self.tmp)
        # 清掉可能被别的测试留下的全局配置/连接
        config_module._config = None
        config_module._config_cache.clear()
        database.close_db()
        accounts.reset_for_tests()

        self.a_dir = self.tmp / "tenants" / "user-a"
        self.b_dir = self.tmp / "tenants" / "user-b"
        _write_config(self.a_dir / "config.yaml", "CompanyA")
        _write_config(self.b_dir / "config.yaml", "CompanyB")

    def tearDown(self):
        database.close_db()
        accounts.reset_for_tests()
        tenancy.reset_current(tenancy.set_current(None))
        if self._old_env is None:
            os.environ.pop("WHATSAPP_BOT_DATA_DIR", None)
        else:
            os.environ["WHATSAPP_BOT_DATA_DIR"] = self._old_env

    def _tenant(self, name: str, path: Path) -> Tenant:
        return Tenant(user_id=name, email=f"{name}@example.com", data_dir=path)

    def test_config_follows_tenant(self):
        token = tenancy.set_current(self._tenant("a", self.a_dir))
        try:
            self.assertEqual(config_module.get_config().business.company_name, "CompanyA")
        finally:
            tenancy.reset_current(token)

        token = tenancy.set_current(self._tenant("b", self.b_dir))
        try:
            self.assertEqual(config_module.get_config().business.company_name, "CompanyB")
        finally:
            tenancy.reset_current(token)

    def test_database_files_are_separate(self):
        token = tenancy.set_current(self._tenant("a", self.a_dir))
        try:
            conn_a = database.get_connection()
            conn_a.execute(
                "INSERT INTO customers(phone,name) VALUES(?,?)",
                ("+15550000001", "A 的客户"),
            )
            conn_a.commit()
            a_path = config_module.get_config().database.path
        finally:
            tenancy.reset_current(token)

        token = tenancy.set_current(self._tenant("b", self.b_dir))
        try:
            conn_b = database.get_connection()
            b_count = conn_b.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
            b_path = config_module.get_config().database.path
        finally:
            tenancy.reset_current(token)

        self.assertNotEqual(a_path, b_path)
        self.assertEqual(b_count, 0, "B 不应该看到 A 的客户")

    def test_tenant_dirs_are_created(self):
        path = tenancy.ensure_tenant_dir("user-c", template=ROOT / "config.yaml")
        self.assertTrue((path / "config.yaml").exists())
        self.assertTrue((path / "logs").is_dir())


class AccountStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wa-accounts-"))
        self._old_env = os.environ.get("WHATSAPP_BOT_DATA_DIR")
        os.environ["WHATSAPP_BOT_DATA_DIR"] = str(self.tmp)
        accounts.reset_for_tests()

    def tearDown(self):
        accounts.reset_for_tests()
        if self._old_env is None:
            os.environ.pop("WHATSAPP_BOT_DATA_DIR", None)
        else:
            os.environ["WHATSAPP_BOT_DATA_DIR"] = self._old_env

    def test_create_and_authenticate(self):
        user = accounts.create_user("owner@example.com", "supersecret1", self.tmp)
        self.assertEqual(accounts.count_users(), 1)
        self.assertEqual(accounts.authenticate("owner@example.com", "supersecret1")["id"],
                         user["id"])
        self.assertIsNone(accounts.authenticate("owner@example.com", "wrongpass"))
        self.assertIsNone(accounts.authenticate("nobody@example.com", "supersecret1"))

    def test_duplicate_email_rejected(self):
        accounts.create_user("dup@example.com", "supersecret1", self.tmp)
        with self.assertRaises(ValueError):
            accounts.create_user("DUP@example.com", "supersecret2", self.tmp)

    def test_session_lifecycle(self):
        user = accounts.create_user("s@example.com", "supersecret1", self.tmp)
        token = accounts.create_session(user["id"])
        session = accounts.resolve_session(token)
        self.assertIsNotNone(session)
        self.assertEqual(session["email"], "s@example.com")

        accounts.revoke_session(token)
        self.assertIsNone(accounts.resolve_session(token))
        self.assertIsNone(accounts.resolve_session("bogus-token"))


if __name__ == "__main__":
    unittest.main()
