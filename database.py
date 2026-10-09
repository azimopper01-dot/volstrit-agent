"""
database.py — Postlar tarixi, job natijalari va AI kvota hisobi.

Barcha sanalar vaqt mintaqasi (config.TZ) bo'yicha saqlanadi.
"""
import json
from datetime import timedelta
from typing import Optional

import aiosqlite

from config import DB_PATH, now_tz, now_iso, today_str


# ===== YOZISH ===
async def _execute(sql: str, params: tuple = ()):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(sql, params)
        await db.commit()


async def _query_one(sql: str, params: tuple = ()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cur:
            return await cur.fetchone()


async def _query_all(sql: str, params: tuple = ()):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(sql, params) as cur:
            return await cur.fetchall()


# ===== INIT =====
async def init_db():
    """Bazani va jadvallarni yaratadi (mavjudlari o'zgartirilmaydi)."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL")

        await db.execute("""
            CREATE TABLE IF NOT EXISTS posts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                topic TEXT,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                approved_at TEXT,
                sent_at TEXT,
                message_id INTEGER,
                error TEXT
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                options TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                sent_at TEXT,
                message_id INTEGER
            )
        """)

        # Job natijalari — "bugun 08:30 ishi bajarildimi?" degan savolga javob
        await db.execute("""
            CREATE TABLE IF NOT EXISTS job_runs (
                job_id TEXT NOT NULL,
                run_date TEXT NOT NULL,
                status TEXT NOT NULL,
                finished_at TEXT,
                error TEXT,
                PRIMARY KEY (job_id, run_date)
            )
        """)

        # AI so'rovlari hisobi (kvota nazorati uchun)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS ai_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                success INTEGER DEFAULT 1,
                note TEXT
            )
        """)

        # Rasmlar uchun alohida kvota (matndan alohida hisoblanadi)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS image_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts TEXT NOT NULL,
                success INTEGER DEFAULT 1,
                note TEXT
            )
        """)

        # Real vaqtda berilgan bir martalik vazifalar (/schedule)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS adhoc_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_at TEXT NOT NULL,
                topic TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT,
                finished_at TEXT,
                error TEXT
            )
        """)

        # Migratsiya: eski bazalarda "category" ustuni yo'q bo'lishi mumkin
        cur = await db.execute("PRAGMA table_info(posts)")
        cols = {r[1] for r in await cur.fetchall()}
        if "category" not in cols:
            await db.execute(
                "ALTER TABLE posts ADD COLUMN category TEXT DEFAULT ''"
            )
            print("🔄 posts jadvaliga 'category' ustuni qo'shildi")

        await db.commit()
    print("✅ Ma'lumotlar bazasi tayyor.")


# ===== POSTLAR =====
async def save_post(content: str, topic: str = "", category: str = "") -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO posts (content, topic, category, created_at) VALUES (?, ?, ?, ?)",
            (content, topic, category or "", now_iso())
        )
        await db.commit()
        return cur.lastrowid


async def get_post(post_id: int):
    return await _query_one("SELECT * FROM posts WHERE id = ?", (post_id,))


async def get_post_by_message_id(message_id: int):
    return await _query_one("SELECT * FROM posts WHERE message_id = ?", (message_id,))


async def update_post_status(
    post_id: int,
    status: str,
    message_id: Optional[int] = None,
    error: Optional[str] = None,
):
    now = now_iso()
    if status == "approved":
        await _execute(
            "UPDATE posts SET status = ?, approved_at = ? WHERE id = ?",
            (status, now, post_id)
        )
    elif status == "sent":
        await _execute(
            "UPDATE posts SET status = ?, sent_at = ?, message_id = ?, error = NULL WHERE id = ?",
            (status, now, message_id, post_id)
        )
    elif status in ("rejected", "skipped"):
        await _execute(
            "UPDATE posts SET status = ?, error = ? WHERE id = ?",
            (status, error, post_id)
        )
    else:
        await _execute(
            "UPDATE posts SET status = ?, error = ? WHERE id = ?",
            (status, error, post_id)
        )


async def get_pending_posts():
    return await _query_all(
        "SELECT * FROM posts WHERE status = 'pending' ORDER BY created_at DESC LIMIT 20"
    )


async def get_stale_pending_posts(older_than_hours: int):
    """Ko'p vaqtdan beri tasdiqlanmagan postlar (eslatish uchun)."""
    cutoff = (now_tz() - timedelta(hours=older_than_hours)).isoformat(timespec="seconds")
    return await _query_all(
        "SELECT * FROM posts WHERE status = 'pending' AND created_at <= ? "
        "ORDER BY created_at ASC LIMIT 10",
        (cutoff,)
    )


async def get_recent_posts(limit: int = 10):
    return await _query_all(
        "SELECT * FROM posts ORDER BY created_at DESC LIMIT ?", (limit,)
    )


async def get_recent_topics(limit: int = 5):
    """Yaqinda ishlatilgan mavzular — takrorlanmaslik uchun."""
    return await _query_all(
        "SELECT topic FROM posts WHERE topic IS NOT NULL AND topic != '' "
        "ORDER BY created_at DESC LIMIT ?", (limit,)
    )


async def get_today_posts_count() -> int:
    row = await _query_one(
        "SELECT COUNT(*) AS c FROM posts WHERE status='sent' AND DATE(sent_at) = ?",
        (today_str(),)
    )
    return row["c"] if row else 0


