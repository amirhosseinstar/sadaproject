# ===== مسیر این فایل در پروژه: core/migrations/0017_employee_denied_sections.py (کنار manage.py) =====
# فیلد «بخش‌های بسته‌شده» برای مسئول آموزش (باز/بسته‌کردنِ دسترسی توسط مدیر آموزش)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0016_add_reqtype_to_employee'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='denied_sections',
            field=models.JSONField(blank=True, default=list, verbose_name='بخش‌های بسته‌شده'),
        ),
    ]
