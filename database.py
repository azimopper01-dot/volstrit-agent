"""
database.py — Postlar tarixini SQLite bazasida saqlaydi.
"""
import aiosqlite
from datetime import datetime
from pathlib import Path
from config import DB_PATH


async def init_db():
    """Ma'lumotlar bazasini va jadvallarni yaratadi."""
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DB_PATH) as db:
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

        await db.execute("""
            CREATE TABLE IF NOT EXISTS stats (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT UNIQUE,
                posts_sent INTEGER DEFAULT 0,
                polls_sent INTEGER DEFAULT 0,
                subscribers INTEGER DEFAULT 0
            )
        """)

        await db.commit()
    print("✅ Ma'lumotlar bazasi tayyor.")


async def save_post(content: str, topic: str = "") -> int:
    """Yangi postni bazaga saqlaydi va ID qaytaradi."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO posts (content, topic) VALUES (?, ?)",
            (content, topic)
        )
        await db.commit()
        return cursor.lastrowid


async def get_post(post_id: int):
    """Postni ID bo'yicha oladi."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM posts WHERE id = ?", (post_id,)
        ) as cursor:
            return await cursor.fetchone()


async def update_post_status(
    post_id: int,
    status: str,
    message_id: int = None,
    error: str = None
):
    """Postning holatini yangilaydi."""
    async with aiosqlite.connect(DB_PATH) as db:
        now = datetime.now().isoformat()

        if status == "approved":
            await db.execute(
                "UPDATE posts SET status = ?, approved_at = ? WHERE id = ?",
                (status, now, post_id)
            )
        elif status == "sent":
            await db.execute(
                "UPDATE posts SET status = ?, sent_at = ?, message_id = ? WHERE id = ?",
                (status, now, message_id, post_id)
            )
        elif status == "rejected":
            await db.execute(
                "UPDATE posts SET status = ?, error = ? WHERE id = ?",
                (status, error, post_id)
            )
        else:
            await db.execute(
                "UPDATE posts SET status = ? WHERE id = ?",
                (status, post_id)
            )
        await db.commit()


async def get_pending_posts():
    """Tasdiqlanishi kutilayotgan postlarni oladi."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM posts WHERE status = 'pending' ORDER BY created_at DESC"
        ) as cursor:
            return await cursor.fetchall()


async def get_today_posts_count() -> int:
    """Bugun yuborilgan postlar sonini qaytaradi."""
    today = datetime.now().strftime("%Y-%m-%d")
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM posts WHERE DATE(sent_at) = ? AND status = 'sent'",
            (today,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


async def save_poll(question: str, options: list) -> int:
    """So'rovnomani bazaga saqlaydi."""
    import json
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO polls (question, options) VALUES (?, ?)",
            (question, json.dumps(options, ensure_ascii=False))
        )
        await db.commit()
        return cursor.lastrowid


async def get_stats():
    """Umumiy statistikani qaytaradi."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM posts WHERE status = 'sent'"
        ) as cursor:
            total_sent = (await cursor.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM posts WHERE status = 'pending'"
        ) as cursor:
            pending = (await cursor.fetchone())[0]

        async with db.execute(
            "SELECT COUNT(*) FROM posts WHERE status = 'rejected'"
        ) as cursor:
            rejected = (await cursor.fetchone())[0]

    return {
        "total_sent": total_sent,
        "pending": pending,
        "rejected": rejected,
    }
