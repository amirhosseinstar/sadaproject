import re

from django.db import transaction
from rest_framework import serializers

from core.services import ApprovalError, ensure_username_available
from feedback.branches import canonical_branch_name
from sada_project.utils import parse_jalali_date, to_english_digits

from .models import Member
from .profile import member_missing_fields
from .provinces import PROVINCES


class MemberSearchSerializer(serializers.ModelSerializer):
    """
    برای صفحه‌ی «اعضا» در پنل ادمین: جستجو، وضعیت عضویت (که خودکار از روی
    تاریخ انقضای کارت محاسبه می‌شود - نه چیزی که ادمین دستی روشن/خاموش کند)
    و محرومیت (که وجود/نبودِ MemberBan را نشان می‌دهد).
    """
    first_name = serializers.CharField(source='user.first_name', read_only=True)
    last_name = serializers.CharField(source='user.last_name', read_only=True)
    is_membership_valid = serializers.BooleanField(read_only=True)
    is_banned = serializers.SerializerMethodField()
    ban_reason = serializers.SerializerMethodField()
    # اطلاعات ناقص عضو (فهرست فارسی؛ خالی یعنی کامل) - برای نشان «اطلاعات ناقص» در پنل
    missing_fields = serializers.SerializerMethodField()

    class Meta:
        model = Member
        fields = [
            'id', 'national_id', 'membership_code', 'phone', 'province', 'branch',
            'first_name', 'last_name', 'father_name', 'birth_date', 'card_expires_at', 'is_membership_valid',
            'is_banned', 'ban_reason', 'missing_fields',
        ]
        read_only_fields = ['card_expires_at']

    def get_missing_fields(self, obj):
        return member_missing_fields(obj)

    def get_is_banned(self, obj):
        return hasattr(obj, 'ban')

    def get_ban_reason(self, obj):
        return obj.ban.reason if hasattr(obj, 'ban') else ''


# نام و نام‌خانوادگی/نام پدر: حرف انگلیسی و هیچ نوع رقمی مجاز نیست (همان قاعده‌ی فرم‌های پنل)
_FORBIDDEN_IN_NAME_RE = re.compile('[a-zA-Z0-9۰-۹٠-٩]')


