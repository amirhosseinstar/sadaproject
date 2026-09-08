"""دپارتمان‌های پیش‌فرض را می‌سازد (اگر از قبل نباشند) - اجرا: python manage.py seed_departments"""

from django.core.management.base import BaseCommand

from class_management.models import Department

DEFAULT_DEPARTMENTS = [
    'دوخت و دوز', 'کامپیوتر', 'هنر', 'آشپزی', 'بافتنی', 'فرش و گلیم',
    'زبان‌های خارجه', 'حقوق', 'مدیریت و حسابداری', 'بهداشت و سلامت',
    'فنی', 'قرآن',
]


class Command(BaseCommand):
    help = 'دپارتمان‌های پیش‌فرض سامانه را می‌سازد'

    def handle(self, *args, **options):
        created_count = 0
        for name in DEFAULT_DEPARTMENTS:
            _, created = Department.objects.get_or_create(name=name)
            if created:
                created_count += 1
        self.stdout.write(self.style.SUCCESS(f'{created_count} دپارتمان جدید ساخته شد (از {len(DEFAULT_DEPARTMENTS)} مورد).'))
