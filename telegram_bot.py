"""
telegram_bot.py — Bot, tasdiqlash tizimi va kanalga yuborish.
"""
import asyncio
from aiogram import Bot, Dispatcher, F, Router
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command
from aiogram.enums import ParseMode

from config import (
    BOT_TOKEN, ADMIN_ID, CHANNEL_ID, CHANNEL_LINK, CHANNEL_NAME
)
from database import (
    save_post, get_post, update_post_status,
    get_pending_posts, get_stats, save_poll
)
from ai_generator import generate_post, generate_poll, improve_post

# Bot va Dispatcher
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)


# ===== KLAVIATURALAR =====
def approval_keyboard(post_id: int) -> InlineKeyboardMarkup:
    """Post tasdiqlash tugmalari."""
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


# ===== KOMANDALAR =====
@router.message(Command("start"))
async def cmd_start(message: Message):
    """Bot ishga tushganda."""
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
        f"/stats — statistika\n"
        f"/pending — tasdiqlanmagan postlar\n"
        f"/help — yordam",
        parse_mode=ParseMode.HTML
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    """Yordam."""
    if message.from_user.id != ADMIN_ID:
        return

    await message.answer(
        "📖 <b>Yordam</b>\n\n"
        "1️⃣ <b>/post</b> — AI hozir post yozadi va sizga yuboradi\n"
        "2️⃣ Siz tugmalar orqali tasdiqlaysiz yoki rad etasiz\n"
        "3️⃣ Tasdiqlangan post kanalga chiqadi\n\n"
        "⏰ <b>Avtomatik postlar:</b> 08:30, 13:00, 18:30\n"
        "📊 <b>So'rovnoma:</b> har yakshanba 10:00",
        parse_mode=ParseMode.HTML
    )


@router.message(Command("post"))
async def cmd_post(message: Message):
    """Qo'lda post yozish."""
    if message.from_user.id != ADMIN_ID:
        return

    await message.answer("🤖 AI post yozyapti, kuting...")
    try:
        await create_and_send_post(post_type="morning")
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")


@router.message(Command("poll"))
async def cmd_poll(message: Message):
    """Qo'lda so'rovnoma yaratish."""
    if message.from_user.id != ADMIN_ID:
        return

    await message.answer("🤖 So'rovnoma tayyorlanmoqda...")
    try:
        await create_and_send_poll()
    except Exception as e:
        await message.answer(f"❌ Xatolik: {e}")


@router.message(Command("stats"))
async def cmd_stats(message: Message):
    """Statistika."""
    if message.from_user.id != ADMIN_ID:
        return

    stats = await get_stats()
    await message.answer(
        f"📊 <b>Statistika</b>\n\n"
        f"✅ Yuborilgan: {stats['total_sent']}\n"
        f"⏳ Kutilayotgan: {stats['pending']}\n"
        f"❌ Rad etilgan: {stats['rejected']}",
        parse_mode=ParseMode.HTML
    )


@router.message(Command("pending"))
async def cmd_pending(message: Message):
    """Tasdiqlanmagan postlar."""
    if message.from_user.id != ADMIN_ID:
        return

    posts = await get_pending_posts()
    if not posts:
        await message.answer("✅ Tasdiqlanmagan postlar yo'q.")
        return

    for p in posts:
        await message.answer(
            f"⏳ <b>Post #{p['id']}</b>\n\n{p['content'][:500]}...",
            parse_mode=ParseMode.HTML,
            reply_markup=approval_keyboard(p['id'])
        )


# ===== POST YARATISH =====
async def create_and_send_post(post_type: str = "morning"):
    """Post yaratib, adminga yuboradi."""
    content = await generate_post(post_type=post_type)
    post_id = await save_post(content=content, topic=post_type)

    text = (
        f"📝 <b>Yangi post #{post_id}</b>\n"
        f"🕐 Turi: {post_type}\n"
        f"📏 Belgilar: {len(content)}\n\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"{content}\n"
        f"━━━━━━━━━━━━━━━━"
    )

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=approval_keyboard(post_id)
    )
    return post_id


async def create_and_send_poll():
    """So'rovnoma yaratib, adminga yuboradi."""
    poll_data = await generate_poll()
    poll_id = await save_poll(
        question=poll_data["question"],
        options=poll_data["options"]
    )

    text = (
        f"📊 <b>Yangi so'rovnoma #{poll_id}</b>\n\n"
        f"❓ {poll_data['question']}\n\n"
    )
    for i, opt in enumerate(poll_data["options"], 1):
        text += f"{i}. {opt}\n"

    await bot.send_message(
        chat_id=ADMIN_ID,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Kanalga chiqarish", callback_data=f"poll_send_{poll_id}"),
                InlineKeyboardButton(text="❌ Bekor qilish", callback_data=f"poll_cancel_{poll_id}"),
            ]
        ])
    )
    return poll_id


