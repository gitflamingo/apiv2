# Generated by Django 3.2.16 on 2023-02-10 16:33

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('events', '0039_liveclass'),
    ]

    operations = [
        migrations.AddField(
            model_name='eventtype',
            name='icon_url',
            field=models.URLField(blank=True, default=None, null=True),
        ),
    ]
