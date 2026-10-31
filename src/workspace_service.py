"""Read-only projections for the sales workspace. No AI or sending side effects."""
from datetime import datetime

from database import get_connection


WORKSPACE_QUERY = """
WITH messages AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY customer_id ORDER BY julianday(sent_at) DESC, id DESC
    ) AS position FROM conversations
), reply_state AS (
    SELECT *, ROW_NUMBER() OVER (
        PARTITION BY customer_id ORDER BY julianday(sent_at) DESC, id DESC
    ) AS position FROM conversations
    WHERE direction='inbound' OR status IN ('sent','pending','unknown')
), schedules AS (
    SELECT customer_id, MIN(next_followup_at) AS next_followup_at
    FROM follow_up_schedule WHERE active=1 GROUP BY customer_id
)
SELECT c.id, c.name, c.phone, c.company, c.status,
       m.id AS last_message_id, m.sent_at AS last_msg, m.content AS last_content,
       m.direction AS last_direction, m.status AS last_status,
       (SELECT COUNT(*) FROM conversations WHERE customer_id=c.id) AS msg_count,
       CASE WHEN r.direction='inbound' AND c.status='active' THEN 1 ELSE 0 END AS needs_reply,
       s.next_followup_at, ls.score, ls.segment, ls.last_scored_at
FROM customers c
LEFT JOIN messages m ON m.customer_id=c.id AND m.position=1
LEFT JOIN reply_state r ON r.customer_id=c.id AND r.position=1
LEFT JOIN schedules s ON s.customer_id=c.id
LEFT JOIN lead_scores ls ON ls.customer_id=c.id
"""


def conversation_workspace(limit=50):
    rows = get_connection().execute(
        f"SELECT * FROM ({WORKSPACE_QUERY}) WHERE msg_count>0 "
        "ORDER BY julianday(last_msg) DESC, last_message_id DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(row) for row in rows]


def workspace_overview():
    conn = get_connection()
    now = datetime.now().isoformat()
    needs_reply = conn.execute(
        f"SELECT COUNT(*) FROM ({WORKSPACE_QUERY}) WHERE needs_reply=1"
    ).fetchone()[0]
    tasks = conn.execute(
        f"SELECT * FROM ({WORKSPACE_QUERY}) WHERE status='active' "
        "AND (needs_reply=1 OR julianday(next_followup_at)<=julianday(?)) "
        "ORDER BY needs_reply DESC, julianday(next_followup_at), julianday(last_msg) DESC LIMIT 6",
        (now,)
    ).fetchall()
    leads = conn.execute(
        f"SELECT * FROM ({WORKSPACE_QUERY}) WHERE status='active' AND score>=40 "
        "ORDER BY score DESC, julianday(last_msg) DESC LIMIT 4"
    ).fetchall()
    return {"needs_reply": needs_reply, "tasks": [dict(r) for r in tasks],
            "priority_leads": [dict(r) for r in leads]}
