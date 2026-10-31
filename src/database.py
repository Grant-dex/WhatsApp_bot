from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import get_config

_write_lock = threading.Lock()
# 每个租户一个数据库文件，连接按路径缓存
_conns: dict[str, sqlite3.Connection] = {}

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
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
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    direction TEXT NOT NULL CHECK(direction IN ('inbound','outbound')),
    message_type TEXT NOT NULL DEFAULT 'text',
    content TEXT NOT NULL,
    whatsapp_msg_id TEXT,
    ai_generated INTEGER DEFAULT 0,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- Delivery lifecycle. Inbound rows use 'received'; outbound rows start
    -- as 'pending' and only become 'sent' after the bridge confirms.
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','sent','failed','unknown','received')),
    send_kind TEXT NOT NULL DEFAULT 'legacy'
        CHECK(send_kind IN ('legacy','inbound','instant_reply','proactive','manual')),
    error_message TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS follow_up_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    frequency_days INTEGER NOT NULL DEFAULT 7,
    last_followup_at TIMESTAMP,
    next_followup_at TIMESTAMP,
    template TEXT,
    active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    sending_since TIMESTAMP
);
CREATE TABLE IF NOT EXISTS sent_followups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    schedule_id INTEGER REFERENCES follow_up_schedule(id),
    conversation_id INTEGER REFERENCES conversations(id),
    status TEXT NOT NULL DEFAULT 'sent',
    error_message TEXT,
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_conv_customer ON conversations(customer_id, sent_at);
CREATE INDEX IF NOT EXISTS idx_conv_msg_id ON conversations(whatsapp_msg_id);
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
-- Atomic daily quota counters. used counts confirmed sends and unknown
-- results (an unknown result may have reached WhatsApp); reserved holds
-- in-flight reservations so concurrent senders cannot exceed the limit.
CREATE TABLE IF NOT EXISTS send_quota (
    day TEXT PRIMARY KEY,
    used INTEGER NOT NULL DEFAULT 0,
    reserved INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_followup_next ON follow_up_schedule(next_followup_at) WHERE active=1;
CREATE TABLE IF NOT EXISTS product_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS product_files (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_doc_id INTEGER REFERENCES product_docs(id) ON DELETE CASCADE,
    filename TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'application/pdf',
    file_size INTEGER DEFAULT 0,
    file_data BLOB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_product_files_doc ON product_files(product_doc_id);
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    order_no TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    product TEXT,
    quantity INTEGER DEFAULT 1,
    unit_price REAL,
    total_amount REAL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','confirmed','processing','shipped','delivered','cancelled')),
    order_date TEXT,
    delivery_date TEXT,
    currency TEXT DEFAULT 'USD',
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_orders_customer ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);

-- Agent tables: state persistence, lead scoring, decision log, AI memory
CREATE TABLE IF NOT EXISTS bot_state (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS lead_scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL UNIQUE REFERENCES customers(id),
    score INTEGER NOT NULL DEFAULT 0,
    segment TEXT NOT NULL DEFAULT 'new' CHECK(segment IN ('hot','warm','cold','new','dormant')),
    signals TEXT DEFAULT '{}',
    last_scored_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_lead_scores_segment ON lead_scores(segment);
CREATE INDEX IF NOT EXISTS idx_lead_scores_score ON lead_scores(score DESC);
CREATE TABLE IF NOT EXISTS agent_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER REFERENCES customers(id),
    decision_type TEXT NOT NULL,
    reasoning TEXT,
    context TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_agent_decisions_customer ON agent_decisions(customer_id, created_at);
CREATE TABLE IF NOT EXISTS ai_memory_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    entry_type TEXT NOT NULL DEFAULT 'summary',
    content TEXT NOT NULL,
    importance INTEGER DEFAULT 1,
    conversation_id INTEGER REFERENCES conversations(id),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_memory_customer ON ai_memory_entries(customer_id, created_at);
"""


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _migrate_conversation_delivery(conn: sqlite3.Connection) -> None:
    """Incrementally add delivery-state columns to a legacy database.

    The migration is intentionally idempotent: it checks PRAGMA table_info
    first, so running it twice (or after a partial failure) is safe.

    Legacy rows cannot be re-verified. We preserve them without deleting data:
      * inbound rows become 'received'
      * outbound rows that already carry a real platform id become 'sent'
      * all other legacy outbound rows become 'unknown' rather than claiming
        they were delivered successfully.
    """
    cols = _table_columns(conn, "conversations")
    if "status" not in cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN status TEXT NOT NULL DEFAULT 'unknown'")
    if "send_kind" not in cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN send_kind TEXT NOT NULL DEFAULT 'legacy'")
    if "error_message" not in cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN error_message TEXT")
    if "updated_at" not in cols:
        conn.execute("ALTER TABLE conversations ADD COLUMN updated_at TIMESTAMP")

    conn.execute(
        "UPDATE conversations SET status='received' "
        "WHERE direction='inbound' AND (status IS NULL OR status='' OR status='pending' OR status='unknown')"
    )
    conn.execute(
        "UPDATE conversations SET status='sent' "
        "WHERE direction='outbound' AND whatsapp_msg_id IS NOT NULL AND whatsapp_msg_id<>'' "
        "AND (status IS NULL OR status='' OR status='unknown' OR status='pending')"
    )
    conn.execute(
        "UPDATE conversations SET status='unknown' "
        "WHERE direction='outbound' AND status='pending' AND send_kind='legacy'"
    )
    conn.execute(
        "UPDATE conversations SET send_kind='inbound' "
        "WHERE direction='inbound' AND send_kind='legacy'"
    )
    conn.execute(
        "UPDATE conversations SET send_kind='legacy' "
        "WHERE direction='outbound' AND send_kind='legacy'"
    )
    conn.execute("UPDATE conversations SET updated_at=sent_at WHERE updated_at IS NULL")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_conv_status ON conversations(status, sent_at)")

    # One platform id should map to one local message. Older databases may
    # contain duplicates; in that case keep the non-unique index and rely on
    # the write lock for de-duplication.
    try:
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_conv_wa_msg_id_unique "
            "ON conversations(whatsapp_msg_id) "
            "WHERE whatsapp_msg_id IS NOT NULL AND whatsapp_msg_id<>''"
        )
    except sqlite3.IntegrityError:
        pass


def _migrate_followup_sending_claim(conn: sqlite3.Connection) -> None:
    """Add a per-schedule in-flight claim used to prevent duplicate sends."""
    cols = _table_columns(conn, "follow_up_schedule")
    if "sending_since" not in cols:
        conn.execute("ALTER TABLE follow_up_schedule ADD COLUMN sending_since TIMESTAMP")


MIGRATIONS = [
    (1, "conversation_delivery_status", _migrate_conversation_delivery),
    (2, "followup_sending_claim", _migrate_followup_sending_claim),
]


def _apply_migrations(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version INTEGER PRIMARY KEY, name TEXT NOT NULL, "
        "applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    applied = {r[0] for r in conn.execute("SELECT version FROM schema_migrations").fetchall()}
    for version, name, migrate in MIGRATIONS:
        if version in applied:
            continue
        try:
            conn.execute("BEGIN IMMEDIATE")
            migrate(conn)
            conn.execute(
                "INSERT INTO schema_migrations(version, name) VALUES(?,?)",
                (version, name),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise


def _reset_stale_quota_reservations(conn: sqlite3.Connection) -> None:
    """Clear in-flight reservations left by a previous process.

    The desktop app runs a single backend process, so at startup no send can
    still be in flight. This prevents a crash between reserve and commit from
    permanently consuming quota. Multi-process deployments would need expiring
    reservation rows instead.
    """
    try:
        conn.execute("UPDATE send_quota SET reserved=0, updated_at=? WHERE reserved<>0",
                     (datetime.now().isoformat(),))
        conn.commit()
    except sqlite3.Error:
        pass


def get_connection() -> sqlite3.Connection:
    """返回当前租户的连接（按数据库文件路径缓存）。"""
    cfg = get_config()
    db_path = Path(cfg.database.path).resolve()
    key = str(db_path)
    conn = _conns.get(key)
    if conn is None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA foreign_keys=ON;")
        conn.executescript(SCHEMA)
        _apply_migrations(conn)
        _reset_stale_quota_reservations(conn)
        # Legacy one-off migrations retained for older databases.
        try: conn.execute("ALTER TABLE orders ADD COLUMN currency TEXT DEFAULT 'USD'")
        except: pass
        try: conn.execute("ALTER TABLE customers ADD COLUMN email TEXT DEFAULT ''")
        except: pass
        conn.commit()
        _conns[key] = conn
    return conn


def close_db():
    for conn in list(_conns.values()):
        try:
            conn.close()
        except sqlite3.Error:
            pass
    _conns.clear()


def get_or_create_customer(phone: str, name: Optional[str] = None) -> dict:
    conn = get_connection()
    with _write_lock:
        row = conn.execute("SELECT * FROM customers WHERE phone=?", (phone,)).fetchone()
        if row:
            return dict(row)
        cur = conn.execute("INSERT INTO customers(phone,name) VALUES(?,?)", (phone, name or phone))
        conn.commit()
    return dict(conn.execute("SELECT * FROM customers WHERE id=?", (cur.lastrowid,)).fetchone())


def update_customer(phone: str, new_phone: Optional[str] = None, **kwargs) -> Optional[dict]:
    allowed = {"name", "email", "company", "notes", "status", "tags"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if new_phone:
        updates["phone"] = new_phone
    if not updates:
        return None
    updates["updated_at"] = datetime.now().isoformat()
    lookup_phone = new_phone or phone
    set_clause = ", ".join(f"{k}=?" for k in updates)
    conn = get_connection()
    with _write_lock:
        try:
            conn.execute(f"UPDATE customers SET {set_clause} WHERE phone=?", list(updates.values()) + [phone])
            conn.commit()
        except sqlite3.IntegrityError:
            # UNIQUE constraint on phone — likely duplicate phone number
            raise
    row = conn.execute("SELECT * FROM customers WHERE phone=?", (lookup_phone,)).fetchone()
    return dict(row) if row else None


MESSAGE_STATUSES = {"pending", "sent", "failed", "unknown", "received"}
OUTBOUND_STATUSES = {"pending", "sent", "failed", "unknown"}
SEND_KINDS = {"legacy", "inbound", "instant_reply", "proactive", "manual"}


def save_message(customer_id: int, direction: str, content: str,
                 whatsapp_msg_id: Optional[str] = None, ai_generated: bool = False,
                 status: Optional[str] = None, send_kind: Optional[str] = None,
                 error_message: Optional[str] = None,
                 dedupe_content_window_seconds: int = 0) -> Optional[int]:
    """Persist a message and return its id, or None for a duplicate inbound id.

    Outbound rows default to 'pending'; only a bridge receipt may move them to
    'sent'. Inbound rows default to 'received'. De-duplication happens under
    the write lock so concurrent webhook deliveries cannot insert twice.
    """
    if direction not in ("inbound", "outbound"):
        raise ValueError(f"invalid direction: {direction}")
    if status is None:
        status = "received" if direction == "inbound" else "pending"
    if status not in MESSAGE_STATUSES:
        raise ValueError(f"invalid message status: {status}")
    if send_kind is None:
        send_kind = "inbound" if direction == "inbound" else "legacy"
    if send_kind not in SEND_KINDS:
        raise ValueError(f"invalid send kind: {send_kind}")

    conn = get_connection()
    with _write_lock:
        if whatsapp_msg_id:
            row = conn.execute(
                "SELECT id FROM conversations WHERE whatsapp_msg_id=?",
                (whatsapp_msg_id,),
            ).fetchone()
            if row:
                return None
        elif direction == "inbound" and dedupe_content_window_seconds > 0:
            cutoff = (datetime.now() - timedelta(seconds=dedupe_content_window_seconds)).isoformat()
            row = conn.execute(
                "SELECT id FROM conversations WHERE customer_id=? AND direction='inbound' "
                "AND content=? AND sent_at>=? ORDER BY id DESC LIMIT 1",
                (customer_id, content, cutoff),
            ).fetchone()
            if row:
                return None
        now = datetime.now().isoformat()
        cur = conn.execute(
            "INSERT INTO conversations(customer_id,direction,content,whatsapp_msg_id,"
            "ai_generated,sent_at,status,send_kind,error_message,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)",
            (customer_id, direction, content, whatsapp_msg_id, int(ai_generated),
             now, status, send_kind, error_message, now))
        conn.commit()
    return cur.lastrowid


def get_message(conversation_id: int) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM conversations WHERE id=?", (conversation_id,)).fetchone()
    return dict(row) if row else None


def get_message_by_whatsapp_id(whatsapp_msg_id: str) -> Optional[dict]:
    if not whatsapp_msg_id:
        return None
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM conversations WHERE whatsapp_msg_id=? ORDER BY id LIMIT 1",
        (whatsapp_msg_id,),
    ).fetchone()
    return dict(row) if row else None


def update_message_delivery(conversation_id: int, status: str,
                            whatsapp_msg_id: Optional[str] = None,
                            error_message: Optional[str] = None) -> dict:
    """Apply a bridge result idempotently.

    Rules:
      * a confirmed 'sent' is terminal and is never downgraded by a late
        failure/unknown receipt;
      * failed/unknown may later be upgraded to 'sent' (the platform id
        finally arrived);
      * repeating the same receipt changes nothing and never inserts a row.
    """
    if status not in OUTBOUND_STATUSES:
        raise ValueError(f"invalid outbound status: {status}")

    conn = get_connection()
    with _write_lock:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone()
        if not row:
            return {"ok": False, "error": "message not found", "changed": False}
        current = row["status"]
        if row["direction"] != "outbound":
            return {"ok": False, "error": "not an outbound message", "changed": False,
                    "message": dict(row)}

        same_id = (not whatsapp_msg_id) or (row["whatsapp_msg_id"] == whatsapp_msg_id)
        if current == "sent" and status != "sent":
            return {"ok": True, "changed": False, "previous": current,
                    "status": current, "message": dict(row),
                    "note": "confirmed send is terminal"}
        if current == status and same_id and (status == "sent" or row["error_message"] == error_message):
            return {"ok": True, "changed": False, "previous": current,
                    "status": current, "message": dict(row)}

        new_msg_id = whatsapp_msg_id or row["whatsapp_msg_id"]
        new_error = None if status == "sent" else error_message
        now = datetime.now().isoformat()
        try:
            conn.execute(
                "UPDATE conversations SET status=?, whatsapp_msg_id=?, error_message=?, "
                "updated_at=? WHERE id=?",
                (status, new_msg_id, new_error, now, conversation_id),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            conn.rollback()
            logger.warning("Duplicate whatsapp_msg_id %s for conversation %s",
                           new_msg_id, conversation_id)
            return {"ok": False, "changed": False,
                    "error": "duplicate whatsapp_msg_id", "message": dict(row)}
        updated = conn.execute(
            "SELECT * FROM conversations WHERE id=?", (conversation_id,)
        ).fetchone()
        return {"ok": True, "changed": True, "previous": current,
                "status": status, "message": dict(updated)}


def count_sent_messages_today(kind: Optional[str] = None) -> int:
    """Count messages confirmed as sent today. Pending/failed/unknown never count."""
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")
    sql = (
        "SELECT COUNT(*) AS cnt FROM conversations "
        "WHERE direction='outbound' AND status='sent' AND date(sent_at)=?"
    )
    params: list = [today]
    if kind:
        sql += " AND send_kind=?"
        params.append(kind)
    row = conn.execute(sql, params).fetchone()
    return row["cnt"] if row else 0


def count_today_outbound_by_status(status: str) -> int:
    conn = get_connection()
    today = datetime.now().strftime("%Y-%m-%d")
    row = conn.execute(
        "SELECT COUNT(*) AS cnt FROM conversations "
        "WHERE direction='outbound' AND status=? AND date(sent_at)=?",
        (status, today),
    ).fetchone()
    return row["cnt"] if row else 0


# ── Daily send quota (atomic reservation) ──────────────────────────────────────

def _quota_day(day: Optional[str] = None) -> str:
    return day or datetime.now().strftime("%Y-%m-%d")


def _ensure_quota_row(conn: sqlite3.Connection, day: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM send_quota WHERE day=?", (day,)).fetchone()
    if row:
        return row
    # Include pre-migration auto-sent rows so an upgrade cannot reset today's
    # quota to zero mid-day. Legacy manual sends (ai_generated=0) are excluded.
    used = conn.execute(
        "SELECT COUNT(*) AS cnt FROM conversations "
        "WHERE direction='outbound' AND status IN ('sent','unknown') "
        "AND date(sent_at)=? "
        "AND (send_kind='proactive' OR (send_kind='legacy' AND ai_generated=1))",
        (day,),
    ).fetchone()["cnt"]
    conn.execute(
        "INSERT INTO send_quota(day, used, reserved, updated_at) VALUES(?,?,0,?)",
        (day, used, datetime.now().isoformat()),
    )
    return conn.execute("SELECT * FROM send_quota WHERE day=?", (day,)).fetchone()


def get_daily_quota_usage(day: Optional[str] = None) -> dict:
    day = _quota_day(day)
    conn = get_connection()
    with _write_lock:
        row = _ensure_quota_row(conn, day)
        conn.commit()
    return {"day": day, "used": row["used"], "reserved": row["reserved"],
            "total": row["used"] + row["reserved"]}


def reserve_daily_quota(limit: int, day: Optional[str] = None) -> bool:
    """Atomically reserve one proactive send slot.

    Uses BEGIN IMMEDIATE so concurrent requests serialize in SQLite. Callers
    must release (definite failure) or commit (sent/unknown) the reservation.
    """
    if limit <= 0:
        return False
    day = _quota_day(day)
    conn = get_connection()
    with _write_lock:
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = _ensure_quota_row(conn, day)
            if row["used"] + row["reserved"] >= limit:
                conn.rollback()
                return False
            conn.execute(
                "UPDATE send_quota SET reserved=reserved+1, updated_at=? WHERE day=?",
                (datetime.now().isoformat(), day),
            )
            conn.commit()
            return True
        except Exception:
            conn.rollback()
            raise


def release_daily_quota(day: Optional[str] = None) -> None:
    day = _quota_day(day)
    conn = get_connection()
    with _write_lock:
        conn.execute(
            "UPDATE send_quota SET reserved=CASE WHEN reserved>0 THEN reserved-1 ELSE 0 END, "
            "updated_at=? WHERE day=?",
            (datetime.now().isoformat(), day),
        )
        conn.commit()


def commit_daily_quota(day: Optional[str] = None) -> None:
    """Turn a reservation into a used slot (confirmed or possibly delivered)."""
    day = _quota_day(day)
    conn = get_connection()
    with _write_lock:
        conn.execute(
            "UPDATE send_quota SET reserved=CASE WHEN reserved>0 THEN reserved-1 ELSE 0 END, "
            "used=used+1, updated_at=? WHERE day=?",
            (datetime.now().isoformat(), day),
        )
        conn.commit()


def get_recent_conversations(customer_id: int, limit: int = 20) -> list[dict]:
    conn = get_connection()
    # Only delivered inbound/sent outbound messages feed the AI context. A
    # pending/failed/unknown generated reply must not look like something the
    # bot actually said.
    rows = conn.execute(
        "SELECT * FROM conversations WHERE customer_id=? "
        "AND status IN ('received','sent') "
        "ORDER BY sent_at DESC LIMIT ?",
        (customer_id, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_last_ai_reply_time(customer_id: int) -> Optional[datetime]:
    conn = get_connection()
    row = conn.execute(
        "SELECT sent_at FROM conversations WHERE customer_id=? AND ai_generated=1 "
        "AND direction='outbound' AND status IN ('sent','pending','unknown') "
        "ORDER BY sent_at DESC LIMIT 1",
        (customer_id,)).fetchone()
    return datetime.fromisoformat(row["sent_at"]) if row else None


def count_ai_replies_since(since: datetime) -> int:
    conn = get_connection()
    return conn.execute(
        "SELECT COUNT(*) as cnt FROM conversations WHERE ai_generated=1 "
        "AND direction='outbound' AND status='sent' AND sent_at>=?",
        (since.isoformat(),)).fetchone()["cnt"]


def ensure_followup_schedule(customer_id: int, frequency_days: int = 7, template: Optional[str] = None) -> dict:
    conn = get_connection()
    row = conn.execute("SELECT * FROM follow_up_schedule WHERE customer_id=? AND active=1", (customer_id,)).fetchone()
    if row:
        return dict(row)
    next_at = datetime.now() + timedelta(days=frequency_days)
    with _write_lock:
        cur = conn.execute(
            "INSERT INTO follow_up_schedule(customer_id,frequency_days,next_followup_at,template) VALUES(?,?,?,?)",
            (customer_id, frequency_days, next_at.isoformat(), template))
        conn.commit()
    return dict(conn.execute("SELECT * FROM follow_up_schedule WHERE id=?", (cur.lastrowid,)).fetchone())


def get_customers_due_for_followup() -> list[dict]:
    conn = get_connection()
    now = datetime.now().isoformat()
    rows = conn.execute(
        """SELECT fs.id AS schedule_id, fs.customer_id AS customer_id,
                  fs.frequency_days, fs.last_followup_at, fs.next_followup_at,
                  fs.template, fs.active, fs.created_at AS schedule_created_at,
                  c.phone, c.name, c.company, c.notes, c.tags
           FROM follow_up_schedule fs JOIN customers c ON fs.customer_id=c.id
           WHERE fs.next_followup_at<=? AND fs.active=1 AND c.status='active'
           ORDER BY fs.next_followup_at""", (now,)).fetchall()
    return [dict(r) for r in rows]


def update_followup_schedule(schedule_id: int):
    cfg = get_config()
    conn = get_connection()
    row = conn.execute("SELECT * FROM follow_up_schedule WHERE id=?", (schedule_id,)).fetchone()
    if not row:
        return
    freq = row["frequency_days"] or cfg.scheduler.default_followup_days
    now = datetime.now()
    with _write_lock:
        conn.execute("UPDATE follow_up_schedule SET last_followup_at=?, next_followup_at=? WHERE id=?",
                     (now.isoformat(), (now + timedelta(days=freq)).isoformat(), schedule_id))
        conn.commit()


def claim_followup_schedule(schedule_id: int, stale_seconds: int = 900) -> bool:
    """Atomically claim one schedule for sending.

    Prevents a manual send-now and an automatic tick from sending the same
    follow-up twice. A stale claim (crashed process) can be reclaimed after
    ``stale_seconds``.
    """
    conn = get_connection()
    now = datetime.now()
    cutoff = (now - timedelta(seconds=stale_seconds)).isoformat()
    with _write_lock:
        cur = conn.execute(
            "UPDATE follow_up_schedule SET sending_since=? "
            "WHERE id=? AND (sending_since IS NULL OR sending_since < ?)",
            (now.isoformat(), schedule_id, cutoff),
        )
        conn.commit()
        return cur.rowcount == 1


def release_followup_claim(schedule_id: int) -> None:
    conn = get_connection()
    with _write_lock:
        conn.execute(
            "UPDATE follow_up_schedule SET sending_since=NULL WHERE id=?",
            (schedule_id,),
        )
        conn.commit()


def record_followup(customer_id: int, schedule_id: int, conversation_id: Optional[int],
                    status: str = "sent", error_message: Optional[str] = None) -> int:
    conn = get_connection()
    with _write_lock:
        now = datetime.now().isoformat()
        cur = conn.execute(
            "INSERT INTO sent_followups(customer_id,schedule_id,conversation_id,status,error_message,sent_at) VALUES(?,?,?,?,?,?)",
            (customer_id, schedule_id, conversation_id, status, error_message, now))
        conn.commit()
    return cur.lastrowid


# ── Bot State (persistent KV store) ──────────────────────────────────────────────

def get_bot_state(key: str) -> Optional[str]:
    conn = get_connection()
    row = conn.execute("SELECT value FROM bot_state WHERE key=?", (key,)).fetchone()
    return row["value"] if row else None


def set_bot_state(key: str, value: str):
    conn = get_connection()
    with _write_lock:
        conn.execute(
            "INSERT INTO bot_state(key, value, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (key, value, datetime.now().isoformat()))
        conn.commit()


# ── Lead Scores ──────────────────────────────────────────────────────────────────

def upsert_lead_score(customer_id: int, score: int, segment: str, signals: str = "{}"):
    conn = get_connection()
    now = datetime.now().isoformat()
    with _write_lock:
        conn.execute(
            "INSERT INTO lead_scores(customer_id, score, segment, signals, last_scored_at, updated_at) "
            "VALUES(?,?,?,?,?,?) ON CONFLICT(customer_id) DO UPDATE SET "
            "score=excluded.score, segment=excluded.segment, signals=excluded.signals, "
            "last_scored_at=excluded.last_scored_at, updated_at=excluded.updated_at",
            (customer_id, score, segment, signals, now, now))
        conn.commit()


def get_lead_score(customer_id: int) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM lead_scores WHERE customer_id=?", (customer_id,)).fetchone()
    return dict(row) if row else None


def get_top_leads(segment: Optional[str] = None, limit: int = 50) -> list[dict]:
    conn = get_connection()
    if segment:
        rows = conn.execute(
            "SELECT ls.*, c.name, c.phone, c.company FROM lead_scores ls "
            "JOIN customers c ON ls.customer_id=c.id "
            "WHERE ls.segment=? ORDER BY ls.score DESC LIMIT ?",
            (segment, limit)).fetchall()
    else:
        rows = conn.execute(
            "SELECT ls.*, c.name, c.phone, c.company FROM lead_scores ls "
            "JOIN customers c ON ls.customer_id=c.id "
            "ORDER BY ls.score DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_customers_by_segment(segment: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT ls.*, c.name, c.phone, c.company, c.notes FROM lead_scores ls "
        "JOIN customers c ON ls.customer_id=c.id "
        "WHERE ls.segment=? ORDER BY ls.score DESC", (segment,)).fetchall()
    return [dict(r) for r in rows]


def get_all_lead_scores() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT ls.*, c.name, c.phone, c.company FROM lead_scores ls "
        "JOIN customers c ON ls.customer_id=c.id ORDER BY ls.score DESC").fetchall()
    return [dict(r) for r in rows]


def get_segment_counts() -> dict:
    conn = get_connection()
    rows = conn.execute(
        "SELECT segment, COUNT(*) as cnt FROM lead_scores GROUP BY segment").fetchall()
    return {r["segment"]: r["cnt"] for r in rows}


# ── Agent Decision Log ───────────────────────────────────────────────────────────

def log_agent_decision(customer_id: int, decision_type: str, reasoning: str = "",
                       context: str = "{}"):
    conn = get_connection()
    with _write_lock:
        conn.execute(
            "INSERT INTO agent_decisions(customer_id, decision_type, reasoning, context) "
            "VALUES(?,?,?,?)", (customer_id, decision_type, reasoning, context))
        conn.commit()


def get_recent_decisions(limit: int = 50) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT ad.*, c.name, c.phone FROM agent_decisions ad "
        "LEFT JOIN customers c ON ad.customer_id=c.id "
        "ORDER BY ad.created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]


def get_customer_decisions(customer_id: int, limit: int = 20) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM agent_decisions WHERE customer_id=? "
        "ORDER BY created_at DESC LIMIT ?", (customer_id, limit)).fetchall()
    return [dict(r) for r in rows]


# ── AI Memory ────────────────────────────────────────────────────────────────────

def add_memory_entry(customer_id: int, entry_type: str, content: str,
                     importance: int = 1, conversation_id: Optional[int] = None) -> int:
    conn = get_connection()
    with _write_lock:
        cur = conn.execute(
            "INSERT INTO ai_memory_entries(customer_id, entry_type, content, importance, "
            "conversation_id) VALUES(?,?,?,?,?)",
            (customer_id, entry_type, content, importance, conversation_id))
        conn.commit()
    return cur.lastrowid


def get_customer_memory(customer_id: int, limit: int = 10,
                        entry_type: Optional[str] = None) -> list[dict]:
    conn = get_connection()
    if entry_type:
        rows = conn.execute(
            "SELECT * FROM ai_memory_entries WHERE customer_id=? AND entry_type=? "
            "ORDER BY importance DESC, created_at DESC LIMIT ?",
            (customer_id, entry_type, limit)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM ai_memory_entries WHERE customer_id=? "
            "ORDER BY importance DESC, created_at DESC LIMIT ?",
            (customer_id, limit)).fetchall()
    return [dict(r) for r in rows]


def get_memory_summary(customer_id: int, max_entries: int = 5) -> str:
    """Return a condensed text summary of customer memory for prompt injection."""
    entries = get_customer_memory(customer_id, limit=max_entries)
    if not entries:
        return ""
    lines = []
    for e in entries:
        tag = {"summary": "📝", "intent": "🎯", "preference": "⭐", "objection": "⚠️"}.get(e["entry_type"], "•")
        lines.append(f"{tag} {e['content']}")
    return "\n".join(lines)


# ── Product Files (PDF/documents for sending via WhatsApp) ──────────────────────

def save_product_file(product_doc_id: int, filename: str, mime_type: str,
                       file_data: bytes, file_size: int = 0) -> int:
    conn = get_connection()
    with _write_lock:
        cur = conn.execute(
            "INSERT INTO product_files(product_doc_id, filename, mime_type, file_size, file_data) "
            "VALUES(?,?,?,?,?)",
            (product_doc_id, filename, mime_type, file_size or len(file_data), file_data))
        conn.commit()
    return cur.lastrowid


def get_product_file(product_doc_id: int) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM product_files WHERE product_doc_id=? ORDER BY id DESC LIMIT 1",
        (product_doc_id,)).fetchone()
    return dict(row) if row else None


def search_product_files(query: str, limit: int = 5) -> list[dict]:
    """Search product_docs by title/content and return matching docs with file info."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT pd.id, pd.title, pd.content, pf.filename, pf.mime_type, pf.file_size "
        "FROM product_docs pd "
        "LEFT JOIN product_files pf ON pd.id = pf.product_doc_id "
        "WHERE pd.title LIKE ? OR pd.content LIKE ? "
        "ORDER BY pd.id DESC LIMIT ?",
        (f"%{query}%", f"%{query}%", limit)).fetchall()
    return [dict(r) for r in rows]


def find_best_matching_document(customer_message: str) -> Optional[dict]:
    """Use keyword matching to find the most relevant document for a customer request.

    Returns the best-matching doc with file info, or None if no good match.
    """
    import re
    # Extract key terms from the message
    keywords = []
    # Model numbers: MWM TCG3016, MAN 12M55, G3516H, etc.
    model_patterns = [
        r'(?:MWM\s*)?TCG\d+[A-Z]?\d*', r'(?:MAN\s*)?\d+[A-Z]\d+[A-Z]?',
        r'G\d+[A-Z]\d*', r'L\d+[A-Z]\d+', r'TM\d+[A-Z]?\d*',
        r'CG\d+[A-Z]?\d*', r'LP\d+[A-Z]\d+[A-Z]?',
        r'\d+[A-Z]\d+[A-Z]?\d*',  # General model number pattern
    ]
    for pat in model_patterns:
        matches = re.findall(pat, customer_message, re.IGNORECASE)
        keywords.extend(matches)

    # Power requirements
    power_match = re.search(r'(\d+\.?\d*)\s*(?:MW|kW|kw|KW)', customer_message)
    if power_match:
        keywords.append(f"{power_match.group(1)}")

    # Document type hints
    doctype_map = {
        'datasheet': ['datasheet', 'data sheet', 'spec', 'specification', '规格', '参数表'],
        'manual': ['manual', 'operation', 'maintenance', 'manual', '说明书', '操作', '保养'],
        'price': ['price', 'pricing', '报价', '价格', 'quote'],
        'catalog': ['catalog', 'brochure', 'leaflet', '型谱', '目录', '样本'],
        'questionnaire': ['questionnaire', 'survey', '调查表', '问卷'],
        'profile': ['company', 'profile', '公司', '简介', 'about'],
    }
    for doctype, patterns in doctype_map.items():
        if any(p.lower() in customer_message.lower() for p in patterns):
            keywords.append(doctype)

    if not keywords:
        return None

    # Search product_docs for matching keywords
    conn = get_connection()
    best_match = None
    best_score = 0

    for kw in keywords[:5]:  # Limit to top 5 keywords
        rows = conn.execute(
            "SELECT pd.id, pd.title, pd.content, pf.filename, pf.mime_type, "
            "pf.file_size "
            "FROM product_docs pd "
            "LEFT JOIN product_files pf ON pd.id = pf.product_doc_id "
            "WHERE pd.title LIKE ?",
            (f"%{kw}%",)).fetchall()
        for r in rows:
            score = 0
            title_lower = (r["title"] or "").lower()
            # Exact model match is strongest signal
            if kw.lower() in title_lower:
                score += 10
            # Prefer docs that have files attached
            if r["filename"]:
                score += 5
            # Penalize non-English titles (less likely to be what customer wants)
            if score > best_score:
                best_score = score
                best_match = r

    if best_match and best_score >= 5:
        return dict(best_match)
    return None

