"""Regression tests for TASK-001 reliability fixes.

Run from the repository root:
    PYTHONPATH=src python -m unittest discover -s tests -v
"""
from __future__ import annotations

import asyncio
import io
import sqlite3
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import config as config_module  # noqa: E402
from config import (  # noqa: E402
    AIConfig, APIConfig, AppConfig, BridgeConfig, BusinessConfig, Config,
    DatabaseConfig, SchedulerConfig,
)
import bot_state  # noqa: E402
import database  # noqa: E402
import message_router  # noqa: E402
import scheduler  # noqa: E402
import send_service  # noqa: E402
from bot_state import (  # noqa: E402
    is_paused, was_batch_pushed_today,
)
from database import (  # noqa: E402
    close_db, count_sent_messages_today, get_connection, get_daily_quota_usage,
    get_message, get_or_create_customer, record_followup, release_daily_quota,
    reserve_daily_quota, save_message, update_message_delivery,
)
from send_service import (  # noqa: E402
    apply_delivery_receipt, check_proactive_eligibility, send_followup_now,
    send_manual_message,
)


class ReliabilityTestCase(unittest.TestCase):
    """Fresh temporary SQLite database + isolated config for every test."""

    create_db = True

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmp.name) / "test.db"
        cfg = Config(
            app=AppConfig(timezone="Asia/Shanghai"),
            business=BusinessConfig(
                quiet_hours_start=0, quiet_hours_end=0,  # 0..0 is never quiet
                max_auto_replies_per_hour=1000,
                max_auto_replies_per_day=40,
                min_delay_between_messages_seconds=0,
            ),
            ai=AIConfig(reply_cooldown_minutes=0),
            scheduler=SchedulerConfig(followup_check_interval_minutes=5),
            database=DatabaseConfig(path=str(self.db_path)),
            bridge=BridgeConfig(host="127.0.0.1", port=3999),
            api=APIConfig(host="127.0.0.1", port=8999),
        )
        config_module._config = cfg
        close_db()
        if self.create_db:
            get_connection()
            bot_state.set_paused(False)
            bot_state.set_proactive_followups_enabled(True)

    def tearDown(self):
        close_db()
        config_module._config = None
        self.tmp.cleanup()

    # ── helpers ────────────────────────────────────────────────────────────

    def add_customer(self, phone: str, status: str = "active",
                     name: str = "Test Customer") -> int:
        customer = get_or_create_customer(phone, name)
        if status != "active":
            conn = get_connection()
            conn.execute("UPDATE customers SET status=? WHERE id=?", (status, customer["id"]))
            conn.commit()
        return customer["id"]

    def add_schedule(self, customer_id: int, *, due: bool = True,
                     active: int = 1, frequency_days: int = 7) -> int:
        conn = get_connection()
        next_at = (datetime.now() - timedelta(hours=1) if due
                   else datetime.now() + timedelta(days=1)).isoformat()
        cur = conn.execute(
            "INSERT INTO follow_up_schedule(customer_id,frequency_days,next_followup_at,active) "
            "VALUES(?,?,?,?)",
            (customer_id, frequency_days, next_at, active),
        )
        conn.commit()
        return cur.lastrowid

    def inbound_count(self, customer_id: int) -> int:
        conn = get_connection()
        return conn.execute(
            "SELECT COUNT(*) FROM conversations WHERE customer_id=? AND direction='inbound'",
            (customer_id,),
        ).fetchone()[0]

    def outbound_rows(self, customer_id: int) -> list[dict]:
        conn = get_connection()
        rows = conn.execute(
            "SELECT * FROM conversations WHERE customer_id=? AND direction='outbound' "
            "ORDER BY id", (customer_id,)
        ).fetchall()
        return [dict(r) for r in rows]


