"""
توابع کمکی مشترک بین اپ‌های مختلف پروژه.
"""

import datetime

PERSIAN_DIGITS = '۰۱۲۳۴۵۶۷۸۹'


def to_persian_digits(number, pad=2):
    """
    عدد را به رقم‌های فارسی تبدیل می‌کند (همان کاری که تابع toPersianDigits
    در فرانت‌اند sada.html/sada-admin.html انجام می‌دهد)، مثلاً:
    to_persian_digits(1) -> '۰۱'
    """
    s = str(number).rjust(pad, '0')
    return ''.join(PERSIAN_DIGITS[int(ch)] for ch in s)


def gregorian_to_jalali(gy, gm, gd):
    """
    تبدیل یک تاریخ میلادی به شمسی - دقیقاً همان الگوریتمی که در فرانت‌اند
    (تابع gregorianToJalali در sada-admin.html و صفحات اصلی سایت) استفاده
    می‌شود، اینجا هم به پایتون منتقل شده تا بک‌اند هم بتواند مستقل و بدون
    وابستگی به فرانت، «امروز» را به شمسی تشخیص دهد.
    """
    g_d_m = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334]
    jy = 0 if gy <= 1600 else 979
    gy -= 621 if gy <= 1600 else 1600
    gy2 = gy + 1 if gm > 2 else gy
    days = (365 * gy) + ((gy2 + 3) // 4) - ((gy2 + 99) // 100) + ((gy2 + 399) // 400) - 80 + gd + g_d_m[gm - 1]
    jy += 33 * (days // 12053)
    days %= 12053
    jy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        jy += (days - 1) // 365
        days = (days - 1) % 365
    jm = 1 + (days // 31) if days < 186 else 7 + ((days - 186) // 30)
    jd = 1 + (days % 31) if days < 186 else 1 + ((days - 186) % 30)
    return jy, jm, jd


def today_jalali():
    """تاریخ امروز (بر اساس ساعت سرور) به شمسی، به‌صورت (سال, ماه, روز)."""
    now = datetime.date.today()
    return gregorian_to_jalali(now.year, now.month, now.day)


# رقم‌های فارسی (۰-۹) و عربی (٠-٩) -> انگلیسی
_DIGIT_MAP = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def to_english_digits(text):
    """همه‌ی رقم‌های فارسی/عربی یک متن را به انگلیسی تبدیل می‌کند."""
    return str(text or '').translate(_DIGIT_MAP)


def parse_jalali_date(text, allow_future=False):
    """
    یک تاریخ شمسی متنی مثل «۱۳۷۰/۰۵/۱۲» یا «1370-5-12» را به (سال, ماه, روز) تبدیل
    می‌کند؛ اگر متن خالی یا نامعتبر باشد None برمی‌گرداند.

    قواعد: رقم فارسی/عربی/انگلیسی، جداکننده‌ی / یا - یا . ؛ سال چهاررقمی بین ۱۲۰۰ تا
    سال جاری (تاریخ آینده معتبر نیست)؛ ماه ۱ تا ۱۲؛ روز ۱ تا ۳۱ برای شش ماه اول و ۱ تا
    ۳۰ برای شش ماه دوم. (روزِ ۳۰ اسفند عمداً بدون بررسی کبیسه پذیرفته می‌شود تا یک
    تاریخ تولد واقعی به‌خاطر تقریبِ الگوریتم کبیسه اشتباهاً رد نشود.)
    """
    import re

    cleaned = to_english_digits(text).strip().replace('\u200f', '').replace('\u200e', '')
    match = re.fullmatch(r'(\d{4})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{1,2})', cleaned)
    if not match:
        return None
    year, month, day = (int(g) for g in match.groups())
    if not 1 <= month <= 12:
        return None
    if not 1 <= day <= (31 if month <= 6 else 30):
        return None
    today = today_jalali()
    # تاریخ آینده به‌طور پیش‌فرض نامعتبر است (مثلاً تاریخ تولد)؛ برای فیلتر بازه‌ی تاریخ می‌شود allow_future=True داد
    if year < 1200 or (not allow_future and (year, month, day) > today):
        return None
    return year, month, day


def jalali_age(birth, today=None):
    """
    سنِ کامل (به سال) کسی که در تاریخ شمسی birth=(سال, ماه, روز) به دنیا آمده، در
    تاریخ today (پیش‌فرض: امروز). اگر تولد هنوز «امسال» نرسیده باشد، یک سال کمتر است.
    """
    today = today or today_jalali()
    age = today[0] - birth[0]
    if (today[1], today[2]) < (birth[1], birth[2]):
        age -= 1
    return age


def jalali_to_gregorian(jy, jm, jd):
    """تاریخ شمسی (سال، ماه، روز) را به میلادی (سال، ماه، روز) تبدیل می‌کند (معکوس gregorian_to_jalali)."""
    jy += 1595
    days = -355668 + (365 * jy) + ((jy // 33) * 8) + (((jy % 33) + 3) // 4) + jd
    days += ((jm - 1) * 31) if jm < 7 else (((jm - 7) * 30) + 186)
    gy = 400 * (days // 146097)
    days %= 146097
    if days > 36524:
        days -= 1
        gy += 100 * (days // 36524)
        days %= 36524
        if days >= 365:
            days += 1
    gy += 4 * (days // 1461)
    days %= 1461
    if days > 365:
        gy += (days - 1) // 365
        days = (days - 1) % 365
    gd = days + 1
    leap = (gy % 4 == 0 and gy % 100 != 0) or (gy % 400 == 0)
    month_lengths = [0, 31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    gm = 0
    while gm < 13 and gd > month_lengths[gm]:
        gd -= month_lengths[gm]
        gm += 1
    return gy, gm, gd
