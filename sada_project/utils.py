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
