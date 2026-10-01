"""
test_tz_fix.py — Vaqt zonasi tuzatilishini DALIL bilan tekshiradi.

ESKI kod:  CronTrigger(hour=8, minute=30)              -> timezone = konteyner TZ (UTC)
YANGI KOD: CronTrigger(hour=8, minute=30, timezone=TZ) -> timezone = Asia/Tashkent

Railway konteynerida TZ=UTC (simulyatsiya qilinadi).
"""
import os
import time
from datetime import datetime

# --- Railway konteynerini simulyatsiya qilamiz: TZ=UTC ---
os.environ["TZ"] = "UTC"
if hasattr(time, "tzset"):
    time.tzset()

from zoneinfo import ZoneInfo
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

TASHKENT = ZoneInfo("Asia/Tashkent")
UTC = ZoneInfo("UTC")

print("=" * 62)
print("Railway konteyner TZ =", os.environ["TZ"], "(UTC)")
print("=" * 62)

sched = BackgroundScheduler(timezone=TASHKENT)   # config.py shuni qiladi

# --- ESKI USUL ---
sched.add_job(lambda: None, CronTrigger(hour=8, minute=30), id="eski")
# --- YANGI USUL (tuzatilgan) ---
sched.add_job(lambda: None, CronTrigger(hour=8, minute=30, timezone=TASHKENT), id="yangi")
# --- haftalik ---
sched.add_job(
    lambda: None,
    CronTrigger(day_of_week="sun", hour=10, minute=0, timezone=TASHKENT),
    id="yangi_haftalik",
)
# --- eski haftalik ---
sched.add_job(
    lambda: None,
    CronTrigger(day_of_week="sun", hour=10, minute=0),
    id="eski_haftalik",
)

sched.start(paused=True)  # ishga tushirmaydi, faqat trigger'larni hisoblaydi

jobs = {j.id: j for j in sched.get_jobs()}

print("\n📅 'Ertalabki post (08:30)' — keyingi bajarilish vaqti:\n")
print(f"  ESKI  (timezone berilmagan): {jobs['eski'].next_run_time}")
print(f"  YANGI (timezone=TZ):        {jobs['yangi'].next_run_time}")

print("\n📅 'Haftalik so'rovnoma (yakshanba 10:00)':\n")
print(f"  ESKI : {jobs['eski_haftalik'].next_run_time}")
print(f"  YANGI: {jobs['yangi_haftalik'].next_run_time}")

# --- Vaqt oralig'ini o'lchash ---
def gap(a_id, b_id):
    a = jobs[a_id].next_run_time.astimezone(UTC)
    b = jobs[b_id].next_run_time.astimezone(UTC)
    return (b - a).total_seconds() / 3600

d1 = gap("eski", "yangi")
d2 = gap("eski_haftalik", "yangi_haftalik")

print("\n" + "=" * 62)
print("📊 NATIJA")
print("=" * 62)
print(f"  Kunlik postlar vaqt farqi:  {d1:+.0f} soat")
print(f"  Haftalik so'rovnoma farqi: {d2:+.0f} soat")

ok = abs(d1 + 5.0) < 0.01 and abs(d2 + 5.0) < 0.01
print()
if ok:
    print("  ✅ TASDIQLANDI: eski kodda barcha ishlar aynan 5 soat KECHIKDI.")
    print("     Loglar bilan mos:  08:30 -> 13:30 | 13:00 -> 18:00 | 18:30 -> 23:30")
    print("     YANGI kod esa ularni Asia/Tashkent da BELGILANGAN VAQTDA bajaradi.")
else:
    print(f"  ⚠️  kutilgan -5 soat emas, {d1} / {d2}")

# --- Trigger timezone maydoni ---
print("\n🔍 Trigger timezone maydoni:")
for jid in ("eski", "yangi", "eski_haftalik", "yangi_haftalik"):
    print(f"  {jid:18} -> {jobs[jid].trigger.timezone}")

sched.shutdown(wait=False)
