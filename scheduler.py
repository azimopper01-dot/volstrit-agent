"""
scheduler.py — Kunlik, haftalik va real vaqtda berilgan vazifalarni bajaradi.

TUZATILGAN ASOSIY XATO:
    Eski kodda `CronTrigger(hour=h, minute=m)` timezone BERILMAGAN edi.
    APScheduler 3.x bunday trigger'ni konteynerning mahalliy vaqti bilan
    yaratadi — Railway'da bu UTC. Natijada barcha postlar +5 soat kechikadi
    (08:30 -> 13:30). Endi har bir trigger'ga `timezone=TZ` aniq beriladi.

QO'SHILGANLAR:
  * misfire_grace_time — ish kechikib kelsa ham bajariladi
  * coalesce — ko'p o'tkazilgan ishni bittaga jamlaydi
  * catch-up — konteyner ish vaqtida qayta ishga tushsa, o'tib ketgan
    ish darhol bajariladi (post hech qachon o'tkazilmaydi)
  * heartbeat — tiriklikni logga yozib turadi
  * /schedule orqali beriladigan real vaqt vazifalari
"""
import asyncio
import html
import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import (
    POST_TIME_MORNING, POST_TIME_NOON, POST_TIME_EVENING,
    POLL_DAY, POLL_TIME, TIMEZONE, TZ, ADMIN_ID,
    AUTO_PUBLISH, AUTO_PUBLISH_LABEL, AI_DAILY_LIMIT, NOTIFY_ADMIN, now_tz,
    APPROVAL_TIMEOUT_HOURS, APPROVAL_REMINDERS,
)
import database
from telegram_bot import create_and_send_post, create_and_send_poll, safe_send

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("scheduler")

scheduler = AsyncIOScheduler(timezone=TZ)

# Ish nomlari -> (job_id, vaqt, tip)
JOBS_META = {}


def parse_time(time_str: str):
    """'08:30' -> (8, 30)"""
    try:
        hour, minute = str(time_str).strip().split(":")
        return int(hour), int(minute)
    except (ValueError, AttributeError):
        logger.error("Vaqt formati noto'g'ri: %r (08:30 kutilgan)", time_str)
        raise


# ===== BARCHA ISHLAR UCHUN YAGONA ISHIVCHI =====
async def _run_job(job_id: str, label: str, coro_factory, catch_up: bool = False):
    """
    Ishni bajaradi, natijani bazaga yozadi va xatolarni ushlaydi.
    Hech qachon job butunlay "jimgina" xotiraga ketmaydi.
    """
    prefix = "🔁 Qayta bajarilmoqda" if catch_up else "▶️ Bajarilmoqda"
    print(f"{prefix}: {label}")
    try:
        result = await coro_factory()
        await database.mark_job_run(job_id, "ok")
        print(f"✅ {label} — bajarildi")
        return result
    except Exception as e:
        logger.exception("%s ishida xato", label)
        await database.mark_job_run(job_id, "failed", error=f"{type(e).__name__}: {e}")
        print(f"❌ {label} — xato: {type(e).__name__}: {e}")
        if NOTIFY_ADMIN:
            try:
                await safe_send(
                    ADMIN_ID,
                    f"🚨 <b>Ish bajarilmadi: {label}</b>\n"
                    f"Xato: {str(e)[:400]}\n"
                    f"Job: <code>{job_id}</code>",
                )
            except Exception:
                pass
        return None


# ===== KUNLIK ISHLAR =====
# Muhim: bir kunda 3 ta post bo'ladi. Har biriga ALHIDDA mavzu beriladi —
# aks holda uchala post bir xil mavzuda chiqib, kanal zerikarli bo'ladi.
_USED_TOPICS: set = set()


def _reset_topics():
    global _USED_TOPICS
    _USED_TOPICS = set()


async def job_morning_post(catch_up: bool = False):
    return await _run_job(
        "morning_post", f"🌅 Ertalabki post ({POST_TIME_MORNING})",
        lambda: create_and_send_post(post_type="morning", used_topics=_USED_TOPICS),
        catch_up
    )


async def job_noon_post(catch_up: bool = False):
    return await _run_job(
        "noon_post", f"☀️ Tushlikdagi post ({POST_TIME_NOON})",
        lambda: create_and_send_post(post_type="noon", used_topics=_USED_TOPICS),
        catch_up
    )