class InboundHandlingTests(ReliabilityTestCase):
    def test_pause_stores_inbound_without_llm_or_reply(self):
        bot_state.set_paused(True)
        with patch("message_router.generate_reply", return_value="should not run") as gen, \
             patch("message_router.extract_and_store_memory") as mem:
            result = asyncio.run(
                message_router.handle_incoming_message("+8613900000001", "Need a 1MW genset", "wa-in-1")
            )
            self.assertTrue(result["stored"])
            self.assertEqual(result["reason"], "bot_paused")
            gen.assert_not_called()
            mem.assert_not_called()
        self.assertEqual(self.inbound_count(result["customer_id"]), 1)
        self.assertEqual(self.outbound_rows(result["customer_id"]), [])
        row = get_message(result["conversation_id"])
        self.assertEqual(row["status"], "received")

    def test_duplicate_inbound_is_stored_once_and_has_no_action(self):
        bot_state.set_paused(True)
        with patch("message_router.generate_reply") as gen:
            first = asyncio.run(
                message_router.handle_incoming_message("+8613900000002", "hello", "wa-dup-1")
            )
            second = asyncio.run(
                message_router.handle_incoming_message("+8613900000002", "hello", "wa-dup-1")
            )
        self.assertTrue(first["stored"])
        self.assertFalse(second["stored"])
        self.assertEqual(second["reason"], "duplicate")
        self.assertEqual(self.inbound_count(first["customer_id"]), 1)
        gen.assert_not_called()

    def test_opted_out_stores_inbound_but_never_replies(self):
        cid = self.add_customer("+8613900000003", status="opted_out")
        with patch("message_router.generate_reply") as gen:
            result = asyncio.run(
                message_router.handle_incoming_message("+8613900000003", "Are you there?", "wa-out-1")
            )
        self.assertTrue(result["stored"])
        self.assertEqual(result["reason"], "opted_out")
        self.assertEqual(result["reply_blocked_by"], "contact_status")
        self.assertEqual(self.inbound_count(cid), 1)
        self.assertEqual(self.outbound_rows(cid), [])
        gen.assert_not_called()

    def test_instant_reply_is_pending_until_callback(self):
        cid = self.add_customer("+8613900000004")
        with patch("message_router.generate_reply", return_value="Hello, how can I help?"), \
             patch("message_router.extract_and_store_memory"):
            result = asyncio.run(
                message_router.handle_incoming_message("+8613900000004", "Need a generator", "wa-in-2")
            )
        self.assertEqual(result["action"], "reply")
        out_id = result["conversation_id"]
        self.assertEqual(get_message(out_id)["status"], "pending")
        self.assertEqual(count_sent_messages_today(), 0)

        # Bridge reports a definite failure: the generated text must not count.
        apply_delivery_receipt(out_id, "failed", error="bridge down")
        self.assertEqual(get_message(out_id)["status"], "failed")
        self.assertEqual(count_sent_messages_today(), 0)

        # A later success receipt upgrades failed -> sent and stores the real id.
        apply_delivery_receipt(out_id, "sent", whatsapp_msg_id="wa-real-1")
        row = get_message(out_id)
        self.assertEqual(row["status"], "sent")
        self.assertEqual(row["whatsapp_msg_id"], "wa-real-1")
        self.assertEqual(count_sent_messages_today(), 1)

        # Repeating the receipt is idempotent.
        again = apply_delivery_receipt(out_id, "sent", whatsapp_msg_id="wa-real-1")
        self.assertFalse(again["changed"])
        self.assertEqual(len(self.outbound_rows(cid)), 1)
        # A late failure must not downgrade a confirmed send.
        late = apply_delivery_receipt(out_id, "failed", error="late failure")
        self.assertFalse(late["changed"])
        self.assertEqual(get_message(out_id)["status"], "sent")

    def test_unknown_receipt_is_distinct_from_failure(self):
        cid = self.add_customer("+8613900000005")
        with patch("message_router.generate_reply", return_value="A reply"), \
             patch("message_router.extract_and_store_memory"):
            result = asyncio.run(
                message_router.handle_incoming_message("+8613900000005", "Question?", "wa-in-3")
            )
        out_id = result["conversation_id"]
        apply_delivery_receipt(out_id, "unknown", error="timeout")
        row = get_message(out_id)
        self.assertEqual(row["status"], "unknown")
        self.assertEqual(count_sent_messages_today(), 0)
        self.assertEqual(len(self.outbound_rows(cid)), 1)


class ManualSendTests(ReliabilityTestCase):
    def test_manual_chat_is_independent_of_proactive_switch_and_quota(self):
        cid = self.add_customer("+8613900000010")
        bot_state.set_paused(True)
        bot_state.set_proactive_followups_enabled(False)
        config_module._config.business.max_auto_replies_per_day = 1
        # Exhaust the proactive quota.
        self.assertTrue(reserve_daily_quota(1))
        before = get_daily_quota_usage()["total"]

        with patch("send_service.send_message", new_callable=AsyncMock,
                   return_value={"status": "sent", "message_id": "wa-manual-1"}):
            result = asyncio.run(send_manual_message(cid, "+8613900000010", "Hello from a human"))

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "sent")
        row = get_message(result["conversation_id"])
        self.assertEqual(row["status"], "sent")
        self.assertEqual(row["whatsapp_msg_id"], "wa-manual-1")
        self.assertEqual(row["send_kind"], "manual")
        # Human chat does not consume the proactive quota.
        self.assertEqual(get_daily_quota_usage()["total"], before)
        self.assertEqual(count_sent_messages_today(), 1)


