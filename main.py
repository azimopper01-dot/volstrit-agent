"""
main.py — Bot + Scheduler ni bir vaqtda ishga tushiradi.

MUHIM: bitta bot tokeni bilan FAQAT bitta poller ishlashi kerak.
Ikkalasi bir vaqtda ishlasa Telegram "Conflict: terminated by other
getUpdates request" beradi va ikkalasi ham ishdan chiqadi.
Shuning uchun mahalliy kompyuterda AL_LOCAL_MODE=1 talab qilinadi.
"""
import asyncio
import logging
import sys

from aiogram.exceptions import TelegramConflictError, TelegramNetworkError

from config import (
    check_config, BOT_TOKEN, ADMIN_ID, CHANNEL_ID,
    IS_RAILWAY, RAILWAY_ENV_NAME, AL_LOCAL_MODE, SHOULD_POLL,
    DB_IS_PERSISTENT, TIMEZONE, now_tz, AUTO_PUBLISH, AUTO_PUBLISH_LABEL,
    AI_DAILY_LIMIT,
)
from database import init_db, ai_used_today
from telegram_bot import bot, dp, safe_send
from scheduler import (
    start_scheduler, stop_scheduler, catch_up_missed_jobs,
    next_run_summary, notify_startup,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("main")


async def on_startup():
    """Bot ishga tushganda bajariladi."""
    print("=" * 52)
    print("🚀 Volstrit Agent ishga tushmoqda...")
    print("=" * 52)

    check_config()

    print(f"📢 Kanal: {CHANNEL_ID}")
    print(f"👤 Admin ID: {ADMIN_ID}")
    print(f"🚂 Muhit: {'Railway / ' + RAILWAY_ENV_NAME if IS_RAILWAY else 'MAHHALLIY kompyuter'}")
    print(f"🔌 Polling ruxsat: {SHOULD_POLL}")
    if not DB_IS_PERSISTENT:
        print("⚠️  Diqqat: bazaningiz vaqtinchik — har deploy'da tozalanadi.")
        print("    💡 Railway'ga Volume qo'shing (/data) va DB_PATH=/data/posts.db qiling.")

    await init_db()

    # Scheduler (trigger timezone'lari config.TZ bilan aniq belgilangan)
    start_scheduler()

    # Kechikkan ishlarni tiklash
    await catch_up_missed_jobs()

    used = await ai_used_today()
    print(f"🤖 AI bugun: {used}/{AI_DAILY_LIMIT}")
    print(f"📤 Avtomatik kanalga yuborish: {AUTO_PUBLISH_LABEL}")

    await notify_startup(next_run_summary())

    print("\n✅ Bot tayyor! Polling boshlanmoqda...\n")


async def on_shutdown():
    print("\n🛑 Bot to'xtatilmoqda...")
    stop_scheduler()
    try:
        await bot.session.close()
    except Exception:
        pass
    print("✅ Bot to'xtatildi.")


async def polling_supervisor():
    """
    Polling'ni qayta-qayta ishga tushiradi.

    TelegramConflictError = boshqa poller bor. Bu holda aniq xabar beramiz
    va kutamiz — qachon u to'xtasa, o'zimiz avtomatik davom etamiz.
    """
    backoff = 5
    while True:
        try:
            await dp.start_polling(
                bot,
                allowed_updates=["message", "callback_query"],
                handle_signals=False,
            )
            # start_polling qaytishi = normal to'xtash
            logger.info("Polling to'xtadi, qayta ishga tushirilmoqda...")
        except TelegramConflictError:
            backoff = min(backoff * 2, 300)
            logger.error(
                "❌ KONFLIKT: Bu bot tokeni bilan boshqa poller ishlayapti! "
                "Railway loglarida ikkinchi nusxa bo'lsa — uni darhol o'chiring. "
                "Mahalliy kompyuterda botni ishga tushirmang "
                "(yoki .env da AL_LOCAL_MODE=1 qo'ying). "
                "%s sekundan keyin qayta uriladi.",
                backoff,
            )
            await asyncio.sleep(backoff)
            continue
        except (TelegramNetworkError, asyncio.TimeoutError) as e:
            backoff = min(backoff * 2, 120)
            logger.warning("Tarmoq xatosi (%s) — %ss keyin qayta uriladi", e, backoff)
            await asyncio.sleep(backoff)
            continue
        except Exception as e:
            backoff = min(backoff * 2, 120)
            logger.exception("Kutilmagan xato: %s — %ss keyin", e, backoff)
            await asyncio.sleep(backoff)
            continue

        backoff = 5
        await asyncio.sleep(backoff)


async def main():
    try:
        await on_startup()

        if not SHOULD_POLL:
            print("\n" + "!" * 66)
            print("❌ POLLING O'CHIRILGAN.")
            print("   Bu bot tokeni bilan ikkala joyda bir vaqtda ishlash mumkin emas —")
            print("   Telegram ikkinchisini darhol o'ldiradi (Conflict).")
            print()
            print("   Tanlang:")
            print("     • Railway — avtomatik ishlaydi, bu xato chiqmaydi")
            print("     • Mahalliy — .env faylga AL_LOCAL_MODE=1 qo'shing,")
            print("       lekin POLLING o'chqasangiz Railway ishlashda qoladi")
            print("!" * 66 + "\n")
            # Scheduler ishlayveradi, faqat Telegram polling o'chqancha
            while True:
                await asyncio.sleep(3600)

        print("=" * 52)
        print(f"🕐 Hozirgi vaqt: {now_tz():%Y-%m-%d %H:%M:%S} ({TIMEZONE})")
        print(next_run_summary())
        print("=" * 52 + "\n")

        await polling_supervisor()

    except KeyboardInterrupt:
        print("\n⚠️ Ctrl+C bosildi.")
    except Exception as e:
        logger.exception("Halokatli xato")
        print(f"❌ Xatolik: {e}")
        sys.exit(1)
    finally:
        await on_shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Xayr!")
