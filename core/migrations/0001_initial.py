from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='Employee',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=150, verbose_name='نام و نام خانوادگی')),
                ('role', models.CharField(max_length=50, verbose_name='سمت')),
                ('dept', models.CharField(max_length=100, verbose_name='دپارتمان')),
                ('branch', models.CharField(max_length=100, verbose_name='شعبه')),
                ('phone', models.CharField(max_length=20, verbose_name='شماره تماس')),
            ],
            options={
                'verbose_name': 'نیروی انسانی',
                'verbose_name_plural': 'نیروی انسانی',
            },
        ),
    ]
