"""
ai_generator.py — Gemini AI orqali fond bozori mavzusida post yozadi.

Muhim o'zgarishlar:
1. `generate_content()` SINXRON funksiya — uni `asyncio.to_thread()` orqali
   ishga tushiramiz. Aks holda 30+ soniya event loopni bloklab qo'yadi va
   Telegram polling to'xtab qoladi.
2. 429 (kvota) xatosida exponential backoff + server aytgan `retry_after`.
   Kunlik kvota tugab qolganda darhol zaxira (fallback) matn ishlatiladi.
3. Kvota ogohlantirish chegarasi — bazadagi hisobga qarab.
4. AI ishlanmasa ham kanal bo'sh qolmaydi.
"""
import asyncio
import html
import random
import re

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, GoogleAPIError

from config import (
    GEMINI_API_KEY, GEMINI_MODEL, GEMINI_TIMEOUT, GEMINI_MAX_OUTPUT_TOKENS,
    AI_MAX_RETRIES, AI_RETRY_BASE_DELAY, AI_DAILY_LIMIT, AI_MINUTE_LIMIT,
    AI_MAX_RETRY_WAIT, CHANNEL_NAME, CHANNEL_TOPIC, CHANNEL_LANG,
    CHANNEL_STYLE, AUDIENCE, MAX_POST_LENGTH, now_tz,
)
import database


# ===== XATOLAR =====
class QuotaExhausted(Exception):
    """Kunlik kvota tugab qoldi — qayta urishning ma'nosiz."""


class TransientAIError(Exception):
    """Qayta urish mumkin bo'lgan xato."""

    def __init__(self, message: str, retry_after: int = 0):
        super().__init__(message)
        self.retry_after = retry_after


# Gemini'ni sozlash
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)

GEN_CONFIG = {
    "temperature": 0.9,
    "top_p": 0.95,
    "max_output_tokens": GEMINI_MAX_OUTPUT_TOKENS,
    "candidate_count": 1,
}


# ===== TIZIM PROMPTI =====
SYSTEM_PROMPT = f"""Sen "{CHANNEL_NAME}" nomli Telegram kanal uchun professional SMM menejersan.

KANAL HAQIDA:
- Mavzu: {CHANNEL_TOPIC}
- Til: {CHANNEL_LANG} (o'zbek tili, lotin yozuvida)
- Uslub: {CHANNEL_STYLE}
- Auditoriya: {AUDIENCE} (ham yangi boshlovchilar, ham tajribalilar)

VAZIFANG:
Fond bozori haqida qisqa, qiziqarli va foydali post yozish.

QOIDALAR:
1. Post {MAX_POST_LENGTH - 800}-{MAX_POST_LENGTH - 1500} belgidan oshmasin
2. Sodda va tushunarli tilda yozing — murakkab atamalarni izohlang
3. Har bir postda kamida 1 ta amaliy maslahat yoki tahlil bo'lsin
4. Emoji ishlatilsin, lekin me'yorida (3-5 ta)
5. Oxirida 3-4 ta hashtag qo'ying: #fond #aksiya #forex #kripto kabi
6. Hech qachon aniq "sotib oling" yoki "soting" deb maslahat bermang —
   bu moliyaviy maslahat hisoblanadi
7. Raqamlar va faktlar ishonchli bo'lsin
8. Savol bilan tugating — obunachilarni fikr bildirishga severance
9. HTML teglar (<b>, <i>, <a>) ISHLATMA — bu Telegram'ni buzadi
10. "&", "<", ">" belgilaridan foydalanma

POST TUZILISHI:
- Sarlavha (qisqa, e'tiborni tortuvchi)
- Asosiy ma'lumot (2-3 paragraf)
- Amaliy maslahat yoki xulosa
- Savol
- Hashtaglar

FAQAT POST MATNINI QAYTARING. Hech qanday izoh, tushuntirish yoki
qo'shimcha matn yozmang."""


