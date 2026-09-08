from rest_framework import serializers

from .models import Member


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

    class Meta:
        model = Member
        fields = [
            'id', 'national_id', 'membership_code', 'phone', 'province', 'branch',
            'first_name', 'last_name', 'father_name', 'birth_date', 'card_expires_at', 'is_membership_valid',
            'is_banned', 'ban_reason',
        ]
        read_only_fields = ['card_expires_at']

    def get_is_banned(self, obj):
        return hasattr(obj, 'ban')

    def get_ban_reason(self, obj):
        return obj.ban.reason if hasattr(obj, 'ban') else ''


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
        'is_employee': employee is not None,
        'employee_role': employee.role if employee else None,
        'employee_depts': (employee.depts or []) if employee else [],
        'employee_branch': employee.branch if employee else None,
    }
