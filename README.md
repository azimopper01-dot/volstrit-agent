# Volstrit Agent

Telegram kanali uchun avtomatik SMM agenti: Gemini AI orqali post yozadi,
belgilangan vaqtda kanalga joylaydi.

---

## ⚠️ MUHIM: FAQAT BIR POLLER

Bir bot tokeni bilan **faqat bitta** poller ishlashi shart. Ikkinchisi
ishga tushsa Telegram darhol uni o'ldiradi:

```
TelegramConflictError: Conflict: terminated by other getUpdates request;
make sure that only one bot instance is running
```

| Nima qilinadi | Nima bo'ladi |
|---|---|
| Railway + mahalliy kompyuter bir vaqtda | ❌ Ikkalasi ham to'xtaydi |
| Faqat Railway | ✅ To'g'ri ishlaydi |
| Faqat mahalliy (`.env` da `AL_LOCAL_MODE=1`) | ✅ To'g'ri ishlaydi |

Railway'da `AL_LOCAL_MODE` qiymatiga qarab ahamiyat yo'q — u avtomatik
yoqiladi. Mahalliy kompyuterda esa `AL_LOCAL_MODE=true` bo'lmasa bot
**pollingni yoqmaydi** va nima uchunini tushuntirib beradi.

> ⚠️ Railway ishlayotgan paytda kompyuteringizda botni ishga tushirmang.
> Ishni sinab ko'rmoqchi bo'lsangiz — avval Railway'ni to'xtating.

---

## 📅 Vazifalar

| Vazifa | Vaqt (Asia/Tashkent) |
|---|---|
| 🌅 Ertalabki post | 08:30 |
| ☀️ Tushlikdagi post | 13:00 |
| 🌆 Kechki post | 18:30 |
| 📊 Haftalik so'rovnoma | Yakshanba 10:00 |

Vaqtlar `.env` orqali o'zgartiriladi va **faqat** `TIMEZONE` ko'rsatilgan
vaqtda bajariladi.

### Real vaqtda vazifa berish

```
/schedule 14:30 Bitcoin haqida yoz
/schedule +20m kripto bozori tahlili
/schedule 2h neft va oltin narxlari
```

---

## 🤖 Buyruqlar

| Buyruq | Vazifasi |
|---|---|
| `/post` | Hozir post yozadi va kanalga yuboradi |
| `/poll` | So'rovnoma yaratadi |
| `/schedule HH:MM mavzu` | Real vaqtda vazifa beradi |
| `/today` | Bugungi avtomatik ishlar natijasi |
| `/health` | Bot holati, keyingi ish vaqtlari, AI kvota |
| `/stats` | Statistika |
| `/pending` | Tasdiqlanmagan postlar |
| `/cancel` | Joriy amalni bekor qilish |

Yuborilgan post xabaridagi tugmalar:

- 🗑 **Kanaldan o'chirish** — xato postni darhol olib tashlaydi
- 🔁 **Qayta yozish** — keyin buyruq yozasiz (`qisqaroq qil 12`,
  `boshqa mavzu: kripto`) — eski xabar o'chiriladi, yangisi chiqadi

---

## 📤 Yuborish tartibi

**Hozirgi rejim: `AUTO_PUBLISH=false`** (tasdiqlash bilan)

`
08:30 da bot AI orqali post yozadi
   -> post SIZGA yuboriladi (tugmalar bilan)
   -> siz qoniqarsangiz "✅ Tasdiqlash" bosasiz
   -> FAQAT SHUNDAN KEYIN kanalga chiqadi
`

Sizga keladigan xabarda 4 ta tugma bor:

| Tugma | Vazifasi |
|---|---|
| ✅ Tasdiqlash | Kanalga chiqaradi |
| ❌ Rad etish | Bekor qiladi |
| ✏️ Qayta yozish | Keyin qisqaroq qil 12 / oshqa mavzu: kripto deb yozasiz |
| ⏭ Keyingi | O'tkazib yuboradi |

