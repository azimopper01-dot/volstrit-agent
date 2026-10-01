"""
test_pipeline.py — Butun oqimni AI/Telegram stubs bilan sinovdan o'tkazadi.

HOZIRGI REJIM: AUTO_PUBLISH=false
  -> post avval ADMINGA yuboriladi, kanalga faqat "Tasdiqlash"dan keyin chiqadi

Sinov qilinadiganlar:
  1. Ma'lumotlar bazasi va jadvallar yaratiladi
  2. Kechikkan ish "catch-up" bilan tiklanadi (post o'tkazilmaydi)
  3. Job natijalari bazaga yoziladi — takrorlashning oldi olinadi
  4. Real vaqtda berilgan vazifa (/schedule) o'z vaqtida bajariladi
  5. AI kvota: chegarada AI chaqirilmaydi, zaxira matn bilan post chiqadi
  6. 429 rate-limit: server aytgancha kutib, qayta urinadi
  7. ADMIN TUGMASI: "Tasdiqlash" -> kanalga chiqadi, "Rad etish" -> chiqmaydi
  8. HTML belgilari kanalni buzmaydi
"""
import asyncio
import os
import sys
import types
from datetime import datetime, timedelta

# ---------- VAQT QAT'IY (test uchun) ----------
TZ_NAME = "Asia/Tashkent"
FIXED_NOW = datetime.fromisoformat("2026-10-01T13:35:00")   # 13:35 Tashkent

os.environ["TZ"] = TZ_NAME
os.environ["TIMEZONE"] = TZ_NAME
os.environ["DB_PATH"] = "test_pipeline.db"
os.environ["BOT_TOKEN"] = "123456:TEST-STUB-TOKEN"
os.environ["ADMIN_ID"] = "5543462752"
os.environ["CHANNEL_ID"] = "@VolstritStart"
os.environ["GEMINI_API_KEY"] = "stub-key"
os.environ["GEMINI_MODEL"] = "stub-model"
os.environ["AUTO_PUBLISH"] = "false"      # <-- TASDIQLASH REJIMI
os.environ["AI_DAILY_LIMIT"] = "20"
os.environ["AI_MINUTE_LIMIT"] = "20"
os.environ["POST_TIME_MORNING"] = "08:30"
os.environ["POST_TIME_NOON"] = "13:00"
os.environ["POST_TIME_EVENING"] = "18:30"
os.environ["POLL_DAY"] = "sunday"
os.environ["POLL_TIME"] = "10:00"

# ---------- TELEGRAM STUB ----------
SENT = []          # (chat_id, text)
DELETED = []       # (chat_id, message_id)
CALLS = {"generate": 0}
QUOTA_MODE = {"on": False}


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid
        self.text = ""

    async def answer(self, text="", **kw):
        SENT.append((f"reply:{self.message_id}", text))

    async def edit_reply_markup(self, reply_markup=None):
        return True


class FakeUser:
    def __init__(self, uid):
        self.id = uid


class FakeCallback:
    """cb_approve / cb_reject va h.k. ni sinash uchun."""
    def __init__(self, data, uid):
        self.data = data
        self.from_user = FakeUser(uid)
        self.message = FakeMsg(999)
        self.answers = []

    async def answer(self, text="", show_alert=False):
        self.answers.append(text)


class FakeBot:
    def __init__(self, token=None, default=None, session=None):
        self.token = token
        self.session = session
        self._mid = 100

    async def send_message(self, chat_id, text, **kw):
        self._mid += 1
        SENT.append((chat_id, text))
        return FakeMsg(self._mid)

    async def send_poll(self, chat_id, question, options, **kw):
        self._mid += 1
        SENT.append((chat_id, f"POLL: {question}"))
        return FakeMsg(self._mid)

    async def delete_message(self, chat_id, mid):
        DELETED.append((chat_id, mid))
        return True

    async def delete_webhook(self, **kw):
        return True

    class _Session:
        async def close(self):
            pass
    session = _Session()


def _identity_decorator(*a, **k):
    def wrap(fn):
        return fn
    if len(a) == 1 and callable(a[0]) and not k:
        return a[0]
    return wrap


class FakeRouter:
    def __getattr__(self, name):
        return _identity_decorator


