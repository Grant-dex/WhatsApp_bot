"""bridge_manager 与多租户调度的单元测试。

不启动真实 Node 进程，只验证端口分配、注册表持久化、租户上下文解析，
以及调度器"遍历所有租户"的行为。
"""
from __future__ import annotations

import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import tenancy  # noqa: E402
from tenancy import Tenant  # noqa: E402


class BridgeManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wa-bridge-"))
        self._old_env = os.environ.get("WHATSAPP_BOT_DATA_DIR")
        os.environ["WHATSAPP_BOT_DATA_DIR"] = str(self.tmp)
        self.bm = importlib.reload(importlib.import_module("bridge_manager"))
        self.bm._ports.clear()
        self.bm._procs.clear()

    def tearDown(self):
        token = tenancy.set_current(None)
        tenancy.reset_current(token)
        if self._old_env is None:
            os.environ.pop("WHATSAPP_BOT_DATA_DIR", None)
        else:
            os.environ["WHATSAPP_BOT_DATA_DIR"] = self._old_env

    def test_ports_are_unique_and_in_pool(self):
        p1 = self.bm._allocate_port()
        self.bm._ports["u1"] = p1
        p2 = self.bm._allocate_port()
        self.assertNotEqual(p1, p2)
        self.assertGreaterEqual(p1, 3101)
        self.assertLessEqual(p2, 3999)

    def test_registry_roundtrip(self):
        self.bm._ports["u1"] = 3111
        self.bm._save_registry()
        self.bm._ports.clear()
        self.bm._load_registry()
        self.assertEqual(self.bm.port_for("u1"), 3111)
        self.assertTrue((self.tmp / "bridges.json").exists())

    def test_current_port_follows_tenant(self):
        self.bm._ports["u2"] = 3222
        tenant = Tenant("u2", "u2@example.com", self.tmp / "tenants" / "u2")
        token = tenancy.set_current(tenant)
        try:
            self.assertEqual(self.bm.current_port(), 3222)
        finally:
            tenancy.reset_current(token)

    def test_current_port_falls_back_to_config(self):
        import config as config_module

        config_module.load_config(str(ROOT / "config.yaml"))
        self.assertEqual(self.bm.current_port(), config_module.get_config().bridge.port)

    def test_status_without_tenant(self):
        self.assertEqual(self.bm.status()["online"], False)


class SchedulerTenantTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wa-sched-"))
        self._old_env = os.environ.get("WHATSAPP_BOT_DATA_DIR")
        os.environ["WHATSAPP_BOT_DATA_DIR"] = str(self.tmp)

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("WHATSAPP_BOT_DATA_DIR", None)
        else:
            os.environ["WHATSAPP_BOT_DATA_DIR"] = self._old_env

    def test_runs_job_once_per_user(self):
        import scheduler

        users = [
            {"id": "u1", "email": "u1@example.com", "data_dir": str(self.tmp / "t1")},
            {"id": "u2", "email": "u2@example.com", "data_dir": str(self.tmp / "t2")},
        ]
        seen = []
        with patch("accounts.list_users", return_value=users):
            scheduler._run_for_tenants(
                lambda: seen.append(tenancy.current().user_id))
        self.assertEqual(seen, ["u1", "u2"])

    def test_falls_back_to_single_run_without_users(self):
        import scheduler

        seen = []
        with patch("accounts.list_users", return_value=[]):
            scheduler._run_for_tenants(
                lambda: seen.append(tenancy.current()))
        self.assertEqual(seen, [None])


if __name__ == "__main__":
    unittest.main()


class BridgeWatchdogTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wa-watchdog-"))
        self._old_env = os.environ.get("WHATSAPP_BOT_DATA_DIR")
        os.environ["WHATSAPP_BOT_DATA_DIR"] = str(self.tmp)
        self.bm = importlib.reload(importlib.import_module("bridge_manager"))
        self.bm._ports.clear()
        self.bm._procs.clear()
        self.bm._enabled.clear()
        self.bm._restarts.clear()

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("WHATSAPP_BOT_DATA_DIR", None)
        else:
            os.environ["WHATSAPP_BOT_DATA_DIR"] = self._old_env

    def _tenant(self):
        return Tenant("u1", "u1@example.com", self.tmp / "tenants" / "u1")

    def test_restarts_dead_bridge_once(self):
        self.bm._ports["u1"] = 3999
        self.bm._enabled["u1"] = True
        calls = []
        with patch.object(self.bm, "_alive", return_value=False), \
             patch.object(self.bm, "_tenant_for", return_value=self._tenant()), \
             patch.object(self.bm, "start", side_effect=lambda t: calls.append(t) or {"online": True, "port": 3999}):
            results = self.bm.reconcile()
        self.assertEqual(len(calls), 1)
        self.assertEqual(results[0]["action"], "restarted")

    def test_healthy_bridge_is_left_alone(self):
        self.bm._ports["u1"] = 3999
        self.bm._enabled["u1"] = True
        with patch.object(self.bm, "_alive", return_value=True), \
             patch.object(self.bm, "start") as start_mock:
            self.bm.reconcile()
        start_mock.assert_not_called()

    def test_gives_up_after_repeated_crashes(self):
        self.bm._ports["u1"] = 3999
        self.bm._enabled["u1"] = True
        import time as _time
        self.bm._restarts["u1"] = [_time.time() for _ in range(3)]
        with patch.object(self.bm, "_alive", return_value=False), \
             patch.object(self.bm, "start") as start_mock:
            results = self.bm.reconcile()
        start_mock.assert_not_called()
        self.assertEqual(results[0]["action"], "disabled")
        self.assertNotIn("u1", self.bm._enabled)

    def test_started_bridge_is_marked_enabled(self):
        tenant = self._tenant()
        self.bm._enabled.clear()
        fake_proc = unittest.mock.MagicMock()
        fake_proc.poll.return_value = None
        fake_proc.pid = 123

        with patch.object(self.bm, "_node_bin", return_value="/usr/bin/node"), \
             patch.object(self.bm, "_allocate_port", return_value=3998), \
             patch.object(self.bm, "_alive", return_value=True), \
             patch.object(self.bm, "_api_port", return_value=8000), \
             patch.object(self.bm.subprocess, "Popen", return_value=fake_proc), \
             patch.object(self.bm, "_save_registry"):
            self.bm.start(tenant)
        self.assertTrue(self.bm._enabled.get("u1"))
