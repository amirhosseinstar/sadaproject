# دستی بازنویسی شد: به‌جای حذف مستقیم dept، ابتدا دپارتمان‌های موجود هر
# نیروی انسانی را به فیلد جدید depts (لیست) منتقل می‌کند تا داده‌ای گم نشود.

from django.db import migrations, models


def copy_dept_to_depts(apps, schema_editor):
    Employee = apps.get_model('core', 'Employee')
    for emp in Employee.objects.all():
        emp.depts = [emp.dept] if emp.dept else []
        emp.save(update_fields=['depts'])


def copy_depts_to_dept(apps, schema_editor):
    """برای امکان برگشت (migrate به عقب) - اولین دپارتمان لیست را برمی‌گرداند."""
    Employee = apps.get_model('core', 'Employee')
    for emp in Employee.objects.all():
        emp.dept = emp.depts[0] if emp.depts else ''
        emp.save(update_fields=['dept'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_teacherapplicant'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='depts',
            field=models.JSONField(blank=True, default=list, verbose_name='دپارتمان‌ها'),
        ),
        migrations.RunPython(copy_dept_to_depts, copy_depts_to_dept),
        migrations.RemoveField(
            model_name='employee',
            name='dept',
        ),
    ]