async def job_evening_post(catch_up: bool = False):
    return await _run_job(
        "evening_post", f"🌆 Kechki post ({POST_TIME_EVENING})",
        lambda: create_and_send_post(post_type="evening", used_topics=_USED_TOPICS),
        catch_up
    )


async def job_weekly_poll(catch_up: bool = False):
    return await _run_job(
        "weekly_poll", f"📊 Haftalik so'rovnoma ({POLL_DAY} {POLL_TIME})",
        create_and_send_poll, catch_up
    )


# ===== KUNLIK TOZALASH VA ESLATISH =====
async def _daily_cleanup():
    """Eski AI va rasm hisoblarini tozalash."""
    try:
        await database.prune_ai_usage()
        await database.prune_image_usage()
    except Exception as e:
        logger.warning("Tozalashda xato: %s", e)


async def job_new_day_reset():
    """
    Har kuni 00:05 da ishlatilgan mavzular ro'yxatini tozalaydi.

    Aks holda bir necha kundan keyin barcha mavzular "ishlatilgan"
    bo'lib qoladi va yana takrorlanish boshlanadi.
    """
    _reset_topics()
    print(f"🔄 Yangi kun — mavzular ro'yxati tozalandi ({now_tz():%Y-%m-%d})")


async def job_remind_pending():
    """
    AUTO_PUBLISH=false rejimida post kanalgacha tasdiqlashni kutadi.
    Admin uzoq javob bermagan bo'lsa — eslatish yuboradi, shunda post
    unutilib qolmaydi.
    """
    if not (APPROVAL_REMINDERS and NOTIFY_ADMIN):
        return

    try:
        stale = await database.get_stale_pending_posts(APPROVAL_TIMEOUT_HOURS)
    except Exception as e:
        logger.warning("Tasdiqlanmagan postlarni tekshirib bo'lmadi: %s", e)
        return

    if not stale:
        return

    ids = ", ".join(f"#{p['id']}" for p in stale)
    print(f"⏰ {len(stale)} ta post {APPROVAL_TIMEOUT_HOURS} soatdan beri "
          f"tasdiqlanmagan: {ids}")
    try:
        await safe_send(
            ADMIN_ID,
            f"⏰ <b>{len(stale)} ta post tasdiqlashni kutmoqda</b>\n\n"
            f"{html.escape(ids)}\n\n"
            f"Ular {APPROVAL_TIMEOUT_HOURS} soatdan beri kutilmoqda.\n"
            f"Ko'rish va tasdiqlash: <code>/pending</code>",
        )
    except Exception as e:
        logger.warning("Eslatish yuborilmadi: %s", e)


# ===== REAL VAQTDA BERILGAN VAZIFALAR =====
async def heartbeat_tick():
    """
    Har 1 daqiqada /schedule orqali berilgan vazifalarni tekshiradi va bajaradi.
    Bu — "uzluksiz ishlash"ning kaliti: ishlab qolsa ham, qayta ishga
    tushsa ham hech bir vazifa yo'qolmaydi.
    """
    await run_adhoc_tasks()


async def run_adhoc_tasks():
    """Muddati kelgan /schedule vazifalarini bajaradi."""
    now = now_tz()
    try:
        tasks = await database.get_pending_adhoc_tasks()
    except Exception as e:
        logger.warning("Adhoc vazifalarni o'qib bo'lmadi: %s", e)
        return

    for t in tasks:
        try:
            run_at = datetime.fromisoformat(t["run_at"])
        except ValueError:
            await database.finish_adhoc_task(t["id"], "failed", "vaqt formati xato")
            continue

        if run_at > now:
            continue

        print(f"⏱ Real vaqt vazifasi #{t['id']}: {t['topic']}")
        try:
            await create_and_send_post(topic=t["topic"])
            await database.finish_adhoc_task(t["id"], "ok")
        except Exception as e:
            logger.exception("Adhoc vazifa xatosi")
            await database.finish_adhoc_task(t["id"], "failed", str(e))


