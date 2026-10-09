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
from typing import Optional

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, GoogleAPIError

from config import (
    GEMINI_API_KEY, GEMINI_MODEL, GEMINI_TIMEOUT, GEMINI_MAX_OUTPUT_TOKENS,
    AI_MAX_RETRIES, AI_RETRY_BASE_DELAY, AI_DAILY_LIMIT, AI_MINUTE_LIMIT,
    AI_MAX_RETRY_WAIT, CHANNEL_NAME, CHANNEL_TOPIC, CHANNEL_LANG,
    CHANNEL_STYLE, AUDIENCE, MAX_POST_LENGTH, now_tz,
    IMAGE_ENABLED, IMAGE_MODEL, IMAGE_QUALITY, AI_IMAGE_DAILY_LIMIT,
    IMAGE_TIMEOUT,
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
    # Yuqori temperatura = har safar boshqacha matn.
    # Pastda (0.7-0.9) model bir xil javobni takrorlab beradi.
    "temperature": 1.0,
    "top_p": 0.98,
    "max_output_tokens": GEMINI_MAX_OUTPUT_TOKENS,
    "candidate_count": 1,
}


# ===== TIZIM PROMPTI =====
# Muhim: qoidalar qisqa va aniq. Uzun ro'yxatli promptlarda model
# promptni o'zini qaytarib beradi ("Checked.", "1. Post 600-900 belgi").
SYSTEM_PROMPT = f"""Sen "{CHANNEL_NAME}" Telegram kanalining SMM menyasisan.

Kanal: {CHANNEL_TOPIC}
Til: o'zbek tili, lotin yozuvi
Auditoriya: {AUDIENCE} — yangi va tajribali investorlar
Uslub: sodda, tushunarli, ilhomlantiruvchi

Yagona vazifang: tayyor Telegram post matnini yozish.

Post qanday bo'lishi kerak:
- Birinchi qator: qisqa, e'tiborni tortuvchi sarlavha (emoji bilan)
- Keyin: 2-3 qator asosiy ma'lumot yoki kuzatish
- Keyin: bitta amaliy maslahat yoki xulosa
- Oxirida: obunachiga savol
- Oxirida: 3-4 ta hashtag (#fond #aksiya #forex #kripto)

Yodingizda tuting:
- Matn 500-900 belgi orasida bo'lsin
- Murakkab atamalarni oddiy tilda izohlang
- Emoji 3-5 ta, keragidan ko'p emas
- "Sotib oling" yoki "soting" deb aniq maslahat bermang
- HTML teglari va ampersand belgisini ishlatmang
- Raqamlar va faktlar ishonchli bo'lsin

Javobingiz: FAQAT tayyor post matni.
Bu yerda hech qanday izoh, tushuntirish, ro'yxat yoki "Checked" kabi
so'zlar yozilmaydi — ular yozilsa, javob noto'g'ri hisoblanadi."""


# ===== TUZILMA VA OCHILISH USLUBLARI =====
# Nima uchun bu kerak: prompt bir xil bo'lsa, model bir xil javob beradi.
# Har safar TURLI tuzilma va ochilish berilsa — matn ham, o'lcham ham,
# joylashuv ham o'zgaradi. Bu — "har doim yangi post" ning asosi.

POST_FORMATS = [
    ("savol bilan ochilish", "Boshlang'ich savol bering, keyin javobni bering"),
    ("savol + ro'yxat", "Savol, keyin 3-4 punktli qisqa ro'yxat, oxirida xulosa"),
    ("qisqa hikoya", "Bitta real hayot misolini qisqa hikoya qilib yozing, undan dars oling"),
    ("noto'g'ri tasavvur", "Ko'pchilikda uchraydigan xato tasavvurni ayting, to'g'risini oching"),
    ("taqqoslash", "Ikki yondashuvni yoki ikki aktivni qiyoslab yozing"),
    ("aniq raqam bilan", "Bitta aniq raqam yoki foizdan boshlang"),
    ("savol + javob + savol", "Bir savol, unga javob, keyin obunachiga savol"),
    ("og'irlatilgan maslahat", "Ogohlantirish tonida boshlang, keyin yechim bering"),
    ("kunlik sharh", "Kunning vaziyatiga qisqa ishora qilib, tahlil bering"),
    ("3 ta qoida", "Uchta qisqa qoida ro'yxati, har biri bir juml bilan izohlangan"),
]

OPENINGS = [
    "Emoji bilan qisqa sarlavha",
    "Savol bilan sarlavha",
    "Sho'xta bayonot bilan sarlavha",
    "Raqam bilan sarlavha",
    "Qisqa hikoya bilan sarlavha",
]

