"""
پنل مدیریت اعضا.

طبق تصمیم پروژه، اسم «دانش‌پژوه» برای اعضای عادی (کسانی که در دوره‌ها
ثبت‌نام می‌کنند) استفاده می‌شود، نه «کاربر» یا «عضو». برای همین این بخش دو
مسیر کاملاً جدا دارد:

  - «دانش‌پژوهان» (پایین‌تر در همین فایل): برای افزودن/مدیریت دانش‌پژوه‌ها.
    فرم افزودنش، در یک صفحه، هم حساب ورود (کد ملی + رمز) و هم اطلاعات
    عضویت را می‌سازد - نیازی نیست اول یک «کاربر» جدا بسازید.

  - «کاربرها» (پنل پیش‌فرض جنگو، زیر «تأیید هویت و اجازه‌ها»): از این به بعد
    فقط برای ساختن حساب‌های ادمین/مدیر سیستم استفاده می‌شود. دانش‌پژوه‌های
    عادی دیگر در این لیست دیده نمی‌شوند (که شلوغ و گیج‌کننده نشود).
"""

from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .models import AdminAccount, Member, OTPCode, EmployeeOTPCode
from .provinces import PROVINCES

User = get_user_model()

# دقیقاً همان ۳۱ استانی که در سایت اصلی (province.html) برای انتخاب استان
# استفاده می‌شود - تا نام استانِ دانش‌پژوه با نام استانِ ثبت‌شده روی شعب یکی باشد
PROVINCE_CHOICES = [('', '— انتخاب استان —')] + [(p, p) for p in PROVINCES]


# ---------------------------------------------------------------------------
# دانش‌پژوهان (Member) - فرم افزودن که همه‌چیز را در یک صفحه می‌سازد
# ---------------------------------------------------------------------------

class MemberCreationForm(forms.ModelForm):
    """فرم «افزودن دانش‌پژوه» - حساب ورود و اطلاعات عضویت را با هم می‌سازد."""

    first_name = forms.CharField(label='نام', max_length=150)
    last_name = forms.CharField(label='نام خانوادگی', max_length=150)
    province = forms.ChoiceField(
        label='استان محل سکونت', choices=PROVINCE_CHOICES,
        help_text='دانش‌پژوه فقط می‌تواند در کلاس‌های همین استان (چه حضوری چه مجازی) ثبت‌نام کند؛ کلاس‌های مجازی سراسری برای همه‌ی استان‌ها آزاد است.',
    )

    class Meta:
        model = Member
        fields = ['national_id', 'membership_code', 'phone', 'province', 'branch', 'father_name', 'birth_date', 'card_expires_at']
        labels = {
            'national_id': 'کد ملی (همین، نام کاربری ورود هم می‌شود)',
        }

    def clean_national_id(self):
        national_id = self.cleaned_data['national_id'].strip()
        if len(national_id) != 10 or not national_id.isdigit():
            raise forms.ValidationError('کد ملی باید دقیقاً ۱۰ رقم باشد.')
        if User.objects.filter(username=national_id).exists():
            raise forms.ValidationError('دانش‌پژوهی با این کد ملی از قبل ثبت شده است.')
        return national_id


class MemberChangeForm(forms.ModelForm):
    """فرم «ویرایش دانش‌پژوه» - نام و نام‌خانوادگی از روی حساب کاربری‌اش خوانده می‌شود."""

    first_name = forms.CharField(label='نام', max_length=150)
    last_name = forms.CharField(label='نام خانوادگی', max_length=150)
    province = forms.ChoiceField(label='استان محل سکونت', choices=PROVINCE_CHOICES)

    class Meta:
        model = Member
        fields = ['national_id', 'membership_code', 'phone', 'province', 'branch', 'father_name', 'birth_date', 'card_expires_at']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name