class BridgeResultTests(ReliabilityTestCase):
    @staticmethod
    def _response(status_code, data):
        class FakeResponse:
            def __init__(self):
                self.status_code = status_code
                self._data = data
                self.reason_phrase = "test"

            def json(self):
                return self._data

        return FakeResponse()

    @staticmethod
    def _client(response=None, exc=None):
        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def post(self, *args, **kwargs):
                if exc:
                    raise exc
                return response

        return FakeClient()

    def test_timeout_is_unknown_not_failed(self):
        import bridge_client
        import httpx
        client = self._client(exc=httpx.ReadTimeout("timeout"))
        with patch("bridge_client.httpx.AsyncClient", return_value=client):
            result = asyncio.run(bridge_client.send_message("+8613900000006", "hi"))
        self.assertEqual(result["status"], "unknown")
        self.assertEqual(result["error_code"], "timeout")

    def test_connect_error_is_definite_failure(self):
        import bridge_client
        import httpx
        client = self._client(exc=httpx.ConnectError("down"))
        with patch("bridge_client.httpx.AsyncClient", return_value=client):
            result = asyncio.run(bridge_client.send_message("+8613900000007", "hi", max_retries=1))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "bridge_unreachable")

    def test_sent_result_keeps_platform_message_id(self):
        import bridge_client
        client = self._client(response=self._response(200, {"status": "sent", "message_id": "wa-2"}))
        with patch("bridge_client.httpx.AsyncClient", return_value=client):
            result = asyncio.run(bridge_client.send_message("+8613900000008", "hi"))
        self.assertEqual(result["status"], "sent")
        self.assertEqual(result["message_id"], "wa-2")

    def test_unauthenticated_bridge_is_failed(self):
        import bridge_client
        client = self._client(response=self._response(503, {"error": "not authenticated"}))
        with patch("bridge_client.httpx.AsyncClient", return_value=client):
            result = asyncio.run(bridge_client.send_message("+8613900000009", "hi", max_retries=1))
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["error_code"], "bridge_unauthenticated")


