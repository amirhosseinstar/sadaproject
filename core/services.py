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


def ensure_username_available(username: str, exclude_user_pk=None) -> None:
    """
    مطمئن می‌شود «نام کاربری» قابل استفاده است، وگرنه ApprovalError می‌دهد.

    سه حالت برای حسابی که این نام کاربری را دارد:
      ۱) حساب مدیر سیستم (superuser/staff، مثل «admin» که با createsuperuser ساخته
         می‌شود): همیشه رد می‌شود، با پیامی که دلیل را می‌گوید.
      ۲) حساب واقعی (مدرس/متصدی یا دانش‌پژوه): رد می‌شود.
      ۳) حساب «یتیم» - نه Employee دارد نه Member (مثلاً از مدرسی که قبل از رفع
         باگ حذف شده و حسابش جا مانده): هیچ‌کس نمی‌تواند با آن وارد شود و فقط
         نام کاربری را قفل کرده؛ پس حذف می‌شود و نام آزاد می‌شود.
    """
    qs = User.objects.filter(username=username)
    if exclude_user_pk is not None:
        qs = qs.exclude(pk=exclude_user_pk)
    user = qs.first()
    if user is None:
        return
    if user.is_superuser or user.is_staff:
        raise ApprovalError(f'نام کاربری «{username}» متعلق به حساب مدیر سیستم است؛ نام کاربری دیگری وارد کنید.')
    # hasattr روی رابطه‌ی یک‌به‌یکِ معکوس: اگر Employee/Member نداشته باشد False می‌شود
    if hasattr(user, 'employee') or hasattr(user, 'member'):
        raise ApprovalError(f'نام کاربری «{username}» قبلاً استفاده شده؛ نام کاربری دیگری وارد کنید.')
    user.delete()


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
    ensure_username_available(username)

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