# ===== CALLBACK HANDLERLAR =====
@router.callback_query(F.data.startswith("approve_"))
async def cb_approve(callback: CallbackQuery):
    """Postni tasdiqlash."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return

    post_id = int(callback.data.split("_")[1])
    post = await get_post(post_id)

    if not post:
        await callback.answer("❌ Post topilmadi", show_alert=True)
        return

    if post["status"] == "sent":
        await callback.answer("⚠️ Bu post allaqachon yuborilgan", show_alert=True)
        return

    try:
        # Kanalga yuborish
        sent = await bot.send_message(
            chat_id=CHANNEL_ID,
            text=post["content"],
            parse_mode=ParseMode.HTML
        )
        await update_post_status(post_id, "sent", message_id=sent.message_id)

        # Adminga xabar
        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(
            f"✅ Post #{post_id} kanalga muvaffaqiyatli yuborildi!"
        )
        await callback.answer("✅ Yuborildi!")

    except Exception as e:
        await callback.answer(f"❌ Xatolik: {e}", show_alert=True)
        await update_post_status(post_id, "pending", error=str(e))


@router.callback_query(F.data.startswith("reject_"))
async def cb_reject(callback: CallbackQuery):
    """Postni rad etish."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return

    post_id = int(callback.data.split("_")[1])
    await update_post_status(post_id, "rejected", error="Admin rad etdi")

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"❌ Post #{post_id} rad etildi.")
    await callback.answer("❌ Rad etildi")


@router.callback_query(F.data.startswith("rewrite_"))
async def cb_rewrite(callback: CallbackQuery):
    """Postni qayta yozish."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return

    post_id = int(callback.data.split("_")[1])
    post = await get_post(post_id)

    await callback.message.answer(
        f"✏️ Post #{post_id} uchun izohingizni yozing.\n"
        f"Masalan: <i>qisqaroq qil</i>, <i>boshqa mavzu</i>, <i>ko'proq raqam qo'sh</i>",
        parse_mode=ParseMode.HTML
    )

    # Keyingi xabarni kutish (state kerak — soddalik uchun callback.data orqali)
    await callback.answer()


@router.callback_query(F.data.startswith("skip_"))
async def cb_skip(callback: CallbackQuery):
    """Postni o'tkazib yuborish."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return

    post_id = int(callback.data.split("_")[1])
    await update_post_status(post_id, "skipped", error="Admin o'tkazib yubordi")

    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"⏭ Post #{post_id} o'tkazib yuborildi.")
    await callback.answer("⏭ O'tkazildi")


@router.callback_query(F.data.startswith("poll_send_"))
async def cb_poll_send(callback: CallbackQuery):
    """So'rovnomani kanalga chiqarish."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return

    import json
    from database import DB_PATH
    import aiosqlite

    poll_id = int(callback.data.split("_")[2])

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM polls WHERE id = ?", (poll_id,)) as cursor:
            poll = await cursor.fetchone()

    if not poll:
        await callback.answer("❌ So'rovnoma topilmadi", show_alert=True)
        return

    options = json.loads(poll["options"])

    try:
        sent = await bot.send_poll(
            chat_id=CHANNEL_ID,
            question=poll["question"],
            options=options,
            is_anonymous=True
        )

        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "UPDATE polls SET status = 'sent', sent_at = datetime('now'), message_id = ? WHERE id = ?",
                (sent.message_id, poll_id)
            )
            await db.commit()

        await callback.message.edit_reply_markup(reply_markup=None)
        await callback.message.answer(f"✅ So'rovnoma #{poll_id} kanalga chiqarildi!")
        await callback.answer("✅ Yuborildi!")

    except Exception as e:
        await callback.answer(f"❌ Xatolik: {e}", show_alert=True)


@router.callback_query(F.data.startswith("poll_cancel_"))
async def cb_poll_cancel(callback: CallbackQuery):
    """So'rovnomani bekor qilish."""
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Ruxsat yo'q", show_alert=True)
        return

    poll_id = int(callback.data.split("_")[2])
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(f"❌ So'rovnoma #{poll_id} bekor qilindi.")
    await callback.answer("❌ Bekor qilindi")


# ===== BOTNI ISHGA TUSHIRISH =====
async def start_bot():
    """Botni ishga tushiradi (polling rejimida)."""
    print("🤖 Bot ishga tushmoqda...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(start_bot())