class MemberUpdateSerializer(serializers.Serializer):
    """
    ویرایش اطلاعات یک عضو موجود از پنل ادمین (فقط مدیر/مسئول آموزش). ساخت عضو جدید
    از این مسیر ممکن نیست؛ اعضای تازه فقط از پنل ادمین جنگو اضافه می‌شوند.

    همه‌ی فیلدها اختیاری‌اند (ویرایش جزئی)؛ هر فیلدی که فرستاده شود اعتبارسنجی می‌شود:
      - نام / نام‌خانوادگی: الزامی (خالی نمی‌شود)، بدون حرف انگلیسی و رقم
      - نام پدر: بدون حرف انگلیسی و رقم (می‌تواند خالی باشد)
      - تاریخ تولد: شمسی معتبر (مثل ۱۳۷۰/۰۵/۱۲) و نه آینده؛ با رقم انگلیسی ذخیره می‌شود
      - کد ملی: ۱۰ رقم، منحصربه‌فرد؛ با عوض شدنش «نام کاربری» ورود هم عوض می‌شود
      - کد عضویت: ۱۴ رقم، منحصربه‌فرد
      - موبایل: 09xxxxxxxxx و منحصربه‌فرد (می‌تواند خالی باشد)
      - استان: یکی از ۳۱ استان (یا خالی)؛ شعبه: یکی از شعب واقعی (یا خالی)
    تاریخ انقضای کارت عضویت عمداً از این مسیر قابل ویرایش نیست (قرار است از دیتابیس
    مرکزی همگام شود).
    """
    first_name = serializers.CharField(max_length=150, required=False, trim_whitespace=True)
    last_name = serializers.CharField(max_length=150, required=False, trim_whitespace=True)
    father_name = serializers.CharField(max_length=100, required=False, allow_blank=True, trim_whitespace=True)
    birth_date = serializers.CharField(max_length=20, required=False, allow_blank=True, trim_whitespace=True)
    national_id = serializers.CharField(max_length=30, required=False, trim_whitespace=True)
    membership_code = serializers.CharField(max_length=30, required=False, trim_whitespace=True)
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, trim_whitespace=True)
    province = serializers.CharField(max_length=100, required=False, allow_blank=True, trim_whitespace=True)
    branch = serializers.CharField(max_length=100, required=False, allow_blank=True, trim_whitespace=True)

    def _validate_name(self, value):
        if _FORBIDDEN_IN_NAME_RE.search(value):
            raise serializers.ValidationError('فقط حروف فارسی مجاز است (حرف انگلیسی و عدد قبول نیست).')
        return re.sub(r'\s+', ' ', value)

    def validate_first_name(self, value):
        return self._validate_name(value)

    def validate_last_name(self, value):
        return self._validate_name(value)

    def validate_father_name(self, value):
        return self._validate_name(value) if value else ''

    def validate_birth_date(self, value):
        if not value:
            return ''
        parsed = parse_jalali_date(value)
        if parsed is None:
            raise serializers.ValidationError('تاریخ تولد نامعتبر است (مثلاً ۱۳۷۰/۰۵/۱۲؛ تاریخ آینده هم قبول نیست).')
        return f'{parsed[0]:04d}/{parsed[1]:02d}/{parsed[2]:02d}'

    def validate_national_id(self, value):
        value = to_english_digits(value)
        if not re.fullmatch(r'\d{10}', value):
            raise serializers.ValidationError('کد ملی باید دقیقاً ۱۰ رقم باشد.')
        if Member.objects.filter(national_id=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError('این کد ملی برای عضو دیگری ثبت شده است.')
        return value

    def validate_membership_code(self, value):
        value = to_english_digits(value)
        if not re.fullmatch(r'\d{14}', value):
            raise serializers.ValidationError('کد عضویت باید دقیقاً ۱۴ رقم باشد.')
        if Member.objects.filter(membership_code=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError('این کد عضویت برای عضو دیگری ثبت شده است.')
        return value

    def validate_phone(self, value):
        value = to_english_digits(value)
        if not value:
            return None   # خالی = بدون شماره (ستون unique است، پس ''، نه None، تکراری می‌شد)
        if not re.fullmatch(r'09\d{9}', value):
            raise serializers.ValidationError('شماره موبایل باید مثل 09xxxxxxxxx (۱۱ رقم) باشد.')
        if Member.objects.filter(phone=value).exclude(pk=self.instance.pk).exists():
            raise serializers.ValidationError('این شماره موبایل برای عضو دیگری ثبت شده است.')
        return value

    def validate_province(self, value):
        if value and value not in PROVINCES:
            raise serializers.ValidationError('استان انتخاب‌شده معتبر نیست.')
        return value

    def validate_branch(self, value):
        if not value:
            return ''
        canonical = canonical_branch_name(value)
        if canonical is None:
            raise serializers.ValidationError('شعبه‌ی انتخاب‌شده معتبر نیست.')
        return canonical

    def update(self, instance, validated_data):
        user = instance.user
        with transaction.atomic():
            if 'first_name' in validated_data:
                user.first_name = validated_data.pop('first_name')
            if 'last_name' in validated_data:
                user.last_name = validated_data.pop('last_name')

            # نام کاربریِ ورود همان کد ملی است؛ با عوض شدن کد ملی، همگام می‌شود
            new_nid = validated_data.get('national_id')
            if new_nid and new_nid != instance.national_id:
                try:
                    ensure_username_available(new_nid, exclude_user_pk=user.pk)
                except ApprovalError as e:
                    raise serializers.ValidationError({'national_id': str(e)})
                user.username = new_nid
            user.save()

            for field, value in validated_data.items():
                setattr(instance, field, value)
            instance.save()
        return instance


class MemberProfileSerializer(serializers.Serializer):
    """
    اطلاعاتی که بعد از ورود موفق (یا در /api/auth/me/) به فرانت‌اند برگردانده می‌شود.
    عمداً یک Serializer ساده (نه ModelSerializer) است چون هم برای اعضای عادی
    و هم برای کارکنان (که پروفایل Member ندارند، فقط کارمند/ادمین هستند) استفاده می‌شود.
    """
    id = serializers.IntegerField()
    username = serializers.CharField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    is_staff = serializers.BooleanField()
    is_member = serializers.BooleanField()
    national_id = serializers.CharField(allow_null=True, required=False)
    membership_code = serializers.CharField(allow_null=True, required=False)
    phone = serializers.CharField(allow_null=True, required=False)
    province = serializers.CharField(allow_null=True, required=False)
    branch = serializers.CharField(allow_null=True, required=False)
    is_employee = serializers.BooleanField()
    employee_role = serializers.CharField(allow_null=True, required=False)
    employee_depts = serializers.ListField(child=serializers.CharField(), required=False)
    employee_branch = serializers.CharField(allow_null=True, required=False)


def build_profile_payload(user):
    """
    آبجکت User جنگو را (به‌همراه پروفایل Member و/یا Employee اگر وجود
    داشته باشد) به یک دیکشنری ساده برای پاسخ API تبدیل می‌کند.

    نکته: یک حساب کاربری می‌تواند فقط دانش‌پژوه باشد، فقط مدرس باشد، یا
    (در آینده) هر دو - برای همین is_member و is_employee مستقل از هم‌اند.
    """
    member = getattr(user, 'member', None)
    employee = getattr(user, 'employee', None)
    return {
        'id': user.id,
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'is_staff': user.is_staff,
        'is_member': member is not None,
        'national_id': member.national_id if member else None,
        'membership_code': member.membership_code if member else None,
        'phone': member.phone if member else None,
        'province': member.province if member else None,
        'branch': member.branch if member else None,
        'father_name': member.father_name if member else None,
        'birth_date': member.birth_date if member else None,
        'is_employee': employee is not None,
        'employee_role': employee.role if employee else None,
        'employee_depts': (employee.depts or []) if employee else [],
        'employee_branch': employee.branch if employee else None,
    }
