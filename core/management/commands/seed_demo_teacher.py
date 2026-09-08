"""
یک نیروی انسانی (مدرس) نمونه می‌سازد تا بشود فرآیند ورود مدرسین را واقعاً امتحان کرد.
اجرا: python manage.py seed_demo_teacher
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand

from core.models import Employee

User = get_user_model()

DEMO_USERNAME = 'ostad.rezaei'
DEMO_PASSWORD = 'Amoozesh@1404'


class Command(BaseCommand):
    help = 'یک مدرس نمونه برای تست فرآیند ورود مدرسین می‌سازد'

    def handle(self, *args, **options):
        user, created = User.objects.get_or_create(
            username=DEMO_USERNAME,
            defaults={'first_name': 'محمد', 'last_name': 'رضایی'},
        )
        user.set_password(DEMO_PASSWORD)
        user.save()

        employee, _ = Employee.objects.update_or_create(
            user=user,
            defaults={
                'name': 'محمد رضایی',
                'role': 'مدرس',
                'dept': 'فناوری اطلاعات',
                'branch': 'دفتر مرکزی خانه کارگر',
                'phone': '09121230022',
            },
        )

        self.stdout.write(self.style.SUCCESS('مدرس نمونه ساخته/به‌روزرسانی شد:'))
        self.stdout.write(f'  نام کاربری: {DEMO_USERNAME}')
        self.stdout.write(f'  گذرواژه برای ورود: {DEMO_PASSWORD}')