# Har safar promptga qo'shiladigan tasodifiy "kayfiyat" — matnni
# har gal boshqacha ohanga olib boradi.
TONES = [
    "sodda va do'stona",
    "qisqa va aniq",
    "yengil hazil bilan",
    "amaliy va foydali",
    "o'quvchini rag'batlantiruvchi",
    "savol berishga undovchi",
    " tajriba va bilimni taqqoslagan",
]

# Mavzu bo'yicha qisqa fakt/eslatma — matnga aniq zarrachalar kiritadi
FACT_HINTS = [
    "diqqat qiling: bir kunlik tebranish uzoq muddatli trend emas",
    "eslatib o'tamiz: likvidlik past bo'lsa, katta order narxni tez suradi",
    "Muhim: foiz stavkalari oshsa, aksiyalar bilan birga oltin ham qiziydi",
    "kuchsiz nuqta: kompaniya qarziga haddan tashqari ko'p bog'lansa, xavf ortadi",
    "esda boriring: har bir portfelda kamida bir necha soha bo'lishi kerak",
    "amaliy qoida: rejangizni yozmasdan savdo qilmang",
    "og'rlantirmoqchi bo'lamiz: natijani emas, jarayonni kuzating",
    "aniqlik uchun: har bir kompaniyaning moliyaviy hisoboti ochiq bo'ladi",
]


# ===== POST MAVZULARI — 6 KATEGORIYA =====
# Kategoriyalar (har bir post bittasiga kiradi):
#   1) YANGILIKLAR        — bozordagi joriy voqealar
#   2) FOYDALI MA'LUMOT    — ta'lim va bilim
#   3) KRIPTO YANGILIKLARI — Bitcoin, Ethereum, altcoin
#   4) FX YANGILIKLARI     — valyuta juftliklari
#   5) MOTIVATSIYA         — ruhlantiruvchi postlar
#   6) TREADING XATOLARI   — keng tarqalgan xatolar
#
# (topic, angle, category) — angle matnning burchagini belgilaydi.
# category promptga uzatiladi — shunda AI har postda o'z turida yozadi.

POST_TOPICS = [
    # ===== 1) YANGILIKLAR =====
    ("Bozor yangiligi", "global bozorda kuzatilayotgan asosiy o'zgarishlar", "yangilik"),
    ("Indekslar holati", "asosiy fond bozori indekslaridagi harakat", "yangilik"),
    ("Makro yangiliklar", "iqtisodiy ko'rsatkichlar va ularning ta'siri", "yangilik"),
    ("Kompaniya hisoboti", "yangi natijalar va ularning bozorga ta'siri", "yangilik"),
    ("Bozor sentimenti", "investorlar kayfiyati va uning o'zgarishi", "yangilik"),
    ("Bozor o'zgarishlari", "narxlarda keskin o'zgarish bo'lgan paytlar", "yangilik"),

    # ===== 2) FOYDALI MA'LUMOT =====
    ("Likvidlik tushunchasi", "bitta aktivning qanchalik tez sotilishi", "foydali"),
    ("Diversifikatsiya", "portfelni to'g'ri taqsimlash qoidalari", "foydali"),
    ("Risk boshqaruvi", "xavfni qanday nazorat qilish kerak", "foydali"),
    ("Foyda va zarar", "pozitsiya yopish qoidalari", "foydali"),
    ("Uzoq muddatli investitsiya", "foiz va kompaniyaning ishi", "foydali"),
    ("Boshlang'ich qadamlar", "birinchi marta investitsiya qilish", "foydali"),
    ("Portfolio balansi", "aktivlar taqsimotini kuzatish", "foydali"),
    ("Vaqt boshqaruvi", "qachon savdo qilish kerak", "foydali"),
    ("Taxlil usullari", "asosiy va texnikal tahlil farqi", "foydali"),

    # ===== 3) KRIPTO YANGILIKLARI =====
    ("Bitcoin", "narx harakati va uni ta'sirlagan omillar", "kripto"),
    ("Ethereum", "zaxira tizimining rivojlanishi", "kripto"),
    ("Altcoinlar", "kichik kriptovalyutalardagi harakat", "kripto"),
    ("Kripto yangiliklari", "bozordagi so'nggi voqealar", "kripto"),
    ("Staking va DeFi", "foiz olish va markazlashtirilmagan moliya", "kripto"),
    ("Kripto xavflari", "bozor kuchli tebranish qachon bo'ladi", "kripto"),

    # ===== 4) FX YANGILIKLARI =====
    ("EUR/USD", "yevropa dollari juftligidagi tendensiya", "fx"),
    ("GBP/USD", "sterlin va dollar o'zaro munosabati", "fx"),
    ("USD/JPY", "yen va dollar kuchining o'zgarishi", "fx"),
    ("Oltin va neft", "tinchlik valyutalari bozordagi o'rni", "fx"),
    ("Markaziy banklar", "foiz stavkalari qarorlari va ta'siri", "fx"),
    ("Forex yangiliklari", "valyuta bozoridagi yangi voqealar", "fx"),

    # ===== 5) MOTIVATSIYA =====
    ("Sabr va intizom", "emotionga bo'linmaslik", "motivatsiya"),
    ("Zarar va tiklanish", "yo'qotilgan kunlardan keyin nima qilish", "motivatsiya"),
    ("Realistic maqsad", "juda katta maqsad qo'yish xatosi", "motivatsiya"),
    ("O'rganish", "har kuni yangi narsa o'rganish", "motivatsiya"),
    ("Ishonch va shubha", "qaror qabul qilishdagi muvozanat", "motivatsiya"),
    ("Uzoq muddatli fikr", "qisqa muddatga bog'lanmaslik", "motivatsiya"),

    # ===== 6) TREADING XATOLARI =====
    ("Xatolar: rejasiz savdo", "reja yo'qligi natijada kelib chiqadi", "xatolar"),
    ("Xatolar: haddan tashqari ishonch", "orziyalik natijada qanday zarar beradi", "xatolar"),
    ("Xatolar: zarar beruvchi savdo", "takrorlanuvchi xatolarni tahlil qilish", "xatolar"),
    ("Xatolar: valyuta hisobini tushmaslik", "kurs o'zgarishining ta'siri", "xatolar"),
    ("Xatolar: kunlik shovqin", "qisqa muddatli tebranishni chalg'itish", "xatolar"),
    ("Xatolar: nazoratni yo'qotish", "hisobni to'xtotmaslik", "xatolar"),
    ("Xatolar: minimal va maksimal", "kirish va chiqish nuqtalarini belgilash", "xatolar"),
    ("Xatolar: hissiyot bilan", "emotsiya qarorni qanday buzadi", "xatolar"),
]

