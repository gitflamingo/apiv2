# Generated by Django 3.2.15 on 2022-09-07 23:04

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('certificate', '0016_userspecialty_update_hash'),
    ]

    operations = [
        migrations.AddField(
            model_name='layoutdesign',
            name='foot_note',
            field=models.CharField(default=None, max_length=250, null=True),
        ),
    ]
