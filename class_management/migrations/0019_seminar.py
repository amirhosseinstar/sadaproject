# ===== مسیر این فایل در پروژه: class_management/migrations/0019_seminar.py (کنار manage.py) =====
# -*- coding: utf-8 -*-
# مایگریشنِ افزودن سمینار/کارگاه: سه مدل تازه (Seminar، SeminarSession، SeminarEnrollment).
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('academic_calendar', '0002_calendardocument'),
        ('core', '0016_add_reqtype_to_employee'),
        ('members', '0008_member_birth_date_member_father_name'),
        ('class_management', '0018_add_class_type_to_department_and_lesson'),
    ]

    operations = [
        migrations.CreateModel(
            name='Seminar',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200, verbose_name='نام سمینار/کارگاه')),
                ('class_type', models.CharField(choices=[('حضوری', 'حضوری'), ('مجازی', 'مجازی')], default='حضوری', max_length=10, verbose_name='نوع برگزاری')),
                ('is_national', models.BooleanField(default=False, help_text='فقط برای سمینارهای مجازی معنی دارد - یعنی دانش‌پژوهان همه‌ی استان‌ها می‌بینندش.', verbose_name='سراسری (بدون وابستگی به استان)')),
                ('branch', models.CharField(blank=True, max_length=100, verbose_name='شعبه')),
                ('capacity', models.PositiveIntegerField(verbose_name='ظرفیت')),
                ('description', models.TextField(blank=True, verbose_name='توضیحات')),
                ('is_published', models.BooleanField(default=True, verbose_name='منتشرشده')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ثبت')),
                ('department', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='seminars', to='class_management.department')),
                ('teacher', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='seminars', to='core.employee')),
                ('term', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='seminars', to='academic_calendar.academicterm', verbose_name='دوره')),
            ],
            options={
                'verbose_name': 'سمینار/کارگاه',
                'verbose_name_plural': 'سمینارها و کارگاه‌ها',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='SeminarSession',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.CharField(max_length=20, verbose_name='تاریخ')),
                ('start_time', models.CharField(max_length=10, verbose_name='ساعت شروع')),
                ('end_time', models.CharField(max_length=10, verbose_name='ساعت پایان')),
                ('seminar', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='sessions', to='class_management.seminar')),
            ],
            options={
                'verbose_name': 'جلسه‌ی سمینار',
                'verbose_name_plural': 'جلسه‌های سمینار',
                'ordering': ['date', 'start_time'],
            },
        ),
        migrations.CreateModel(
            name='SeminarEnrollment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('enrolled_at', models.DateTimeField(auto_now_add=True, verbose_name='تاریخ ثبت‌نام')),
                ('member', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='seminar_enrollments', to='members.member')),
                ('seminar', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='enrollments', to='class_management.seminar')),
            ],
            options={
                'verbose_name': 'ثبت‌نام سمینار',
                'verbose_name_plural': 'ثبت‌نام‌های سمینار',
            },
        ),
        migrations.AddConstraint(
            model_name='seminarenrollment',
            constraint=models.UniqueConstraint(fields=('seminar', 'member'), name='unique_seminar_member'),
        ),
    ]
