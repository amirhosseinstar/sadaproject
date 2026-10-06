# ===== مسیر این فایل در پروژه: class_management/migrations/0020_seminar_lesson.py (کنار manage.py) =====
# -*- coding: utf-8 -*-
# مایگریشنِ افزودنِ فیلدِ «درس» به سمینار/کارگاه - دقیقاً مثلِ کلاس، سمینار هم
# باید بر اساسِ یک درسِ از قبل تعریف‌شده ساخته شود (قبلاً فقط نامِ آزاد داشت).
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('class_management', '0019_seminar'),
    ]

    operations = [
        migrations.AddField(
            model_name='seminar',
            name='lesson',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='seminars',
                to='class_management.lesson',
                verbose_name='درس',
                help_text='سمینار هم مثل کلاس، بر اساس یک درسِ از قبل تعریف‌شده ساخته می‌شود.',
            ),
        ),
    ]
