"""
ai_generator.py — Gemini AI orqali fond bozori mavzusida post yozadi.
"""
import google.generativeai as genai
from datetime import datetime
from config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    CHANNEL_NAME,
    CHANNEL_TOPIC,
    CHANNEL_LANG,
    CHANNEL_STYLE,
    AUDIENCE,
)

# Gemini'ni sozlash
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel(GEMINI_MODEL)


# ===== TIZIM PROMPTI (AI'ga kanal uslubini o'rgatish) =====
SYSTEM_PROMPT = f"""Sen "{CHANNEL_NAME}" nomli Telegram kanal uchun professional SMM menejersan.

KANAL HAQIDA:
- Mavzu: {CHANNEL_TOPIC}
- Til: {CHANNEL_LANG} (o'zbek tili, lotin yozuvida)
- Uslub: {CHANNEL_STYLE}
- Auditoriya: {AUDIENCE} (ham yangi boshlovchilar, ham tajribalilar)

VAZIFANG:
Fond bozori haqida qisqa, qiziqarli va foydali post yozish.

QOIDALAR:
1. Post 600-900 belgidan oshmasin (Telegram uchun ideal)
2. Sodda va tushunarli tilda yozing — murakkab atamalarni izohlang
3. Har bir postda kamida 1 ta amaliy maslahat yoki tahlil bo'lsin
4. Emoji ishlatilsin, lekin me'yorida (3-5 ta)
5. Oxirida 3-4 ta hashtag qo'ying: #fond #aksiya #forex #kripto kabi
6. Hech qachon aniq "sotib oling" yoki "soting" deb maslahat bermang — bu moliyaviy maslahat hisoblanadi
7. Raqamlar va faktlar ishonchli bo'lsin
8. Savol bilan tugating — obunachilarni fikr bildirishga undang

POST TUZILISHI:
- Sarlavha (qisqa, e'tiborni tortuvchi)
- Asosiy ma'lumot (2-3 paragraf)
- Amaliy maslahat yoki xulosa
- Savol
- Hashtaglar

FAQAT POST MATNINI QAYTARING. Hech qanday izoh, tushuntirish yoki qo'shimcha matn yozmang."""


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


async def generate_post(topic: str = None, post_type: str = "morning") -> str:
    """
    AI orqali post yozadi.
    
    Args:
        topic: Post mavzusi (agar None bo'lsa, vaqtga qarab tanlanadi)
        post_type: 'morning', 'noon', 'evening'
    
    Returns:
        Tayyor post matni
    """
    if not topic:
        # Vaqtga qarab mavzu tanlash
        index = datetime.now().timetuple().tm_yday % len(POST_TOPICS)
        topic = POST_TOPICS[index]

    # Vaqtga qarab qo'shimcha ko'rsatma
    time_context = {
        "morning": "Bu ertalabki post — kun boshida bozor yangiliklari va reja haqida yozing.",
        "noon": "Bu tushlikdagi post — qisqa tahlil yoki qiziqarli fakt haqida yozing.",
        "evening": "Bu kechki post — kun yakuni, xulosa yoki ertangi kunga tayyorgarlik haqida yozing.",
    }
    context = time_context.get(post_type, "")

    prompt = f"""{SYSTEM_PROMPT}

BUGUNGI MAVZU: {topic}

QO'SHIMCHA KO'RSATMA: {context}

Endi yuqoridagi qoidalarga muvofiq post yozing."""

    try:
        response = model.generate_content(prompt)
        post_text = response.text.strip()
        return post_text
    except Exception as e:
        print(f"❌ AI xatolik: {e}")
        raise


async def generate_poll() -> dict:
    """
    Haftalik so'rovnoma savolini yaratadi.
    
    Returns:
        {"question": "...", "options": ["...", "...", ...]}
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

JAVOBNI FAQAT QUYIDAGI FORMATDA QAYTARING (boshqa hech narsa yozmang):
SAVOL: <savol matni>
VARIANT: <1-variant>
VARIANT: <2-variant>
VARIANT: <3-variant>
VARIANT: <4-variant>"""

    try:
        response = model.generate_content(prompt)
        text = response.text.strip()

        # Javobni tahlil qilish
        question = ""
        options = []
        for line in text.split("\n"):
            line = line.strip()
            if line.startswith("SAVOL:"):
                question = line.replace("SAVOL:", "").strip()
            elif line.startswith("VARIANT:"):
                options.append(line.replace("VARIANT:", "").strip())

        if not question or len(options) < 2:
            raise ValueError("AI noto'g'ri format qaytardi")

        return {"question": question, "options": options}
    except Exception as e:
        print(f"❌ So'rovnoma xatolik: {e}")
        raise


async def improve_post(original: str, feedback: str) -> str:
    """
    Admin fikriga ko'ra postni qayta yozadi.
    
    Args:
        original: Asl post matni
        feedback: Adminning izohi (masalan, "qisqaroq qil", "boshqa mavzu")
    """
    prompt = f"""{SYSTEM_PROMPT}

QUYIDAGI POSTNI ADMIN FIKRIGA KO'RA QAYTA YOZING:

ASL POST:
{original}

ADMIN FIKRI:
{feedback}

Yangi postni yozing (faqat post matnini qaytaring):"""

    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        print(f"❌ AI xatolik: {e}")
        raise


if __name__ == "__main__":
    import asyncio

    async def test():
        print("🧪 Test: post yozish...")
        post = await generate_post(post_type="morning")
        print("\n" + "=" * 50)
        print(post)
        print("=" * 50 + "\n")

        print("🧪 Test: so'rovnoma...")
        poll = await generate_poll()
        print(f"\nSavol: {poll['question']}")
        for opt in poll["options"]:
            print(f"  • {opt}")

    asyncio.run(test())
