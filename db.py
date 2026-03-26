"""SQLite による未返信メール状態管理"""
import os
import sqlite3
from datetime import datetime, timedelta

import config

_DB_PATH = os.path.join(config.DATA_DIR, "mailreminder.db")


def _connect() -> sqlite3.Connection:
    os.makedirs(config.DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """テーブル作成（初回のみ）"""
    conn = _connect()
    conn.execute("""\
        CREATE TABLE IF NOT EXISTS tracked_emails (
            message_id   TEXT PRIMARY KEY,
            subject      TEXT NOT NULL,
            sender       TEXT NOT NULL,
            sender_email TEXT NOT NULL,
            needs_reply  INTEGER NOT NULL DEFAULT 0,
            draft_created INTEGER NOT NULL DEFAULT 0,
            replied      INTEGER NOT NULL DEFAULT 0,
            urgency      TEXT,
            first_seen   TEXT NOT NULL,
            last_checked TEXT NOT NULL,
            notified     INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()


def upsert_email(message_id: str, subject: str, sender: str,
                 sender_email: str, needs_reply: bool,
                 draft_created: bool, urgency: str | None) -> None:
    """メールをトラッキングに追加/更新"""
    now = datetime.now().isoformat()
    conn = _connect()
    conn.execute("""\
        INSERT INTO tracked_emails
            (message_id, subject, sender, sender_email, needs_reply,
             draft_created, urgency, first_seen, last_checked)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(message_id) DO UPDATE SET
            last_checked = excluded.last_checked,
            draft_created = MAX(draft_created, excluded.draft_created)
    """, (message_id, subject, sender, sender_email,
          int(needs_reply), int(draft_created), urgency, now, now))
    conn.commit()
    conn.close()


def mark_replied(message_ids: set[str]) -> None:
    """返信済みとしてマーク"""
    if not message_ids:
        return
    conn = _connect()
    for mid in message_ids:
        conn.execute(
            "UPDATE tracked_emails SET replied = 1 WHERE message_id = ?",
            (mid,))
    conn.commit()
    conn.close()


def get_unreplied_overdue(hours: int | None = None) -> list[dict]:
    """閾値を超えた未返信メールを取得"""
    if hours is None:
        hours = config.REPLY_ALERT_HOURS
    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    conn = _connect()
    rows = conn.execute("""\
        SELECT message_id, subject, sender, sender_email, urgency, first_seen
        FROM tracked_emails
        WHERE needs_reply = 1 AND replied = 0 AND first_seen < ?
        ORDER BY first_seen ASC
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_tracked_unreplied_ids() -> list[str]:
    """未返信のmessage_id一覧を取得"""
    conn = _connect()
    rows = conn.execute(
        "SELECT message_id FROM tracked_emails WHERE needs_reply = 1 AND replied = 0"
    ).fetchall()
    conn.close()
    return [r["message_id"] for r in rows]


def cleanup_old(days: int = 30) -> int:
    """古いレコードを削除"""
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = _connect()
    cursor = conn.execute(
        "DELETE FROM tracked_emails WHERE first_seen < ?", (cutoff,))
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    return deleted
