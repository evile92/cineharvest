# Google Collection Extractor (أداة استخراج أفلام ومسلسلات Google Collection)

أداة بايثون احترافية وسريعة مصممة لبيئة **Windows** تعمل على استخراج جميع أسماء الأفلام والمسلسلات الموجودة داخل قوائم ومجموعات **Google Collections** (مثل قائمة المراقبة Watchlist) تلقائيًا وتجاوز الـ Lazy Loading والـ Infinite Scroll، ثم حفظ الأسماء منظفة بدقة في ملف `TXT` وملف `JSON`.

---

## المميزات الرئيسية
- **التمرير الذكي (Smart Infinite Scroll):** تتبع عدد العناصر تلقائيًا والاستمرار في التمرير حتى انتهاء القائمة دون الوقوع في حلقات لا نهائية.
- **نظام استخراج متعدد الاستراتيجيات (Multi-Strategy Extraction):** عدم الاعتماد على Selector واحد فقط؛ تجربة عناصر الـ DOM، وسِمات `aria-label`، وروابط البحث، وبيانات الصفحة الداخلية.
- **تنظيف متقدم وتصفية دقيقة:** إزالة أزرار Google UI (مثل Save, Share, Remove, More) وإزالة الترقيم وفك ترميز HTML Entities.
- **إزالة التكرار مع الحفاظ الصارم على الترتيب:** الاحتفاظ بترتيب الظهور الأصلي للعناصر في القائمة.
- **دعم كامل لـ UTF-8:** دعم لا تشوبه شائبة للغة العربية والإنجليزية ورموز التشكيل وجميع لغات العالم.
- **وضع تشخيص المشاكل (`--debug`):** حفظ لقطة شاشة للصفحة `screenshot.png`، وملف الـ HTML الكامل `page.html`، وسجل العمليات `extraction.log`.
- **معالجة متقدمة للأخطاء:** رسائل إرشادية واضحة لأي مشكلة في الاتصال، تسجيل الدخول، أو CAPTCHA.

---

## متطلبات التشغيل (Prerequisites)
1. **نظام التشغيل:** Windows 10 أو Windows 11.
2. **Python:** إصدار Python 3.10 أو أحدث.
3. **Playwright Chromium:** متصفح Chromium الخاص بمكتبة Playwright.

---

## خطوات التثبيت والتشغيل السريع (Installation & Quick Start)

افتح موجه الأوامر (PowerShell أو CMD) وانتقل إلى مجلد المشروع:

```powershell
cd google_collection_extractor
```

### 1. تثبيت المتطلبات (Dependencies):
```powershell
pip install -r requirements.txt
```

### 2. تثبيت متصفح Chromium الخاص بـ Playwright:
```powershell
playwright install chromium
```

### 3. التشغيل المباشر:
```powershell
python main.py
```

---

## خيارات وأوامر التشغيل المتقدمة (CLI Options)

### 1. استخراج أي رابط Google Collection مخصص:
```powershell
python main.py --url "https://www.google.com/collections/s/list/YOUR_LIST_ID/..."
```

### 2. تفعيل وضع التشخيص والـ Debug:
```powershell
python main.py --debug
```
يقوم بحفظ لقطة شاشة `debug/screenshot.png` ومصدر الصفحة `debug/page.html` وملف السجل `debug/extraction.log`.

### 3. إظهار نافذة المتصفح (لتسجيل الدخول اليدوي أو حل CAPTCHA):
إذا كانت المجموعة خاصة أو طلب Google تسجيل الدخول يدويًا:
```powershell
python main.py --no-headless
```
سيفتح المتصفح بنافذة مرئية تتيح لك تسجيل الدخول ثم يواصل البرنامج الاستخراج تلقائيًا.

### 4. تخصيص مدة التمرير والمهلة:
```powershell
python main.py --max-scrolls 150 --scroll-delay 2.0
```

---

## هيكل المشروع (Project Structure)

```
google_collection_extractor/
│
├── main.py              # نقطة البداية، معالجة معاملات CLI والطباعة في سطر الأوامر
├── extractor.py         # محرك Playwright، التمرير اللانهائي، ونظام الاستخراج
├── cleaner.py           # تنظيف العناوين، إزالة التكرار، والتحقق من الأنواع
├── config.py            # إعدادات النظام، الثوابت، والمسارات
├── requirements.txt     # مكتبات بايثون المطلوبة
├── README.md            # دليل الاستخدام والتوثيق
│
├── output/              # مجلد المخرجات
│   ├── movies_and_series.txt    # ملف TXT يحتوي على كل عنوان في سطر مستقل
│   └── movies_and_series.json   # ملف JSON يحتوي على العناوين والروابط
│
└── debug/               # ملفات التشخيص عند حدوث خطأ أو تفعيل --debug
    ├── screenshot.png
    ├── page.html
    └── extraction.log
```

---

## صيغة المخرجات (Output Format)

### ملف `output/movies_and_series.txt`:
```txt
The Mentalist
Fallout
Marrowbone
Jeepers Creepers
The Constant Gardener
Lawless
World War II with Tom Hanks
Widow's Bay
The Secret Life of Walter Mitty
From Beijing with Love
Mindhunters
Devil
Force Majeure
Freaky Friday
Jerry & Marge Go Large
RocknRolla
D-Day
WarGames
12 Monkeys
Rise of the Guardians
```

### ملف `output/movies_and_series.json`:
```json
[
  {
    "title": "The Mentalist",
    "url": "https://www.google.com/search?q=The+Mentalist...",
    "type": "tv"
  },
  {
    "title": "Fallout",
    "url": "https://www.google.com/search?q=Fallout...",
    "type": "tv"
  }
]
```

---

## حل المشاكل الشائعة (Troubleshooting)

| المشكلة | السبب | الحل المقترح |
|---|---|---|
| `Chromium browser is not installed` | لم يتم تحميل متصفح Playwright | نفذ الأمر: `playwright install chromium` |
| `Google is requesting account sign-in` | القائمة خاصة أو تتطلب حسابًا | شغل البرنامج مع خيار: `python main.py --no-headless` وسجل دخولك في النافذة |
| `Google returned HTTP status 404` | رابط القائمة غير صحيح أو تم حذفه | تأكد من صحة الرابط وأن خيار المشاركة مفعّل |
| `UnicodeEncodeError` في Terminal القديم | ترميز سطر الأوامر ليس UTF-8 | يقوم البرنامج تلقائيًا بضبط UTF-8، أو نفذ `chcp 65001` في موجه أوامر Windows |