@admin.register(Member)
class MemberAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'national_id', 'membership_code', 'phone', 'province', 'branch', 'card_expires_at', 'membership_status')
    search_fields = ('national_id', 'membership_code', 'phone', 'user__first_name', 'user__last_name')
    list_filter = ('province', 'branch')

    def membership_status(self, obj):
        return 'معتبر' if obj.is_membership_valid else 'منقضی‌شده'
    membership_status.short_description = 'وضعیت عضویت'

    def get_form(self, request, obj=None, **kwargs):
        kwargs['form'] = MemberChangeForm if obj else MemberCreationForm
        return super().get_form(request, obj, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change:
            # ساخت حساب کاربری تازه، هم‌زمان با ساخت دانش‌پژوه - رمز واقعی
            # جنگو دیگر پرسیده نمی‌شود (ورود واقعی از طریق MemberAuthBackend
            # مستقیم با کد عضویت/شماره موبایل چک می‌شود، نه این رمز)؛ فقط
            # چون خودِ جنگو یک رمز برای هر حساب لازم دارد، همینجا یک رمز
            # داخلی (کد عضویت) برایش ست می‌شود.
            user = User.objects.create_user(
                username=form.cleaned_data['national_id'],
                password=form.cleaned_data.get('membership_code') or form.cleaned_data.get('phone') or User.objects.make_random_password(),
                first_name=form.cleaned_data['first_name'],
                last_name=form.cleaned_data['last_name'],
            )
            obj.user = user
        else:
            # ویرایش: نام/نام‌خانوادگی روی همان حساب کاربری موجود به‌روزرسانی شود
            obj.user.first_name = form.cleaned_data['first_name']
            obj.user.last_name = form.cleaned_data['last_name']
            obj.user.save()
        super().save_model(request, obj, form, change)


# ---------------------------------------------------------------------------
# کدهای یکبارمصرف پیامکی - فقط برای مشاهده (تا وقتی پیامک واقعی وصل شود،
# از همین‌جا می‌شود کد تولیدشده را برای تست دید)
# ---------------------------------------------------------------------------

@admin.register(OTPCode)
class OTPCodeAdmin(admin.ModelAdmin):
    list_display = ('member', 'code', 'purpose', 'created_at', 'expires_at', 'is_used')
    list_filter = ('purpose', 'is_used')
    search_fields = ('member__national_id', 'code')
    readonly_fields = ('member', 'code', 'purpose', 'created_at', 'expires_at', 'is_used')

    def has_add_permission(self, request):
        return False


@admin.register(EmployeeOTPCode)
class EmployeeOTPCodeAdmin(admin.ModelAdmin):
    list_display = ('employee', 'code', 'purpose', 'created_at', 'expires_at', 'is_used')
    list_filter = ('purpose', 'is_used')
    search_fields = ('employee__name', 'employee__phone', 'code')
    readonly_fields = ('employee', 'code', 'purpose', 'created_at', 'expires_at', 'is_used')

    def has_add_permission(self, request):
        return False


# ---------------------------------------------------------------------------
# مدرسین (تأییدشده/متقاضی) عمداً اینجا (پنل ادمین جنگو) دیده نمی‌شوند -
# مدیریت‌شان (مشاهده، ویرایش، تأیید) کاملاً از پنل ادمین اصلی
# (sada-admin.html/sada-admin-officer.html، از طریق core API) انجام می‌شود.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# متصدیان (مدیر آموزش/مسئول آموزش) عمداً اینجا (پنل ادمین جنگو) دیده
# نمی‌شوند - طبق تصمیم پروژه، تنها راه ساخته‌شدن متصدی، پنل ادمین اصلی
# (sada-admin.html، از طریق core.api/staff) است، نه پنل جنگو.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# کاربرها (User) - از این به بعد، فقط برای حساب‌های ادمین/مدیر سیستم
# ---------------------------------------------------------------------------

class AdminUserCreationForm(forms.ModelForm):
    """
    فرم افزودن ادمین. برخلاف فرم پیش‌فرض جنگو، همیشه is_staff را روشن
    می‌کند، چون این صفحه دیگر مخصوص ساختن حساب مدیر/ادمین سیستم است.
    """
    password = forms.CharField(label='رمز عبور', widget=forms.PasswordInput)

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'is_superuser')
        labels = {
            'username': 'نام کاربری',
            'is_superuser': 'دسترسی کامل (مدیر ارشد)',
        }

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_staff = True  # این پنل فقط برای ساخت ادمین است
        user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
        return user


class AdminUserAdmin(BaseUserAdmin):
    """پنل «کاربرها» - فقط حساب‌های ادمین (is_staff=True) را نشان و مدیریت می‌کند."""

    list_display = ('username', 'first_name', 'last_name', 'is_superuser', 'is_active')
    add_form = AdminUserCreationForm
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'first_name', 'last_name', 'password', 'is_superuser'),
        }),
    )

    def get_queryset(self, request):
        # دانش‌پژوهان (که هرکدام هم یک User دارند) اینجا نشان داده نشوند
        return super().get_queryset(request).filter(is_staff=True)


admin.site.unregister(User)
admin.site.register(AdminAccount, AdminUserAdmin)