async def get_stats():
    sent = await _query_one("SELECT COUNT(*) AS c FROM posts WHERE status='sent'")
    pending = await _query_one("SELECT COUNT(*) AS c FROM posts WHERE status='pending'")
    rejected = await _query_one("SELECT COUNT(*) AS c FROM posts WHERE status='rejected'")
    total = await _query_one("SELECT COUNT(*) AS c FROM posts")
    polls = await _query_one("SELECT COUNT(*) AS c FROM polls WHERE status='sent'")

    return {
        "total_sent": sent["c"] if sent else 0,
        "pending": pending["c"] if pending else 0,
        "rejected": rejected["c"] if rejected else 0,
        "total": total["c"] if total else 0,
        "polls_sent": polls["c"] if polls else 0,
        "today": await get_today_posts_count(),
    }


# ===== POLLAR =====
async def save_poll(question: str, options: list) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO polls (question, options, created_at) VALUES (?, ?, ?)",
            (question, json.dumps(options, ensure_ascii=False), now_iso())
        )
        await db.commit()
        return cur.lastrowid


async def get_poll(poll_id: int):
    return await _query_one("SELECT * FROM polls WHERE id = ?", (poll_id,))


async def update_poll_status(poll_id: int, status: str, message_id: Optional[int] = None):
    if status == "sent":
        await _execute(
            "UPDATE polls SET status=?, sent_at=?, message_id=? WHERE id=?",
            (status, now_iso(), message_id, poll_id)
        )
    elif status == "cancelled":
        await _execute("UPDATE polls SET status=? WHERE id=?", (status, poll_id))
    else:
        await _execute("UPDATE polls SET status=? WHERE id=?", (status, poll_id))


# ===== JOB NATIJALARI (catch-up uchun) =====
async def mark_job_run(job_id: str, status: str, error: Optional[str] = None):
    """Bugungi ish natijasini yozadi. job_id + sana unique."""
    await _execute(
        """
        INSERT INTO job_runs (job_id, run_date, status, finished_at, error)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(job_id, run_date) DO UPDATE SET
            status = excluded.status,
            finished_at = excluded.finished_at,
            error = excluded.error
        """,
        (job_id, today_str(), status, now_iso(), (error or "")[:500])
    )


async def job_already_ran(job_id: str) -> bool:
    """Bugun bu ish bajarilganmi?"""
    row = await _query_one(
        "SELECT status FROM job_runs WHERE job_id = ? AND run_date = ?",
        (job_id, today_str())
    )
    return bool(row and row["status"] == "ok")


async def get_job_runs():
    """Oxirgi 15 ish natijasi (diagnostika uchun)."""
    return await _query_all(
        "SELECT * FROM job_runs ORDER BY finished_at DESC LIMIT 15"
    )


async def get_today_job_runs():
    return await _query_all(
        "SELECT * FROM job_runs WHERE run_date = ? ORDER BY job_id",
        (today_str(),)
    )


# ===== AI KVOTA HISOBI =====
async def record_ai_call(success: bool = True, note: str = ""):
    await _execute(
        "INSERT INTO ai_usage (ts, success, note) VALUES (?, ?, ?)",
        (now_iso(), 1 if success else 0, (note or "")[:200])
    )


async def ai_used_today() -> int:
    row = await _query_one(
        "SELECT COUNT(*) AS c FROM ai_usage WHERE success = 1 AND DATE(ts) = ?",
        (today_str(),)
    )
    return row["c"] if row else 0


async def ai_used_last_minute() -> int:
    row = await _query_one(
        """
        SELECT COUNT(*) AS c FROM ai_usage
        WHERE success = 1 AND ts >= datetime('now', '-1 minute')
        """
    )
    return row["c"] if row else 0


async def prune_ai_usage(keep_days: int = 7):
    await _execute(
        "DELETE FROM ai_usage WHERE ts < datetime('now', ?)",
        (f"-{keep_days} days",)
    )


# ===== RASM KVOTA HISOBI =====
async def record_image_call(success: bool = True, note: str = ""):
    await _execute(
        "INSERT INTO image_usage (ts, success, note) VALUES (?, ?, ?)",
        (now_iso(), 1 if success else 0, (note or "")[:200])
    )


async def ai_used_images_today() -> int:
    row = await _query_one(
        "SELECT COUNT(*) AS c FROM image_usage WHERE success = 1 AND DATE(ts) = ?",
        (today_str(),)
    )
    return row["c"] if row else 0


async def prune_image_usage(keep_days: int = 7):
    await _execute(
        "DELETE FROM image_usage WHERE ts < datetime('now', ?)",
        (f"-{keep_days} days",)
    )


# ===== REAL VAQTDA VAZIFALAR (/schedule) =====
async def add_adhoc_task(run_at_iso: str, topic: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "INSERT INTO adhoc_tasks (run_at, topic, status, created_at) VALUES (?, ?, 'pending', ?)",
            (run_at_iso, topic, now_iso())
        )
        await db.commit()
        return cur.lastrowid


async def get_pending_adhoc_tasks():
    return await _query_all(
        "SELECT * FROM adhoc_tasks WHERE status = 'pending' ORDER BY run_at"
    )


async def finish_adhoc_task(task_id: int, status: str, error: Optional[str] = None):
    await _execute(
        "UPDATE adhoc_tasks SET status=?, finished_at=?, error=? WHERE id=?",
        (status, now_iso(), (error or "")[:500], task_id)
    )


async def get_adhoc_tasks(limit: int = 10):
    return await _query_all(
        "SELECT * FROM adhoc_tasks ORDER BY id DESC LIMIT ?", (limit,)
    )