class ProactiveSendTests(ReliabilityTestCase):
    def test_switch_off_blocks_automatic_send_and_scheduler_ticks(self):
        cid = self.add_customer("+8613910000001")
        sid = self.add_schedule(cid)
        bot_state.set_proactive_followups_enabled(False)
        with patch("send_service.send_message", new_callable=AsyncMock,
                   return_value={"status": "sent", "message_id": "wa-mock"}) as bridge, \
             patch("send_service._message_for_target", return_value="follow up"):
            result = asyncio.run(send_followup_now(sid, manual=False))
            self.assertEqual(result["status"], "blocked")
            self.assertEqual(result["reason"], "proactive_disabled")
            bridge.assert_not_awaited()

            check = asyncio.run(scheduler.check_followups())
            self.assertEqual(check.get("skipped"), "proactive_disabled")
            batch = asyncio.run(scheduler.auto_batch_push())
            self.assertEqual(batch.get("skipped"), "proactive_disabled")
        self.assertEqual(self.outbound_rows(cid), [])
        self.assertFalse(was_batch_pushed_today())

    def test_manual_override_is_explicit_and_cannot_override_pause(self):
        cid = self.add_customer("+8613910000002")
        sid = self.add_schedule(cid)
        bot_state.set_proactive_followups_enabled(False)
        with patch("send_service.send_message", new_callable=AsyncMock,
                   return_value={"status": "sent", "message_id": "wa-mock"}) as bridge, \
             patch("send_service._message_for_target", return_value="follow up"):
            blocked = asyncio.run(send_followup_now(sid, manual=True))
            self.assertEqual(blocked["status"], "blocked")
            self.assertIn("proactive_disabled", blocked["overridable_reasons"])
            bridge.assert_not_awaited()

            allowed = asyncio.run(send_followup_now(
                sid, manual=True, overrides=["proactive_disabled"]
            ))
            self.assertEqual(allowed["status"], "sent")
            self.assertIn("proactive_disabled", allowed["overrides_applied"])
            bridge.assert_awaited_once()

        # A new due schedule is required for another attempt.
        cid2 = self.add_customer("+8613910000003")
        sid2 = self.add_schedule(cid2)
        bot_state.set_paused(True)
        with patch("send_service.send_message", new_callable=AsyncMock,
                   return_value={"status": "sent", "message_id": "wa-mock"}) as bridge, \
             patch("send_service._message_for_target", return_value="follow up"):
            paused = asyncio.run(send_followup_now(
                sid2, manual=True, overrides=["bot_paused", "proactive_disabled"]
            ))
            self.assertEqual(paused["reason"], "bot_paused")
            bridge.assert_not_awaited()

    def test_contact_status_and_inactive_schedule_are_not_overridable(self):
        cid = self.add_customer("+8613910000004", status="blocked")
        sid = self.add_schedule(cid)
        with patch("send_service.send_message", new_callable=AsyncMock,
                   return_value={"status": "sent", "message_id": "wa-mock"}) as bridge, \
             patch("send_service._message_for_target", return_value="follow up"):
            result = asyncio.run(send_followup_now(sid, manual=True, overrides=["customer_blocked"]))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "customer_blocked")
        bridge.assert_not_awaited()

        cid2 = self.add_customer("+8613910000005")
        sid2 = self.add_schedule(cid2, active=0)
        with patch("send_service.send_message", new_callable=AsyncMock,
                   return_value={"status": "sent", "message_id": "wa-mock"}) as bridge, \
             patch("send_service._message_for_target", return_value="follow up"):
            result = asyncio.run(send_followup_now(sid2, manual=True, overrides=["schedule_inactive"]))
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["reason"], "schedule_inactive")
        bridge.assert_not_awaited()

    def test_failure_releases_quota_and_unknown_keeps_it(self):
        # Definite failure: slot is released, so a subsequent attempt can send.
        cid = self.add_customer("+8613910000006")
        sid = self.add_schedule(cid)
        bot_state.set_paused(False)
        with patch("send_service._message_for_target", return_value="follow up"), \
             patch("send_service.send_message", new_callable=AsyncMock,
                   return_value={"status": "failed", "error": "bridge down"}) as bridge:
            failed = asyncio.run(send_followup_now(sid, manual=False))
            self.assertEqual(failed["status"], "failed")
            usage = get_daily_quota_usage()
            self.assertEqual(usage["total"], 0)
            bridge.assert_awaited_once()

            with patch("send_service.send_message", new_callable=AsyncMock,
                       return_value={"status": "sent", "message_id": "wa-3"}):
                sent = asyncio.run(send_followup_now(sid, manual=False))
            self.assertEqual(sent["status"], "sent")
            self.assertEqual(get_daily_quota_usage()["used"], 1)

        # Unknown: keep the quota and advance the schedule so there is no blind retry.
        cid2 = self.add_customer("+8613910000007")
        sid2 = self.add_schedule(cid2)
        used_before = get_daily_quota_usage()["used"]
        sent_before = count_sent_messages_today("proactive")
        with patch("send_service._message_for_target", return_value="follow up"), \
             patch("send_service.send_message", new_callable=AsyncMock,
                   return_value={"status": "unknown", "error": "timeout"}) as bridge:
            unknown = asyncio.run(send_followup_now(sid2, manual=False))
            self.assertEqual(unknown["status"], "unknown")
            self.assertEqual(get_daily_quota_usage()["used"], used_before + 1)
            self.assertEqual(count_sent_messages_today("proactive"), sent_before)
            bridge.assert_awaited_once()
            retry = asyncio.run(send_followup_now(sid2, manual=False))
            self.assertEqual(retry["status"], "blocked")  # not_due or quota
            bridge.assert_awaited_once()  # no automatic retry
        conn = get_connection()
        row = conn.execute(
            "SELECT status FROM sent_followups WHERE schedule_id=?", (sid2,)
        ).fetchone()
        self.assertEqual(row["status"], "unknown")

    def test_pause_during_batch_stops_remaining_sends(self):
        cid1 = self.add_customer("+8613910000008", name="One")
        cid2 = self.add_customer("+8613910000009", name="Two")
        self.add_schedule(cid1)
        self.add_schedule(cid2)

        calls = {"n": 0}

        async def fake_bridge(phone, message):
            calls["n"] += 1
            bot_state.set_paused(True)  # user pauses while the first send is in flight
            return {"status": "sent", "message_id": "wa-batch-1"}

        with patch("send_service._message_for_target", return_value="follow up"), \
             patch("send_service.send_message", side_effect=fake_bridge), \
             patch("scheduler.get_random_delay", return_value=0):
            result = asyncio.run(scheduler.check_followups())

        self.assertEqual(calls["n"], 1)
        self.assertEqual(result.get("sent"), 1)
        self.assertEqual(result.get("blocked"), 1)

    def test_concurrent_manual_and_auto_paths_cannot_exceed_quota(self):
        config_module._config.business.max_auto_replies_per_day = 1
        cid1 = self.add_customer("+8613910000010")
        cid2 = self.add_customer("+8613910000011")
        sid1 = self.add_schedule(cid1)
        sid2 = self.add_schedule(cid2)

        async def fake_bridge(phone, message):
            await asyncio.sleep(0.05)
            return {"status": "sent", "message_id": "wa-concurrent"}

        async def run_both():
            return await asyncio.gather(
                send_followup_now(sid1, manual=True),
                send_followup_now(sid2, manual=False),
            )

        with patch("send_service._message_for_target", return_value="follow up"), \
             patch("send_service.send_message", side_effect=fake_bridge) as bridge:
            results = asyncio.run(run_both())

        statuses = sorted(r["status"] for r in results)
        self.assertEqual(statuses, ["blocked", "sent"])
        self.assertEqual(bridge.await_count, 1)
        self.assertEqual(get_daily_quota_usage()["used"], 1)

    def test_same_schedule_cannot_be_sent_twice_concurrently(self):
        cid = self.add_customer("+8613910000013")
        sid = self.add_schedule(cid)

        async def fake_bridge(phone, message):
            await asyncio.sleep(0.05)
            return {"status": "sent", "message_id": "wa-claim-1"}

        async def run_both():
            return await asyncio.gather(
                send_followup_now(sid, manual=True),
                send_followup_now(sid, manual=True),
            )

        with patch("send_service._message_for_target", return_value="follow up"), \
             patch("send_service.send_message", side_effect=fake_bridge) as bridge:
            results = asyncio.run(run_both())

        statuses = sorted(r["status"] for r in results)
        self.assertEqual(statuses, ["blocked", "sent"])
        self.assertEqual(bridge.await_count, 1)
        blocked = [r for r in results if r["status"] == "blocked"][0]
        self.assertEqual(blocked["reason"], "already_sending")
        self.assertEqual(get_daily_quota_usage()["used"], 1)

    def test_quota_reservation_is_atomic_across_threads(self):
        results: list[bool] = []
        barrier = threading.Barrier(12)

        def worker():
            barrier.wait()
            results.append(reserve_daily_quota(3))

        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(sum(1 for r in results if r), 3)
        self.assertEqual(get_daily_quota_usage()["reserved"], 3)
        for _ in range(3):
            release_daily_quota()
        self.assertEqual(get_daily_quota_usage()["total"], 0)

    def test_quiet_hours_is_overridable_only_by_manual_action(self):
        config_module._config.business.quiet_hours_start = 0
        config_module._config.business.quiet_hours_end = 23
        cid = self.add_customer("+8613910000012")
        sid = self.add_schedule(cid)
        with patch("send_service.send_message", new_callable=AsyncMock,
                   return_value={"status": "sent", "message_id": "wa-mock"}) as bridge, \
             patch("send_service._message_for_target", return_value="follow up"):
            auto = asyncio.run(send_followup_now(sid, manual=False))
            self.assertEqual(auto["reason"], "quiet_hours")
            self.assertEqual(auto["overridable_reasons"], [])
            bridge.assert_not_awaited()

            manual = asyncio.run(send_followup_now(
                sid, manual=True, overrides=["quiet_hours"]
            ))
            self.assertEqual(manual["status"], "sent")
            self.assertIn("quiet_hours", manual["overrides_applied"])


