"""
لاگ (گزارش رویدادها) سامانه.

AuditLog: هر رویداد مهم (ورود/خروج، ویرایش اطلاعات، پرداخت و ...) یک رکورد «فقط‌اضافه‌شونده»
است؛ هیچ‌کس (حتی مدیر) نمی‌تواند از داخل برنامه آن را ویرایش یا حذف کند، و طبق تصمیم پروژه
برای همیشه نگه داشته می‌شود.

LoginThrottle: شمارنده‌ی تلاش‌های ناموفق ورود برای «قفل موقت» (کوچک و قابل‌پاک‌سازی، جدا از لاگ
همیشگی تا با حمله‌ی تلاش زیاد، لاگ بی‌نهایت بزرگ نشود).
"""

from django.conf import settings
from django.db import models


class AppendOnlyQuerySet(models.QuerySet):
    """مجموعه‌ی پرس‌وجویی که ویرایش و حذف گروهی را رد می‌کند."""

    def update(self, **kwargs):
        raise PermissionError('لاگ فقط اضافه می‌شود؛ ویرایش آن مجاز نیست.')

    def delete(self):
        raise PermissionError('لاگ فقط اضافه می‌شود؛ حذف آن مجاز نیست.')

    def bulk_update(self, *args, **kwargs):
        raise PermissionError('لاگ فقط اضافه می‌شود؛ ویرایش آن مجاز نیست.')


class AuditLog(models.Model):
    CATEGORY_AUTH = 'auth'
    CATEGORY_MEMBER = 'member'
    CATEGORY_TEACHER = 'teacher'
    CATEGORY_STAFF = 'staff'
    CATEGORY_CLASS = 'class'
    CATEGORY_FINANCE = 'finance'
    CATEGORY_FEEDBACK = 'feedback'
    CATEGORY_SURVEY = 'survey'
    CATEGORY_SETTINGS = 'settings'
    CATEGORY_CHOICES = [
        (CATEGORY_AUTH, 'ورود و خروج'),
        (CATEGORY_MEMBER, 'اعضا'),
        (CATEGORY_TEACHER, 'مدرسین'),
        (CATEGORY_STAFF, 'کارکنان'),
        (CATEGORY_CLASS, 'کلاس و ثبت‌نام'),
        (CATEGORY_FINANCE, 'امور مالی'),
        (CATEGORY_FEEDBACK, 'انتقادات و پیشنهادات'),
        (CATEGORY_SURVEY, 'نظرسنجی'),
        (CATEGORY_SETTINGS, 'تنظیمات'),
    ]

    STATUS_SUCCESS = 'success'
    STATUS_FAILED = 'failed'
    STATUS_BLOCKED = 'blocked'
    STATUS_CHOICES = [
        (STATUS_SUCCESS, 'موفق'),
        (STATUS_FAILED, 'ناموفق'),
        (STATUS_BLOCKED, 'مسدود'),
    ]

    created_at = models.DateTimeField('زمان', auto_now_add=True, db_index=True)
    category = models.CharField('دسته', max_length=10, choices=CATEGORY_CHOICES, db_index=True)
    action = models.CharField('کد رویداد', max_length=40, db_index=True)
    summary = models.CharField('شرح', max_length=300)
    status = models.CharField('وضعیت', max_length=8, choices=STATUS_CHOICES, default=STATUS_SUCCESS, db_index=True)

    # انجام‌دهنده. اگر حساب او بعداً حذف شود، خودِ لاگ و «نام/سمت» ثبت‌شده می‌ماند.
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    actor_name = models.CharField('انجام‌دهنده', max_length=150, blank=True)
    actor_role = models.CharField('سمت', max_length=40, blank=True)

    # شعبه‌ی مربوط به رویداد؛ مسئول آموزش فقط رویدادهای شعبه‌ی خودش را می‌بیند
    branch = models.CharField('شعبه', max_length=100, blank=True, db_index=True)

    target_type = models.CharField('نوع مورد', max_length=40, blank=True)
    target_id = models.CharField('شناسه‌ی مورد', max_length=40, blank=True)
    target_label = models.CharField('مورد', max_length=200, blank=True)
    # [{"field": "نام پدر", "old": "...", "new": "..."}]
    changes = models.JSONField('تغییرات', default=list, blank=True)

    # فقط برای رویدادهای ورود: نام کاربری/کد ملی واردشده (هرگز رمز یا کد عضویت)
    identifier = models.CharField('شناسه‌ی واردشده', max_length=150, blank=True, db_index=True)
    ip = models.GenericIPAddressField('آدرس IP', null=True, blank=True)
    user_agent = models.CharField('مرورگر', max_length=300, blank=True)

    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        verbose_name = 'رویداد لاگ'
        verbose_name_plural = 'لاگ سامانه'
        ordering = ['-created_at', '-id']

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise PermissionError('لاگ فقط اضافه می‌شود؛ ویرایش آن مجاز نیست.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError('لاگ فقط اضافه می‌شود؛ حذف آن مجاز نیست.')

    def __str__(self):
        return f'{self.created_at:%Y-%m-%d %H:%M} - {self.summary}'


class LoginThrottle(models.Model):
    """
    شمارنده‌ی تلاش ناموفق ورود برای هر «حساب» (کلید حساب مثل member:12 یا user:5؛ برای نام
    ناشناس unknown:متن). با رسیدن به سقف، حساب برای چند دقیقه قفل می‌شود.
    """
    key = models.CharField('کلید حساب', max_length=170, unique=True)
    fail_count = models.PositiveIntegerField('تعداد تلاش ناموفق', default=0)
    window_started_at = models.DateTimeField('شروع بازه‌ی شمارش', null=True, blank=True)
    locked_until = models.DateTimeField('مسدود تا', null=True, blank=True, db_index=True)
    last_attempt_at = models.DateTimeField('آخرین تلاش', db_index=True)
    known = models.BooleanField('حساب واقعی است', default=False)

    class Meta:
        verbose_name = 'شمارنده‌ی تلاش ورود'
        verbose_name_plural = 'شمارنده‌های تلاش ورود'

    def __str__(self):
        return f'{self.key} ({self.fail_count})'
