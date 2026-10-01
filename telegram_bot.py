"""
telegram_bot.py — Bot, tasdiqlash tizimi va kanalga yuborish.

Muhim o'zgarishlar:
1. Postlar endi TO'G'RI KANALGA avtomatik yuboriladi (config.AUTO_PUBLISH).
   Admin xabarni ko'rib, keyinchalik o'chira yoki qayta yozdirishi mumkin.
2. Kanal xabarlari parse_mode=O'CHIRILGAN holda yuboriladi — AI matnidagi
   `&`, `<`, `>` belgilari Telegram'ni "can't parse entities" bilan
   buzmasligi uchun.
3. Telegram 429 (flood) va timeout'larda qayta urish.
4. Yangi buyruqlar: /schedule, /health, /jobs, /today.
"""
import asyncio
import html
import logging
from datetime import timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.client.default import DefaultRequestProperties
from aiogram.filters import Command
from aiogram.enums import ParseMode
from aiogram.exceptions import (
    TelegramRetryAfter, TelegramBadRequest,
    TelegramNetworkError, TelegramForbiddenError
)

from config import (
    BOT_TOKEN, ADMIN_ID, CHANNEL_ID, CHANNEL_LINK, CHANNEL_NAME,
    AUTO_PUBLISH, AUTO_PUBLISH_LABEL, NOTIFY_ADMIN, MAX_POST_LENGTH,
    TELEGRAM_CONNECT_TIMEOUT, TELEGRAM_READ_TIMEOUT, TELEGRAM_SEND_RETRIES,
    TIMEZONE, now_tz, now_iso, POST_TIME_MORNING, POST_TIME_NOON,
    POST_TIME_EVENING, POLL_DAY, POLL_TIME, AI_DAILY_LIMIT,
)
import database
from ai_generator import (
    generate_post, generate_post_for_topic, generate_poll, improve_post
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)
logger = logging.getLogger("telegram_bot")

# Bot va Dispatcher
# Standart timeout'lar juda past (5s) — Railway'da "Request timeout" beradi.
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultRequestProperties(
        connect_timeout=TELEGRAM_CONNECT_TIMEOUT,
        read_timeout=TELEGRAM_READ_TIMEOUT,
    ),
)

dp = Dispatcher()
router = Router()
dp.include_router(router)


# ===== XAVFSIK YUBORISH =====
async def safe_send(chat_id: int | str, text: str, **kwargs):
    """Xatolarga chidamli yuborish: 429 / timeout / entity xatolarini uradi."""
    last = None
    for attempt in range(1, TELEGRAM_SEND_RETRIES + 1):
        try:
            return await bot.send_message(chat_id=chat_id, text=text, **kwargs)

        except TelegramRetryAfter as e:
            wait = min(int(e.retry_after or 5) + 1, 60)
            logger.warning("Flood control: %ss kutamiz (urinish %s)", wait, attempt)
            last = e
            await asyncio.sleep(wait)

        except TelegramBadRequest as e:
            msg = str(e)
            if "message is too long" in msg.lower() or "too long" in msg.lower():
                limit = 4000
                logger.warning("Xabar uzun, %s belgiga qisqartiramiz", limit)
                return await bot.send_message(
                    chat_id=chat_id, text=text[:limit] + "\n\n…", **kwargs
                )
            if "can't parse entities" in msg.lower() and kwargs.get("parse_mode"):
                # HTML muvaffaqiyatsiz — oddiy matn sifatida qayta yuboramiz
                logger.warning("HTML parse xatosi, oddiy matn bilan yuboriladi")
                kwargs = dict(kwargs)
                kwargs.pop("parse_mode", None)
                kwargs.pop("reply_markup", None)
                return await bot.send_message(chat_id=chat_id, text=text, **kwargs)
            logger.error("TelegramBadRequest: %s", msg)
            raise

        except (TelegramNetworkError, TelegramForbiddenError) as e:
            last = e
            logger.warning("Telegram tarmoq xatosi (urinish %s): %s", attempt, e)
            await asyncio.sleep(min(2 ** attempt, 10))

    raise last if last else RuntimeError("yuborilmadi")


