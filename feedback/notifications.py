"""
اطلاع‌رسانی پاسخ انتقاد/پیشنهاد به فرستنده از طریق پیامک.

فعلاً سرویس پیامک واقعی وصل نیست: members.sms.send_sms فقط پیامک را در لاگ
سرور چاپ می‌کند. وقتی API سرویس پیامک آماده شد، فقط بدنه‌ی همان یک تابع
(members/sms.py::send_sms) عوض شود - این فایل و بقیه‌ی کد هیچ تغییری لازم ندارند.
"""

import logging

from members.sms import send_sms

logger = logging.getLogger('sms')


def build_reply_sms_text(item):
    """متن پیامکی که برای فرستنده‌ی انتقاد/پیشنهاد ارسال می‌شود."""
    return (
        f'سامانه سدا - خانه کارگر\n'
        f'پاسخ {item.get_kind_display()} شما:\n'
        f'{item.reply_text}\n'
        f'{item.replier_name}'
    )


def send_reply_sms(item):
    """
    پاسخ ثبت‌شده را به شماره‌ی فرستنده پیامک می‌کند. شماره‌ای که خودِ فرستنده
    در فرم وارد کرده اولویت دارد؛ اگر خالی بود، شماره‌ی ثبت‌شده‌ی عضویتش.

    این تابع هیچ‌وقت خطا بالا نمی‌دهد: خرابی سرویس پیامک نباید باعث شود
    «ثبت پاسخ» در پنل شکست بخورد (پاسخ در هر حال ذخیره شده است).
    برمی‌گرداند: True اگر تابع ارسال، موفقیت گزارش کرده باشد.
    """
    phone = item.phone or (item.member.phone if item.member else '') or ''
    if not phone:
        logger.info('پیامک پاسخ برای مورد %s ارسال نشد: شماره‌ای وجود ندارد.', item.pk)
        return False
    try:
        return bool(send_sms(phone, build_reply_sms_text(item)))
    except Exception:
        logger.exception('ارسال پیامک پاسخ برای مورد %s با خطا مواجه شد.', item.pk)
        return False
