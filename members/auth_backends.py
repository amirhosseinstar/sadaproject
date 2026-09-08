"""
بک‌اند احراز هویت سفارشی برای اعضا.

طبق طراحی صفحه‌ی ورود (login.html)، عضو با «کد ملی» (نام کاربری) و
«کد عضویت یا شماره موبایل» (گذرواژه) وارد می‌شود - یعنی هرکدام از این دو
مقدار (کد عضویت یا شماره موبایل ثبت‌شده‌ی همان عضو) به‌عنوان گذرواژه قبول
می‌شود، نه یک رمز جداگانه‌ی دیگر. کد ملی تنها راه شناسایی شخص است (کد
عضویت دیگر به‌عنوان نام کاربری جایگزین قبول نمی‌شود).
"""

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import BaseBackend

from .models import Member

User = get_user_model()


class MemberAuthBackend(BaseBackend):
    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None

        member = (
            Member.objects
            .select_related('user')
            .filter(national_id=username)
            .first()
        )
        if member is None:
            return None

        user = member.user
        # گذرواژه یا کد عضویت خودِ همین عضو است، یا شماره موبایل ثبت‌شده‌اش
        valid = password == member.membership_code or (member.phone and password == member.phone)
        if valid and user.is_active:
            return user
        return None

    def get_user(self, user_id):
        try:
            return User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return None
