import academic_calendar.models
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='AcademicTerm',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('year', models.PositiveIntegerField(verbose_name='سال (شمسی)')),
                ('order', models.PositiveSmallIntegerField(verbose_name='شماره\u200cی دوره در سال')),
                ('registration', models.JSONField(validators=[academic_calendar.models.validate_date_range], verbose_name='بازه\u200cی ثبت\u200cنام')),
                ('classes', models.JSONField(validators=[academic_calendar.models.validate_date_range], verbose_name='بازه\u200cی برگزاری کلاس')),
                ('move', models.JSONField(validators=[academic_calendar.models.validate_date_range], verbose_name='بازه\u200cی جابه\u200cجایی')),
                ('exam', models.JSONField(validators=[academic_calendar.models.validate_date_range], verbose_name='بازه\u200cی آزمون نهایی')),
                ('is_active', models.BooleanField(default=True, verbose_name='فعال')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'دوره\u200cی تقویم آموزشی',
                'verbose_name_plural': 'تقویم آموزشی',
                'ordering': ['year', 'order'],
                'unique_together': {('year', 'order')},
            },
        ),
    ]