class MigrationTests(ReliabilityTestCase):
    create_db = False

    def test_legacy_database_upgrade_preserves_rows_and_is_idempotent(self):
        close_db()
        # Build an old-style database without the delivery columns.
        conn = sqlite3.connect(str(self.db_path))
        conn.executescript("""
            CREATE TABLE customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                email TEXT,
                company TEXT,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                tags TEXT DEFAULT '[]',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL REFERENCES customers(id),
                direction TEXT NOT NULL,
                message_type TEXT NOT NULL DEFAULT 'text',
                content TEXT NOT NULL,
                whatsapp_msg_id TEXT,
                ai_generated INTEGER DEFAULT 0,
                sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE follow_up_schedule (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_id INTEGER NOT NULL REFERENCES customers(id),
                frequency_days INTEGER NOT NULL DEFAULT 7,
                last_followup_at TIMESTAMP,
                next_followup_at TIMESTAMP,
                template TEXT,
                active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO follow_up_schedule(customer_id,frequency_days,next_followup_at,active)
                VALUES(1,7,'2026-01-01T00:00:00',1);
            INSERT INTO customers(phone,name) VALUES('+8613920000001','Legacy');
            INSERT INTO conversations(customer_id,direction,content,whatsapp_msg_id,ai_generated)
                VALUES(1,'inbound','old inbound',NULL,0);
            INSERT INTO conversations(customer_id,direction,content,whatsapp_msg_id,ai_generated)
                VALUES(1,'outbound','old outbound with id','wa-old-1',1);
            INSERT INTO conversations(customer_id,direction,content,whatsapp_msg_id,ai_generated)
                VALUES(1,'outbound','old outbound without id',NULL,1);
        """)
        conn.commit()
        legacy_count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        conn.close()

        upgraded = get_connection()
        rows = [dict(r) for r in upgraded.execute(
            "SELECT content,direction,status,send_kind,whatsapp_msg_id "
            "FROM conversations ORDER BY id"
        ).fetchall()]
        self.assertEqual(len(rows), legacy_count)
        self.assertEqual(rows[0]["status"], "received")
        self.assertEqual(rows[1]["status"], "sent")
        self.assertEqual(rows[1]["whatsapp_msg_id"], "wa-old-1")
        self.assertEqual(rows[2]["status"], "unknown")
        self.assertEqual(len([r for r in rows if r["status"] == "unknown"]), 1)
        schedule_cols = {r[1] for r in upgraded.execute("PRAGMA table_info(follow_up_schedule)").fetchall()}
        self.assertIn("sending_since", schedule_cols)
        self.assertEqual(
            upgraded.execute("SELECT COUNT(*) FROM follow_up_schedule").fetchone()[0], 1
        )
        migrations = upgraded.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
        self.assertEqual(migrations, 2)

        # Close/reopen applies no duplicate migration and loses no rows.
        close_db()
        upgraded = get_connection()
        self.assertEqual(
            upgraded.execute("SELECT COUNT(*) FROM conversations").fetchone()[0], legacy_count
        )
        self.assertEqual(
            upgraded.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0], 2
        )


