"""
پنل مدیریت جنگو - اپ core عمداً تقریباً هیچ مدلی را در پنل ادمین جنگو ثبت نمی‌کند: مدیریت «شعب»،
«مدرسین» و «مسئولان آموزش» به پنل اصلی (sada-admin.html، از طریق core.api) منتقل شده است.

تنها استثنا: حذف «مدیر آموزش».
طبق قاعده‌ی سامانه، مدیران آموزش نمی‌توانند یکدیگر را حذف کنند؛ حذف یک مدیر فقط با «برنامه‌نویس/ابرکاربر»
است. راهش همین‌جاست: /django-admin/ ← «نیروهای انسانی» (فقط مدیرانِ آموزش را نشان می‌دهد؛ فقط برای ابرکاربر دیده می‌شود، و فقط حذف دارد؛
افزودن و ویرایش از اینجا ممکن نیست). حذف یک مدیر، حساب ورودش را هم پاک می‌کند (تا نام‌کاربری برای
همیشه قفل نماند) و در لاگ ثبت می‌شود. آخرین مدیر آموزش قابل حذف نیست.
"""

from django.contrib import admin, messages

from core.models import Employee
from core.permissions import ROLE_MANAGER
from logs.recorder import record


class ManagerRemovalAdmin(admin.ModelAdmin):
    list_display = ('name', 'role', 'branch', 'phone')
    search_fields = ('name', 'phone')

    def get_queryset(self, request):
        return super().get_queryset(request).filter(role=ROLE_MANAGER)

    # فقط ابرکاربر؛ فقط مشاهده و حذف
    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def _remove_one(self, request, employee):
        """یک مدیر را (با حساب ورودش) حذف می‌کند؛ اگر آخرین مدیر باشد حذف نمی‌کند و False برمی‌گرداند."""
        remaining = Employee.objects.filter(role=ROLE_MANAGER, user__isnull=False).exclude(pk=employee.pk).count()
        if remaining < 1:
            self.message_user(request, f'«{employee.name}» آخرین مدیر آموزش است و حذف نمی‌شود.', level=messages.ERROR)
            return False
        user, name, branch = employee.user, employee.name, employee.branch
        employee.delete()
        if user is not None and not user.is_superuser and not user.is_staff:
            user.delete()
        record(
            request, 'staff', 'manager_delete_superuser', f'حذف مدیر آموزش «{name}» توسط ابرکاربر سیستم',
            target_type='مدیر آموزش', target_label=name, branch=branch,
        )
        return True

    def delete_model(self, request, obj):
        self._remove_one(request, obj)

    def delete_queryset(self, request, queryset):
        for employee in list(queryset):
            self._remove_one(request, employee)


admin.site.register(Employee, ManagerRemovalAdmin)
