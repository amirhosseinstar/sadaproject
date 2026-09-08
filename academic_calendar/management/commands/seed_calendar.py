"""
همان ۱۱ دوره‌ی نمونه‌ای که در سایت اصلی (sada.html) و پنل ادمین به‌صورت
ثابت نوشته شده بود را در دیتابیس واقعی می‌سازد، تا API واقعاً چیزی برای
نمایش داشته باشد.

اجرا: python manage.py seed_calendar
"""

from django.core.management.base import BaseCommand

from academic_calendar.models import AcademicTerm

YEAR = 1405

# (order, regStart, regEnd, classStart, classEnd, moveStart, moveEnd, examStart, examEnd)
PERIODS = [
    (1,  (1, 7),  (1, 13), (1, 14), (2, 10), (1, 12), (1, 13), (2, 9),  (2, 10)),
    (2,  (2, 11), (2, 17), (2, 18), (3, 14), (2, 16), (2, 17), (3, 13), (3, 14)),
    (3,  (3, 15), (3, 21), (3, 22), (4, 18), (3, 20), (3, 21), (4, 17), (4, 18)),
    (4,  (4, 19), (4, 25), (4, 26), (5, 22), (4, 24), (4, 25), (5, 21), (5, 22)),
    (5,  (5, 23), (5, 29), (5, 30), (6, 26), (5, 28), (5, 29), (6, 25), (6, 26)),
    (6,  (6, 27), (7, 2),  (7, 3),  (7, 30), (7, 1),  (7, 2),  (7, 29), (7, 30)),
    (7,  (8, 1),  (8, 7),  (8, 8),  (9, 5),  (8, 6),  (8, 7),  (9, 4),  (9, 5)),
    (8,  (9, 6),  (9, 12), (9, 13), (10, 10),(9, 11), (9, 12), (10, 9), (10, 10)),
    (9,  (10, 11),(10, 17),(10, 18),(11, 15),(10, 16),(10, 17),(11, 14),(11, 15)),
    (10, (11, 16),(11, 22),(11, 23),(12, 20),(11, 21),(11, 22),(12, 19),(12, 20)),
    (11, (12, 15),(12, 21),(12, 21),(12, 27),(12, 19),(12, 20),(12, 26),(12, 27)),
]


def point(m, d):
    return {'m': m, 'd': d}


class Command(BaseCommand):
    help = 'داده‌ی نمونه‌ی تقویم آموزشی (سال ۱۴۰۵) را می‌سازد'

    def handle(self, *args, **options):
        created_count = 0
        for order, reg_s, reg_e, cls_s, cls_e, mv_s, mv_e, ex_s, ex_e in PERIODS:
            _, created = AcademicTerm.objects.update_or_create(
                year=YEAR, order=order,
                defaults={
                    'registration': {'start': point(*reg_s), 'end': point(*reg_e)},
                    'classes': {'start': point(*cls_s), 'end': point(*cls_e)},
                    'move': {'start': point(*mv_s), 'end': point(*mv_e)},
                    'exam': {'start': point(*ex_s), 'end': point(*ex_e)},
                    'is_active': True,
                },
            )
            if created:
                created_count += 1

        self.stdout.write(self.style.SUCCESS(
            f'تقویم آموزشی سال {YEAR}: {len(PERIODS)} دوره ثبت/به‌روزرسانی شد ({created_count} مورد جدید).'
        ))