class AdminApiTests(ReliabilityTestCase):
    def setUp(self):
        super().setUp()
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import admin_api
        app = FastAPI()
        app.include_router(admin_api.router)
        self.client = TestClient(app)

    def test_proactive_setting_persists_across_reads(self):
        # Simulate a never-configured install (the base fixture enables it).
        conn = get_connection()
        conn.execute("DELETE FROM bot_state WHERE key='proactive_followups_enabled'")
        conn.commit()
        r = self.client.get("/admin/api/settings/proactive-followups")
        self.assertEqual(r.status_code, 200)
        self.assertFalse(r.json()["enabled"])
        self.assertFalse(r.json()["configured"])
        self.assertEqual(r.json()["applies_to"], ["followup_check_5m", "auto_batch_10am"])

        put = self.client.put("/admin/api/settings/proactive-followups", json={"enabled": True})
        self.assertTrue(put.json()["ok"])
        self.assertTrue(put.json()["enabled"])
        self.assertTrue(put.json()["configured"])

        self.assertTrue(self.client.get("/admin/api/settings/proactive-followups").json()["enabled"])
        self.assertTrue(bot_state.is_proactive_followups_enabled())
        self.assertTrue(self.client.get("/admin/api/bot-state").json()["proactive_followups_enabled"])

        # Survives a backend restart (new connection to the same SQLite file).
        close_db()
        get_connection()
        self.assertTrue(self.client.get("/admin/api/settings/proactive-followups").json()["enabled"])

    def test_batch_start_requires_confirmation_and_non_empty_queue(self):
        # Empty queue: even a confirmed request must not mark the day.
        r = self.client.post("/admin/api/followups/batch/start", json={"confirmed": True})
        self.assertFalse(r.json()["ok"])
        self.assertEqual(r.json()["status"], "empty")
        self.assertFalse(was_batch_pushed_today())

        cid = self.add_customer("+8613930000001")
        self.add_schedule(cid)

        # Missing confirmation: do not mark.
        r = self.client.post("/admin/api/followups/batch/start", json={})
        self.assertFalse(r.json()["ok"])
        self.assertEqual(r.json()["status"], "not_confirmed")
        self.assertFalse(was_batch_pushed_today())

        # Legacy mark endpoint is guarded the same way.
        r = self.client.post("/admin/api/followups/mark-batch-pushed", json={})
        self.assertFalse(r.json()["ok"])
        self.assertFalse(was_batch_pushed_today())

        # Confirmed, non-empty queue: mark only now.
        r = self.client.post("/admin/api/followups/batch/start", json={"confirmed": True})
        self.assertTrue(r.json()["ok"])
        self.assertTrue(r.json()["marked"])
        self.assertTrue(was_batch_pushed_today())

    def test_batch_start_does_not_mark_when_paused(self):
        cid = self.add_customer("+8613930000002")
        self.add_schedule(cid)
        bot_state.set_paused(True)
        r = self.client.post("/admin/api/followups/batch/start", json={"confirmed": True})
        self.assertFalse(r.json()["ok"])
        self.assertEqual(r.json()["reason"], "bot_paused")
        self.assertFalse(was_batch_pushed_today())

    def test_send_now_endpoint_uses_unified_service(self):
        cid = self.add_customer("+8613930000004")
        sid = self.add_schedule(cid)
        with patch("send_service._message_for_target", return_value="follow up"), \
             patch("send_service.send_message", new_callable=AsyncMock,
                   return_value={"status": "sent", "message_id": "wa-api-1"}):
            r = self.client.post(f"/admin/api/followups/{sid}/send-now", json={})
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["status"], "sent")
        self.assertEqual(body["message_id"], "wa-api-1")
        conv = get_message(body["conversation_id"])
        self.assertEqual(conv["status"], "sent")
        self.assertEqual(conv["send_kind"], "proactive")

    def test_send_manual_endpoint_records_delivery_state(self):
        cid = self.add_customer("+8613930000005")
        with patch("send_service.send_message", new_callable=AsyncMock,
                   return_value={"status": "failed", "error": "bridge down"}):
            r = self.client.post("/admin/api/send-manual", json={
                "customer_id": cid,
                "phone": "+8613930000005",
                "message": "human message",
            })
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["status"], "failed")
        self.assertEqual(body["bridge_result"]["status"], "failed")
        rows = self.outbound_rows(cid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "failed")
        self.assertEqual(rows[0]["send_kind"], "manual")
        self.assertEqual(count_sent_messages_today(), 0)

    def test_dashboard_counts_only_sent_and_shows_unknown_separately(self):
        cid = self.add_customer("+8613930000003")
        conn = get_connection()
        today = datetime.now().isoformat()
        for status, kind in [("sent", "proactive"), ("failed", "proactive"), ("unknown", "proactive")]:
            conn.execute(
                "INSERT INTO conversations(customer_id,direction,content,ai_generated,sent_at,status,send_kind,updated_at) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (cid, "outbound", status, 1, today, status, kind, today),
            )
        conn.commit()
        with patch("admin_api._get_bridge_status", new_callable=AsyncMock,
                   return_value={"online": False, "authenticated": False, "phone": None}):
            r = self.client.get("/admin/api/dashboard")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["counts"]["today_ai_replies"], 1)
        self.assertEqual(r.json()["counts"]["unknown_fu_today"], 0)  # no sent_followups rows yet

        conn.execute(
            "INSERT INTO sent_followups(customer_id,status,error_message,sent_at) VALUES(?,?,?,?)",
            (cid, "unknown", "timeout", today),
        )
        conn.commit()
        with patch("admin_api._get_bridge_status", new_callable=AsyncMock,
                   return_value={"online": False, "authenticated": False, "phone": None}):
            r = self.client.get("/admin/api/dashboard")
        self.assertEqual(r.json()["counts"]["unknown_fu_today"], 1)
        self.assertEqual(r.json()["counts"]["sent_fu_today"], 0)


if __name__ == "__main__":
    unittest.main()
