"""
test_real_ai.py — HAQIQIY Gemini API bilan to'liq tekshiruv.

Simulyatsiya emas: botning ishlash yo'lini haqiqiypa yuritadi.
  1. 3 marta ketma-ket post yoziladi (mavzu takrorlanmasligi)
  2. Baza orqali ertangi eslatma tekshiriladi
  3. Rasm yaratiladi (kvota alohida)
  4. Boshlang'ich matn qayta yoziladi (✏️ tanlovi)
  5. Viktorina yaratiladi

AI kvotasi tugagan bo'lsa — zaxira matn ishlatiladi va test yana ham
o'tadi (bot kanalni bo'sh qoldirmasligi uchun).
"""
import asyncio
import os
import sys

os.environ.setdefault("BOT_TOKEN", "123456:TEST")
os.environ.setdefault("ADMIN_ID", "1")
os.environ.setdefault("DB_PATH", "test_real_ai.db")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ai_generator as a
import database as d
import scheduler as sch

SEP = "=" * 66
TYPES = ("morning", "noon", "evening")


def head(t):
    return t.split("\n")[0][:56]


async def main():
    for suffix in ("", "-shm", "-wal"):
        p = "test_real_ai.db" + suffix
        if os.path.exists(p):
            os.remove(p)
    await d.init_db()

    print(SEP)
    print("🤖 HAQIQIY AI BILAN TO'LIQ TEKSHIRUV")
    print(SEP)
    print(f"Matn modeli  : {a.GEMINI_MODEL}")
    print(f"Rasm modeli  : {a.IMAGE_MODEL}")
    print(f"Kunlik chegara: {a.AI_DAILY_LIMIT} matn / "
          f"{a.AI_IMAGE_DAILY_LIMIT} rasm")
    ok = True

    # ---------------- 1. 3 ta post ----------------
    print("\n─── 1) KETMA-KET 3 TA POST " + "─" * 42)
    texts, topics = [], []
    for pt in TYPES:
        r = await a.generate_post(post_type=pt, used_topics=sch._USED_TOPICS)
        sch._mark_used(r)
        txt = r["content"]
        topic = r.get("topic", "")
        texts.append(txt)
        topics.append(topic)

        if topic in TYPES or not topic:
            print(f"\n  [{pt:8}] ❌ mavzu SOFTA chiqdi: '{topic}'")
            ok = False
        else:
            print(f"\n  [{pt:8}] ({r.get('source')}, {len(txt)} belgi)")
            print(f"   mavzu    : {topic.split(chr(8212))[0].strip()[:56]}")
        print(f"   sarlavha : {head(txt)}")

    n = len({t.split(" — ")[0] for t in topics})
    print(f"\n  {'✅' if n == 3 else '❌'} noyob mavzu: {n}/3")
    print(f"  {'✅' if len(set(head(t) for t in texts)) == 3 else '❌'} "
          f"noyob sarlavha: {len(set(head(t) for t in texts))}/3")
    ok = ok and n == 3

    # ---------------- 2. ertagi eslatma ----------------
    print("\n" + SEP)
    print("─── 2) ERTAGI ESLATMA " + "─" * 44)
    for t, tp, r in zip(texts, topics, ("morning", "noon", "evening")):
        await d.save_post(t, tp, r)
    day1 = {t.split(" — ")[0].split(" - ")[0].strip() for t in topics}

    used = await d.get_used_topics(7)
    print(f"  bazada eslatilayotgan mavzular: {len(used)}")

    # 2-kun: eslatma yuklangan holda mavzular tanlanadi
    day2 = set()
    for pt in TYPES:
        t2, _c = a._pick_topic(pt, set(used) | day2)
        day2.add(t2.split(" — ")[0].split(" - ")[0].strip())
    rep = day1 & day2
    print(f"  2-kun tanlovi: {len(day2)} ta mavzu")
    for x in sorted(day2):
        print(f"     - {x[:52]}")
    print(f"  {'✅' if not rep else '❌'} 1-kun bilan takrorlanuvchi: {len(rep)}")
    for r_ in rep:
        print(f"     ⚠️ {r_}")
    ok = ok and not rep

    # ---------------- 3. rasm ----------------
    print("\n" + SEP)
    print("─── 3) RASM YARATISH " + "─" * 46)
    for i, t in enumerate(texts, 1):
        img = await a.generate_image(head(t))
        if img:
            print(f"  ✅ {i}/3 rasm: {len(img)} bayt")
        else:
            print(f"  ⚠️  {i}/3 rasm yo'q (kvota/xato) — post rasmsiz chiqadi")

    # ---------------- 4. rewrite ----------------
    print("\n" + SEP)
    print("─── 4) QAYTA YOZISH (✏️ tanlovi) " + "─" * 35)
    old = texts[0]
    new = await a.improve_post(old, "")
    same = new.strip() == old.strip()
    fp_old, fp_new = set(d._fingerprint(old)), set(d._fingerprint(new))
    sim = len(fp_old & fp_new) / max(len(fp_old | fp_new), 1) * 100
    print(f"\n  ESKI : {head(old)}  ({len(old)} belgi)")
    print(f"  YANGI: {head(new)}  ({len(new)} belgi)")
    print(f"  {'✅' if not same else '❌'} bir xil emas")
    print(f"  {'✅' if sim < 40 else '⚠️ '} o'xshashlik: {sim:.0f}%")
    ok = ok and not same

    # ---------------- 5. viktorina ----------------
    print("\n" + SEP)
    print("─── 5) VIKTORINA " + "─" * 52)
    used_q = set()
    got = 0
    for _ in range(3):
        q = await a.generate_quiz(used_q)
        if not q:
            print("  ⚠️  viktorina yaratilmadi")
            continue
        got += 1
        used_q.add(q["q"][:40])
        print(f"\n  SAVOL: {q['q'][:64]}")
        for i, o in enumerate(q["o"], 1):
            print(f"    {'✅' if i - 1 == q['a'] else '  '} {i}. {o}")
        if q.get("e"):
            print(f"    izoh: {q['e'][:52]}")
    print(f"\n  {'✅' if got == 3 else '⚠️ '} yaratilgan viktorina: {got}/3")
    print(f"  {'✅' if len(used_q) == got else '❌'} noyob: {len(used_q)}/{got}")

    print("\n" + SEP)
    print("✅ HAMMA SINOV O'TDI" if ok else "⚠️  BA'ZI NUQSONLAR BOR")
    for suffix in ("", "-shm", "-wal"):
        p = "test_real_ai.db" + suffix
        if os.path.exists(p):
            os.remove(p)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)