"""
یک عضو نمونه می‌سازد تا بشود فرآیند ورود را واقعاً امتحان کرد.
اجرا: python manage.py seed_demo_member
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from members.models import Member

User = get_user_model()

DEMO_NATIONAL_ID = '0012345678'
DEMO_MEMBERSHIP_CODE = '52102112830166'
DEMO_PASSWORD = DEMO_MEMBERSHIP_CODE  # طبق راهنمای صفحه‌ی ورود: گذرواژه = کد عضویت


class Command(BaseCommand):
    help = 'یک عضو نمونه برای تست فرآیند ورود می‌سازد'

    def handle(self, *args, **options):
        user, created = User.objects.get_or_create(
            username=DEMO_NATIONAL_ID,
            defaults={'first_name': 'سارا', 'last_name': 'کاظمی'},
        )
        user.set_password(DEMO_PASSWORD)
        user.save()

        member, _ = Member.objects.update_or_create(
            user=user,
            defaults={
                'national_id': DEMO_NATIONAL_ID,
                'membership_code': DEMO_MEMBERSHIP_CODE,
                'phone': '09121230011',
                'province': 'تهران',
                'branch': 'دفتر مرکزی خانه کارگر',
            },
        )

        self.stdout.write(self.style.SUCCESS('عضو نمونه ساخته/به‌روزرسانی شد:'))
        self.stdout.write(f'  کد ملی (نام کاربری): {DEMO_NATIONAL_ID}')
        self.stdout.write(f'  کد عضویت: {DEMO_MEMBERSHIP_CODE}')
        self.stdout.write(f'  گذرواژه برای ورود: {DEMO_PASSWORD}')