async def heartbeat_log():
    """Har 10 daqiqada bir marta tiriklik belgisini yozadi."""
    ai_used = await database.ai_used_today()
    today = await database.get_today_posts_count()
    upcoming = []
    for job in scheduler.get_jobs():
        nxt = getattr(job, "next_run_time", None)
        if nxt and job.id != "heartbeat":
            upcoming.append(f"{job.id}@{nxt:%H:%M}")
    print(
        f"💓 Tirik | {now_tz():%H:%M:%S} ({TIMEZONE}) | "
        f"bugun: {today} post | AI: {ai_used}/{AI_DAILY_LIMIT} | "
        f"keyingi: {', '.join(sorted(upcoming)) or '-'}"
    )


# ===== CATCH-UP (o'tib ketgan ishni tutish) =====
async def catch_up_missed_jobs():
    """
    Ishga tushishda bugunning vaqt o'tib ketgan ishlari bajarilganmi tekshiriladi.
    Konteyner 08:35 da qayta ishga tushsa, 08:30 dagi post darhol chiqadi.
    """
    now = now_tz()
    caught = 0

    plan = [
        ("morning_post", POST_TIME_MORNING, job_morning_post),
        ("noon_post", POST_TIME_NOON, job_noon_post),
        ("evening_post", POST_TIME_EVENING, job_evening_post),
    ]

    # Haftalik so'rovnoma: faqat to'g'ri kun bo'lsa
    if POLL_DAY[:3].lower() == now.strftime("%a").lower():
        plan.append(("weekly_poll", POLL_TIME, job_weekly_poll))

    for job_id, time_str, func in plan:
        try:
            h, m = parse_time(time_str)
        except ValueError:
            continue

        scheduled = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if now < scheduled:
            continue  # hali vaqti kelmagan

        if await database.job_already_ran(job_id):
            continue  # bugun allaqachon bajarilgan

        # Bir kundan eskirgan bo'lsa o'tkazib yuboramiz
        if (now - scheduled) > timedelta(days=1):
            continue

        dt = (now - scheduled).total_seconds() / 60
        print(
            f"⚠️  '{job_id}' ishi {dt:.0f} daqiqa kechikan — "
            f"HOZIR bajarilmoqda (catch-up)"
        )
        await func(catch_up=True)
        caught += 1

    if caught:
        print(f"🔁 Jami {caught} ta kechikkan ish tiklandi.")
    else:
        print("✅ Kechikkan ish topilmadi.")
    return caught


# ===== SOZLASH =====
def setup_scheduler():
    """Barcha vazifalarni rejalashtiradi."""
    JOBS_META.clear()

    daily = [
        ("morning_post", POST_TIME_MORNING, job_morning_post, "🌅 Ertalabki post"),
        ("noon_post", POST_TIME_NOON, job_noon_post, "☀️ Tushlikdagi post"),
        ("evening_post", POST_TIME_EVENING, job_evening_post, "🌆 Kechki post"),
    ]

    for job_id, time_str, func, label in daily:
        h, m = parse_time(time_str)
        scheduler.add_job(
            func,
            # >>> TUZATISH: timezone=TZ majburiy. Aks holda UTC ishlatiladi. <<<
            CronTrigger(hour=h, minute=m, timezone=TZ),
            id=job_id,
            replace_existing=True,
            name=f"{label} ({time_str} {TIMEZONE})",
            # kechikib kelsa ham bajarilsin, o'tkazilmasin
            misfire_grace_time=3600,
            coalesce=True,
            max_instances=1,
        )
        JOBS_META[job_id] = (time_str, label)

    # Haftalik so'rovnoma
    h, m = parse_time(POLL_TIME)
    scheduler.add_job(
        job_weekly_poll,
        CronTrigger(day_of_week=POLL_DAY[:3], hour=h, minute=m, timezone=TZ),
        id="weekly_poll",
        replace_existing=True,
        name=f"📊 Haftalik so'rovnoma ({POLL_DAY} {POLL_TIME} {TIMEZONE})",
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )
    JOBS_META["weekly_poll"] = (POLL_TIME, "📊 Haftalik so'rovnoma")

    # Real vaqt vazifalari uchun "tik" — har daqiqada tekshiradi
    scheduler.add_job(
        heartbeat_tick,
        IntervalTrigger(minutes=1),
        id="heartbeat",
        replace_existing=True,
        name="💓 Real vaqt vazifalari (1 daqiqa)",
        max_instances=1,
        coalesce=True,
    )

    # 10 daqiqada bir tiriklik logi
    scheduler.add_job(
        heartbeat_log,
        IntervalTrigger(minutes=10),
        id="status_log",
        replace_existing=True,
        name="💓 Status log",
        max_instances=1,
        coalesce=True,
    )

    # Tasdiqlanmagan postlarga eslatish (AUTO_PUBLISH=false rejimida muhim)
    scheduler.add_job(
        job_remind_pending,
        IntervalTrigger(hours=1),
        id="remind_pending",
        replace_existing=True,
        name="⏰ Tasdiqlanmagan postlarga eslatish",
        max_instances=1,
        coalesce=True,
    )

    # Eski AI hisoblarini tozalash
    scheduler.add_job(
        _daily_cleanup,
        IntervalTrigger(hours=24),
        id="cleanup",
        replace_existing=True,
        name="🧹 Tozalash",
    )

    # Har kuni 00:05 da mavzular ro'yxatini tozalash (takrorlanmaslik uchun)
    scheduler.add_job(
        job_new_day_reset,
        CronTrigger(hour=0, minute=5, timezone=TZ),
        id="daily_reset",
        replace_existing=True,
        name="🔄 Yangi kun — mavzularni tozalash",
        misfire_grace_time=3600,
        coalesce=True,
        max_instances=1,
    )

    print("✅ Scheduler sozlandi:")
    for job in scheduler.get_jobs():
        print(f"   • {job.name}")
    print("   ⏳ Aniq vaqtlar scheduler.start() dan keyin chiqariladi.")


