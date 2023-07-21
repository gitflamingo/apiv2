# Generated by Django 3.2.19 on 2023-07-21 01:58

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0049_alter_event_free_for_bootcamps'),
    ]

    operations = [
        migrations.AlterField(
            model_name='eventtype',
            name='description',
            field=models.CharField(default='',
                                   help_text='This will be publicly shown to 4geeks.com users',
                                   max_length=255),
        ),
        migrations.AlterField(
            model_name='eventtype',
            name='icon_url',
            field=models.URLField(blank=True, default=None, null=True),
        ),
    ]