# ===== POST MAVZULARI (navbatma-navbat ishlatiladi) =====
POST_TOPICS = [
    "Kunlik bozor yangiliklari: asosiy indekslar va valyuta kurslari",
    "Bitta aksiya tahlili: mashhur kompaniya misolida",
    "Kripto bozori: Bitcoin va Ethereum holati",
    "Forex: asosiy valyuta juftliklari tahlili",
    "Boshlovchilar uchun: fond bozoriga qanday kirish mumkin",
    "Riskni boshqarish: portfelni diversifikatsiya qilish sirlari",
    "Neft va oltin narxlari: nima bo'lyapti?",
    "Kompaniya hisobotlari: nimalarga e'tibor berish kerak",
    "Uzoq muddatli investitsiya strategiyalari",
    "Bozor psixologiyasi: qo'rquv va ochko'zlik",
]


# ===== ZAXIRA MATNLAR (AI ishlamasa ham kanal bo'sh qolmaydi) =====
# Har biri o'zbek tilida, taxminan 500-800 belgi, faqat ta'lim maqsadida.
FALLBACK_POSTS = {
    "morning": [
        """🌅 Yaxshi tong, bugungi kun uchun reja

Birja — kun davomida o'zgarib turadigan joy. Sabahki sessiya ko'pincha
eng faol qismi bo'ladi, lekin shu bilan birga eng tartibsiz qismi ham.

📌 Kunning birinchi qoidasi:
Ertalabki tebranishni (gap) signal deb qabul qilmaslik kerak. Ko'p kompaniyalar
biror yangilik chiqishi oldidan yoki keyin sun'iy ravishda ko'tariladi
va tushiriladi.

💡 Amaliy maslahat:
Bugun uchun rejangizni oldindan yozib qo'ying — qaysi aktive, qaysi summa,
qanday xato holatida chiquvsiz. Reja bo'lmasa, hissiyot qaror qabul qiladi.

Sizning portfelingizda birinchi navbatda nimaga e'tibor bering?

#fond #aksiya #forex #kripto #smm""",
        """🌅 Ertalabki sessiya: nima kutiladi?

Ko'pchilik ertalabki grafiklarni "ishonchli signal" deb qaror qiladi.
Amalda ertalabki harakat ko'pincha omil (news) natijasi bo'ladi.

📊 Nima uchun muhim:
1. Omil chiqishi oldidan narx tebranadi
2. Tebranishdan keyin asosiy harakat boshlanadi
3. Ertalabki "gaplarning" ko'pchisi 10 daqiqada yopiladi

💡 Amaliy maslahat:
Agar birja yopilayotgan bo'lsa, ertalabki faollik past bo'ladi — bu
normal holat. Asosiy e'tibor sessiya boshlanishiga qaratilsin.

Birja bozorida eng qiyin savol qaysi?

#fond #forex #kripto #analiz""",
    ],
    "noon": [
        """☀️ Tushlikdagi vaziyat: kun o'rtasidagi xulosa

Kun o'rtasida bozor odatda "kutilayotgan" holatda bo'ladi. Sabab
bir — birjalar hisobdorlar asosiy ma'lumotlarni (hisobotlar, statistika)
chiqaradi.

📌 E'tibor bering:
- Likvidlik pasayadi, spread kengayadi
- Kichik order'lar narxni ko'proq tebranishga olib keladi
- Kun o'rtasidagi signal ko'pincha kechqurun aniqlanadi

💡 Amaliy maslahat:
Tushlikda ochilgan pozitsiyani tekshirib qo'ying — mo'ljaldan chetlashgan
bo'lsa, rejangizga muvofiq harakatni rejalashtiring.

Siz kunlik tahlilni qachon qilasiz?

#fond #aksiya #forex #kripto""",
        """☀️ Kun o'rtasi: qisqa tahlil

Buzozdagi trend kuchaygan sayin, aksariyat yangi boshlovchilar
"signal topdim" deb xato qaror qabul qiladi.

⚠️ Eng ko'p uchraydigan xato:
Qisqa muddatli ko'tarilishni uzoq muddatli trend deb qabul qilish.
Trend asosan qisqa qisqa pauzalar bilan boradi — bu normal holat,
zaiflik emas.

💡 Amaliy maslahat:
Har bir pozitsiyada ikki savolni yozib qo'ying:
1. Bu savolga javobim qanday?
2. Javobim noto'g'ri bo'lsa, qanday harakat qilaman?

Siz savollarga yozib qo'yasizmi yoki xotiradan ishlaysizmi?

#fond #analiz #kripto #forex""",
    ],
    "evening": [
        """🌆 Kechki xulosa: kunni yakunlash

Birja kuni tugashdan oldin "kundalik vaziyat" deb nomlanadigan bosqich
o'tadi. Unda asosan hisobdorlar kelgusi kunga pozitsiyalarini yopadi.

📌 Nima uchun muhim:
- Ko'p kompaniyalar ertasi kuni uchun gap chiqaradi
- Bu gaplar harakatsiz kunlarda katta ta'sir ko'rsatadi
- Kechki o'zgarish ertalabki harakatni to'liq bekor qilishi mumkin

💡 Amaliy maslahat:
Kun yakunida "bugun nimani o'rgandim" degan bitta jumla yozib qo'ying.
Bir haftada bu sizga eng foydali "darslik" bo'lib qoladi.

Siz kun yakunida nima qilasiz?

#fond #aksiya #forex #kripto #smm""",
        """🌆 Kechqurun: ertani tayyorlash

Yaxshi investor kechqurun bo'sh vaqtini sarflamaydi — ertasi kunga
tayyorlanadi.

📋 Oddiy ro'yxat:
1. Ertasi kungi uchun bozor iqlimini aniqlang (gaplar, makro ma'lumotlar)
2. Ochilgan pozitsiyalarni qayta ko'ring
3. Xavf chegarasini belgilang
4. Vazifalarni yozib qo'ying — "hammasi" bu yerda "hech narsa" degani

💡 Amaliy maslahat:
Bir kunlik "kuzatish" emas, balki yozma reja — bu sizni hissiyotdan
saqlab qoladi.

Siz ertani qanday tayyorlaysiz?

#fond #analiz #kripto #forex""",
    ],
    "default": [
        """📊 Kanalimizdan foydali ma'lumot

Fond bozori — ko'p odam uchun hali ham murakkab ko'rinadi. Keling,
asosiy tushunchalarni sodda qilib ko'rib chiqamiz.

📌 Likvidlik — aynan shu aktivi qancha tez va qancha hajmda sotib
olish mumkinligi. Likvidlik past bo'lsa, katta order narxni
sezilarli darajada qo'zgartiradi.

📌 Diversifikatsiya — barcha mablag'ni bitta sohaga qo'yish xavfi.
Turli sohalar bir-biriga bog'liq bo'lmasa, zarar kamayadi.

💡 Amaliy maslahat:
Kichik summa bilan real tajriba oling. Nazariy bilim va amaliy
tajriba — ikkalasi bir xil emas.

Siz qaysi tushunchani o'rgatishimni xohlaysiz?

#fond #aksiya #forex #kripto""",
    ],
}