# aiogram
_stub_module = lambda name, **attrs: (
    sys.modules.__setitem__(name, types.SimpleNamespace(**attrs)) or sys.modules[name]
)
sys.modules["aiogram"] = types.SimpleNamespace(
    Bot=FakeBot,
    Dispatcher=lambda: types.SimpleNamespace(
        include_router=lambda r: None, start_polling=None),
    F=types.SimpleNamespace(
        data=types.SimpleNamespace(startswith=lambda s: False),
        text=object()),
    Router=FakeRouter,
)
sys.modules["aiogram.types"] = types.SimpleNamespace(
    Message=object, CallbackQuery=object,
    InlineKeyboardMarkup=lambda **k: k, InlineKeyboardButton=lambda **k: k)
sys.modules["aiogram.client"] = types.ModuleType("aiogram.client")
sys.modules["aiogram.client.session"] = types.ModuleType("aiogram.client.session")
sys.modules["aiogram.client.session.aiohttp"] = types.SimpleNamespace(
    AiohttpSession=lambda **k: types.SimpleNamespace(timeout=k.get("timeout", 60)))
sys.modules["aiogram.client.default"] = types.SimpleNamespace(
    DefaultBotProperties=lambda **k: types.SimpleNamespace(**k))
sys.modules["aiogram.filters"] = types.SimpleNamespace(Command=lambda *a, **k: None)
sys.modules["aiogram.enums"] = types.SimpleNamespace(ParseMode=types.SimpleNamespace(HTML="HTML"))


class _ApiErr(Exception):
    pass


class _Rsrc(_ApiErr):
    pass


sys.modules["aiogram.exceptions"] = types.SimpleNamespace(
    TelegramRetryAfter=type("TelegramRetryAfter", (_ApiErr,), {}),
    TelegramBadRequest=type("TelegramBadRequest", (_ApiErr,), {}),
    TelegramNetworkError=type("TelegramNetworkError", (_ApiErr,), {}),
    TelegramForbiddenError=type("TelegramForbiddenError", (_ApiErr,), {}),
    TelegramConflictError=type("TelegramConflictError", (_ApiErr,), {}),
)


# ---------- GEMINI STUB ----------
class FakeModel:
    def __init__(self, name=None):
        self.name = name

    def generate_content(self, prompt, **kw):
        CALLS["generate"] += 1
        if QUOTA_MODE["on"]:
            raise _Rsrc(
                "429 You exceeded your current quota. "
                "quota_id: GenerateRequestsPerDayPerProjectPerModel-FreeTier "
                "quota_value: 20 Please retry in 50.7s."
            )
        return types.SimpleNamespace(
            text=(
                "🧪 TEST POST\n\n"
                "Bu suniy matn va u yetarli uzunlikda bo'lishi kerak, "
                "aks holda tizim uni 'prompt qaytardi' deb rad etadi. "
                "<b>HTML teglari</b> va & ampersand ham ataylab qo'yilgan — "
                "ular tozalanishi kerak.\n\n"
                "💡 Maslahat: test matnida ham haqiqiydek struktura bo'lsin.\n\n"
                "Savol: nimaga yoqdi?\n\n"
                "#fond #aksiya #forex #kripto"
            )
        )


sys.modules["google"] = types.ModuleType("google")
sys.modules["google.generativeai"] = types.SimpleNamespace(
    configure=lambda **k: None, GenerativeModel=lambda name=None: FakeModel(name))
sys.modules["google.api_core"] = types.ModuleType("google.api_core")
sys.modules["google.api_core.exceptions"] = types.SimpleNamespace(
    ResourceExhausted=_Rsrc, GoogleAPIError=_ApiErr)

# ---------- DASTURNI IMPORT QILISH ----------
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database
import config
import scheduler as sch
import telegram_bot as tg
import ai_generator as ai

OK, FAIL = "✅", "❌"
results = []


def check(label, cond, extra=""):
    results.append((cond, label, extra))
    print(f"  {OK if cond else FAIL} {label}" + (f" — {extra}" if extra else ""))


def to_channel():
    return any(c == "@VolstritStart" for c, _ in SENT)


def to_admin():
    return any(c == config.ADMIN_ID for c, _ in SENT)


