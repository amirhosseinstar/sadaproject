"""
تنظیمات «قفل موقت ورود». مقدارها را می‌شود در settings.py با همین نام‌ها عوض کرد:

  LOGIN_MAX_FAILURES            حداکثر تلاش ناموفق پشت‌سرهم قبل از مسدودی        (پیش‌فرض ۵)
  LOGIN_FAILURE_WINDOW_MINUTES  تلاش‌ها در چند دقیقه شمرده می‌شوند              (پیش‌فرض ۱۵)
  LOGIN_LOCKOUT_MINUTES         مدت مسدودی حساب                                 (پیش‌فرض ۱۰)
  LOGIN_WARN_AFTER              از چندمین تلاش ناموفق، «تلاش باقی‌مانده» هشدار داده شود (پیش‌فرض ۳)
  OTP_MAX_REQUESTS              حداکثر «درخواست کد پیامکی» برای هر حساب در بازه    (پیش‌فرض ۳)
  OTP_REQUEST_WINDOW_MINUTES    بازه‌ی شمارش درخواست کد پیامکی                    (پیش‌فرض ۱۰)
  OTP_REQUEST_BLOCK_MINUTES     مدت محدودیت بعد از رسیدن به سقف                    (پیش‌فرض ۱۰)
  LOGS_TRUST_PROXY_HEADER       اگر سرور پشت پراکسی (nginx) است و IP واقعی در X-Forwarded-For می‌آید
                                True کنید تا IP درست ثبت شود (پیش‌فرض False)
"""

from django.conf import settings


def _get(name, default):
    return getattr(settings, name, default)


def max_failures():
    return int(_get('LOGIN_MAX_FAILURES', 5))


def window_minutes():
    return int(_get('LOGIN_FAILURE_WINDOW_MINUTES', 15))


def lockout_minutes():
    return int(_get('LOGIN_LOCKOUT_MINUTES', 10))


def warn_after():
    return int(_get('LOGIN_WARN_AFTER', 3))


def trust_proxy_header():
    return bool(_get('LOGS_TRUST_PROXY_HEADER', False))


def otp_max_requests():
    return int(_get('OTP_MAX_REQUESTS', 3))


def otp_window_minutes():
    return int(_get('OTP_REQUEST_WINDOW_MINUTES', 10))


def otp_block_minutes():
    return int(_get('OTP_REQUEST_BLOCK_MINUTES', 10))
