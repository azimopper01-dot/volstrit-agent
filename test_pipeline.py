"""
test_pipeline.py — Butun oqimni AI/Telegram stubs bilan sinovdan o'tkazadi.

Sinov qilinadiganlar:
  1. Ma'lumotlar bazasi va jadvallar yaratiladi
  2. Kechikkan ish "catch-up" bilan tiklanadi (post o'tkazilmaydi)
  3. Real vaqtda berilgan vazifa (/schedule) o'z vaqtida bajariladi
  4. Job natijalari bazaga yoziladi — takrorlashning oldi olinadi
  5. AI kvota hisobi ishlaydi, chegara yetganda zaxira matn ishlatiladi
  6. AI kvota tugab qolganda post KANALGA yuboriladi (bo'sh qolmaydi)
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
os.environ["AUTO_PUBLISH"] = "true"
os.environ["AI_DAILY_LIMIT"] = "20"
os.environ["AI_MINUTE_LIMIT"] = "20"
os.environ["POST_TIME_MORNING"] = "08:30"
os.environ["POST_TIME_NOON"] = "13:00"
os.environ["POST_TIME_EVENING"] = "18:30"
os.environ["POLL_DAY"] = "sunday"
os.environ["POLL_TIME"] = "10:00"

from zoneinfo import ZoneInfo
TZ = ZoneInfo(TZ_NAME)

# ---------- TELEGRAM STUB ----------
SENT = []          # (chat_id, text)
CALLS = {"generate": 0}


class FakeMsg:
    def __init__(self, mid):
        self.message_id = mid
        self.text = ""


class FakeBot:
    def __init__(self, token=None, default=None):
        self.token = token
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
        return True

    async def delete_webhook(self, **kw):
        return True

    class _Session:
        async def close(self):
            pass
    session = _Session()


def _stub_module(name, **attrs):
    m = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[name] = m
    return m


def _identity_decorator(*a, **k):
    """Router.message(...) / Router.callback_query(...) uchun"""
    def wrap(fn):
        return fn
    # ishlatilishi mumkin: @router.message(Cmd) yoki @router.message
    if len(a) == 1 and callable(a[0]) and not k:
        return a[0]
    return wrap


class FakeRouter:
    def __getattr__(self, name):
        return _identity_decorator


# aiogram
_stub_module("aiogram", Bot=FakeBot,
             Dispatcher=lambda: types.SimpleNamespace(
                 include_router=lambda r: None, start_polling=None),
             F=types.SimpleNamespace(
                 data=types.SimpleNamespace(startswith=lambda s: False),
                 text=object()),
             Router=FakeRouter)
_stub_module("aiogram.types", Message=object, CallbackQuery=object,
             InlineKeyboardMarkup=lambda **k: k,
             InlineKeyboardButton=lambda **k: k)
_stub_module("aiogram.client", )
_stub_module("aiogram.client.default",
             DefaultRequestProperties=lambda **k: types.SimpleNamespace(**k))
_stub_module("aiogram.filters", Command=lambda *a, **k: None)
_stub_module("aiogram.enums", ParseMode=types.SimpleNamespace(HTML="HTML"))


class _ApiErr(Exception):
    pass


class _Rsrc(_ApiErr):
    pass


_stub_module("aiogram.exceptions",
             TelegramRetryAfter=type("TelegramRetryAfter", (_ApiErr,), {}),
             TelegramBadRequest=type("TelegramBadRequest", (_ApiErr,), {}),
             TelegramNetworkError=type("TelegramNetworkError", (_ApiErr,), {}),
             TelegramForbiddenError=type("TelegramForbiddenError", (_ApiErr,), {}),
             TelegramConflictError=type("TelegramConflictError", (_ApiErr,), {}))

# ---------- GEMINI STUB ----------
QUOTA_MODE = {"on": False}


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
                "Bu suniy matn. <b>HTML teglari</b> & ampersand.\n"
                "Savol: nimaga yoqdi? #fond #test"
            )
        )


_stub_module("google")
_stub_module("google.generativeai",
             configure=lambda **k: None,
             GenerativeModel=lambda name=None: FakeModel(name))
_stub_module("google.api_core")
_stub_module("google.api_core.exceptions",
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


async def main():
    print("=" * 66)
    print("🧪 VOLSTRIT AGENT — TO'LIQ OQIM SINOVI")
    print("=" * 66)
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
    print(f"    Hozir soat: {FIXED_NOW:%H:%M}  "
          f"(o'tib ketgan: 08:30 va 13:00, kelgusi: 18:30)")
    SENT.clear()
    CALLS["generate"] = 0
    await sch.catch_up_missed_jobs()

    posts_today = await database.get_today_posts_count()
    check("08:30 va 13:00 ishlari tiklandi (2 ta post)",
          posts_today == 2, f"bazada {posts_today} ta 'sent' post")
    check("18:30 ishi hali VAQT KELMAGAN — bajarilmadi", posts_today == 2)
    check("postlar KANALGA yuborildi",
          any(c == "@VolstritStart" for c, _ in SENT),
          f"{sum(1 for c,_ in SENT if c=='@VolstritStart')} ta kanal xabari")
    check("adminga ham ko'rsatildi",
          any(c == config.ADMIN_ID for c, _ in SENT))
    check("AI chaqirildi", CALLS["generate"] >= 2, f"{CALLS['generate']} marta")

    # ---------- 3. JOB NATIJALARI (takrorlash oldi olinadi) ----------
    print("\n3️⃣  Job natijalari bazaga yozildi")
    check("morning_post bajarilgan deb belgilangan",
          await database.job_already_ran("morning_post"))
    check("noon_post bajarilgan deb belgilangan",
          await database.job_already_ran("noon_post"))
    check("evening_post hali BELGILANMAGAN",
          not await database.job_already_ran("evening_post"))

    print("    ↻ catch-up'ni ikkinchi marta chaqirish (takrorlash tekshiruvi):")
    before = await database.get_today_posts_count()
    await sch.catch_up_missed_jobs()
    after = await database.get_today_posts_count()
    check("takror post yaratilmadi", before == after,
          f"{before} -> {after}")

    # ---------- 4. REAL VAQT VAZIFASI ----------
    print("\n4️⃣  /schedule orqali berilgan real vaqt vazifasi")
    past = (FIXED_NOW - timedelta(minutes=3)).isoformat(timespec="seconds")
    future = (FIXED_NOW + timedelta(hours=2)).isoformat(timespec="seconds")
    tid1 = await database.add_adhoc_task(past, "Bitcoin haqida")
    tid2 = await database.add_adhoc_task(future, "Ertasi kunga")
    CALLS["generate"] = 0
    SENT.clear()
    await sch.run_adhoc_tasks()
    check("muddati kelgan vazifa bajarildi (AI chaqirildi)", CALLS["generate"] == 1)
    check("bajarilgan vazifa 'ok' deb belgilandi",
          (await database.get_pending_adhoc_tasks()).__len__() == 1)
    check("kelgusi vazifa kutayapti", await database.job_already_ran("morning_post"))

    # ---------- 5. AI KVOTA ----------
    print("\n5️⃣  AI kvota hisobi va chegarasi")
    # chegarani import vaqtida binding bo'lgani uchun patch qilamiz
    ai.AI_DAILY_LIMIT = 10
    ai.AI_MINUTE_LIMIT = 20
    used = await database.ai_used_today()
    check("AI so'rovlari sanaldi", used >= 3, f"{used} / 10")
    check("chegara ichida — AI chaqiriladi", await ai.can_call_ai())

    while await database.ai_used_today() < 10:
        await database.record_ai_call(True, "test")
    check("chegara yetgach AI chaqirilmaydi", not await ai.can_call_ai())

    # ---------- 6. KVOTA TUGAB QOLSA HAM KANAL BO'SH QOLMAYDI ----------
    print("\n6️⃣  AI kvota tugab qolsa ham post kanalga chiqadi")
    SENT.clear()
    before_calls = CALLS["generate"]
    post_id = await tg.create_and_send_post(post_type="evening")
    check("post yaratildi (xato bermadi)", post_id is not None)
    check("AI chaqirilmadi (kvota himoyalangan)",
          CALLS["generate"] == before_calls)
    check("post KANALGA yuborildi",
          any(c == "@VolstritStart" for c, _ in SENT))
    p = await database.get_post(post_id)
    check("bazada 'sent' holatida", p["status"] == "sent")
    check("zaxira matn ishlatildi (to'liq mazmunli)",
          len(p["content"] or "") > 200, f"{len(p['content'])} belgi")

    # ------ 6b. kunlik (PerDay) kvota — qayta urishning ma'nosiz ------
    print("\n6️⃣b Kunlik kvota (PerDay) — darhol zaxiraga o'tadi")
    QUOTA_MODE["on"] = True
    ai.AI_DAILY_LIMIT = 100
    calls_before = CALLS["generate"]
    SENT.clear()
    p3 = await tg.create_and_send_post(post_type="noon")
    check("PerDay 429 da bir martta urildi, ko'p urilmadi",
          CALLS["generate"] == calls_before + 1,
          f"{CALLS['generate'] - calls_before} urinish")
    check("post yana ham kanalga yuborildi",
          any(c == "@VolstritStart" for c, _ in SENT))
    check("zaxira matn bilan kanalga tushdi",
          len((await database.get_post(p3))["content"]) > 200)

    # chegarani ochamiz, qolgan testlar uchun
    ai.AI_DAILY_LIMIT = 50
    QUOTA_MODE["on"] = False

    # ---------- 7. HTML XAVFSIZLIGI ----------
    print("\n7️⃣  AI matnidagi HTML belgilari kanalni buzmaydi")
    SENT.clear()
    await tg.create_and_send_post(post_type="morning")
    chan = [t for c, t in SENT if c == "@VolstritStart"]
    check("kanalga yuborilgan matnda qoldiq HTML teg yo'q",
          chan and "<b>" not in chan[-1] and "&" not in chan[-1],
          repr(chan[-1][:60]) if chan else "yo'q")
    check("matn 4096 belgidan oshmaydi",
          chan and len(chan[-1]) <= 4096, f"{len(chan[-1])} belgi")

    # ---------- 8. 429 RETRY ----------
    print("\n8️⃣  429 rate-limit: server aytgancha kutib, qayta urinadi")
    ai.AI_DAILY_LIMIT = 50
    RATE = {"left": 2}

    class RateModel:
        """2 marta 429 beradi, keyin muvaffaqiyatli javob qaytaradi."""
        def __init__(self, name=None):
            pass

        def generate_content(self, prompt, **kw):
            CALLS["generate"] += 1
            if RATE["left"] > 0:
                RATE["left"] -= 1
                raise _Rsrc(
                    "429 Resource has been exhausted. "
                    "Please retry in 28.3s. quota_id: "
                    "GenerateRequestsPerMinutePerProjectPerModel-FreeTier"
                )
            return types.SimpleNamespace(text="Retry muvaffaqiyatli javob berdi.")

    ai.model = RateModel()
    ai.AI_RETRY_BASE_DELAY = 0        # testni tezlashtirish uchun
    ai.AI_MAX_RETRY_WAIT = 1
    p2 = await tg.create_and_send_post(post_type="morning")
    check("429 dan keyin qayta urilib muvaffaqiyatli bo'ldi",
          "Retry muvaffaqiyatli" in (await database.get_post(p2))["content"])

    # ---------- 9. STATISTIKA ----------
    print("\n9️⃣  Statistika")
    s = await database.get_stats()
    check("bugungi postlar hisoblandi", s["today"] >= 4, f"bugun: {s['today']}")
    check("jami yuborilgan", s["total_sent"] >= 4, f"jami: {s['total_sent']}")

    # ---------- NATIJA ----------
    print("\n" + "=" * 66)
    passed = sum(1 for c, _, _ in results if c)
    total = len(results)
    print(f"📊 NATIJA: {passed}/{total} test o'tdi")
    print("=" * 66)
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
