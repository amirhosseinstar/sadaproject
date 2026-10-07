"""
دسترسی‌های مشترک بین اپ‌ها: «مدیر آموزش»، «مسئول آموزش» و «مدرس».

قبلاً این تعریف فقط داخل اپ feedback بود؛ چون اپ members (ویرایش اطلاعات اعضا) هم
همین قاعده را لازم دارد، اینجا یک‌جا نگه داشته می‌شود تا هیچ‌وقت دو جا با هم فرق نکنند.

قاعده‌ی کلی امنیت پروژه:
  - هر مسیرِ «نوشتن» (POST/PUT/PATCH/DELETE) فقط برای کاربر واردشده با سمت مناسب باز است؛
    تنها استثناها: فرم عمومی درخواست همکاری مدرس، و ثبت‌نام/تأیید هویت دانش‌پژوه (که خودشان
    کد ملی + کد عضویت می‌خواهند و تلاش ناموفقشان محدود می‌شود).
  - هر مسیرِ «خواندن» که اطلاعات شخصی دارد (کد ملی، تلفن، نمره، کد عضویت) فقط برای
    کارکنان یا خودِ صاحب اطلاعات است.
"""

from rest_framework import permissions

ROLE_MANAGER = 'مدیر آموزش'
ROLE_OFFICER = 'مسئول آموزش'
ROLE_TEACHER = 'مدرس'
STAFF_ROLES = (ROLE_MANAGER, ROLE_OFFICER)


def staff_role(user):
    """
    سمت مدیریتی کاربر: «مدیر آموزش»، «مسئول آموزش»، یا None (هیچ‌کدام).
    ابرکاربر جنگو مثل مدیر آموزش حساب می‌شود.
    """
    if not (user and user.is_authenticated):
        return None
    if user.is_superuser:
        return ROLE_MANAGER
    # اگر کاربر Employee نداشته باشد، getattr مقدار None برمی‌گرداند
    employee = getattr(user, 'employee', None)
    if employee is not None and employee.role in STAFF_ROLES:
        return employee.role
    return None


def teacher_employee(user):
    """نیروی انسانیِ «مدرس» متصل به این کاربرِ واردشده، یا None اگر مدرس نیست."""
    if not (user and user.is_authenticated):
        return None
    employee = getattr(user, 'employee', None)
    if employee is not None and employee.role == ROLE_TEACHER:
        return employee
    return None


def member_of(user):
    """دانش‌پژوه (Member) متصل به این کاربرِ واردشده، یا None."""
    if not (user and user.is_authenticated):
        return None
    return getattr(user, 'member', None)


# ---------------------------------------------------------------------------
# محدودکردن «مسئول آموزش» به شعبه‌ی خودش
# ---------------------------------------------------------------------------

def _norm_branch(name):
    """نام شعبه را برای مقایسه یکدست می‌کند (ی/ک عربی، نیم‌فاصله، فاصله‌ی اضافه)."""
    from feedback.branches import _normalize
    return _normalize(name)


def officer_branch_name(user):
    """
    نام استانداردِ شعبه‌ی مسئول آموزش (مثل جدول Branch)؛ برای غیرمسئول None.
    اگر شعبه‌ی مسئول در جدول نباشد، خودِ متن (بدون فاصله‌ی اضافه) برگردانده می‌شود.
    """
    if staff_role(user) != ROLE_OFFICER:
        return None
    from feedback.branches import canonical_branch_name
    raw = (user.employee.branch or '').strip()
    return canonical_branch_name(raw) or raw


def same_branch(a, b):
    """آیا دو نام شعبه (با تفاوت‌های نگارشی) یکی هستند؟ نام خالی هرگز برابر نیست."""
    na, nb = _norm_branch(a), _norm_branch(b)
    return bool(na) and na == nb


def scope_to_officer_branch(queryset, user, field='branch'):
    """
    اگر کاربر «مسئول آموزش» است، فقط رکوردهای شعبه‌ی خودش را نگه می‌دارد (مدیر: بدون محدودیت).
    اگر شعبه‌ی مسئول ثبت نشده باشد هیچ رکوردی نمی‌بیند.
    مقایسه در پایتون و با نامِ یکدست‌شده انجام می‌شود تا تفاوت «ي/ی» یا فاصله، دسترسی را نشکند.
    """
    own = officer_branch_name(user)
    if own is None:
        return queryset
    if not own:
        return queryset.none()
    ids = [pk for pk, value in queryset.values_list('pk', field) if same_branch(value, own)]
    return queryset.filter(pk__in=ids)


def branch_values(model, branch_name, field='branch'):
    """
    مقادیر متمایزِ یک فیلد شعبه در این مدل که (با اختلاف‌های نگارشی) همان شعبه‌ی branch_name هستند.
    برای ساختنِ فیلتر کارآمد در پایگاه‌داده: queryset.filter(branch__in=branch_values(...)) - بدون پیمایشِ همه‌ی رکوردها.
    """
    values = model._default_manager.order_by().values_list(field, flat=True).distinct()
    return [v for v in values if same_branch(v, branch_name)]


# ---------------------------------------------------------------------------
# کلاس‌های دسترسی
# ---------------------------------------------------------------------------

class IsEducationStaff(permissions.BasePermission):
    """
    فقط کاربر واردشده‌ای که سمتش «مدیر آموزش» یا «مسئول آموزش» است.

    نکته: عمداً از is_staff استفاده نمی‌کنیم، چون در این پروژه برای حساب
    مدیر/مسئول آموزش هیچ‌جا is_staff=True نمی‌شود (سمت در Employee.role است).
    """

    def has_permission(self, request, view):
        return staff_role(request.user) is not None


class IsEducationManager(permissions.BasePermission):
    """فقط «مدیر آموزش» (ابرکاربر جنگو هم مدیر حساب می‌شود)؛ مسئول آموزش نه."""

    def has_permission(self, request, view):
        return staff_role(request.user) == ROLE_MANAGER


class ReadOnlyOrEducationStaff(permissions.BasePermission):
    """خواندن برای همه (صفحه‌های عمومی سایت)؛ نوشتن فقط مدیر یا مسئول آموزش."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return staff_role(request.user) is not None


class ReadOnlyOrEducationManager(permissions.BasePermission):
    """خواندن برای همه؛ نوشتن فقط «مدیر آموزش»."""

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return True
        return staff_role(request.user) == ROLE_MANAGER
