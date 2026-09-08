"""
منطق کسب‌وکار مشترک اپ core - جدا از views.py تا هم API (core/views.py) و هم
پنل ادمین جنگو (members/admin.py) بتوانند دقیقاً همین یک تابع را صدا بزنند و
هیچ‌وقت این دو جا با هم فرق نکنند.
"""

from django.contrib.auth import get_user_model

from .models import Employee, TeacherApplicant

User = get_user_model()


class ApprovalError(Exception):
    """وقتی تأیید درخواست به هر دلیلی ممکن نیست (مثلاً نام کاربری تکراری)."""


def approve_teacher_applicant(applicant: TeacherApplicant, username: str, password: str) -> Employee:
    """
    یک درخواست همکاری را تأیید می‌کند: یک Employee واقعی (role='مدرس')
    و یک حساب ورود (User) با نام‌کاربری/رمزی که همین لحظه از ادمین/مسئول
    آموزش گرفته شده می‌سازد، سپس وضعیت درخواست را «تأییدشده» می‌کند.

    نام‌کاربری/رمز دیگر بخشی از فرم ثبت‌نام متقاضی نیستند - طبق تصمیم
    پروژه، این‌ها همیشه همین لحظه‌ی تأیید از ادمین پرسیده می‌شوند (چه در
    پنل سفارشی HTML چه در پنل جنگو)، برای همین اینجا اختیاری نیستند.

    این تنها راهی است که باید یک Employee جدید ساخته شود؛ هم API
    (core/views.py) و هم پنل ادمین جنگو (members/admin.py) باید همین تابع
    را صدا بزنند، نه این‌که منطق را جای دیگری دوباره بنویسند.
    """
    if applicant.status == TeacherApplicant.STATUS_APPROVED:
        raise ApprovalError('این درخواست قبلاً تأیید شده است.')

    username = (username or '').strip()
    if not username:
        raise ApprovalError('برای تأیید، نام کاربری لازم است.')
    if not password:
        raise ApprovalError('برای تأیید، رمز عبور لازم است.')
    if User.objects.filter(username=username).exists():
        raise ApprovalError(f'نام کاربری «{username}» قبلاً استفاده شده؛ نام کاربری دیگری وارد کنید.')

    user = User.objects.create_user(
        username=username,
        password=password,
        first_name=applicant.first_name,
        last_name=applicant.last_name,
    )

    employee = Employee.objects.create(
        user=user,
        name=f'{applicant.first_name} {applicant.last_name}'.strip(),
        role='مدرس',
        depts=applicant.depts or [],
        branch=applicant.branch,
        phone=applicant.phone,
        national_id=applicant.national_id,
        father_name=applicant.father_name,
        birth_date=applicant.birth_date,
        education_level=applicant.education_level,
        address=applicant.address,
        photo=applicant.photo if applicant.photo else None,
        resume=applicant.resume if applicant.resume else None,
    )

    applicant.status = TeacherApplicant.STATUS_APPROVED
    applicant.save(update_fields=['status'])

    return employee