# Kategoriyalar bo'yicha qisqa tavsif — promptga uzatiladi,
# shunda AI har postda o'z turida (yangilik/xato/motivatsiya) yozadi.
CATEGORY_HINTS = {
    "yangilik": "bu YENGILIK bo'lishi kerak — nima bo'ldi, nima uchun muhim, "
                "nima qilish kerak. Aniq raqamlar bilan yoz",
    "foydali": "bu TA'LIM bo'lishi kerak — tushunchani oddiy tilda tushuntiring, "
               "misol bering, amaliy foyda keltiring",
    "kripto": "kripto bozori haqida — Bitcoin/Ethereum/altcoin, "
              "bozor dinamikasi va xavflar",
    "fx": "valyuta bozori haqida — EUR/USD, GBP/USD, USD/JPY, "
          "markaziy banklar, oltin-neft",
    "motivatsiya": "bu RUHANTIRUVCHI bo'lishi kerak — qisqa, ilhomlantiruvchi, "
                   "o'quvchini oldinga undovchi. Sabr va intizom haqida",
    "xatolar": "bu XATO bo'lishi kerak — keng tarqalgan xatoni ayting, "
               "nima uchun xato, uni qanday tuzatish kerak",
}

# Har bir postga birga yuboriladigan rasm uslublari (rasm prompti uchun).
IMAGE_STYLES = [
    ("financial chart", "3D-render, ko'k va yashil ranglar, fond bozori grafigi"),
    ("candlestick chart", "chiroli narx grafigi, yorqin ranglar, futuristik uslub"),
    ("stock market", "aksiyalar, raqamlar va o'sish chizig'i, zamonaviy grafika"),
    ("crypto coins", "Bitcoin va Ethereum simvoli, porlaydigan metall effekti"),
    ("city skyline", "zamonaviy shahar manzarasi, moliyaviy hudud, tunda"),
    ("trading desk", "profesional treyder ish stoli, monitorlar, kichik yorug'lik"),
    ("abstract finance", "moliyaviy grafika, chiziqli naqshlar,gradient ranglar"),
    ("globe economy", "global iqtisodiyot shakli, xaritalar va valyuta belgilari"),
    ("luxury watch", "ibratli soat va moliyaviy muvaffaqiyat ramzi, yumshoq yorug'lik"),
    ("data visualization", "rangli diagrammalar va statistik grafikalar"),
    ("smartphone investing", "telefonda grafik ko'rsatilgan, qulay uslub"),
    ("golden coins", "oltin tangalar va moliyaviy barqarorlik ramzi"),
    ("mountain peak", "moliyaviy cho'qqilish cho'qqisi, motivatsiya uchun"),
    ("bank building", "klassik bank binosi, ishonch va barqarorlik"),
    # motivatsiya uchun
    ("sunrise mountain", "cho'qqidan quyosh ko'tarilishi, yaxshi kelajak"),
    ("runner finish", "marafon tugash chizig'i, g'alaba va intizom"),
    ("compass path", "kompas va yo'l, to'g'ri yo'nalish"),
    ("growth plant", "o'suvchi o'simlik, uzoq muddatli o'sish"),
    # xatolar uchun
    ("broken chart", "uzilgan grafik, xato va ogohlantirish"),
    ("warning triangle", "diqqat belgisi, xavfni ko'rsatish"),
    ("stop sign finance", "savdodan to'xtash belgisi, xato nazorati"),
    # kripto uchun
    ("bitcoin coin", "oltiin Bitcoin tangasi, kripto simvoli"),
    ("blockchain cubes", "zanjir bloklari, texnologiya"),
    # fx uchun
    ("currency arrows", "turli valyuta strelkalari, kurs o'zgarishi"),
    ("trading terminal", "foreks terminali, valyuta juftliklari"),
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
        """🌅 Ertalabki reja: uchta ustun

Har bir sessiya boshida o'zingizga uchta savol bering:
1. Bugun qaysi sohani kuzataman?
2. Qaysi yangilik narxga ta'sir qilishi mumkin?
3. Qanday shartda pozitsiyani yopaman?

📌 Nima uchun muhim:
Aniq reja bo'lmaganda, har bir tebranish qaror
kaqalligiga aylanadi. Reja bo'lsa, tebranish — bu
shunchaki ma'lumot.

💡 Amaliy maslahat:
Rejangizni yozib qo'ying va uni buzishga shoshiling.
Intizom — investitsiyaning eng qimmat qismi.

Siz ertalabki sessiyada nima bilan boshlaysiz?

#fond #aksiya #forex #kripto""",
        """🌅 Bugungi kun uchun uchta e'tibor

Kunlik ritm — investitsiyaning eng muhim odati.
Kunlik tahlil bir necha daqiqa bilan boshlanadi:
bozor ochilishi, Asiya sessiyasi yakuni, Yevropa kirishi.

📌 Nima uchun muhim:
Har bir sessiyaning o'z "ruhi" bor. Toshxon
tushunishdan yaxshi — qachon qimmat, qachon
arzon bo'lishini oldindan bilib bo'lmaydi,
lekin tayyorgarlik mumkin.

💡 Amaliy maslahat:
Har kuni bir xil vaqtda tahlil qiling. Bu
odat barqarorlikni oshiradi.

Qachon bozor ko'rishni eng yoqgan usul?

#fond #analiz #kripto #forex""",
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
        """☀️ Tushlikdagi savol: likvidlik

Likvidlik — bitta savolga javob: "men xohlagan
miqdorda qancha tez sotib olsam bo'ladi?"

📌 Nima uchun muhim:
Likvidlik past bo'lganda kichik order ham
narxni sezilarli surilishga majbur qiladi. Bu
yirik kompaniyalarda kam, kichiklarda ko'p
bo'ladi.

💡 Amaliy maslahat:
Yangi kompaniya tanlaganda avval likvidlikni
tekshiring — u ishlab turgan kompaniya bo'lsa,
mashina ham yaxshi ishlaydi.

Likvidlikni qanday tekshirasiz?

#fond #aksiya #forex #kripto""",
        """☀️ Bugungi savol: nima uchun bozor ko'tarildi?

Har bir tebranishning biror sababi bor. Sababni
bilmasangiz, keyingi tebranishda ham xato qilasiz.

📌 Uchta asosiy sabab:
1. Yangi ma'lumot — hisobot, statistika, gap
2. Katta order — bir fonda ko'p hajm
3. Havo — qo'rquv yoki ishtiyoq

💡 Amaliy maslahat:
Ko'tarilish sababini yozib boring. Keyin bir xil
holat yana bo'lsa — tayyor bo'lasiz.

Siz bozor sabablarini qanday kuzatarsiz?

#fond #analiz #kripto""",
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
        """🌆 Kechki savol: qaysi xato takrorlanmoqda?

Har bir muvaffaqiyatsizlikda bitta savol bor:
"bu xato bir marta bo'ldimi yoki takrorlanadi?"

📌 Takrorlanuvchi xatolar:
1. Rejasiz savdo — eng ko'p uchraydi
2. Xavfsizlik chegarasini qo'ymaslik
3. Katta pozitsiyada haddan tashqari ishonch

💡 Amaliy maslahat:
Oxirgi 10 ta qaroringizni yozib ko'ring. Qaysi
biri sizga eng ko'p qiyinchilik tug'irdi?

Sizning eng ko'p takrorlanuvchi xatoyingiz qaysi?

#fond #forex #kripto #smm""",
        """🌆 Kechqurun: barqarorlik tekshiruvi

Barqarorlik — "men bilsam bo'lardim" emas,
"men har doim qilaman" degan odat.

📋 Uchta oddiy tekshiruv:
1. Portfelda bitta soha egarmasligi
2. Xavf chegaralari yozilganmi
3. Kelgusi hafta uchun reja bor

💡 Amaliy maslahat:
Bu uchtasi bir marta qilingan bo'lsa, bozor
qanday bo'lishidan qat'i nazar, siz barqarorsiz.

Siz qaysi birini birinchi bo'lib tuzatildi?

#fond #aksiya #analiz #forex""",
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


# ===== RASM YARATISH =====
# Rasmlar AI orqali yaratiladi. Muhim:
#  * kvota alohida hisoblanadi (AI_IMAGE_DAILY_LIMIT)
#  * kvota yo'q yoki xato bo'lsa — post YANA HAM chiqadi, faqat rasmsiz
#  * rasm generatsiyasi sekin, shuning uchun timeout qo'yilgan

_IMAGE_MODEL = None


def _get_image_model():
    """Rasmlar uchun alohida model (matndan alohida kvota)."""
    global _IMAGE_MODEL
    if _IMAGE_MODEL is None:
        try:
            _IMAGE_MODEL = genai.GenerativeModel(IMAGE_MODEL)
        except Exception as e:
            print(f"⚠️  Rasm modeli yuklanmadi: {e}")
            return None
    return _IMAGE_MODEL


def _sync_generate_image(prompt: str):
    """
    Sinxron rasm yaratish — faqat thread ichida ishlating.

    google-generativeai 0.8.3 da `response_modalities` maydoni yo'q
    (u yangi SDK versiyalarida bor). Rasmli modellar default ravishda
    rasm qaytaradi, shuning uchun qo'shimcha parametr kerak emas.
    """
    m = _get_image_model()
    if m is None:
        raise TransientAIError("Rasm modeli mavjud emas")
    response = m.generate_content(
        prompt,
        request_options={"timeout": IMAGE_TIMEOUT},
    )
    if not response.candidates:
        raise TransientAIError("AI rasm qaytarmadi")
    for part in (response.candidates[0].content.parts or []):
        inline = getattr(part, "inline_data", None)
        if inline and getattr(inline, "data", None):
            return (inline.data, inline.mime_type or "image/png")
    raise TransientAIError("AI rasm qaytarmadi")


def build_image_prompt(topic: str, style: str) -> str:
    """Rasm uchun prompt — matn yozish emas, faqat vizual tasvir."""
    return (
        f"Create a modern, professional financial illustration.\n"
        f"Subject: {topic}\n"
        f"Style: {style}\n\n"
        f"Requirements:\n"
        f"- 16:9 wide banner, suitable for a Telegram channel header\n"
        f"- Modern 3D render look, deep blue and green palette\n"
        f"- Clean composition, no text, no letters, no numbers, no logos\n"
        f"- Professional financial news illustration\n"
        f"- Soft cinematic lighting, high detail"
    )


async def generate_image(topic: str, style: str = "", category: str = "") -> Optional[bytes]:
    """
    Post uchun rasm yaratadi. Qaytaradi: (bytes, mime_type) yoki None.

    Hech qachon istisno ko'tarmaydi — None qaytarsa post rasmsiz chiqadi.
    """
    if not IMAGE_ENABLED:
        return None

    used = await database.ai_used_images_today()
    if used >= AI_IMAGE_DAILY_LIMIT:
        print(f"   🖼  Rasm kvota tugagan ({used}/{AI_IMAGE_DAILY_LIMIT}) — rasmsiz")
        return None

    style = style or _pick_image_style(category=category)
    prompt = build_image_prompt(topic, style)

    for attempt in range(1, 3):
        try:
            result = await asyncio.to_thread(_sync_generate_image, prompt)
            await database.record_image_call(True, style)
            print(f"   🖼  Rasm tayyor ({attempt}) — {style[:40]}")
            return result
        except ResourceExhausted as e:
            await database.record_image_call(False, "image_429")
            if "PerDay" in str(e) or "per day" in str(e).lower():
                print("   🖼  Rasm uchun kunlik kvota tugagan — rasmsiz")
                return None
            wait = min(_parse_retry_after(e) or 8, 40)
            print(f"   ⚠️  Rasm 429, {wait}s kutamiz ({attempt})")
            await asyncio.sleep(wait)
        except Exception as e:
            await database.record_image_call(False, "image_err")
            print(f"   ⚠️  Rasm xatosi ({attempt}): {type(e).__name__}: {e}")
            await asyncio.sleep(3)

    print("   ⚠️  Rasm yaratilmadi — post rasmsiz yuboriladi")
    return None


# Post turiga mos kategoriya — kunlik reja tabiiy o'zgaradi:
#   ertalab = yangilik (bozor ochilishi)
#   tushlik = foydali ma'lumot yoki kripto/FX
#   kechki  = xatolar yoki motivatsiya
TYPE_CATEGORIES = {
    "morning": ["yangilik", "fx", "foydali"],
    "noon": ["kripto", "foydali", "yangilik"],
    "evening": ["xatolar", "motivatsiya", "foydali"],
}


def _pick_topic(post_type: str = "morning", used: set = None):
    """
    Mavzuni tanlaydi va QAYTARADI:
        (mavzu_burchagi, kategoriya)

    Eski kod: `yday % len(POST_TOPICS)` — har kuni bir xil natija berardi.
    Yangi:
      1. Post turiga mos kategoriyalar preferensiya qilinadi
         (ertalab — yangilik, kechki — xato/motivatsiya)
      2. ishlatilgan mavzular chiqariladi
      3. tasodifiy tanlanadi
    """
    prefer = TYPE_CATEGORIES.get(post_type, [])
    pool = list(POST_TOPICS)

    if used:
        fresh = [p for p in pool if p[0] not in used]
        if fresh:
            pool = fresh
        else:
            used.clear()

    # avval kategoriya mos mavzular
    matched = [p for p in pool if p[2] in prefer]
    if matched:
        pool = matched

    topic, angle, category = random.choice(pool)

    type_hint = {
        "morning": "Bugungi kun uchun reja va asosiy e'tibor nuqtalari",
        "noon": "Qisqa tahlil yoki dolzarb savol",
        "evening": "Kun yakuni: xulosa va ertangi kunga tayyorgarlik",
    }.get(post_type, "")

    return f"{topic} — {angle}. {type_hint}".strip(), category


def _pick_image_style(used: set = None, category: str = "") -> str:
    """Rasm uslubini tanlaydi (takrorlanmaslik + kategoriyaga moslik)."""
    styles = list(IMAGE_STYLES)

    # kategoriyaga mos uslublar (nomlar orqali)
    hints = {
        "yangilik": ("trading desk", "financial chart", "stock market",
                     "data visualization", "smartphone investing"),
        "foydali": ("data visualization", "financial chart", "abstract finance",
                    "bank building", "smartphone investing"),
        "kripto": ("bitcoin coin", "crypto coins", "blockchain cubes",
                   "financial chart", "golden coins"),
        "fx": ("currency arrows", "trading terminal", "globe economy",
               "financial chart", "candlestick chart"),
        "motivatsiya": ("sunrise mountain", "runner finish", "compass path",
                        "growth plant", "mountain peak"),
        "xatolar": ("warning triangle", "broken chart", "stop sign finance",
                    "abstract finance", "bank building"),
    }
    prefer = hints.get(category or "", ())

    if prefer:
        matched = [s for s in styles if s[0] in prefer]
        if matched:
            styles = matched

    if used:
        fresh = [s for s in styles if s[0] not in used]
        if fresh:
            styles = fresh

    name, desc = random.choice(styles)
    return f"{name} ({desc})"


def _fallback(post_type: str, reason: str = "", used: set = None) -> str:
    """AI o'rniga ishlatiladigan zaxira matn (takrorlanmaslik bilan)."""
    bank = FALLBACK_POSTS.get(post_type) or FALLBACK_POSTS["default"]
    if used:
        fresh = [t for t in bank if t not in used]
        if fresh:
            bank = fresh
    text = random.choice(bank)
    if reason:
        print(f"⚠️  Zaxira matn ishlatildi ({post_type}): {reason}")
    return text


def _looks_like_garbage(text: str, min_len: int = 250) -> bool:
    """
    AI promptning o'zini yoki ro'yxatni qaytarganini aniqlaydi.

    Sabab: ba'zi modellar "Checked." / "1. Post 600-900 belgi" kabi
    prompt matnini qaytaradi — bu kanalga chiqsa obuna buziladi.
    """
    if not text:
        return True
    t = text.strip()
    if len(t) < min_len:
        return True
    if re.match(r"^(checked|done|ok|ready)\b[\.\s]*$", t, re.IGNORECASE):
        return True
    if re.search(r"POST TUZILISHI|QOIDALAR:|JUDA MUHIM", t):
        return True
    lines = [x for x in t.split("\n") if x.strip()]
    if lines:
        bullets = sum(1 for x in lines
                      if x.strip().startswith(("*", "-", "1.", "2.", "3.")))
        if bullets > len(lines) * 0.7:
            return True
    return False


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

            # AI promptni o'zini qaytargan bo'lsa — qayta uramiz
            # (poll uchun matn tabiiy qisqa, shuning uchun chegarasi boshqa)
            min_len = 80 if label == "poll" else 250
            if _looks_like_garbage(text, min_len=min_len):
                await database.record_ai_call(False, "bad_output")
                raise TransientAIError(
                    "AI prompt matnini qaytardi (post emas)"
                )

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
async def generate_post(topic: str = None, post_type: str = "morning",
                        used_topics: set = None, with_image: bool = True) -> dict:
    """
    AI orqali post yozadi va (imkon bo'lsa) rasm yaratadi.

    Qaytaradi:
        {"content": str, "image": bytes|None, "topic": str, "source": str}

    Hech qachon istisno ko'tarmaydi — AI ishlamasa zaxira matn,
    rasm yaratilmasa None (post rasmsiz chiqadi).
    """
    category = ""
    if not topic:
        topic, category = _pick_topic(post_type, used_topics)

    time_context = {
        "morning": "Bu ertalabki post - kun boshida bozor yangiliklari va reja haqida.",
        "noon": "Bu tushlikdagi post - qisqa tahlil yoki qiziqarli fakt haqida.",
        "evening": "Bu kechki post - kun yakuni, xulosa va ertangi kunga tayyorgarlik.",
    }.get(post_type, "")

    # Kategoriya promptga uzatiladi - har post o'z turida chiqadi
    cat_hint = CATEGORY_HINTS.get(category, "")
    cat_line = (chr(10) + "Bu postning KATEGORIYASI: " + cat_hint) if cat_hint else ""

    # HAR SAFAR BOSHQA prompt: tuzilma, ochilish, ohang va fakt
    # tasodifiy tanlanadi — shuning uchun matn ham doim yangi bo'ldi.
    fmt, fmt_desc = random.choice(POST_FORMATS)
    opening = random.choice(OPENINGS)
    tone = random.choice(TONES)
    fact = random.choice(FACT_HINTS)
    seed = random.randint(1000, 9999)

    # Yaqinda chiqarilgan postlarni ko'rsatamiz — model ularni
    # TAKRORLAMASLIGI kerak. Bu "har safar yangi"ning asosiy kaliti.
    avoid = ""
    try:
        recent = await database.get_recent_posts(3)
        titles = []
        for r in recent:
            first = (r["content"] or "").strip().split("\n")[0][:80]
            if first:
                titles.append(f"- {first}")
        if titles:
            avoid = ("\nMANA O'ZGA POSTLAR (bularni TAKRORLAMANG, "
                     "boshqa sarlavha va boshqa misol ishlating):\n"
                     + "\n".join(titles) + "\n")
    except Exception:
        pass

    prompt = f"""{SYSTEM_PROMPT}

Bu postning mavzusi: {topic}
Post turi: {time_context}{cat_line}
{avoid}
SHU POST UCHUN QAT'IY KO'RSATMALAR:
1. Tuzilish: {fmt} - {fmt_desc}
2. Sarlavha uslubi: {opening}
3. Ohang: {tone}
4. Matnga shu fikrni yumshoq tarzda qo'shing: {fact}
5. Bu post boshqa postlardan butunlay boshqacha bo'lsin -
   boshqa sarlavha, boshqa misol, boshqa izoh boshqacha bo'lsin.
6. Matn uzunligi {500 + seed % 250}-{700 + seed % 200} belgi orasida bo'lsin.

Shu mavzu bo'yicha tayyor post matnini yoz."""

    source = "AI"
    try:
        text = await _call_with_retry(prompt, f"post/{post_type}")
        cleaned = _clean(text)
        if not cleaned:
            raise TransientAIError("bo'sh matn")
    except (QuotaExhausted, TransientAIError) as e:
        cleaned = _fallback(post_type, str(e), used_topics)
        source = "zaxira"
    except Exception as e:
        cleaned = _fallback(post_type, f"{type(e).__name__}: {e}", used_topics)
        source = "zaxira"

    image = None
    if with_image:
        image = await generate_image(topic, category=category)
        if image:
            image = image[0] if isinstance(image, tuple) else image

    return {"content": cleaned, "image": image, "topic": topic,
            "category": category, "source": source}


async def generate_post_for_topic(topic: str) -> str:
    """Aniq mavzu bo'yicha post (real vaqtda berilgan vazifa uchun)."""
    # /schedule orqali kelgan mavzu ham tasodifiy uslub oladi —
    # aks holda u avvalgi postlarga o'xshab qoladi.
    fmt, fmt_desc = random.choice(POST_FORMATS)
    opening = random.choice(OPENINGS)
    tone = random.choice(TONES)
    seed = random.randint(1000, 9999)

    prompt = f"""{SYSTEM_PROMPT}

Bu postning mavzusi: {topic}

SHU POST UCHUN KO'RSATMALAR:
- Tuzilish: {fmt} — {fmt_desc}
- Sarlavha: {opening}
- Ohang: {tone}
- Boshqa postlardan butunlay boshqacha bo'lsin
- Uzunligi {500 + seed % 250}-{700 + seed % 200} belgi

Shu mavzu bo'yicha tayyor post matnini yoz."""

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
Til: o'zbek tili, lotin yozuvi

Savol qisqa va aniq bo'lsin (60 belgidan oshmasin).
Unda 3-5 ta javob variant bo'lsin, har biri 30 belgidan oshmasin.
Savol obunachilarni fikr bildirishga undasin va mavzu dolzarb bo'lsin.

Javobni faqat shu formatda yoz, boshqa hech narsa emas:
SAVOL: <savol>
VARIANT: <birinchi variant>
VARIANT: <ikkinchi variant>
VARIANT: <uchinchi variant>
VARIANT: <to'rtinchi variant>"""

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

        # AI ko'pincha "<savol>" shablonini qaytaradi — buni rad etamiz
        if not question or len(options) < 2:
            raise TransientAIError("AI noto'g'ri format qaytardi")
        if "<" in question or question.lower().startswith("<savol"):
            raise TransientAIError("AI shablon qaytardi, haqiqiy savol emas")
        options = [o for o in options if o and not o.startswith("<")]
        if len(options) < 2:
            raise TransientAIError("AI variantlari bo'sh")
        return {"question": question, "options": options[:10]}

    except Exception as e:
        print(f"❌ So'rovnoma yaratilmadi: {e}")
        return None


async def improve_post(original: str, feedback: str) -> str:
    """
    Admin fikriga ko'ra postni QAYTADAN yozadi.

    Muhim o'zgarishlar (eski kod ishlamaydi edi):
    1. Eski matn "ESKI MATNNI TAKRORLANG" degan ogohlantirishsiz
       berilardi — AI ko'pincha aynan o'shanini qaytarardi.
       Endi uni "faqat manba" sifatida ko'rsatamiz.
    2. Xato bo'lsa eski matn QAYTARILMASDI — yangi mavzuga
       ko'ra yoziladi (chunki ma'no "o'zgartirish" edi).
    3. Tuzilma/ohang yana tasodifiy tanlanadi.
    """
    request = (feedback or "").strip()
    if not request:
        request = "butunlay boshqa so'zlar bilan qayta yoz, bir xil fikrni takrorlama"

    fmt, fmt_desc = random.choice(POST_FORMATS)
    opening = random.choice(OPENINGS)
    tone = random.choice(TONES)
    seed = random.randint(1000, 9999)

    # Eski matnni QISQARTIRB beramiz — model uni ko'rib ketmasin,
    # faqat mavzu mazmunini tushishi uchun.
    old_brief = (original or "").strip()[:280]

    prompt = f"""{SYSTEM_PROMPT}

ADMIN SIZGA BUYURMADI: "{request}"

QOIDALAR:
1. Yuqoridagi buyruqni BARCHA darajada bajarish shart.
2. Agar buyruqda yangi mavzu ko'rsatilgan bo'lsa — o'sha mavzu
   bo'yicha butunlay yangi post yoz.
3. AGAR buyruq qisqaroq/uzunroq qilishni so'rasa — uzunligini o'zgartir.
4. Eski matnni TAKRORLAMA. Sarlavha, misol va izoh boshqacha bo'lsin.
5. Tuzilish: {fmt} — {fmt_desc}
6. Sarlavha: {opening}
7. Ohang: {tone}
8. Uzunligi {450 + seed % 250}-{700 + seed % 200} belgi.

MANBA (mavzuni tushish uchun, matnini KOPYALAMANG):
{old_brief}

Faqat tayyor post matnini qaytaring."""

    try:
        text = await _call_with_retry(prompt, "rewrite")
        cleaned = _clean(text)
        if cleaned and not _looks_like_garbage(cleaned, min_len=200):
            return cleaned
        raise TransientAIError("qayta yozilgan matn sifatsiz")
    except Exception as e:
        print(f"❌ Qayta yozib bo'lmadi: {type(e).__name__}: {e}")

    # Zaxira: buyruq matnini o'zi mavzu sifatida ishlatamiz.
    # Eski matnni QAYTARMASLIGIMIZ kerak — ma'no "o'zgartirish" edi.
    try:
        return await generate_post_for_topic(request)
    except Exception:
        return ""


if __name__ == "__main__":
    async def test():
        print(f"🧪 Model: {GEMINI_MODEL}  TZ: {now_tz()}")
        print(f"🧪 AI kvota: {await database.ai_used_today()}/{AI_DAILY_LIMIT}\n")
        post = await generate_post(post_type="morning")
        print("=" * 50)
        print(post)
        print("=" * 50)

    asyncio.run(test())