def _pick_topic() -> str:
    """Bugungi kun uchun mavzuni tanlaydi (vaqt mintaqasiga mos)."""
    index = now_tz().timetuple().tm_yday % len(POST_TOPICS)
    return POST_TOPICS[index]


def _fallback(post_type: str, reason: str = "") -> str:
    """AI o'rniga ishlatiladigan zaxira matn."""
    bank = FALLBACK_POSTS.get(post_type) or FALLBACK_POSTS["default"]
    text = random.choice(bank)
    if reason:
        print(f"⚠️  Zaxira matn ishlatildi ({post_type}): {reason}")
    return text


def _clean(text: str) -> str:
    """HTML teglari, Telegram limitidan uzun matn va bo'sh joylarni tozalaydi."""
    if not text:
        return ""
    text = text.replace("\r\n", "\n")
    # AI ba'zan HTML teglari qo'yadi — ular kanalda buziladi
    text = re.sub(r"</?(b|i|u|s|code|pre|a|br)\s*/?>", "", text, flags=re.IGNORECASE)
    text = html.unescape(text)
    # "&" kabi belgilar keyinchalik xato beradi
    text = text.replace("&", "-").replace("<", "-").replace(">", "-")
    # Telegram chegarasi
    if len(text) > MAX_POST_LENGTH:
        text = text[: MAX_POST_LENGTH - 40].rstrip() + "\n\n…"
    return text.strip()


# ===== KVOTA TEKSHIRUV =====
async def quota_left() -> int:
    """Bugun qancha AI so'rovi qoldi."""
    return max(0, AI_DAILY_LIMIT - await database.ai_used_today())


