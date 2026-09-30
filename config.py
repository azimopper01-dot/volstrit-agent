"""
config.py — Barcha sozlamalarni .env fayldan o'qib oladi.
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# .env faylni yuklash
load_dotenv()

# ===== ASOSIY PAPKALAR =====
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


# ===== TELEGRAM =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
CHANNEL_ID = os.getenv("CHANNEL_ID", "@VolstritStart")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/VolstritStart")


# ===== AI (GEMINI) =====
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")


# ===== KANAL SOZLAMALARI =====
CHANNEL_NAME = os.getenv("CHANNEL_NAME", "Volstrit uchun start")
CHANNEL_TOPIC = os.getenv(
    "CHANNEL_TOPIC",
    "fond birjasi, forex, kripto, indekslar, aksiyalar"
)
CHANNEL_LANG = os.getenv("CHANNEL_LANG", "uz")
CHANNEL_STYLE = os.getenv("CHANNEL_STYLE", "sodda_va_tushunarli")
AUDIENCE = os.getenv("AUDIENCE", "yangi_va_tajribali")


# ===== POST VAQTLARI =====
POST_TIME_MORNING = os.getenv("POST_TIME_MORNING", "08:30")
POST_TIME_NOON = os.getenv("POST_TIME_NOON", "13:00")
POST_TIME_EVENING = os.getenv("POST_TIME_EVENING", "18:30")
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tashkent")


# ===== SO'ROVNOMA =====
POLL_DAY = os.getenv("POLL_DAY", "sunday")
POLL_TIME = os.getenv("POLL_TIME", "10:00")


# ===== MA'LUMOTLAR BAZASI =====
DB_PATH = os.getenv("DB_PATH", str(DATA_DIR / "posts.db"))


# ===== XAVFSIZLIK =====
APPROVAL_TIMEOUT_HOURS = int(os.getenv("APPROVAL_TIMEOUT_HOURS", "2"))


# ===== TEKSHIRISH =====
def check_config():
    """Muhim sozlamalar mavjudligini tekshiradi."""
    missing = []
    if not BOT_TOKEN:
        missing.append("BOT_TOKEN")
    if not GEMINI_API_KEY:
        missing.append("GEMINI_API_KEY")
    if not ADMIN_ID:
        missing.append("ADMIN_ID")

    if missing:
        raise ValueError(
            f"❌ Quyidagi muhit o'zgaruvchilari topilmadi: {', '.join(missing)}\n"
            f"❗ .env faylni to'ldirganingizni tekshiring."
        )
    print("✅ Barcha sozlamalar to'g'ri yuklandi.")


if __name__ == "__main__":
    check_config()
    print(f"📢 Kanal: {CHANNEL_NAME} ({CHANNEL_ID})")
    print(f"⏰ Post vaqtlari: {POST_TIME_MORNING}, {POST_TIME_NOON}, {POST_TIME_EVENING}")
    print(f"🌍 Vaqt mintaqasi: {TIMEZONE}")
    print(f"💾 Baza: {DB_PATH}")