Agar 2 soat ichida tasdiqlanmasa, bot sizga **eslatish** yuboradi
(`/pending` orqali ko'rish mumkin).

Almashtirish uchun `AUTO_PUBLISH=true` — unda post avtomatik kanalga
chiqadi va siz keyinchalik "Kanaldan o'chirish" bilan olib tashlashingiz mumkin.

## 🔒 Nima uchun kanal hech qachon bo'sh qolmaydi

1. **AI kvota tugab qolsa ham** — 5 ta tayyor zaxira post matnidan biri
   ishlatiladi va post kanalga chiqadi.
2. **429 rate-limit** — server aytgan `retry_after` bo'yicha kutib, 3 marta
   qayta urinadi.
3. **Kunlik kvota (PerDay) tugab qolsa** — qayta urishning ma'nosiz, darhol
   zaxiraga o'tadi.
4. **AI/network xatosida** — ish `failed` deb bazaga yoziladi va adminga
   xabar yuboriladi (`/today` da ko'rinadi).
5. **AI matnidagi `&`, `<`, `>`** — kanalga yuborishdan oldin tozalanadi,
   "can't parse entities" xatosi chiqmaydi.
6. **4096 belgidan uzun matn** — avtomatik qisqartiriladi.

## ⏱ Nima uchun hech qanday vazifa o'tkazilmaydi

1. **Catch-up** — konteyner ish vaqtida qayta ishga tushsa (masalan 08:35 da),
   o'tib ketgan 08:30 ishi **darhol** bajariladi.
2. **`misfire_grace_time=3600`** — ish 1 soat kechiksa ham bajariladi.
3. **`coalesce=True`** — bot o'chib qolgan paytdagi ko'p o'tkazilgan ishni
   bittaga jamlaydi.
4. **Job natijasi bazada** — bir kunlik ish bir marta bajariladi, takrorlanmaydi.
5. **Har 1 daqiqalik "tik"** — `/schedule` vazifalari tekshiriladi.

---

## 🚂 Railway'da o'rnatish

### 1. Variables

Service → Variables → **+ New Variable**:

```
BOT_TOKEN          = <botfather dan>
ADMIN_ID           = <sizning telegram ID>
CHANNEL_ID         = @VolstritStart
GEMINI_API_KEY     = <AI Studio dan>
GEMINI_MODEL       = gemini-1.5-flash
TIMEZONE           = Asia/Tashkent
POST_TIME_MORNING  = 08:30
POST_TIME_NOON     = 13:00
POST_TIME_EVENING  = 18:30
POLL_DAY           = sunday
POLL_TIME          = 10:00
AUTO_PUBLISH       = false
DB_PATH            = /data/posts.db     # faqat Volume qo'shsangiz
```

### 2. 🔴 Ma'lumotlarni saqlash uchun Volume (Muhim)

Hozir bazada `data/posts.db` konteyner ichida — **har bir deploy'da
butunlay tozalanadi** (statistika, tarix yo'qoladi).

Railway → Service → **Volumes** → **+ New Volume**:

| Maydon | Qiymat |
|---|---|
| Mount Path | `/data` |

Keyin Variables ga qo'shing: `DB_PATH=/data/posts.db`

Bazani Telegram'ga yuklab olsa bo'ladi:
```bash
railway run cat /data/posts.db > posts_backup.db
```

### 3. Deploy

`railway.json` start command ni belgilaydi (`python -u main.py`) va
`restartPolicy: ON_FAILURE` bilan xato bo'lsa avtomatik qayta ishga
tushiradi. Bot HTTP server emas — healthcheck kerak emas.

### 4. Tekshirish

Deploy'dan keyin loglarda **quyidagilar** ko'rinishi kerak:

```
🚀 Volstrit Agent ishga tushmoqda...
🌍 Vaqt mintaqasi: Asia/Tashkent   (Hozir: 2026-10-01 08:29:00)
✅ Scheduler sozlandi:
   • 🌅 Ertalabki post (08:30 Asia/Tashkent)
       keyingi: 2026-10-02 08:30
   • ☀️ Tushlikdagi post (13:00 Asia/Tashkent)
       keyingi: 2026-10-02 13:00
   • 🌆 Kechki post (18:30 Asia/Tashkent)
       keyingi: 2026-10-02 18:30
   • 📊 Haftalik so'rovnoma (sunday 10:00 Asia/Tashkent)
       keyingi: 2026-10-05 10:00
```

Har 10 daqiqada tiriklik belgisi chiqadi:
```
💓 Tirik | 08:30:04 (Asia/Tashkent) | bugun: 1 post | AI: 1/14 | keyingi: evening_post@18:30, morning_post@08:30
```

Keyin Telegram'da `/health` yozing — u shu ma'lumotlarni ko'rsatadi.

---

## 🔢 AI kvota

Gemini free tier: **5 so'rov/daqiqa**, **20 so'rov/kun**.

| O'zgaruvchi | Standart | Izoh |
|---|---|---|
| `AI_DAILY_LIMIT` | 14 | 20 dan past — chegara tegib qolmasin |
| `AI_MINUTE_LIMIT` | 4 | 5 dan past |
| `AI_MAX_RETRIES` | 3 | 429 da qayta urish soni |

AI kvota oshsa ham tizim to'xtamaydi — zaxira matn ishlatiladi.
Ko'proq post kerak bo'lsa, AI Studio'da **billing** yoqish yoki
boshqa modelga o'tish (`GEMINI_MODEL`) kerak.

---

## 🧪 Sinovlar

```bash
pip install apscheduler==3.10.4 python-dotenv==1.0.1 aiosqlite==0.20.0 tzdata

# Vaqt zonasi tuzatilishini dalil bilan ko'rsatadi
python test_tz_fix.py

# Butun oqimni AI/Telegram stubs bilan sinovdan o'tkazadi
python test_pipeline.py
```

`test_pipeline.py` 40 ta tekshiruvni bajaradi: catch-up, takrorlashning
oldi olinishi, real vaqt vazifalari, kvota himoyasi, 429 retry, HTML
tozalash, admin tugmalari (tasdiqlash / rad etish / ruxsat), eslatish,
statistika.

---

## 📁 Fayllar

| Fayl | Vazifasi |
|---|---|
| `main.py` | Ishga tushirish, polling nazorati, polling himoyasi |
| `scheduler.py` | Cron ishlar (TZ to'g'ri), catch-up, heartbeat |
| `telegram_bot.py` | Buyruqlar, kanalga yuborish, tugmalar |
| `ai_generator.py` | Gemini chaqiruvi, retry, kvota, zaxira matnlar |
| `database.py` | Postlar, ish natijalari, AI kvota, real vaqt vazifalari |
| `config.py` | Sozlamalar, vaqt mintaqasi, `.env` |
