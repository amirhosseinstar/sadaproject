"""
امور مالی: پرداخت به مدرسین (حق‌التدریس هر کلاس).

هر «پرداخت» مربوط به «یک کلاس» و مدرسِ آن است. مبلغ = ساعت کل دوره × نرخ هر ساعت
(ساعت خودکار از زمان‌بندی کلاس؛ نرخ را مدیر/مسئول هنگام ثبت وارد می‌کند و مبلغ
نهایی هم قابل ویرایش دستی است). پرداخت دستی ثبت می‌شود (درگاه آنلاین لازم نیست).
"""

from django.conf import settings
from django.db import models
from django.db.models import Q


class TeacherPayment(models.Model):
    METHOD_BANK = 'bank'
    METHOD_CARD = 'card'
    METHOD_CASH = 'cash'
    METHOD_CHOICES = [
        (METHOD_BANK, 'واریز بانکی'),
        (METHOD_CARD, 'کارت‌به‌کارت'),
        (METHOD_CASH, 'نقدی'),
    ]

    # نوع حق‌الزحمه: «ساعتی» = نرخ هر ساعت × ساعت کل دوره؛ «ماهیانه» = یک مبلغ ثابت ماهیانه
    # (هر دوره/کلاس در سیستم یک ماه حساب می‌شود). مبلغ نهایی (amount) در هر دو حالت قابل ویرایش دستی است.
    FEE_HOURLY = 'hourly'
    FEE_MONTHLY = 'monthly'
    FEE_CHOICES = [(FEE_HOURLY, 'ساعتی'), (FEE_MONTHLY, 'ماهیانه')]

    STATUS_PAID = 'paid'
    STATUS_CANCELED = 'canceled'
    STATUS_CHOICES = [(STATUS_PAID, 'پرداخت‌شده'), (STATUS_CANCELED, 'لغوشده')]

    # اگر کلاس یا مدرس بعداً حذف شوند، خودِ رکورد مالی می‌ماند (SET_NULL)؛ به همین خاطر
    # نام‌ها و شعبه هم به‌صورت «اسنپ‌شات» همان لحظه‌ی ثبت نگه داشته می‌شود.
    class_obj = models.ForeignKey(
        'class_management.Class', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='teacher_payments', verbose_name='کلاس',
    )
    teacher = models.ForeignKey(
        'core.Employee', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='payments', verbose_name='مدرس',
    )
    class_name = models.CharField('نام کلاس', max_length=200)
    teacher_name = models.CharField('نام مدرس', max_length=150)
    branch = models.CharField('شعبه', max_length=100)
    term_label = models.CharField('ترم', max_length=100, blank=True)

    hours = models.DecimalField('ساعت کل دوره', max_digits=8, decimal_places=2, null=True, blank=True)
    fee_type = models.CharField('نوع حق‌الزحمه', max_length=7, choices=FEE_CHOICES, default=FEE_HOURLY)
    # فقط یکی از این دو مقدار معنی دارد: hourly_rate برای «ساعتی»، monthly_fee برای «ماهیانه»
    hourly_rate = models.PositiveBigIntegerField('نرخ هر ساعت (تومان)', null=True, blank=True)
    monthly_fee = models.PositiveBigIntegerField('حق‌الزحمه‌ی ماهیانه (تومان)', null=True, blank=True)
    amount = models.PositiveBigIntegerField('مبلغ پرداختی (تومان)')
    paid_date = models.CharField('تاریخ پرداخت (شمسی)', max_length=10)
    method = models.CharField('روش پرداخت', max_length=6, choices=METHOD_CHOICES)
    tracking_code = models.CharField('شماره پیگیری', max_length=50, blank=True)
    note = models.TextField('توضیحات', blank=True)

    status = models.CharField('وضعیت', max_length=10, choices=STATUS_CHOICES, default=STATUS_PAID)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    created_by_name = models.CharField('ثبت‌کننده', max_length=150, blank=True)
    created_at = models.DateTimeField('تاریخ ثبت', auto_now_add=True)
    updated_at = models.DateTimeField('آخرین ویرایش', auto_now=True)
    canceled_at = models.DateTimeField('تاریخ لغو', null=True, blank=True)
    canceled_by_name = models.CharField('لغوکننده', max_length=150, blank=True)
    cancel_reason = models.TextField('دلیل لغو', blank=True)

    class Meta:
        verbose_name = 'پرداخت به مدرس'
        verbose_name_plural = 'پرداخت‌ها به مدرسین'
        ordering = ['-created_at', '-id']
        constraints = [
            # برای هر کلاس حداکثر «یک» پرداخت فعال؛ پرداخت لغوشده می‌ماند و کلاس دوباره
            # «پرداخت‌نشده» می‌شود تا پرداخت تازه ثبت شود
            models.UniqueConstraint(
                fields=['class_obj'], condition=Q(status='paid'), name='one_paid_payment_per_class',
            ),
        ]

    def __str__(self):
        return f'{self.teacher_name} - {self.class_name} ({self.get_status_display()})'


class TeacherPaymentLog(models.Model):
    """سابقه‌ی تغییرات یک پرداخت: ثبت، ویرایش (با مقدار قبل/بعد) و لغو - هیچ‌وقت حذف نمی‌شود."""
    ACTION_CREATED = 'created'
    ACTION_EDITED = 'edited'
    ACTION_CANCELED = 'canceled'
    ACTION_CHOICES = [
        (ACTION_CREATED, 'ثبت پرداخت'),
        (ACTION_EDITED, 'ویرایش پرداخت'),
        (ACTION_CANCELED, 'لغو پرداخت'),
    ]

    payment = models.ForeignKey(TeacherPayment, on_delete=models.CASCADE, related_name='logs')
    action = models.CharField('عملیات', max_length=10, choices=ACTION_CHOICES)
    actor_name = models.CharField('انجام‌دهنده', max_length=150, blank=True)
    at = models.DateTimeField('زمان', auto_now_add=True)
    # فهرست تغییرها: [{"field": "مبلغ", "old": "...", "new": "..."}]
    changes = models.JSONField('تغییرات', default=list, blank=True)

    class Meta:
        verbose_name = 'سابقه‌ی پرداخت'
        verbose_name_plural = 'سابقه‌ی پرداخت‌ها'
        ordering = ['at', 'id']
