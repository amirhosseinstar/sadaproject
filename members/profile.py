"""
کامل بودن اطلاعات یک عضو (دانش‌پژوه).

هم ثبت‌نام در کلاس‌های دارای رده سنی (class_management) و هم پنل ادمین (نشان
«اطلاعات ناقص» کنار نام عضو) از همین یک تابع استفاده می‌کنند تا تعریف «ناقص» همه‌جا یکی باشد.
"""

from sada_project.utils import parse_jalali_date

# پیامی که اگر اطلاعات عضو ناقص باشد به او نشان داده می‌شود (متن مورد نظر پروژه)
INCOMPLETE_INFO_MESSAGE = 'اطلاعات شما ناقص است؛ لطفاً برای رفع این مشکل با شعبه‌ی مربوطه تماس حاصل فرمایید.'


def member_missing_fields(member):
    """
    فهرست اطلاعات ناقص عضو (به فارسی)؛ لیست خالی یعنی اطلاعات کامل است.

    این موارد لازم‌اند: نام، نام خانوادگی، نام پدر، تاریخ تولد، کد ملی، کد عضویت، شماره
    موبایل، استان و شعبه. تاریخ تولدی که «نامعتبر» باشد (مثلاً متن خراب یا تاریخ آینده) هم
    ناقص حساب می‌شود، چون سن از روی آن محاسبه می‌شود. (تاریخ انقضای کارت عضویت جزو این‌ها
    نیست؛ خالی بودنش یعنی «بدون تاریخ انقضا».)
    """
    user = member.user
    required = [
        ('نام', user.first_name),
        ('نام خانوادگی', user.last_name),
        ('نام پدر', member.father_name),
        ('تاریخ تولد', member.birth_date),
        ('کد ملی', member.national_id),
        ('کد عضویت', member.membership_code),
        ('شماره موبایل', member.phone),
        ('استان', member.province),
        ('شعبه', member.branch),
    ]
    missing = [label for label, value in required if not (value or '').strip()]
    if member.birth_date and member.birth_date.strip() and parse_jalali_date(member.birth_date) is None:
        missing.append('تاریخ تولد (نامعتبر)')
    return missing
