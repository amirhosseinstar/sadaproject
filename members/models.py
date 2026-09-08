from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone

from core.models import Employee, TeacherApplicant

User = get_user_model()


class Member(models.Model):
    """
    عضو خانه کارگر (کسی که در سایت سدا ثبت‌نام دوره می‌کند).

    هر عضو دقیقاً به یک حساب کاربری جنگو (User) وصل است؛ رمز عبور و
    session/login از طریق همان User مدیریت می‌شود (چیزی که خود جنگو از قبل
    امن و آماده پیاده کرده، نیازی به نوشتن دوباره نیست).

    طبق راهنمای صفحه‌ی ورود (login.html):
    - نام کاربری = «کد ملی» یا «کد عضویت»
    - گذرواژه = «کد عضویت» یا «شماره موبایل ثبت‌شده»
    برای همین هم national_id و هم membership_code باید منحصربه‌فرد (unique) باشند،
    چون هرکدام می‌تواند به‌تنهایی برای شناسایی عضو استفاده شود.
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='member',
        verbose_name='حساب کاربری',
    )
    national_id = models.CharField('کد ملی', max_length=10, unique=True)
    membership_code = models.CharField(
        'کد عضویت', max_length=20, unique=True, blank=True, null=True
    )
    phone = models.CharField(
        'شماره موبایل', max_length=15, unique=True, blank=True, null=True
    )
    province = models.CharField('استان', max_length=100, blank=True)
    branch = models.CharField('شعبه', max_length=100, blank=True)
    father_name = models.CharField('نام پدر', max_length=100, blank=True)
    # مثل بقیه‌ی تاریخ‌های این پروژه (تقویم آموزشی، تاریخ شروع کلاس)، عمداً
    # متنی و شمسی است، نه DateField میلادی جنگو - چون این‌جا هیچ‌جا تقویم
    # میلادی استفاده نمی‌شود
    birth_date = models.CharField('تاریخ تولد', max_length=20, blank=True, help_text='به شمسی، مثلاً: ۱۳۷۰/۰۵/۱۲')
    created_at = models.DateTimeField('تاریخ عضویت', auto_now_add=True)

    card_expires_at = models.DateField(
        'تاریخ انقضای کارت عضویت', null=True, blank=True,
        help_text=(
            'تا این تاریخ، کارت عضویت معتبر است. فعلاً این تاریخ باید دستی '
            '(مثلاً همین‌جا در پنل جنگو) وارد شود؛ TODO: وقتی اتصال به دیتابیس '
            'مرکزی خانه کارگر آماده شد، این فیلد باید از آن‌جا همگام‌سازی شود.'
        ),
    )

    class Meta:
        verbose_name = 'دانش‌پژوه'
        verbose_name_plural = 'دانش‌پژوهان'

    @property
    def is_membership_valid(self):
        """
        آیا کارت عضویت این عضو هنوز معتبر است؟

        وضعیت عضویت دیگر چیزی نیست که ادمین دستی «روشن/خاموش» کند - خودکار
        از روی card_expires_at محاسبه می‌شود: اگر امروز از تاریخ انقضا
        گذشته باشد، عضو غیرمعتبر است (تا بیاید کارتش را تمدید کند).

        TODO (اتصال به دیتابیس مرکزی خانه کارگر): فعلاً card_expires_at از
        همین دیتابیس محلی خوانده می‌شود (که فعلاً دستی پر می‌شود). وقتی
        اتصال به سامانه‌ی مرکزی آماده شد، فقط کافی‌ست همین یک متد را عوض
        کنید (مثلاً واقعاً از آن سیستم استعلام بگیرید)؛ جای دیگری از کد
        (سریالایزر، پنل ادمین) نیازی به تغییر ندارد چون همه از همین‌جا
        می‌خوانند.
        """
        if self.card_expires_at is None:
            return True
        return self.card_expires_at >= timezone.localdate()

    def __str__(self):
        return f'{self.user.get_full_name() or self.user.username} ({self.national_id})'


class MemberBan(models.Model):
    """
    محرومیت یک عضو از ثبت‌نام در کلاس‌ها.

    طراحی ساده: وجود یک رکورد یعنی «محروم است»؛ حذف رکورد یعنی «رفع
    محرومیت». چون هر عضو در هر لحظه یا محروم است یا نیست (نه چند بار)،
    OneToOne مناسب‌تر از یک تاریخچه است.
    """
    member = models.OneToOneField(Member, on_delete=models.CASCADE, related_name='ban')
    reason = models.CharField('دلیل محرومیت', max_length=300, blank=True)
    banned_at = models.DateTimeField('تاریخ محرومیت', auto_now_add=True)

    class Meta:
        verbose_name = 'محرومیت عضو'
        verbose_name_plural = 'محرومیت‌های اعضا'

    def __str__(self):
        return f'محرومیت {self.member}'


class OTPCode(models.Model):
    """
    کد یکبارمصرف پیامکی - هم برای «فراموشی رمز عبور» و هم برای «ورود با
    رمز یکبار مصرف» استفاده می‌شود (فیلد purpose مشخص می‌کند کدام است).

    نکته: خود کد به‌صورت متن ساده ذخیره می‌شود (نه هش‌شده)، چون این کد
    فقط چند دقیقه اعتبار دارد و یک‌بار مصرف است - بر خلاف رمز عبور که
    همیشگی است، نگهداری متن ساده‌ی این کدها ریسک امنیتی مهمی ایجاد نمی‌کند.
    """
    PURPOSE_LOGIN = 'login'
    PURPOSE_RESET = 'reset'
    PURPOSE_CHOICES = [
        (PURPOSE_LOGIN, 'ورود با رمز یکبار مصرف'),
        (PURPOSE_RESET, 'فراموشی رمز عبور'),
    ]

    member = models.ForeignKey(
        Member, on_delete=models.CASCADE, related_name='otp_codes', verbose_name='دانش‌پژوه',
    )
    code = models.CharField('کد', max_length=6)
    purpose = models.CharField('هدف', max_length=10, choices=PURPOSE_CHOICES)
    created_at = models.DateTimeField('زمان ساخت', auto_now_add=True)
    expires_at = models.DateTimeField('زمان انقضا')
    is_used = models.BooleanField('استفاده‌شده', default=False)

    class Meta:
        verbose_name = 'کد یکبارمصرف پیامکی'
        verbose_name_plural = 'کدهای یکبارمصرف پیامکی'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.member} - {self.get_purpose_display()} - {self.code}'

    def is_valid(self):
        return not self.is_used and self.expires_at > timezone.now()


class AdminAccount(User):
    """
    این یک «مدل پروکسی» است - جدول جدیدی در دیتابیس نمی‌سازد، فقط باعث
    می‌شود در پنل مدیریت جنگو، به‌جای «کاربرها» عبارت «ادمین‌ها» دیده شود
    (چون این بخش از این به بعد فقط برای ساختن حساب‌های ادمین استفاده می‌شود).
    """
    class Meta:
        proxy = True
        app_label = 'members'
        verbose_name = 'ادمین'
        verbose_name_plural = 'ادمین‌ها'


class Teacher(Employee):
    """
    مدل پروکسی: همان جدول Employee (در اپ core) است، فقط زیر بخش «اعضا»
    (به‌جای «Core») و با نام «مدرسین» در پنل مدیریت جنگو نشان داده می‌شود.

    چرا این‌جا و نه «نیروی انسانی» زیر Core؟ چون طبق طراحی پروژه، تنها
    راهی که یک Employee ساخته می‌شود، تأیید یک TeacherApplicant است - یعنی
    این جدول همیشه فقط شامل مدرسین است، پس منطقی‌تر است کنار «دانش‌پژوهان»
    (که او هم عضوی از «اعضا»ی سایت است) دیده شود.
    """
    class Meta:
        proxy = True
        app_label = 'members'
        verbose_name = 'مدرس (تأییدشده)'
        verbose_name_plural = 'مدرسین (تأییدشده)'


class TeacherApplication(TeacherApplicant):
    """مدل پروکسی: همان جدول TeacherApplicant (در اپ core) است، فقط زیر بخش «اعضا»."""
    class Meta:
        proxy = True
        app_label = 'members'
        verbose_name = 'مدرس متقاضی'
        verbose_name_plural = 'مدرسین (متقاضی)'


class Staff(Employee):
    """
    مدل پروکسی: همان Employee، اما برای «متصدیان» (مدیر آموزش/مسئول
    آموزش) - کسانی که وارد پنل مدیریتی HTML (sada-admin.html یا officer)
    می‌شوند. بر خلاف مدرس (که فقط با تأیید درخواست همکاری ساخته می‌شود)،
    متصدی مستقیماً همین‌جا ساخته می‌شود، چون مفهوم «درخواست همکاری» برای
    این سمت‌ها اصلاً معنی ندارد.
    """
    class Meta:
        proxy = True
        app_label = 'members'
        verbose_name = 'متصدی'
        verbose_name_plural = 'متصدیان'