def print_next_runs():
    """
    Keyingi ish vaqtlarini chiqaradi.

    Muhim: APScheduler'da `next_run_time` faqat `start()` dan keyin
    to'lanadi — shuning uchun bu setup_scheduler() dan keyin
    alohida chaqirilishi SHART.
    """
    print("⏰ KEYINGI ISHLAR VAQTLARI:")
    rows = []
    for job in scheduler.get_jobs():
        nxt = getattr(job, "next_run_time", None)
        if nxt is None:
            continue
        when = nxt.strftime("%Y-%m-%d %H:%M")
        rows.append((nxt, f"   • {job.name}\n       keyingi: {when}"))
    for _, line in sorted(rows):
        print(line)
    if not rows:
        print("   (hech qanday ish rejalashtirilmagan)")
    return rows


def start_scheduler():
    """Schedulerni ishga tushiradi."""
    setup_scheduler()
    scheduler.start()
    print("🚀 Scheduler ishga tushdi.")
    print(f"🌍 Vaqt mintaqasi: {TIMEZONE} | Hozir: {now_tz():%Y-%m-%d %H:%M:%S}")
    print(f"📤 Avtomatik kanalga yuborish: {AUTO_PUBLISH_LABEL}")
    # next_run_time faqat start() dan keyin to'lanadi — shu sabab shu yerda
    print_next_runs()


async def notify_startup(next_runs: str):
    """Ishga tushganda adminga qisqa xabar."""
    if not NOTIFY_ADMIN:
        return
    try:
        await safe_send(
            ADMIN_ID,
            "🚀 <b>Volstrit Agent ishga tushdi!</b>\n\n"
            f"🌍 Vaqt mintaqasi: <code>{TIMEZONE}</code>\n"
            f"🕐 Hozir: <b>{now_tz():%Y-%m-%d %H:%M}</b>\n"
            f"📤 Avtomatik yuborish: {AUTO_PUBLISH_LABEL}\n\n"
            f"{next_runs}\n\n"
            f"📖 Yordam: /help",
        )
    except Exception as e:
        print(f"⚠️ Adminga xabar yuborilmadi: {e}")


def next_run_summary() -> str:
    """Keyingi ish vaqtlarini qisqa matn qilib qaytaradi."""
    rows = []
    for job in scheduler.get_jobs():
        if job.id in ("heartbeat", "status_log", "cleanup"):
            continue
        nxt = getattr(job, "next_run_time", None)
        if nxt:
            rows.append((nxt, f"   • {job.name} → {nxt:%Y-%m-%d %H:%M}"))
    # vaqt bo'yicha tartiblash (cheklanmagan satrlar oxirida)
    return "\n".join(line for _, line in sorted(rows, key=lambda r: r[0]))


def stop_scheduler():
    """Schedulerni to'xtatadi."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("🛑 Scheduler to'xtatildi.")