# ===== KLAVIATURALAR =====
def published_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Kanalga chiqarilgan post uchun boshqaruv tugmalari."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑 Kanaldan o'chirish", callback_data=f"delete_{post_id}"),
            InlineKeyboardButton(text="🔁 Qayta yozish", callback_data=f"rewrite_{post_id}"),
        ],
    ])


def pending_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Tasdiqlash kutilayotgan post uchun."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Tasdiqlash", callback_data=f"approve_{post_id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_{post_id}"),
        ],
        [
            InlineKeyboardButton(text="✏️ Qayta yozish", callback_data=f"rewrite_{post_id}"),
            InlineKeyboardButton(text="⏭ Keyingi", callback_data=f"skip_{post_id}"),
        ],
    ])


def _preview_text(post_id: int, content: str, post_type: str) -> str:
    """Adminga ko'rsatish uchun xabar (HTML escaped — buzilmaydi)."""
    body = html.escape(content or "")[:3000]
    header = (
        f"📝 <b>Yangi post #{post_id}</b>\n"
        f"🕐 Turi: <code>{html.escape(str(post_type))}</code>\n"
        f"📏 Belgilar: {len(content or '')}\n"
    )
    if AUTO_PUBLISH:
        header += "📤 <i>Kanalga avtomatik yuborilgan</i>\n"
    return f"{header}\n{'━' * 16}\n{body}\n{'━' * 16}"


