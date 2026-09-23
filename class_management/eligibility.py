"""
شرایط ثبت‌نام یک عضو در یک کلاس که به «اطلاعات خود عضو» بستگی دارد (رده سنی).

ClassViewSet.enroll این تابع را صدا می‌زند؛ چون هم سایت اصلی و هم پنل مدیر/مسئول آموزش
از همان endpoint ثبت‌نام می‌کنند، این چک دور زده نمی‌شود.
"""

from members.profile import INCOMPLETE_INFO_MESSAGE, member_missing_fields
from sada_project.utils import jalali_age, parse_jalali_date, to_persian_digits


def check_age_eligibility(member, cls):
    """
    اگر کلاس رده سنی نداشته باشد None برمی‌گرداند (هیچ چکی لازم نیست). وگرنه:

      ۱) اگر اطلاعات عضو (هر کدام) ناقص است -> پیام «اطلاعات شما ناقص است…»
      ۲) اگر سن او (از روی تاریخ تولد شمسی، تا امروز) کمتر از حداقل یا بیشتر از
         حداکثر رده سنی کلاس باشد -> پیام «سن شما خارج از رده سنی این کلاس است»

    برمی‌گرداند: None (مجاز است) یا dict آماده‌ی پاسخ خطای ۴۰۰ (شامل کلید detail).
    """
    if not cls.age_limit_enabled or cls.min_age is None or cls.max_age is None:
        return None

    missing = member_missing_fields(member)
    if missing:
        return {'detail': INCOMPLETE_INFO_MESSAGE, 'incomplete_info': True, 'missing_fields': missing}

    age = jalali_age(parse_jalali_date(member.birth_date))
    if age < cls.min_age or age > cls.max_age:
        return {
            'detail': (
                f'سن شما ({to_persian_digits(age, pad=0)} سال) خارج از رده سنی این کلاس '
                f'({to_persian_digits(cls.min_age, pad=0)} تا {to_persian_digits(cls.max_age, pad=0)} سال) است.'
            ),
            'age_not_allowed': True,
            'member_age': age,
            'min_age': cls.min_age,
            'max_age': cls.max_age,
        }
    return None
