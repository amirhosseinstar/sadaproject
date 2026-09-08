import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Member',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('national_id', models.CharField(max_length=10, unique=True, verbose_name='کد ملی')),
                ('membership_code', models.CharField(blank=True, max_length=20, null=True, unique=True, verbose_name='کد عضویت')),
                ('phone', models.CharField(blank=True, max_length=15, null=True, unique=True, verbose_name='شماره موبایل')),
                ('province', models.CharField(blank=True, max_length=100, verbose_name='استان')),
                ('branch', models.CharField(blank=True, max_length=100, verbose_name='شعبه')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='تاریخ عضویت')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='member', to=settings.AUTH_USER_MODEL, verbose_name='حساب کاربری')),
            ],
            options={
                'verbose_name': 'عضو',
                'verbose_name_plural': 'اعضا',
            },
        ),
    ]