async def can_call_ai() -> bool:
    """AI chaqirish xavfsizmi?"""
    if await database.ai_used_today() >= AI_DAILY_LIMIT:
        return False
    if await database.ai_used_last_minute() >= AI_MINUTE_LIMIT:
        return False
    return True


# ===== GEMINI CHAQIRISH =====
def _parse_retry_after(exc: Exception) -> int:
    """Google xatolaridan 'retry after N seconds' ni ajratib oladi."""
    text = str(exc)
    m = re.search(r"retry in ([\d.]+)s", text)
    if m:
        return int(float(m.group(1))) + 1
    m = re.search(r"retry_delay.*?seconds:\s*(\d+)", text, re.S)
    if m:
        return int(m.group(1)) + 1
    m = re.search(r"retry after (\d+)", text)
    if m:
        return int(m.group(1)) + 1
    return 0


def _sync_generate(prompt: str) -> str:
    """Bloklovchi Gemini chaqiruvi (faqat thread ichida ishlating)."""
    response = model.generate_content(
        prompt,
        generation_config=GEN_CONFIG,
        request_options={"timeout": GEMINI_TIMEOUT},
    )
    return (response.text or "").strip()


async def _call_with_retry(prompt: str, label: str) -> str:
    """Kvota hisobi + exponential backoff bilan AI chaqiradi."""
    if not await can_call_ai():
        used = await database.ai_used_today()
        raise QuotaExhausted(f"kvota chegarasi ({used}/{AI_DAILY_LIMIT})")

    last_error = ""
    for attempt in range(1, AI_MAX_RETRIES + 1):
        try:
            # MUHIM: generate_content() bloklovchi — thread'da ishga tushiramiz
            text = await asyncio.to_thread(_sync_generate, prompt)
            if not text:
                raise TransientAIError("AI bo'sh javob qaytardi")

            await database.record_ai_call(True, label)
            print(f"   🤖 AI [{label}] muvaffaqiyatli (urinish {attempt})")
            return text

        except ResourceExhausted as e:
            msg = str(e)
            if "PerDay" in msg or "per day" in msg.lower():
                await database.record_ai_call(False, "quota_429")
                raise QuotaExhausted("kunlik kvota tugab qoldi") from e

            wait = _parse_retry_after(e) or (AI_RETRY_BASE_DELAY * attempt)
            wait = min(wait, AI_MAX_RETRY_WAIT)
            await database.record_ai_call(False, "rate_429")
            last_error = f"429 rate limit, {wait}s kutamiz"
            print(f"   ⚠️  {label}: {last_error} ({attempt}/{AI_MAX_RETRIES})")
            await asyncio.sleep(wait)

        except TransientAIError as e:
            last_error = str(e)
            print(f"   ⚠️  {label}: {last_error} ({attempt}/{AI_MAX_RETRIES})")
            await asyncio.sleep(AI_RETRY_BASE_DELAY * attempt)

        except GoogleAPIError as e:
            await database.record_ai_call(False, "api_error")
            last_error = f"Google API xatosi: {e}"
            print(f"   ⚠️  {label}: {last_error} ({attempt}/{AI_MAX_RETRIES})")
            await asyncio.sleep(AI_RETRY_BASE_DELAY * attempt)

        except Exception as e:
            await database.record_ai_call(False, type(e).__name__)
            last_error = f"{type(e).__name__}: {e}"
            print(f"   ⚠️  {label}: {last_error} ({attempt}/{AI_MAX_RETRIES})")
            await asyncio.sleep(AI_RETRY_BASE_DELAY * attempt)

    raise TransientAIError(last_error or "barcha urinishlar muvaffaqiyatsiz")


