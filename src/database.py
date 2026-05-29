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
    row = conn.execute("SELECT * FROM customers WHERE phone=?", (phone,)).fetchone()
    if row:
        return dict(row)
    with _write_lock:
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
        conn.execute(f"UPDATE customers SET {set_clause} WHERE phone=?", list(updates.values()) + [phone])
        conn.commit()
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
