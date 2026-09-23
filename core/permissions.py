"""
دسترسی‌های مشترک بین اپ‌ها: «مدیر آموزش» و «مسئول آموزش».

قبلاً این تعریف فقط داخل اپ feedback بود؛ چون اپ members (ویرایش اطلاعات اعضا) هم
همین قاعده را لازم دارد، اینجا یک‌جا نگه داشته می‌شود تا هیچ‌وقت دو جا با هم فرق نکنند.
"""

from rest_framework import permissions

ROLE_MANAGER = 'مدیر آموزش'
ROLE_OFFICER = 'مسئول آموزش'
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


class IsEducationStaff(permissions.BasePermission):
    """
    فقط کاربر واردشده‌ای که سمتش «مدیر آموزش» یا «مسئول آموزش» است.

    نکته: عمداً از is_staff استفاده نمی‌کنیم، چون در این پروژه برای حساب
    مدیر/مسئول آموزش هیچ‌جا is_staff=True نمی‌شود (سمت در Employee.role است).
    """

    def has_permission(self, request, view):
        return staff_role(request.user) is not None
