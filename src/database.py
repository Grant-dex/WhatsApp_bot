from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import get_config

_write_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None

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
    sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS follow_up_schedule (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    frequency_days INTEGER NOT NULL DEFAULT 7,
    last_followup_at TIMESTAMP,
    next_followup_at TIMESTAMP,
    template TEXT,
    active INTEGER DEFAULT 1,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
CREATE INDEX IF NOT EXISTS idx_followup_next ON follow_up_schedule(next_followup_at) WHERE active=1;
CREATE TABLE IF NOT EXISTS product_docs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
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


def get_connection() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        cfg = get_config()
        db_path = Path(cfg.database.path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(str(db_path), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL;")
        _conn.execute("PRAGMA foreign_keys=ON;")
        _conn.executescript(SCHEMA)
        # Migrations for existing databases
        try: _conn.execute("ALTER TABLE orders ADD COLUMN currency TEXT DEFAULT 'USD'")
        except: pass
        try: _conn.execute("ALTER TABLE customers ADD COLUMN email TEXT DEFAULT ''")
        except: pass
        _conn.commit()
    return _conn


def close_db():
    global _conn
    if _conn:
        _conn.close()
        _conn = None


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


def save_message(customer_id: int, direction: str, content: str,
                 whatsapp_msg_id: Optional[str] = None, ai_generated: bool = False) -> Optional[int]:
    conn = get_connection()
    if whatsapp_msg_id:
        if conn.execute("SELECT id FROM conversations WHERE whatsapp_msg_id=?", (whatsapp_msg_id,)).fetchone():
            return None
    with _write_lock:
        now = datetime.now().isoformat()
        cur = conn.execute(
            "INSERT INTO conversations(customer_id,direction,content,whatsapp_msg_id,ai_generated,sent_at) VALUES(?,?,?,?,?,?)",
            (customer_id, direction, content, whatsapp_msg_id, int(ai_generated), now))
        conn.commit()
    return cur.lastrowid


def get_recent_conversations(customer_id: int, limit: int = 20) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM conversations WHERE customer_id=? ORDER BY sent_at DESC LIMIT ?",
        (customer_id, limit)).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_last_ai_reply_time(customer_id: int) -> Optional[datetime]:
    conn = get_connection()
    row = conn.execute(
        "SELECT sent_at FROM conversations WHERE customer_id=? AND ai_generated=1 AND direction='outbound' ORDER BY sent_at DESC LIMIT 1",
        (customer_id,)).fetchone()
    return datetime.fromisoformat(row["sent_at"]) if row else None


def count_ai_replies_since(since: datetime) -> int:
    conn = get_connection()
    return conn.execute(
        "SELECT COUNT(*) as cnt FROM conversations WHERE ai_generated=1 AND sent_at>=?",
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
