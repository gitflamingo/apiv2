# Generated by Django 3.2.9 on 2022-02-04 22:20

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('feedback', '0024_survey_response_rate'),
    ]

    operations = [
        migrations.AlterField(
            model_name='survey',
            name='response_rate',
            field=models.FloatField(blank=True, default=None, null=True),
        ),
    ]
