"""
main.py — Bot + Scheduler ni bir vaqtda ishga tushiradi.
"""
import asyncio
import sys
from config import check_config, BOT_TOKEN, ADMIN_ID, CHANNEL_ID
from database import init_db
from telegram_bot import bot, dp
from scheduler import start_scheduler, stop_scheduler


async def on_startup():
    """Bot ishga tushganda bajariladi."""
    print("=" * 50)
    print("🚀 Volstrit Agent ishga tushmoqda...")
    print("=" * 50)

    # Sozlamalarni tekshirish
    check_config()
    print(f"📢 Kanal: {CHANNEL_ID}")
    print(f"👤 Admin ID: {ADMIN_ID}")

    # Bazani tayyorlash
    await init_db()

    # Schedulerni ishga tushirish
    start_scheduler()

    # Adminga xabar
    try:
        await bot.send_message(
            chat_id=ADMIN_ID,
            text=(
                "🚀 <b>Volstrit Agent ishga tushdi!</b>\n\n"
                "⏰ <b>Avtomatik postlar:</b>\n"
                "   • Ertalab: 08:30\n"
                "   • Tushlik: 13:00\n"
                "   • Kechqurun: 18:30\n\n"
                "📊 <b>Haftalik so'rovnoma:</b> yakshanba 10:00\n\n"
                "📖 Yordam uchun /help yozing."
            ),
            parse_mode="HTML"
        )
    except Exception as e:
        print(f"⚠️ Adminga xabar yuborilmadi: {e}")

    print("\n✅ Bot tayyor! Polling boshlanmoqda...\n")


async def on_shutdown():
    """Bot to'xtaganda bajariladi."""
    print("\n🛑 Bot to'xtatilmoqda...")
    stop_scheduler()
    await bot.session.close()
    print("✅ Bot to'xtatildi.")


async def main():
    """Asosiy funksiya."""
    try:
        await on_startup()
        # Polling rejimida ishga tushirish
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        print("\n⚠️ Ctrl+C bosildi.")
    except Exception as e:
        print(f"❌ Xatolik: {e}")
        sys.exit(1)
    finally:
        await on_shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n👋 Xayr!")
