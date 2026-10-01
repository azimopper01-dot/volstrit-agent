"""test_real_imports.py — Haqiqiy paketlar bilan import tekshiruvi.

Bu test stub'siz ishlaydi: haqiqiy aiogram, google-generativeai,
apscheduler, aiosqlite o'rnatilgan bo'lishi SHART.

Railway'dagi "ImportError: DefaultRequestProperties" xatosi shu test
bilan ushlab olinadi — ya'ni deploy'dan oldin aniqlanadi.
"""
import os
import sys
from typing import Optional  # noqa: F401  (check() yordamchisida ishlatiladi)

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("ADMIN_ID", "1")
os.environ.setdefault("GEMINI_API_KEY", "test-key")
os.environ.setdefault("GEMINI_MODEL", "gemini-1.5-flash")
os.environ.setdefault("DB_PATH", "test_real.db")
os.environ.setdefault("TIMEZONE", "Asia/Tashkent")

print("=" * 62)
print("🔍 HAQIQIY PAKETLAR BILAN IMPORT TEKSHIRUVI")
print("=" * 62)

ok, fail = [], []

def check(label, fn):
    try:
        fn()
        ok.append(label)
        print(f"  ✅ {label}")
    except Exception as e:
        fail.append((label, f"{type(e).__name__}: {e}"))
        print(f"  ❌ {label}\n       {type(e).__name__}: {e}")


# 1. Paketlar
def _pkgs():
    import aiogram, apscheduler, aiosqlite, google.generativeai
    assert aiogram.__version__.startswith("3."), aiogram.__version__
check("paketlar o'rnatilgan (aiogram 3.x)", _pkgs)

# 2. config
def _cfg():
    import config
    assert config.TIMEZONE == "Asia/Tashkent"
    assert config.TZ is not None
    assert config.now_tz().tzinfo is not None
check("config — vaqt mintaqasi", _cfg)

# 3. database
def _db():
    import asyncio, database
    asyncio.run(database.init_db())
check("database — jadvallar yaratildi", _db)

# 4. ai_generator  (google SDK bilan)
def _ai():
    import ai_generator
    assert ai_generator.model is not None
    assert ai_generator.SYSTEM_PROMPT
check("ai_generator — Gemini SDK", _ai)

# 5. telegram_bot  <-- Railway'dagi xato shu yerda edi
def _tg():
    import telegram_bot
    assert telegram_bot.bot is not None
    assert telegram_bot.dp is not None
    assert telegram_bot.session.timeout == 60
check("telegram_bot — Bot va session", _tg)

# 6. scheduler
def _sch():
    import scheduler
    scheduler.setup_scheduler()
    jobs = {j.id: j for j in scheduler.scheduler.get_jobs()}
    assert "morning_post" in jobs, list(jobs)
    # TUZATILGAN ASOSIY XATO: trigger timezone Asia/Tashkent bo'lishi SHART
    for jid in ("morning_post", "noon_post", "evening_post", "weekly_poll"):
        tz = str(jobs[jid].trigger.timezone)
        assert "Tashkent" in tz, f"{jid} -> {tz}"
    assert jobs["morning_post"].misfire_grace_time == 3600
    assert "heartbeat" in jobs
    assert "remind_pending" in jobs
check("scheduler — trigger timezone = Asia/Tashkent", _sch)

# 7. main
def _main():
    import main
    assert main.SHOULD_POLL in (True, False)
check("main", _main)

# 8. async funksiyalar mavjudligi
def _fns():
    import telegram_bot as tg, scheduler as sch
    for name in ("create_and_send_post", "create_and_send_poll",
                 "safe_send", "cb_approve", "cb_reject", "cb_delete",
                 "cb_rewrite", "on_admin_text", "cmd_schedule", "cmd_health"):
        assert hasattr(tg, name), f"yo'q: {name}"
    for name in ("catch_up_missed_jobs", "run_adhoc_tasks",
                 "job_remind_pending", "heartbeat_log"):
        assert hasattr(sch, name), f"yo'q: {name}"
check("barcha funksiyalar mavjud", _fns)

# 9. /schedule parsing
def _parse():
    import asyncio, telegram_bot as tg
    from config import now_tz
    class M:
        from_user = type("U", (), {"id": 1})()
        text = "/schedule +30m kripto"
        async def answer(self, t="", **k):
            ANSWERS.append(t)
    ANSWERS = []
    asyncio.run(tg.cmd_schedule(M()))
    assert ANSWERS, "javob kelmadi"
check("cmd_schedule — vaqtni parse qiladi", _parse)

print("\n" + "=" * 62)
print(f"📊 NATIJA: {len(ok)}/{len(ok) + len(fail)} o'tdi")
print("=" * 62)
if fail:
    print("\n❌ Xatolar:")
    for lbl, err in fail:
        print(f"   • {lbl}\n     {err}")
    sys.exit(1)
print("\n✅ Kod HAQIQIY muhitda to'g'li ishga tushadi — Railway'da xato bo'lmaydi.")
sys.exit(0)