async def main():
    print("=" * 68)
    print("🧪 VOLSTRIT AGENT — TO'LIQ OQIM SINOVI (AUTO_PUBLISH=false)")
    print("=" * 68)
    print(f"   Rejim: post avval admonga -> tasdiqlashdan keyin kanalga")
    print(f"   Sozlangan vaqt (TZ={TZ_NAME}): {FIXED_NOW:%Y-%m-%d %H:%M:%S}\n")

    # vaqtni qat'iy qilamiz
    sch.now_tz = lambda: FIXED_NOW
    sch.create_and_send_post.__globals__["now_tz"] = lambda: FIXED_NOW
    database.now_tz = lambda: FIXED_NOW
    database.today_str = lambda: FIXED_NOW.strftime("%Y-%m-%d")
    database.now_iso = lambda: FIXED_NOW.isoformat(timespec="seconds")
    sch.database.now_tz = lambda: FIXED_NOW

    # ---------- 1. BAZA ----------
    print("1️⃣  Ma'lumotlar bazasi")
    if os.path.exists("test_pipeline.db"):
        os.remove("test_pipeline.db")
    await database.init_db()
    import aiosqlite
    async with aiosqlite.connect(database.DB_PATH) as db:
        rows = await (await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )).fetchall()
    tables = {r[0] for r in rows}
    for t in ("posts", "polls", "job_runs", "ai_usage", "adhoc_tasks"):
        check(f"jadval '{t}' yaratildi", t in tables)

    # ---------- 2. CATCH-UP ----------
    print("\n2️⃣  Kechikkan ishlar 'catch-up' bilan tiklanadi")
    print(f"    Hozir soat: {FIXED_NOW:%H:%M}  (o'tib ketgan: 08:30 va 13:00, kelgusi: 18:30)")
    SENT.clear()
    CALLS["generate"] = 0
    await sch.catch_up_missed_jobs()

    check("08:30 va 13:00 ishlari tiklandi (2 ta post)",
          await database.get_today_posts_count() == 0, "hali hech biri kanalda emas")
    check("18:30 ishi hali VAQT KELMAGAN — bajarilmadi",
          not await database.job_already_ran("evening_post"))
    check("AI chaqirildi", CALLS["generate"] >= 2, f"{CALLS['generate']} marta")
    check("postlar ADMINGA yuborildi (tasdiqlash uchun)", to_admin())
    check("KANALGA HALI YO'Q (tasdiqlash kutilmoqda)", not to_channel())
    pend = await database.get_pending_posts()
    check("postlar 'pending' holatida saqlanib qoldi", len(pend) == 2,
          f"{len(pend)} ta pending")

    # ---------- 3. JOB NATIJALARI ----------
    print("\n3️⃣  Job natijalari bazaga yozildi (takrorlash oldi olinadi)")
    check("morning_post bajarilgan", await database.job_already_ran("morning_post"))
    check("noon_post bajarilgan", await database.job_already_ran("noon_post"))
    print("    ↻ catch-up'ni 2-marta chaqirish:")
    SENT.clear()
    await sch.catch_up_missed_jobs()
    check("takror ADMINGA xabar yuborilmadi", not to_admin(),
          "hech narsa yuborilmadi = takror yo'q")

    # ---------- 4. REAL VAQT VAZIFASI ----------
    print("\n4️⃣  /schedule orqali berilgan real vaqt vazifasi")
    past = (FIXED_NOW - timedelta(minutes=3)).isoformat(timespec="seconds")
    future = (FIXED_NOW + timedelta(hours=2)).isoformat(timespec="seconds")
    await database.add_adhoc_task(past, "Bitcoin haqida")
    await database.add_adhoc_task(future, "Ertasi kunga")
    CALLS["generate"] = 0
    SENT.clear()
    await sch.run_adhoc_tasks()
    check("muddati kelgan vazifa bajarildi (AI chaqirildi)", CALLS["generate"] == 1)
    check("bajarilgan vazifa 'ok' belgilandi, kelgusi kutilmoqda",
          len(await database.get_pending_adhoc_tasks()) == 1)
    check("vazifa natijasi ADMINGA yuborildi", to_admin())

    # ---------- 5. KVOTA HIMOYASI ----------
    print("\n5️⃣  AI kvota: chegarada AI chaqirilmaydi, zaxira matn bilan post chiqadi")
    ai.AI_DAILY_LIMIT = 10
    ai.AI_MINUTE_LIMIT = 20
    check("chegara ichida — AI chaqiriladi", await ai.can_call_ai())
    while await database.ai_used_today() < 10:
        await database.record_ai_call(True, "test")
    check("chegara yetgach AI chaqirilmaydi", not await ai.can_call_ai())

    calls_before = CALLS["generate"]
    SENT.clear()
    pid = await tg.create_and_send_post(post_type="evening")
    check("AI chaqirilmadi", CALLS["generate"] == calls_before)
    check("post yana ham ADMINGA yuborildi", to_admin())
    check("zaxira matn ishlatildi (to'liq mazmunli)",
          len((await database.get_post(pid))["content"]) > 200,
          f"{len((await database.get_post(pid))['content'])} belgi")

    print("\n5️⃣b Kunlik kvota (PerDay) — darhol zaxiraga o'tadi")
    ai.AI_DAILY_LIMIT = 100
    QUOTA_MODE["on"] = True
    before = CALLS["generate"]
    pid2 = await tg.create_and_send_post(post_type="noon")
    check("PerDay 429 da bir marta urildi, ko'p urilmadi",
          CALLS["generate"] == before + 1,
          f"{CALLS['generate'] - before} urinish")
    check("post yana ham ADMINGA yuborildi (yo'qolmadi)", to_admin())
    QUOTA_MODE["on"] = False
    ai.AI_DAILY_LIMIT = 50

    # ---------- 6. 429 RETRY ----------
    print("\n6️⃣  429 rate-limit: server aytgancha kutib, qayta urinadi")
    RATE = {"left": 2}

    class RateModel:
        def __init__(self, name=None):
            pass

        def generate_content(self, prompt, **kw):
            CALLS["generate"] += 1
            if RATE["left"] > 0:
                RATE["left"] -= 1
                raise _Rsrc(
                    "429 Resource has been exhausted. Please retry in 28.3s. "
                    "quota_id: GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
                )
            # haqiqiy postga o'xshash, 250+ belgi (himoya o'tsin)
            return types.SimpleNamespace(
                text="Retry muvaffaqiyatli javob berdi.\n\n"
                     "Birja bugun sekin ochildi, lekin hajmi past. "
                     "Ko'pchilik ertalabki tebranishni signal deb oladi, "
                     "bu esa noto'g'ri qarorga olib keladi.\n\n"
                     "💡 Maslahat: rejangizni oldindan yozib qo'ying.\n\n"
                     "Sizningcha ertalabki tebranish ishonchli signalmi?\n\n"
                     "#fond #aksiya #forex #kripto")

    ai.model = RateModel()
    ai.AI_RETRY_BASE_DELAY = 0
    ai.AI_MAX_RETRY_WAIT = 1
    ai.AI_MAX_RETRIES = 3
    SENT.clear()
    pid3 = await tg.create_and_send_post(post_type="morning")
    row3 = await database.get_post(pid3)
    await tg.cb_approve(FakeCallback(f"approve_{pid3}", config.ADMIN_ID))
    row3 = await database.get_post(pid3)
    check("429 dan keyin qayta urib muvaffaqiyatli bo'ldi",
          "Retry muvaffaqiyatli" in row3["content"])
    check("...va haqiqiy post kanalga chiqdi",
          row3["status"] == "sent", row3["status"])

    # ---------- 6b. AI promptni o'zini qaytarsa ----------
    print("\n6️⃣b AI prompt matnini qaytarsa — qayta urinadi, oxirida zaxira")
    class BadModel:
        """Har doim promptni o'zini qaytaradi."""
        def __init__(self, name=None):
            pass

        def generate_content(self, prompt, **kw):
            CALLS["generate"] += 1
            return types.SimpleNamespace(
                text="QOIDALAR:\n1. Post 500-900 belgi\n2. Emoji 3-5 ta\n\nChecked."
            )

    ai.model = BadModel()
    ai.AI_MAX_RETRIES = 2
    SENT.clear()
    ai.model = BadModel()
    ai.AI_MAX_RETRIES = 2
    pid4 = await tg.create_and_send_post(post_type="evening")
    row4 = await database.get_post(pid4)
    content = row4["content"]
    check("prompt-qaytari aniqlanib rad etildi (Checked. yo'q)",
          "Checked" not in content and "QOIDALAR" not in content)
    # AUTO_PUBLISH=false: avval tasdiqlash, keyin kanalga
    SENT.clear()
    await tg.cb_approve(FakeCallback(f"approve_{pid4}", config.ADMIN_ID))
    row4 = await database.get_post(pid4)
    check("zaxira matn tasdiqdan keyin kanalga chiqadi (yo'qolmadi)",
          row4["status"] == "sent" and to_channel(), row4["status"])
    ai.model = FakeModel()
    ai.AI_MAX_RETRIES = 3

    # ---------- 7. ADMIN TUGMALARI ----------
    print("\n7️⃣  Admin tugmalari: Tasdiqlash / Rad etish / O'chirish")
    target = (await database.get_pending_posts())[-1]
    tpid = target["id"]

    # --- Tasdiqlash ---
    SENT.clear()
    cb = FakeCallback(f"approve_{tpid}", config.ADMIN_ID)
    await tg.cb_approve(cb)
    p = await database.get_post(tpid)
    check("'Tasdiqlash' -> post KANALGA yuborildi", to_channel())
    check("...va holati 'sent' bo'ldi", p["status"] == "sent", p["status"])
    check("...va kanal xabari id saqlandi", p["message_id"] is not None)

    # --- Rad etish ---
    rej = (await database.get_pending_posts())[0]
    cb2 = FakeCallback(f"reject_{rej['id']}", config.ADMIN_ID)
    await tg.cb_reject(cb2)
    check("'Rad etish' -> holati 'rejected'",
          (await database.get_post(rej["id"]))["status"] == "rejected")

    # --- Ruxsatsiz user ---
    SENT.clear()
    cb3 = FakeCallback(f"approve_{tpid}", 999999)
    await tg.cb_approve(cb3)
    check("boshqa user tasdiqlay olmaydi", any("Ruxsat" in a for a in cb3.answers))

    # --- Takror tasdiqlash (double-click) ---
    cb4 = FakeCallback(f"approve_{tpid}", config.ADMIN_ID)
    await tg.cb_approve(cb4)
    check("ikkinchi marta tasdiqlash rad etiladi (2 marta chiqmaydi)",
          any("allaqachon" in a for a in cb4.answers))

    # ---------- 8. HTML XAVFSIZLIGI ----------
    print("\n8️⃣  AI matnidagi HTML belgilari kanalni buzmaydi")
    SENT.clear()
    hp = await tg.create_and_send_post(post_type="morning")
    # tasdiqlash -> kanalga chiqadi
    await tg.cb_approve(FakeCallback(f"approve_{hp}", config.ADMIN_ID))
    chan = [t for c, t in SENT if c == "@VolstritStart"]
    check("tasdiqlangan post kanalga chiqdi", len(chan) == 1, f"{len(chan)} ta")
    check("kanal matnida qoldiq HTML teg yo'q",
          chan and "<b>" not in chan[-1] and "&" not in chan[-1],
          repr(chan[-1][:55]) if chan else "yo'q")
    check("matn 4096 belgidan oshmaydi",
          chan and len(chan[-1]) <= 4096,
          f"{len(chan[-1])} belgi" if chan else "yo'q")

    # ---------- 9. ESLATISH ----------
    print("\n9️⃣  Tasdiqlanmagan postga eslatish (APPROVAL_TIMEOUT_HOURS)")
    # haqiqatan ESKI pending post yaratamiz (2 soatdan ko'p)
    old = (FIXED_NOW - timedelta(hours=config.APPROVAL_TIMEOUT_HOURS + 1)).isoformat(
        timespec="seconds")
    await database.save_post(content="Eski post", topic="test")
    async with aiosqlite.connect(database.DB_PATH) as db:
        await db.execute(
            "UPDATE posts SET created_at = ?, status = 'pending' "
            "WHERE id = (SELECT MAX(id) FROM posts)", (old,))
        await db.commit()

    stale = await database.get_stale_pending_posts(config.APPROVAL_TIMEOUT_HOURS)
    check("vaqt o'tgan pending postlar topildi", len(stale) >= 1,
          f"{len(stale)} ta (>{config.APPROVAL_TIMEOUT_HOURS} soat)")
    SENT.clear()
    await sch.job_remind_pending()
    check("adminga eslatish yuborildi", to_admin())

    # ---------- 10. STATISTIKA ----------
    print("\n🔟  Statistika")
    s = await database.get_stats()
    check("jami yaratilgan", s["total"] >= 8, f"{s['total']}")
    check("kanalga yuborilgan (tasdiqlangan)", s["total_sent"] >= 1, f"{s['total_sent']}")
    check("rad etilgan", s["rejected"] >= 1, f"{s['rejected']}")
    check("tasdiqlash kutilmoqda", s["pending"] >= 1, f"{s['pending']}")

    # ---------- NATIJA ----------
    print("\n" + "=" * 68)
    passed = sum(1 for c, _, _ in results if c)
    total = len(results)
    print(f"📊 NATIJA: {passed}/{total} test o'tdi")
    print("=" * 68)
    if passed != total:
        print("\n❌ Xato bergan testlar:")
        for c, lbl, extra in results:
            if not c:
                print(f"   • {lbl} {extra}")
        return 1
    print("\n✅ BARCHA TESTLAR O'TDI — tizim ishlashga tayyor.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
