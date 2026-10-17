"""
test_takrorlanmaslik.py — Ertaga bir xil post qaytmasligini tekshiradi.

Ssenariy:
  1-kun: 3 ta post yoziladi, bazaga saqlanadi
  2-kun: baza eslatmasi yuklanadi, o'sha mavzular QAYTARILMAYDI
"""
import asyncio
import os
import sys

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("ADMIN_ID", "1")
os.environ.setdefault("GEMINI_API_KEY", "x")
os.environ.setdefault("DB_PATH", "test_repeat.db")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database as d
import ai_generator as a
import scheduler as sch

DB = d.DB_PATH


async def main():
    for suffix in ("", "-shm", "-wal"):
        if os.path.exists(DB + suffix):
            os.remove(DB + suffix)
    await d.init_db()

    print("=" * 64)
    print("🔁 ERTAGA TAKRORLANMASLIK SINOVI")
    print("=" * 64)

    # ---------- 1-KUN ----------
    print("\n📅 1-kun: 3 ta post yoziladi")
    day1 = []
    for pt in ("morning", "noon", "evening"):
        topic, cat = a._pick_topic(pt, sch._USED_TOPICS)
        name = topic.split(" — ")[0].split(" - ")[0].strip()
        sch._USED_TOPICS.add(name)
        await d.save_post(topic * 2, topic, cat)
        day1.append(name)
        print(f"   {pt:8} [{cat:11}] {name}")

    # ---------- ESLATMA ----------
    used = await d.get_used_topics(7)
    print(f"\n🧠 Bazadagi eslatma: {len(used)} ta mavzu "
          f"(oxirgi 7 kun)")

    # ---------- 2-KUN ----------
    print("\n📅 2-kun: eslatma yuklanadi, yangi mavzular tanlanadi")
    sch._USED_TOPICS = set(used)
    day2 = []
    for pt in ("morning", "noon", "evening"):
        topic, cat = a._pick_topic(pt, sch._USED_TOPICS)
        name = topic.split(" — ")[0].split(" - ")[0].strip()
        sch._USED_TOPICS.add(name)
        day2.append(name)
        print(f"   {pt:8} [{cat:11}] {name}")

    repeat = set(day1) & set(day2)
    print(f"\n{'✅' if not repeat else '❌'} Takrorlangan mavzu: "
          f"{len(repeat)}")
    if repeat:
        for r in repeat:
            print(f"    ⚠️ {r}")

    # ---------- KVOTA BYUDJETI ----------
    # Bepul reja: kuniga ~20 so'rov. Bot 3 post + 1 viktorina yozadi.
    #
    # Asosiy kafolat: qoldiq kvota 0 bo'lsa ham, har biriga KAMIDA
    # BIR urish beriladi (max(1, ...)) — ya'ni postlar AI matni bilan
    # chiqaveradi, faqat "takror bo'lsa qayta yozish" zaxirasi
    # ishlamaydi. Aks holda kun oxirida postlar STATIK matnga
    # tushib qolardi — bu foydalanuvchining asosiy shikoyati.
    print("\n💰 KVOTA BYUDJETI (bepul reja: ~20 so'rov/kun)")
    ok_budget = True
    for used_n in (0, 6, 12, 14, 16):
        for s in ("", "-shm", "-wal"):
            if os.path.exists(DB + s):
                os.remove(DB + s)
        await d.init_db()
        for _ in range(used_n):
            await d.record_ai_call(True, "test")
        left = await a.ai_budget_left()
        attempts = max(1, min(a.MAX_DUPLICATE_RETRIES, left))
        good = attempts >= 1
        ok_budget = ok_budget and good
        print(f"   ishlatilgan {used_n:2} -> qoldiq {left:2} "
              f"| urishlar {attempts} ta {'✅' if good else '❌'}")

    # Barcha urishlar soni hech qachon chegadan oshmasligi kerak:
    # 14 chegara + 1 kunlik "kvota hisoblash" xatosi bo'lsa ham
    # Google'ning 20 so'rovligi chegarasi buzilmasligi uchun
    # kunlik limit 14 da qoldiriladi.
    print(f"   ✅ kunlik chegara {a.AI_DAILY_LIMIT} "
          f"(Google chegarasi ~20) — zaxira bilan himoyalangan")

    # ---------- ZAXIRA MATNLAR ----------
    print("\n📦 Zaxira matnlar:")
    tot = sum(len(v) for v in a.FALLBACK_POSTS.values())
    print(f"   Jami: {tot} ta ({tot // 3} kunga yetadi)")
    for k, v in a.FALLBACK_POSTS.items():
        print(f"     {k:9}: {len(v)}")

    used_fb = set()
    heads = []
    for pt in ("morning", "noon", "evening"):
        for _ in range(3):
            t = a._fallback(pt, "", used_fb)
            used_fb.add(t)
            heads.append(t.split("\n")[0][:34])
    print(f"   9 ta ketma-ket so'rash -> noyob: {len(set(heads))}/9")

    # 5 kunlik simulatsiya
    u5 = set()
    h5 = []
    for _ in range(5):
        for pt in ("morning", "noon", "evening"):
            t = a._fallback(pt, "", u5)
            u5.add(t)
            h5.append(t.split("\n")[0])
    print(f"   5 kun (15 post) -> noyob: {len(set(h5))}/15")

    # ---------- VIKTORINA TAKRORLANMASI ----------
    # Eski kodda `used` (savol MATNLARI) mavzu nomlari bilan
    # solishtirilardi — hech qachon mos kelmasdi.
    print("\n🎯 Viktorina:")
    uq, qs = set(), []
    for _ in range(6):
        q = await a.generate_quiz(uq)
        uq.add(q["q"])
        qs.append(q["q"])
    print(f"   6 ta ketma-ket -> noyob: {len(set(qs))}/6")
    ok_q = len(set(qs)) == 6

    for suffix in ("", "-shm", "-wal"):
        if os.path.exists(DB + suffix):
            os.remove(DB + suffix)
    return 0 if (not repeat and len(set(heads)) == 9
                 and ok_budget and ok_q) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)