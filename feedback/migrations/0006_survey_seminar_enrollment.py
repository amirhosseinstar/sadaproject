import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("class_management", "0020_seminar_lesson"),
        ("feedback", "0005_general_and_class_surveys"),
    ]

    operations = [
        migrations.AddField(
            model_name="classsurveyresponse",
            name="seminar_enrollment",
            field=models.OneToOneField(
                blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL,
                related_name="survey_response", to="class_management.seminarenrollment",
                verbose_name="ثبت‌نام سمینار",
            ),
        ),
    ]
