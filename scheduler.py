"""
scheduler.py — Kunlik va haftalik vazifalarni rejalashtiradi.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from zoneinfo import ZoneInfo

from config import (
    POST_TIME_MORNING, POST_TIME_NOON, POST_TIME_EVENING,
    POLL_DAY, POLL_TIME, TIMEZONE
)
from telegram_bot import create_and_send_post, create_and_send_poll

# Vaqt mintaqasi
TZ = ZoneInfo(TIMEZONE)

# Scheduler
scheduler = AsyncIOScheduler(timezone=TZ)


def parse_time(time_str: str):
    """'08:30' -> (8, 30)"""
    hour, minute = time_str.split(":")
    return int(hour), int(minute)


async def job_morning_post():
    """Ertalabki post (08:30)."""
    print("🌅 Ertalabki post yaratilmoqda...")
    try:
        await create_and_send_post(post_type="morning")
        print("✅ Ertalabki post adminga yuborildi.")
    except Exception as e:
        print(f"❌ Ertalabki post xatolik: {e}")


async def job_noon_post():
    """Tushlikdagi post (13:00)."""
    print("☀️ Tushlikdagi post yaratilmoqda...")
    try:
        await create_and_send_post(post_type="noon")
        print("✅ Tushlikdagi post adminga yuborildi.")
    except Exception as e:
        print(f"❌ Tushlikdagi post xatolik: {e}")


async def job_evening_post():
    """Kechki post (18:30)."""
    print("🌆 Kechki post yaratilmoqda...")
    try:
        await create_and_send_post(post_type="evening")
        print("✅ Kechki post adminga yuborildi.")
    except Exception as e:
        print(f"❌ Kechki post xatolik: {e}")


async def job_weekly_poll():
    """Haftalik so'rovnoma (yakshanba 10:00)."""
    print("📊 Haftalik so'rovnoma yaratilmoqda...")
    try:
        await create_and_send_poll()
        print("✅ So'rovnoma adminga yuborildi.")
    except Exception as e:
        print(f"❌ So'rovnoma xatolik: {e}")


def setup_scheduler():
    """Barcha vazifalarni rejalashtiradi."""
    # Ertalabki post
    h, m = parse_time(POST_TIME_MORNING)
    scheduler.add_job(
        job_morning_post,
        CronTrigger(hour=h, minute=m),
        id="morning_post",
        replace_existing=True,
        name=f"Ertalabki post ({POST_TIME_MORNING})"
    )

    # Tushlikdagi post
    h, m = parse_time(POST_TIME_NOON)
    scheduler.add_job(
        job_noon_post,
        CronTrigger(hour=h, minute=m),
        id="noon_post",
        replace_existing=True,
        name=f"Tushlikdagi post ({POST_TIME_NOON})"
    )

    # Kechki post
    h, m = parse_time(POST_TIME_EVENING)
    scheduler.add_job(
        job_evening_post,
        CronTrigger(hour=h, minute=m),
        id="evening_post",
        replace_existing=True,
        name=f"Kechki post ({POST_TIME_EVENING})"
    )

    # Haftalik so'rovnoma
    h, m = parse_time(POLL_TIME)
    scheduler.add_job(
        job_weekly_poll,
        CronTrigger(day_of_week=POLL_DAY[:3], hour=h, minute=m),
        id="weekly_poll",
        replace_existing=True,
        name=f"Haftalik so'rovnoma ({POLL_DAY} {POLL_TIME})"
    )

    print("✅ Scheduler sozlandi:")
    for job in scheduler.get_jobs():
        print(f"   • {job.name}")


def start_scheduler():
    """Schedulerni ishga tushiradi."""
    setup_scheduler()
    scheduler.start()
    print("🚀 Scheduler ishga tushdi.")


def stop_scheduler():
    """Schedulerni to'xtatadi."""
    if scheduler.running:
        scheduler.shutdown()
        print("🛑 Scheduler to'xtatildi.")
