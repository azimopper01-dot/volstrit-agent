"""
config.py — Barcha sozlamalarni .env fayldan o'qib oladi.

MUHIM: TZ (vaqt mintaqasi) fayl boshlanishidan OLDIN
`os.environ` ga yoziladi. Aks holda Railway konteynerida TZ=UTC qoladi va
APScheduler ham, datetime.now() ham UTC ishlatadi -> barcha postlar
soatga +5 (UTC+5) kechikadi.
"""
import os
import time as _time
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

# .env faylni yuklash
load_dotenv()


def _env_bool(key: str, default: bool = False) -> bool:
    """'true'/'1'/'yes'/'on'/'ha' -> True"""
    raw = os.getenv(key)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "ha")


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, "").strip() or default)
    except (TypeError, ValueError):
        return default


# ===== VAQT MINTAQASI (eng muhim qism) =====
TIMEZONE = os.getenv("TIMEZONE", "Asia/Tashkent").strip() or "Asia/Tashkent"
os.environ["TZ"] = TIMEZONE
if hasattr(_time, "tzset"):          # faqat Unix/macOS/Linux
    _time.tzset()

try:
    TZ = ZoneInfo(TIMEZONE)
except (ZoneInfoNotFoundError, ValueError, KeyError):
    print(f"⚠️  TIMEZONE='{TIMEZONE}' tizimda topilmadi. UTC'ga qaytarildi.")
    TIMEZONE = "UTC"
    TZ = ZoneInfo("UTC")


def now_tz() -> datetime:
    """Hozirgi vaqt — DOIM sozlangan vaqt mintaqasida."""
    return datetime.now(TZ)


def today_str() -> str:
    """Bugungi sana (YYYY-MM-DD), vaqt mintaqasiga mos."""
    return now_tz().strftime("%Y-%m-%d")


def now_iso() -> str:
    return now_tz().isoformat(timespec="seconds")


# ===== ASOSIY PAFKALAR =====
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


# ===== MUHIT: RAILWAY yoki MAHHALLIY =====
IS_RAILWAY = bool(
    os.getenv("RAILWAY_ENVIRONMENT")
    or os.getenv("RAILWAY_SERVICE_ID")
    or os.getenv("RAILWAY_ENVIRONMENT_NAME")
)
RAILWAY_ENV_NAME = os.getenv("RAILWAY_ENVIRONMENT_NAME") or os.getenv("RAILWAY_ENVIRONMENT") or "local"

# Mahalliy kompyuterda tasodifan polling yoqilmasligi uchun:
# Railway'da avtomatik ishlaydi, mahalliyda esa AL_LOCAL_MODE=1 talab qiladi.
AL_LOCAL_MODE = _env_bool("AL_LOCAL_MODE", False)
SHOULD_POLL = IS_RAILWAY or AL_LOCAL_MODE


# ===== TELEGRAM =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = _env_int("ADMIN_ID", 0)
CHANNEL_ID = os.getenv("CHANNEL_ID", "@VolstritStart")
CHANNEL_LINK = os.getenv("CHANNEL_LINK", "https://t.me/VolstritStart")

# Telegram API kutish vaqtlari (sekund). Past qiymat -> "Request timeout" xatosi
TELEGRAM_CONNECT_TIMEOUT = _env_int("TELEGRAM_CONNECT_TIMEOUT", 30)
TELEGRAM_READ_TIMEOUT = _env_int("TELEGRAM_READ_TIMEOUT", 60)
TELEGRAM_SEND_RETRIES = _env_int("TELEGRAM_SEND_RETRIES", 4)


# ===== AI (GEMINI) =====
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
GEMINI_TIMEOUT = _env_int("GEMINI_TIMEOUT", 120)
GEMINI_MAX_OUTPUT_TOKENS = _env_int("GEMINI_MAX_OUTPUT_TOKENS", 1000)

# Google free-tier chegaralari: 5 so'rov/daqiqa, 20 so'rov/kun.
# Biz chegara chegarasiga tegmaslik uchun biroz pastroq qiymat qo'yamiz.
AI_MAX_RETRIES = _env_int("AI_MAX_RETRIES", 3)
AI_RETRY_BASE_DELAY = _env_int("AI_RETRY_BASE_DELAY", 5)
AI_DAILY_LIMIT = _env_int("AI_DAILY_LIMIT", 14)
AI_MINUTE_LIMIT = _env_int("AI_MINUTE_LIMIT", 4)
AI_MAX_RETRY_WAIT = _env_int("AI_MAX_RETRY_WAIT", 90)


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

# So'rovnoma
POLL_DAY = os.getenv("POLL_DAY", "sunday")
POLL_TIME = os.getenv("POLL_TIME", "10:00")


# ===== YUBORISH TARTIBI =====
# true  -> AI posti tayyor bo'lgach avtomatik kanalga chiqadi (tugmalar orqali
#          admin keyinchroq o'chira/tuzata oladi)
# false -> avval admonga yuboriladi, "Tasdiqlash" tugmasi bosilgach kanalga chiqadi
AUTO_PUBLISH = _env_bool("AUTO_PUBLISH", True)
NOTIFY_ADMIN = _env_bool("NOTIFY_ADMIN", True)
MAX_POST_LENGTH = _env_int("MAX_POST_LENGTH", 4096)

AUTO_PUBLISH_LABEL = "HA" if AUTO_PUBLISH else "YO'Q (tasdiqlash kerak)"


# ===== MA'LUMOTLAR BAZASI =====
# Railway Volume "/data" ga ulangan bo'lsa — redeploy'da ma'lumot YO'QOLMAYDI.
# Aks holda konteyner.filesystem ephemeral bo'lib, har deploy'da bazasi tozalanadi.
_db_env = os.getenv("DB_PATH", "").strip()
_volume = Path("/data")
if _db_env:
    DB_PATH = _db_env
elif _volume.is_dir() and os.access(str(_volume), os.W_OK):
    DB_PATH = "/data/posts.db"
else:
    DB_PATH = str(DATA_DIR / "posts.db")

DB_IS_PERSISTENT = DB_PATH.startswith("/data")


# ===== XAVFSIZLIK =====
APPROVAL_TIMEOUT_HOURS = _env_int("APPROVAL_TIMEOUT_HOURS", 2)


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
            f"❗ Railway > Variables yoki .env faylni to'ldirganingizni tekshiring."
        )

    print("✅ Barcha sozlamalar to'g'ri yuklandi.")
    print(f"🌍 Vaqt mintaqasi: {TIMEZONE}   (Hozir: {now_tz():%Y-%m-%d %H:%M:%S})")
    warn = "" if DB_IS_PERSISTENT else "  ⚠️ VAQTINCHIK (redeploy'da yo'qoladi)"
    print(f"💾 Baza: {DB_PATH}{warn}")
    print(f"🤖 Model: {GEMINI_MODEL}   AI/kun limit: {AI_DAILY_LIMIT}")
    print(f"📤 Avtomatik kanalga yuborish: {AUTO_PUBLISH_LABEL}")


if __name__ == "__main__":
    check_config()
    print(f"📢 Kanal: {CHANNEL_NAME} ({CHANNEL_ID})")
    print(f"⏰ Post vaqtlari: {POST_TIME_MORNING}, {POST_TIME_NOON}, {POST_TIME_EVENING}")
    print(f"📊 So'rovnoma: {POLL_DAY} {POLL_TIME}")
    print(f"🚂 Railway: {IS_RAILWAY} ({RAILWAY_ENV_NAME})   Polling: {SHOULD_POLL}")