# ===== KOMANDALAR =====
@router.message(Command("start"))
async def cmd_start(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Siz admin emassiz.")
        return
    await message.answer(
        f"👋 Salom, Admin!\n\n"
        f"📢 Kanal: <b>{CHANNEL_NAME}</b>\n"
        f"🔗 {CHANNEL_LINK}\n\n"
        f"<b>Buyruqlar:</b>\n"
        f"/post — hozir post yozish\n"
        f"/poll — so'rovnoma yaratish\n"
        f"/schedule HH:MM mavzu — real vaqtda vazifa berish\n"
        f"/stats — statistika\n"
        f"/pending — tasdiqlanmagan postlar\n"
        f"/today — bugungi ishlar\n"
        f"/health — bot holati\n"
        f"/help — yordam",
        parse_mode=ParseMode.HTML
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer(
        f"📖 <b>Yordam</b>\n\n"
        f"1️⃣ <b>/post</b> — AI hozir post yozadi va kanalga yuboradi\n"
        f"2️⃣ Xabar tugmalari orqali o'chirilishi yoki qayta yozilishi mumkin\n\n"
        f"⏰ <b>Avtomatik postlar ({TIMEZONE}):</b> "
        f"{POST_TIME_MORNING}, {POST_TIME_NOON}, {POST_TIME_EVENING}\n"
        f"📊 <b>So'rovnoma:</b> har {POLL_DAY} {POLL_TIME}\n\n"
        f"🕐 <b>Real vaqtda vazifa:</b>\n"
        f"<code>/schedule 14:30 Bitcoin haqida yoz</code>\n"
        f"<code>/schedule +20m kripto tahlil</code>",
        parse_mode=ParseMode.HTML
    )


@router.message(Command("post"))
async def cmd_post(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("🤖 AI post yozyapti, kuting...")
    try:
        await create_and_send_post(post_type="morning")
    except Exception as e:
        logger.exception("Qo'lda post xatosi")
        await message.answer(f"❌ Xatolik: {e}")


@router.message(Command("poll"))
async def cmd_poll(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("🤖 So'rovnoma tayyorlanmoqda...")
    await create_and_send_poll()


@router.message(Command("schedule"))
async def cmd_schedule(message: Message):
    """Real vaqtda vazifa berish: /schedule 14:30 mavzu yoki /schedule +20m mavzu"""
    if message.from_user.id != ADMIN_ID:
        return

    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer(
            "⏰ <b>Foydalanish:</b>\n"
            "<code>/schedule 14:30 Bitcoin haqida yoz</code>\n"
            "<code>/schedule +20m kripto tahlil qil</code>\n"
            "<code>/schedule 2h mavzu</code>",
            parse_mode=ParseMode.HTML
        )
        return

    when, topic = args[1], args[2].strip()
    now = now_tz()

    # "+20m", "2h", "+1h30m"
    rel = None
    import re as _re
    m = _re.fullmatch(r"\+?(\d+)([mhd])", when.lower())
    if m:
        val, unit = int(m.group(1)), m.group(2)
        rel = {"m": timedelta(minutes=val),
               "h": timedelta(hours=val),
               "d": timedelta(days=val)}[unit]
    elif _re.fullmatch(r"\d{1,2}:\d{2}", when):
        try:
            hh, mm = when.split(":")
            target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            if target <= now:
                target += timedelta(days=1)
            rel = target - now
        except ValueError:
            pass

    if rel is None:
        await message.answer("❌ Vaqtni tushunmadim. Namuna: <code>/schedule 14:30 mavzu</code> "
                            "yoki <code>/schedule +20m mavzu</code>", parse_mode=ParseMode.HTML)
        return

    run_at = now + rel
    task_id = await database.add_adhoc_task(run_at.isoformat(timespec="seconds"), topic)
    await message.answer(
        f"✅ Vazifa qayd etildi <b>#{task_id}</b>\n"
        f"🕐 Bajarilishi: <b>{run_at:%Y-%m-%d %H:%M}</b> ({TIMEZONE})\n"
        f"📝 Mavzu: {html.escape(topic)}",
        parse_mode=ParseMode.HTML
    )


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    s = await database.get_stats()
    await message.answer(
        f"📊 <b>Statistika</b>\n\n"
        f"📤 Kanalga yuborilgan: {s['total_sent']}\n"
        f"📅 Bugun: {s['today']}\n"
        f"⏳ Kutilayotgan: {s['pending']}\n"
        f"❌ Rad etilgan: {s['rejected']}\n"
        f"📊 So'rovnoma: {s['polls_sent']}\n"
        f"📝 Jami yaratilgan: {s['total']}",
        parse_mode=ParseMode.HTML
    )


@router.message(Command("pending"))
async def cmd_pending(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    posts = await database.get_pending_posts()
    if not posts:
        await message.answer("✅ Tasdiqlanmagan postlar yo'q.")
        return
    for p in posts:
        await message.answer(
            f"⏳ <b>Post #{p['id']}</b>\n\n{html.escape(p['content'] or '')[:1200]}",
            parse_mode=ParseMode.HTML,
            reply_markup=pending_keyboard(p["id"])
        )


@router.message(Command("today"))
async def cmd_today(message: Message):
    """Bugungi avtomatik ishlar natijasi."""
    if message.from_user.id != ADMIN_ID:
        return
    runs = await database.get_today_job_runs()
    if not runs:
        await message.answer("📭 Bugun hali biror ish natijasi yo'q.")
        return
    lines = [f"📅 <b>Bugungi ishlar</b> ({now_tz():%Y-%m-%d})\n"]
    icons = {"ok": "✅", "failed": "❌", "skipped": "⏭"}
    for r in runs:
        lines.append(
            f"{icons.get(r['status'], '•')} <code>{html.escape(r['job_id'])}</code> — "
            f"{(r['finished_at'] or '')[11:16]}"
            + (f"\n   <i>{html.escape((r['error'] or '')[:120])}</i>" if r["error"] else "")
        )
    await message.answer("\n".join(lines), parse_mode=ParseMode.HTML)


@router.message(Command("health"))
async def cmd_health(message: Message):
    """Bot holati — muammolarni tez ko'rish uchun."""
    if message.from_user.id != ADMIN_ID:
        return

    # Keyingi ish vaqtlari
    try:
        from scheduler import scheduler, JOBS_META
        upcoming = []
        for job in scheduler.get_jobs():
            nxt = getattr(job, "next_run_time", None)
            if nxt:
                upcoming.append(f"   • {job.name} — {nxt:%Y-%m-%d %H:%M}")
        upcoming_txt = "\n".join(sorted(upcoming)) or "   (yo'q)"
    except Exception:
        upcoming_txt = "   (scheduler yuklanmagan)"

    ai_used = await database.ai_used_today()
    stats = await database.get_stats()

    from config import IS_RAILWAY, DB_PATH, DB_IS_PERSISTENT, AUTO_PUBLISH
    await message.answer(
        f"🩺 <b>Bot holati</b>\n\n"
        f"🕐 Hozir: <b>{now_tz():%Y-%m-%d %H:%M:%S}</b> ({TIMEZONE})\n"
        f"🌍 TZ sozlamasi: <code>{TIMEZONE}</code>\n"
        f"🚂 Railway: {IS_RAILWAY}\n"
        f"💾 Baza: <code>{html.escape(DB_PATH)}</code> "
        f"{'🔒 doimiy' if DB_IS_PERSISTENT else '⚠️ vaqtinchik'}\n"
        f"📤 Avtomatik yuborish: {AUTO_PUBLISH_LABEL}\n"
        f"🤖 AI bugun: <b>{ai_used}/{AI_DAILY_LIMIT}</b>\n"
        f"📤 Bugun yuborilgan: {stats['today']}\n\n"
        f"⏰ <b>Keyingi ishlar:</b>\n{upcoming_txt}",
        parse_mode=ParseMode.HTML
    )


# ===== POST YARATISH =====
async def create_and_send_post(post_type: str = "morning", topic: str = None) -> int:
    """
    Post yaratadi va KANALGA yuboradi (AUTO_PUBLISH= True bo'lsa).
    Adminga ko'rish uchun nusxa va boshqaruv tugmalari yuboriladi.
    """
    if topic:
        content = await generate_post_for_topic(topic)
    else:
        content = await generate_post(post_type=post_type)

    post_id = await database.save_post(content=content, topic=post_type)

    sent = None
    if AUTO_PUBLISH:
        try:
            # Kanalga xom (parse_mode'siz) matn — HTML xatolarining oldi olindi
            sent = await safe_send(CHANNEL_ID, content)
            await database.update_post_status(
                post_id, "sent", message_id=sent.message_id
            )
            print(f"✅ Post #{post_id} kanalga yuborildi (msg={sent.message_id})")
        except Exception as e:
            logger.exception("Kanalga yuborish muvaffaqiyatsiz")
            await database.update_post_status(post_id, "pending", error=str(e))
            # Kanalga chiqolmagan bo'lsa, tasdiqlashga qoldiramiz
            if NOTIFY_ADMIN:
                await safe_send(
                    ADMIN_ID,
                    f"⚠️ <b>Post #{post_id} kanalga chiqmadi!</b>\n"
                    f"Sabab: {html.escape(str(e))[:300]}\n"
                    f"Qo'lda yuborish uchun tugmani bosing.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=pending_keyboard(post_id),
                )
            return post_id

    # Adminga ko'rish uchun nusxa
    if NOTIFY_ADMIN:
        try:
            await safe_send(
                ADMIN_ID,
                _preview_text(post_id, content, post_type),
                parse_mode=ParseMode.HTML,
                reply_markup=(published_keyboard(post_id) if sent else pending_keyboard(post_id)),
            )
        except Exception as e:
            logger.warning("Adminga xabar yuborilmadi: %s", e)

    return post_id


async def create_and_send_poll() -> int | None:
    """So'rovnoma yaratib, adminga yuboradi (tasdiqlash bilan)."""
    poll_data = await generate_poll()
    if not poll_data:
        if NOTIFY_ADMIN:
            await safe_send(
                ADMIN_ID,
                "❌ So'rovnoma yaratilmadi (AI kvota tugab qolgan). "
                "Keyinroq /poll bilan qayta urinib ko'ring."
            )
        return None

    import json
    poll_id = await database.save_poll(
        question=poll_data["question"], options=poll_data["options"]
    )

    text = (
        f"📊 <b>Yangi so'rovnoma #{poll_id}</b>\n\n"
        f"❓ {html.escape(poll_data['question'])}\n\n"
    )
    for i, opt in enumerate(poll_data["options"], 1):
        text += f"{i}. {html.escape(opt)}\n"

    try:
        await safe_send(
            ADMIN_ID,
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Kanalga chiqarish", callback_data=f"poll_send_{poll_id}"),
                    InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"poll_cancel_{poll_id}"),
                ]
            ])
        )
    except Exception as e:
        logger.warning("So'rovnoma adminga yuborilmadi: %s", e)
    return poll_id


# ===== CALLBACK HANDLERLAR =====
def _deny(callback: CallbackQuery, text: str = "⛔ Ruxsat yo'q"):
    return callback.answer(text, show_alert=True)


@router.callback_query(F.data.startswith("approve_"))
async def cb_approve(callback: CallbackQuery):
    """Tasdiqlanmagan postni kanalga chiqarish."""
    if callback.from_user.id != ADMIN_ID:
        return await _deny(callback)

    post_id = int(callback.data.split("_")[1])
    post = await database.get_post(post_id)
    if not post:
        return await callback.answer("❌ Post topilmadi", show_alert=True)
    if post["status"] == "sent":
        return await callback.answer("⚠️ Bu post allaqachon yuborilgan", show_alert=True)

    try:
        sent = await safe_send(CHANNEL_ID, post["content"])
        await database.update_post_status(post_id, "sent", message_id=sent.message_id)
        try:
            await callback.message.edit_reply_markup(reply_markup=published_keyboard(post_id))
        except TelegramBadRequest:
            pass
        await callback.message.answer(f"✅ Post #{post_id} kanalga muvaffaqiyatli yuborildi!")
        await callback.answer("✅ Yuborildi!")
    except Exception as e:
        logger.exception("Tasdiqlashda xatolik")
        await database.update_post_status(post_id, "pending", error=str(e))
        await callback.answer(f"❌ Xatolik: {e}"[:190], show_alert=True)


@router.callback_query(F.data.startswith("delete_"))
async def cb_delete(callback: CallbackQuery):
    """Kanalga chiqarilgan postni o'chirish."""
    if callback.from_user.id != ADMIN_ID:
        return await _deny(callback)

    post_id = int(callback.data.split("_")[1])
    post = await database.get_post(post_id)
    if not post or not post["message_id"]:
        return await callback.answer("❌ Xabar topilmadi", show_alert=True)

    try:
        await bot.delete_message(CHANNEL_ID, post["message_id"])
        await database.update_post_status(post_id, "deleted", error="Admin o'chirdi")
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        await callback.message.answer(f"🗑 Post #{post_id} kanaldan o'chirildi.")
        await callback.answer("🗑 O'chirildi")
    except TelegramBadRequest as e:
        await callback.answer(f"❌ O'chirilmadi: {e}"[:190], show_alert=True)
    except Exception as e:
        await callback.answer(f"❌ Xatolik: {e}"[:190], show_alert=True)


@router.callback_query(F.data.startswith("reject_"))
async def cb_reject(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await _deny(callback)
    post_id = int(callback.data.split("_")[1])
    await database.update_post_status(post_id, "rejected", error="Admin rad etdi")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await callback.message.answer(f"❌ Post #{post_id} rad etildi.")
    await callback.answer("❌ Rad etildi")


REWRITE_STATE: dict[int, int] = {}
"""admin_id -> post_id (qayta yozish kutilmoqda)"""


@router.message(Command("cancel"))
async def cmd_cancel(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    if REWRITE_STATE.pop(message.from_user.id, None):
        await message.answer("↩️ Bekor qilindi.")
    else:
        await message.answer("ℹ️ Bekor qilinadigan amal yo'q.")


@router.callback_query(F.data.startswith("rewrite_"))
async def cb_rewrite(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await _deny(callback)
    post_id = int(callback.data.split("_")[1])
    REWRITE_STATE[callback.from_user.id] = post_id
    await callback.message.answer(
        f"✏️ <b>Post #{post_id}</b> uchun buyruq bering.\n\n"
        f"Masalan:\n"
        f"<code>qisqaroq qil 12</code>\n"
        f"<code>kripto haqida yozib ber</code>\n"
        f"<code>boshqa mavzu: neft narxlari</code>\n\n"
        f"Bekor qilish: /cancel",
        parse_mode=ParseMode.HTML
    )
    await callback.answer()


@router.message(F.text)
async def on_admin_text(message: Message):
    """
    Qayta yozish buyruqini qabul qiladi.
    Bu handler oxirida RO'YATDAN ENG KEYIN turadi — buyruqlar birinchi
    ishlaydi, faqat "boshqa xabar" shu yerda ushlanadi.
    """
    if message.from_user.id != ADMIN_ID:
        return

    post_id = REWRITE_STATE.get(message.from_user.id)
    if not post_id:
        return

    feedback = (message.text or "").strip()
    if not feedback or feedback.startswith("/"):
        return

    REWRITE_STATE.pop(message.from_user.id, None)
    post = await database.get_post(post_id)
    if not post:
        await message.answer("❌ Post topilmadi.")
        return

    # "boshqa mavzu: X" yoki "mavzu X" — yangi mavzu sifatida
    topic = None
    for marker in ("boshqa mavzu:", "mavzu:", "mavzu "):
        if feedback.lower().startswith(marker):
            topic = feedback[len(marker):].strip()
            feedback = f"Aniq shu mavzu haqida yozib ber: {topic}"
            break

    await message.answer("🤖 Qayta yozilyapti, kuting...")

    if topic:
        new_content = await generate_post_for_topic(topic)
    else:
        new_content = await improve_post(post["content"], feedback)

    if not new_content:
        await message.answer("❌ Qayta yozib bo'lmadi. /stats bilan kvotani tekshiring.")
        return

    # Eski kanal xabarini o'chirib, yangisini yuboramiz
    old_message_id = post["message_id"]
    if old_message_id:
        try:
            await bot.delete_message(CHANNEL_ID, old_message_id)
        except TelegramBadRequest:
            pass

    try:
        sent = await safe_send(CHANNEL_ID, new_content)
        await database.update_post_status(post_id, "sent", message_id=sent.message_id)
        await message.answer(
            f"✅ Post #{post_id} qayta yozildi va kanalga yangilandi!",
            reply_markup=published_keyboard(post_id),
        )
    except Exception as e:
        await database.update_post_status(post_id, "pending", error=str(e))
        await message.answer(f"❌ Yuborilmadi: {e}")


@router.callback_query(F.data.startswith("skip_"))
async def cb_skip(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await _deny(callback)
    post_id = int(callback.data.split("_")[1])
    await database.update_post_status(post_id, "skipped", error="Admin o'tkazib yubordi")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await callback.message.answer(f"⏭ Post #{post_id} o'tkazib yuborildi.")
    await callback.answer("⏭ O'tkazildi")


@router.callback_query(F.data.startswith("poll_send_"))
async def cb_poll_send(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await _deny(callback)

    import json
    poll_id = int(callback.data.split("_")[2])
    poll = await database.get_poll(poll_id)
    if not poll:
        return await callback.answer("❌ So'rovnoma topilmadi", show_alert=True)

    options = json.loads(poll["options"])
    try:
        sent = await bot.send_poll(
            chat_id=CHANNEL_ID,
            question=poll["question"],
            options=options,
            is_anonymous=True
        )
        await database.update_poll_status(poll_id, "sent", message_id=sent.message_id)
        try:
            await callback.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        await callback.message.answer(f"✅ So'rovnoma #{poll_id} kanalga chiqarildi!")
        await callback.answer("✅ Yuborildi!")
    except Exception as e:
        logger.exception("So'rovnoma yuborish xatosi")
        await callback.answer(f"❌ Xatolik: {e}"[:190], show_alert=True)


@router.callback_query(F.data.startswith("poll_cancel_"))
async def cb_poll_cancel(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        return await _deny(callback)
    poll_id = int(callback.data.split("_")[2])
    await database.update_poll_status(poll_id, "cancelled")
    try:
        await callback.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass
    await callback.message.answer(f"❌ So'rovnoma #{poll_id} bekor qilindi.")
    await callback.answer("❌ Bekor qilindi")


# ===== POLLING =====
async def start_bot():
    """Botni polling rejimida ishga tushiradi."""
    print("🤖 Bot ishga tushmoqda...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query"],
        handle_signals=False,
    )


if __name__ == "__main__":
    asyncio.run(start_bot())
