"""
تنظیمات پروژه‌ی جنگو برای «سدا» (خانه کارگر).

نکته برای توسعه: این فایل عمداً ساده و کامنت‌گذاری‌شده نوشته شده چون
پروژه بک‌اند جنگو ندارید و این اولین بار است که این تنظیمات نوشته می‌شود.
"""

from pathlib import Path
import os

# مسیر ریشه‌ی پروژه (همان پوشه‌ای که manage.py در آن است)
BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# امنیت
# ---------------------------------------------------------------------------
# TODO: قبل از انتقال به سرور واقعی (production)، این مقدار را با یک رشته‌ی
# تصادفی و محرمانه عوض کنید و آن را در کد قرار ندهید (از متغیر محیطی بخوانید).
SECRET_KEY = os.environ.get(
    'DJANGO_SECRET_KEY',
    'django-insecure-dev-only-change-this-in-production-!!!'
)

# TODO: در سرور واقعی این را False کنید.
DEBUG = os.environ.get('DJANGO_DEBUG', 'True') == 'True'

ALLOWED_HOSTS = ['*']  # TODO: در production فقط دامنه‌ی واقعی سایت را بگذارید

# ---------------------------------------------------------------------------
# اپ‌های نصب‌شده
# ---------------------------------------------------------------------------
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # کتابخانه‌های شخص ثالث
    'rest_framework',
    'corsheaders',

    # اپ‌های خودمان
    'core',               # نیروی انسانی (مدرسین/مسئولین) - از قبل وجود داشت
    'members',            # اعضا و احراز هویت (فاز ۱)
    'academic_calendar',  # تقویم آموزشی و ترم‌ها (فاز ۲)
    'class_management',   # دپارتمان‌ها، کلاس‌ها و ثبت‌نام (فاز ۳)
    'feedback',           # انتقادات و پیشنهادات (ثبت از سایت، پاسخ از پنل)
    'finance',            # امور مالی: پرداخت به مدرسین
    'logs',               # لاگ سامانه (رویدادها، ورود ناموفق، قفل موقت)
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'corsheaders.middleware.CorsMiddleware',  # باید قبل از CommonMiddleware باشد
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'core.middleware.OfficerSectionAccessMiddleware',  # بخش‌هایی که مدیر برای مسئول آموزش بسته است (بعد از احراز هویت)
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'sada_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'sada_project.wsgi.application'

# ---------------------------------------------------------------------------
# پایگاه‌داده - همان db.sqlite3 قدیمی، دیتای موجود حفظ می‌شود
# ---------------------------------------------------------------------------
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

# سیستم لاگین سفارشی: امکان ورود با «کد ملی» یا «کد عضویت» (نه فقط username)
AUTHENTICATION_BACKENDS = [
    'members.auth_backends.MemberAuthBackend',
    'django.contrib.auth.backends.ModelBackend',  # برای پنل ادمین جنگو (/django-admin/)
]

LANGUAGE_CODE = 'fa-ir'
TIME_ZONE = 'Asia/Tehran'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'

# فایل‌های آپلودی کاربران (عکس و رزومه‌ی متقاضیان مدرسی و مانند آن)
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ---------------------------------------------------------------------------
# Django REST Framework
# ---------------------------------------------------------------------------
REST_FRAMEWORK = {
    # فعلاً بر پایه‌ی session کار می‌کنیم (همان کوکی که بعد از لاگین ساخته می‌شود)
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.AllowAny',
    ],
}

# ---------------------------------------------------------------------------
# CORS - چون فایل‌های HTML فرانت‌اند (سدا، پنل ادمین) ممکن است از یک آدرس/پورت
# جدا باز شوند، فعلاً برای راحتی توسعه به همه اجازه می‌دهیم.
# TODO: در production این را محدود به دامنه‌ی واقعی سایت کنید.
# ---------------------------------------------------------------------------
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True

# نشست (Session) و کوکی‌ها روی http ساده هم کار کنند (برای تست لوکال)
SESSION_COOKIE_SAMESITE = 'Lax'
CSRF_COOKIE_SAMESITE = 'Lax'


# ---------------------------------------------------------------------------
# سخت‌گیری امنیتی برای سرور واقعی (production)
# ---------------------------------------------------------------------------
# این بخش «فقط» وقتی فعال می‌شود که DJANGO_DEBUG=False تنظیم شده باشد؛ در حالت توسعه
# (پیش‌فرض) هیچ رفتاری عوض نمی‌شود. متغیرهای محیطی موردنیاز در سرور واقعی:
#   DJANGO_DEBUG=False
#   DJANGO_SECRET_KEY=<یک رشته‌ی تصادفیِ بلند و محرمانه>
#   DJANGO_ALLOWED_HOSTS=example.ir,www.example.ir          (دامنه‌ها، با ویرگول)
#   DJANGO_CORS_ORIGINS=https://example.ir                   (آدرس کاملِ سایت؛ اگر فرانت‌اند هم‌دامنه
#                                                             است می‌تواند خالی بماند)
#   DJANGO_HTTPS=True                                        (فقط اگر سایت با https سرو می‌شود)
if not DEBUG:
    from django.core.exceptions import ImproperlyConfigured

    # ۱) کلید محرمانه نباید همان کلید آزمایشیِ داخل کد باشد (با آن می‌شود نشست جعل کرد)
    if SECRET_KEY.startswith('django-insecure'):
        raise ImproperlyConfigured('در حالت production باید DJANGO_SECRET_KEY با یک مقدار تصادفی تنظیم شود.')

    # ۲) فقط دامنه‌های مشخص (نه '*') - جلوی حمله‌ی Host header را می‌گیرد
    ALLOWED_HOSTS = [h.strip() for h in os.environ.get('DJANGO_ALLOWED_HOSTS', '').split(',') if h.strip()]
    if not ALLOWED_HOSTS:
        raise ImproperlyConfigured('در حالت production باید DJANGO_ALLOWED_HOSTS (دامنه‌ی سایت) تنظیم شود.')

    # ۳) CORS: فقط آدرس‌های مجاز، نه همه (همراه با کوکی نشست خطرناک است)
    _origins = [o.strip() for o in os.environ.get('DJANGO_CORS_ORIGINS', '').split(',') if o.strip()]
    CORS_ALLOW_ALL_ORIGINS = False
    CORS_ALLOWED_ORIGINS = _origins
    CSRF_TRUSTED_ORIGINS = _origins

    # ۴) کوکی‌ها فقط روی https (اگر سایت با https سرو می‌شود)
    if os.environ.get('DJANGO_HTTPS', 'False') == 'True':
        SESSION_COOKIE_SECURE = True
        CSRF_COOKIE_SECURE = True
        SECURE_HSTS_SECONDS = 60 * 60 * 24 * 30      # یک ماه؛ بعد از اطمینان می‌شود بیشتر کرد
        SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = 'DENY'
