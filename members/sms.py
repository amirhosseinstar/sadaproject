"""
لایه‌ی ارسال پیامک.

فعلاً به هیچ سرویس واقعی (کاوه‌نگار/ملی‌پیامک/فراپیامک/...) وصل نیست - فقط
پیامک را در لاگ سرور چاپ می‌کند تا در حالت توسعه بشود کد پیامک را دید و
جریان «فراموشی رمز عبور» و «ورود با رمز یکبارمصرف» را کامل تست کرد.

TODO (وقتی کلید API سرویس پیامک آماده شد):
    فقط کافی‌ست بدنه‌ی همین یک تابع (send_sms) عوض شود؛ هیچ‌جای دیگر کد
    (views.py و فرانت‌اند) لازم نیست تغییر کند، چون همه‌جا فقط همین تابع
    را صدا می‌زنند. مثال اتصال به کاوه‌نگار:

        import requests
        def send_sms(phone: str, message: str) -> bool:
            resp = requests.post(
                'https://api.kavenegar.com/v1/{API-KEY}/sms/send.json',
                data={'receptor': phone, 'message': message, 'sender': '...'},
            )
            return resp.ok
"""

import logging

logger = logging.getLogger('sms')


def send_sms(phone: str, message: str) -> bool:
    """
    ارسال یک پیامک به شماره‌ی «phone».

    فعلاً Placeholder است: چیزی واقعاً ارسال نمی‌شود، فقط در کنسول/لاگ سرور
    چاپ می‌شود (برای اینکه در حالت توسعه، کد پیامک قابل مشاهده باشد).
    همیشه True برمی‌گرداند (یعنی «موفق» فرض می‌شود) تا بقیه‌ی جریان برنامه
    (مثل فراموشی رمز عبور) بدون وقفه قابل تست باشد.
    """
    logger.warning('[SMS PLACEHOLDER - هنوز به سرویس واقعی وصل نیست] به %s: %s', phone, message)
    print(f'[SMS PLACEHOLDER] به {phone}: {message}')
    return True
