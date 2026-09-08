# دستی بازنویسی شد: چون مقدار قبلی reqtype یک رشته‌ی ساده بود (نه JSON معتبر)،
# تبدیل مستقیم به JSONField باعث خطای parse می‌شد؛ اول یک فیلد موقت می‌سازیم،
# داده‌های قبلی را به‌صورت یک‌آیتمی داخل لیست منتقل می‌کنیم، بعد جای فیلد
# قدیمی را می‌گیرد - دقیقاً مثل کاری که برای Employee.depts کردیم.

from django.db import migrations, models


def copy_reqtype_to_list(apps, schema_editor):
    TeacherApplicant = apps.get_model('core', 'TeacherApplicant')
    for obj in TeacherApplicant.objects.all():
        obj.reqtype_new = [obj.reqtype] if obj.reqtype else []
        obj.save(update_fields=['reqtype_new'])


def copy_list_to_reqtype(apps, schema_editor):
    """برای امکان برگشت (migrate به عقب) - اولین مقدار لیست را برمی‌گرداند."""
    TeacherApplicant = apps.get_model('core', 'TeacherApplicant')
    for obj in TeacherApplicant.objects.all():
        obj.reqtype = obj.reqtype_new[0] if obj.reqtype_new else ''
        obj.save(update_fields=['reqtype'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_alter_teacherapplicant_postal_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='teacherapplicant',
            name='reqtype_new',
            field=models.JSONField(blank=True, default=list, verbose_name='نوع همکاری درخواستی'),
        ),
        migrations.RunPython(copy_reqtype_to_list, copy_list_to_reqtype),
        migrations.RemoveField(
            model_name='teacherapplicant',
            name='reqtype',
        ),
        migrations.RenameField(
            model_name='teacherapplicant',
            old_name='reqtype_new',
            new_name='reqtype',
        ),
    ]