# ===== ASOSIY FUNKSIYALAR =====
async def generate_post(topic: str = None, post_type: str = "morning") -> str:
    """
    AI orqali post yozadi. AI ishlamasa — zaxira matn qaytaradi.
    Hech qachon istisno ko'tarilmaydi.
    """
    if not topic:
        topic = _pick_topic()

    time_context = {
        "morning": "Bu ertalabki post — kun boshida bozor yangiliklari va reja haqida yozing.",
        "noon": "Bu tushlikdagi post — qisqa tahlil yoki qiziqarli fakt haqida yozing.",
        "evening": "Bu kechki post — kun yakuni, xulosa yoki ertangi kunga tayyorgarlik haqida yozing.",
    }.get(post_type, "")

    prompt = f"""{SYSTEM_PROMPT}

BUGUNGI MAVZU: {topic}

QO'SHIMCHA KO'RSATMA: {time_context}

Endi yuqoridagi qoidalarga muvofiq post yozing."""

    try:
        text = await _call_with_retry(prompt, f"post/{post_type}")
        cleaned = _clean(text)
        return cleaned or _fallback(post_type, "bo'sh matn")
    except (QuotaExhausted, TransientAIError) as e:
        return _fallback(post_type, str(e))
    except Exception as e:
        return _fallback(post_type, f"{type(e).__name__}: {e}")


async def generate_post_for_topic(topic: str) -> str:
    """Aniq mavzu bo'yicha post (real vaqtda berilgan vazifa uchun)."""
    prompt = f"""{SYSTEM_PROMPT}

BUGUNGI MAVZU: {topic}

Endi yuqoridagi qoidalarga muvofiq post yozing."""

    try:
        text = await _call_with_retry(prompt, "post/adhoc")
        cleaned = _clean(text)
        return cleaned or _fallback("default", "bo'sh matn")
    except (QuotaExhausted, TransientAIError) as e:
        return _fallback("default", str(e))
    except Exception as e:
        return _fallback("default", f"{type(e).__name__}: {e}")


async def generate_poll() -> Optional[dict]:
    """
    Haftalik so'rovnoma yaratadi. AI ishlamasa None qaytaradi.
    """
    prompt = f"""Sen "{CHANNEL_NAME}" Telegram kanali uchun so'rovnoma tuzuvchisan.

Kanal mavzusi: {CHANNEL_TOPIC}
Til: o'zbek tili (lotin)

VAZIFA: Fond bozori haqida qiziqarli so'rovnoma tuzing.

QOIDALAR:
1. Savol qisqa va aniq bo'lsin (60 belgidan oshmasin)
2. 3-5 ta javob varianti bo'lsin
3. Har bir variant 30 belgidan oshmasin
4. Savol obunachilarni fikr bildirishga undasin
5. Mavzu dolzarb bo'lsin
6. HTML teglari va "&" belgisidan foydalanma

JAVOBNI FAQAT QUYIDAGI FORMATDA QAYTARING (boshqa hech narsa yozmang):
SAVOL: <savol matni>
VARIANT: <1-variant>
VARIANT: <2-variant>
VARIANT: <3-variant>
VARIANT: <4-variant>"""

    try:
        text = await _call_with_retry(prompt, "poll")
        question = ""
        options = []
        for line in text.split("\n"):
            line = line.strip().replace("&", "-").replace("<", "-").replace(">", "-")
            if line.startswith("SAVOL:"):
                question = line.replace("SAVOL:", "").strip()
            elif line.startswith("VARIANT:"):
                options.append(line.replace("VARIANT:", "").strip())

        if not question or len(options) < 2:
            raise TransientAIError("AI noto'g'ri format qaytardi")
        return {"question": question, "options": options[:10]}

    except Exception as e:
        print(f"❌ So'rovnoma yaratilmadi: {e}")
        return None


async def improve_post(original: str, feedback: str) -> str:
    """Admin fikriga ko'ra postni qayta yozadi."""
    prompt = f"""{SYSTEM_PROMPT}

QUYIDAGI POSTNI ADMIN FIKRIGA KO'RA QAYTA YOZING:

ASL POST:
{original}

ADMIN FIKRI:
{feedback}

Yangi postni yozing (faqat post matnini qaytaring):"""

    try:
        text = await _call_with_retry(prompt, "rewrite")
        return _clean(text)
    except Exception as e:
        print(f"❌ Qayta yozib bo'lmadi: {e}")
        return _clean(original)


if __name__ == "__main__":
    async def test():
        print(f"🧪 Model: {GEMINI_MODEL}  TZ: {now_tz()}")
        print(f"🧪 AI kvota: {await database.ai_used_today()}/{AI_DAILY_LIMIT}\n")
        post = await generate_post(post_type="morning")
        print("=" * 50)
        print(post)
        print("=" * 50)

    asyncio.run(test())
