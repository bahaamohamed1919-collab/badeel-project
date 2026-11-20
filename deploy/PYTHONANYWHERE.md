# رفع Badeel على PythonAnywhere

الموقع هيبقى على لينك زي `https://اسمك.pythonanywhere.com`، بالداتا المصرية الكاملة
(22,757 دوا، والتداخلات، والأمراض، والنشرات)، وموديل البحث متدرب وجاهز.

الوقت: حوالي 20 دقيقة. **مش محتاج تسطّبي أي حاجة على جهازك**، كله من المتصفح.

---

## 1. اعملي حساب (مرة واحدة)

1. افتحي https://www.pythonanywhere.com/registration/register/beginner/
2. **اختاري الـ username بعناية**، لأنه هيبقى اسم اللينك. مثلاً `badeel` يبقى `badeel.pythonanywhere.com`.
3. أكدي الإيميل.

## 2. افتحي شاشة الأوامر

من فوق: **Consoles**، وبعدين تحت **Start a new console** اختاري **Bash**.
هتفتح شاشة سودا. انسخي الأوامر اللي جاية واحد واحد، والصقيها فيها، ودوسي Enter بعد كل واحد.

## 3. نزّلي المشروع وجهزيه

```bash
git clone https://github.com/youssefali62011-arch/badeel-project.git
```
```bash
cd badeel-project
```
```bash
python3.12 -m venv --system-site-packages ~/.virtualenvs/badeel
```
```bash
source ~/.virtualenvs/badeel/bin/activate
```
```bash
pip install -r requirements.txt
```

> لو `python3.12` مش موجود، شوفي أحدث نسخة في **Web**، وبعدين **Add a new web app**، واستخدميها (زي `python3.13`). وخلّي نفس الرقم في الخطوة 4.
>
> `--system-site-packages` معناها إن الموقع هيستخدم مكتبات PythonAnywhere الجاهزة (زي scikit-learn)، فمش هيحمّلها تاني، ومش هيملا المساحة المجانية.

## 4. حمّلي الداتا

```bash
python manage.py import-csv data/egypt/egyptian-drugs.csv --replace
```
```bash
python manage.py import-enrichment dataset
```
```bash
python manage.py install-model deploy/search_model.json
```
```bash
python manage.py create-admin
```

آخر أمر هيسألك عن إيميل الأدمن واسمه وباسورد (15 حرف على الأقل، ومايكونش فيه اسمك ولا إيميلك).
**وانتي بتكتبي الباسورد مش هيظهر حاجة، ده طبيعي.**

## 5. اعملي الموقع

1. من فوق: **Web**، وبعدين **Add a new web app**، وبعدين **Next**.
2. اختاري **Manual configuration** (مش Flask).
3. اختاري **Python 3.12** (نفس الرقم اللي في الخطوة 3)، وبعدين **Next**.

في الصفحة اللي هتفتح، غيّري **USERNAME** في كل سطر لاسم حسابك:

| الخانة | اكتبي فيها |
|---|---|
| **Source code** | `/home/USERNAME/badeel-project` |
| **Virtualenv** | `/home/USERNAME/.virtualenvs/badeel` |

**ملف WSGI:** دوسي على اللينك اللي جنب **WSGI configuration file**، وامسحي كل اللي فيه،
والصقي محتوى الملف `deploy/pythonanywhere_wsgi.py`، وغيّري `YOUR_USERNAME` لاسم حسابك، ودوسي **Save**.

**الملفات الثابتة:** في نفس صفحة Web، تحت **Static files**:

| URL | Directory |
|---|---|
| `/static/` | `/home/USERNAME/badeel-project/badeel/static` |

**HTTPS:** تحت **Security**، خلّي **Force HTTPS** على **Enabled**.

وفي الآخر، دوسي الزرار الأخضر الكبير **Reload** فوق الصفحة.

## 6. افتحي الموقع

`https://USERNAME.pythonanywhere.com`

ادخلي بالإيميل والباسورد اللي عملتيهم في الخطوة 4، وهتلاقي نفسك في لوحة الأدمن.

---

## بعد كده

**عشان تجيبي أي تحديث من GitHub:** افتحي Bash، واكتبي الأوامر دي، وبعدين دوسي **Reload** في صفحة Web.
```bash
cd ~/badeel-project && git pull
```

**مهم: كل 3 شهور** هيوصلك إيميل من PythonAnywhere. ادخلي صفحة **Web** ودوسي
**Run until 3 months from today**، وإلا الموقع هيقف. ده شرط الخطة المجانية.

**حسابات تجريبية للعرض** (مريض وصيدلي):
```bash
python manage.py demo-users
```
الأمر هيطبع الإيميلات والباسوردات. **امسحوها بعد المناقشة**، لأن الموقع مفتوح لأي حد معاه اللينك.

## لو حاجة مااشتغلتش

في صفحة **Web**، افتحي **Error log** (آخر سطور فيه بتقول المشكلة)، وابعتيه لـ Claude.

## ليه الإعدادات دي

| الإعداد | السبب |
|---|---|
| `BADEEL_HTTPS=1` | الكوكيز ماتتبعتش غير على اتصال مشفر |
| `BADEEL_TRUST_PROXY=1` | PythonAnywhere بيحط سيرفر وسيط قدام الموقع. من غير الإعداد ده، كل الزوار هيبانوا بعنوان واحد، والقفل بعد المحاولات الغلط هيقفل على الكل |
| `BADEEL_PUBLIC_NOTICE=1` | شريط فوق كل صفحة بيقول إن دي نسخة تجريبية ومش نصيحة طبية |
| مفاتيح التشفير | بتتعمل لوحدها على السيرفر في فولدر `instance/`، ومابتطلعش منه، ومابتترفعش على GitHub |
