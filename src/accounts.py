"""账号与会话存储（全局，不分租户）。

数据库放在 ``<data>/accounts.db``，与租户目录并列：用户是全局的，
数据才是每租户一份。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from tenancy import base_data_dir

SESSION_COOKIE = "wa_session"
SESSION_TTL_DAYS = 30

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    data_dir      TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'active',
    is_owner      INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    last_seen  TEXT,
    ip         TEXT,
    ua         TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None


def _db_path() -> Path:
    return base_data_dir() / "accounts.db"


def get_conn() -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is None:
            path = _db_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            conn.executescript(_SCHEMA)
            conn.commit()
            _conn = conn
        return _conn


def close_conn() -> None:
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
            _conn = None


def reset_for_tests() -> None:
    """仅供测试：断开连接，让下一次 get_conn() 重新打开。"""
    close_conn()


# ── 密码 ────────────────────────────────────────────────────────────────
# 用标准库 scrypt，不引入额外依赖。格式：
#   scrypt$<n>$<r>$<p>$<salt_b64>$<hash_b64>

_N, _R, _P, _DKLEN = 2 ** 14, 8, 1, 32


def hash_password(password: str) -> str:
    if not isinstance(password, str) or len(password) < 8:
        raise ValueError("密码至少 8 位")
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                            n=_N, r=_R, p=_P, dklen=_DKLEN)
    return "scrypt${}${}${}${}${}".format(
        _N, _R, _P,
        base64.b64encode(salt).decode(),
        base64.b64encode(digest).decode(),
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if scheme != "scrypt":
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(hash_b64)
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt,
                                n=int(n), r=int(r), p=int(p),
                                dklen=len(expected))
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


# ── 用户 ────────────────────────────────────────────────────────────────

def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def count_users() -> int:
    conn = get_conn()
    with _lock:
        row = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()
    return int(row["c"]) if row else 0


def create_user(email: str, password: str, data_dir: Path,
                is_owner: bool = False, user_id: Optional[str] = None) -> Dict:
    email = _normalize_email(email)
    if "@" not in email or len(email) < 5:
        raise ValueError("邮箱格式不正确")
    pwd_hash = hash_password(password)
    user_id = user_id or uuid.uuid4().hex
    now = datetime.now().isoformat(timespec="seconds")
    conn = get_conn()
    with _lock:
        try:
            conn.execute(
                "INSERT INTO users(id,email,password_hash,data_dir,created_at,is_owner)"
                " VALUES(?,?,?,?,?,?)",
                (user_id, email, pwd_hash, str(data_dir), now, 1 if is_owner else 0),
            )
            conn.commit()
        except sqlite3.IntegrityError:
            raise ValueError("该邮箱已注册")
    return {"id": user_id, "email": email, "data_dir": str(data_dir),
            "created_at": now, "is_owner": bool(is_owner)}


def get_user_by_email(email: str) -> Optional[Dict]:
    conn = get_conn()
    with _lock:
        row = conn.execute("SELECT * FROM users WHERE email=?",
                           (_normalize_email(email),)).fetchone()
    return dict(row) if row else None


def get_user(user_id: str) -> Optional[Dict]:
    conn = get_conn()
    with _lock:
        row = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    return dict(row) if row else None


def list_users() -> List[Dict]:
    conn = get_conn()
    with _lock:
        rows = conn.execute("SELECT * FROM users ORDER BY created_at").fetchall()
    return [dict(r) for r in rows]


def authenticate(email: str, password: str) -> Optional[Dict]:
    user = get_user_by_email(email)
    if not user or user["status"] != "active":
        return None
    if not verify_password(password, user["password_hash"]):
        return None
    return user


# ── 会话 ────────────────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_session(user_id: str, ip: str = "", ua: str = "") -> str:
    token = secrets.token_urlsafe(32)
    now = datetime.now()
    conn = get_conn()
    with _lock:
        conn.execute(
            "INSERT INTO sessions(token_hash,user_id,created_at,expires_at,last_seen,ip,ua)"
            " VALUES(?,?,?,?,?,?,?)",
            (_hash_token(token), user_id,
             now.isoformat(timespec="seconds"),
             (now + timedelta(days=SESSION_TTL_DAYS)).isoformat(timespec="seconds"),
             now.isoformat(timespec="seconds"), ip, ua[:200]),
        )
        conn.commit()
    return token


def resolve_session(token: str) -> Optional[Dict]:
    """返回 {user_id, email, data_dir, expires_at}，过期或无效返回 None。"""
    if not token:
        return None
    conn = get_conn()
    with _lock:
        row = conn.execute(
            "SELECT s.token_hash, s.user_id, s.expires_at, u.email, u.data_dir, u.status"
            " FROM sessions s JOIN users u ON u.id = s.user_id"
            " WHERE s.token_hash=?",
            (_hash_token(token),),
        ).fetchone()
        if not row:
            return None
        if row["status"] != "active":
            return None
        try:
            expires = datetime.fromisoformat(row["expires_at"])
        except ValueError:
            return None
        now = datetime.now()
        if expires <= now:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (row["token_hash"],))
            conn.commit()
            return None
        # 滑动续期：剩余不足一半时延长
        if expires - now < timedelta(days=SESSION_TTL_DAYS // 2):
            new_exp = (now + timedelta(days=SESSION_TTL_DAYS)).isoformat(timespec="seconds")
            conn.execute("UPDATE sessions SET last_seen=?, expires_at=? WHERE token_hash=?",
                         (now.isoformat(timespec="seconds"), new_exp, row["token_hash"]))
            conn.commit()
        else:
            conn.execute("UPDATE sessions SET last_seen=? WHERE token_hash=?",
                         (now.isoformat(timespec="seconds"), row["token_hash"]))
            conn.commit()
    return {"user_id": row["user_id"], "email": row["email"],
            "data_dir": row["data_dir"]}


def revoke_session(token: str) -> None:
    if not token:
        return
    conn = get_conn()
    with _lock:
        conn.execute("DELETE FROM sessions WHERE token_hash=?", (_hash_token(token),))
        conn.commit()


def revoke_all_sessions(user_id: str) -> None:
    conn = get_conn()
    with _lock:
        conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
        conn.commit()
