import binascii
import os
import json
from django.db import models
from breathecode.admissions.models import Academy
from breathecode.notify.models import SlackChannel
from datetime import timedelta

__all__ = ['Application', 'Endpoint', 'MonitorScript']

LOADING = 'LOADING'
OPERATIONAL = 'OPERATIONAL'
MINOR = 'MINOR'
CRITICAL = 'CRITICAL'
STATUS = (
    (LOADING, 'Loading'),
    (OPERATIONAL, 'Operational'),
    (MINOR, 'Minor'),
    (CRITICAL, 'Critical'),
)


class Application(models.Model):
    title = models.CharField(max_length=100)

    academy = models.ForeignKey(Academy, on_delete=models.CASCADE)
    status_text = models.CharField(max_length=255, default=None, null=True, blank=True)
    notify_email = models.CharField(max_length=255,
                                    blank=True,
                                    default=None,
                                    null=True,
                                    help_text='Comma separated list of emails')
    notify_slack_channel = models.ForeignKey(
        SlackChannel,
        on_delete=models.SET_NULL,
        blank=True,
        default=None,
        null=True,
        help_text='Please pick an academy first to be able to see the available slack channels to notify')

    status = models.CharField(max_length=20, choices=STATUS, default=OPERATIONAL)

    paused_until = models.DateTimeField(null=True,
                                        blank=True,
                                        default=None,
                                        help_text='if you want to stop checking for a period of time')

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    def __str__(self):
        return self.title


class Endpoint(models.Model):

    url = models.CharField(max_length=255)
    test_pattern = models.CharField(max_length=100,
                                    default=None,
                                    null=True,
                                    blank=True,
                                    help_text='If left blank sys will only ping')
    frequency_in_minutes = models.FloatField(default=30)
    status_code = models.IntegerField(default=200)
    severity_level = models.IntegerField(default=0)
    status_text = models.CharField(max_length=255, default=None, null=True, blank=True, editable=False)
    special_status_text = models.CharField(max_length=255,
                                           default=None,
                                           null=True,
                                           blank=True,
                                           help_text='Add a message for people to see when is down')
    response_text = models.TextField(default=None, null=True, blank=True)
    last_check = models.DateTimeField(default=None, null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS, default=OPERATIONAL)

    application = models.ForeignKey(Application, on_delete=models.CASCADE)

    paused_until = models.DateTimeField(null=True,
                                        blank=True,
                                        default=None,
                                        help_text='if you want to stop checking for a period of time')

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    def __str__(self):
        return self.url


class MonitorScript(models.Model):

    script_slug = models.SlugField(default=None, null=True, blank=True)
    script_body = models.TextField(default=None, null=True, blank=True)

    frequency_delta = models.DurationField(
        default=timedelta(minutes=30),
        help_text='How long to wait for the next execution, defaults to 30 minutes')
    status_code = models.IntegerField(default=200)
    severity_level = models.IntegerField(default=0)
    notify_email = models.CharField(
        max_length=255,
        blank=True,
        default=None,
        null=True,
        help_text=
        'Only specify if need to override the application.notify_email, you can add many comma separated.')
    status_text = models.CharField(max_length=255, default=None, null=True, blank=True, editable=False)
    special_status_text = models.CharField(max_length=255,
                                           default=None,
                                           null=True,
                                           blank=True,
                                           help_text='Add a message for people to see when is down')
    response_text = models.TextField(default=None, null=True, blank=True)
    last_run = models.DateTimeField(default=None, null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS, default=OPERATIONAL)

    application = models.ForeignKey(Application, on_delete=models.CASCADE)

    paused_until = models.DateTimeField(null=True,
                                        blank=True,
                                        default=None,
                                        help_text='if you want to stop checking for a period of time')

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    def __str__(self):
        slug = 'unknown' if not self.script_slug else self.script_slug
        return f'{slug}({self.id})'


LOADING = 'LOADING'
ERROR = 'ERROR'
DONE = 'DONE'
DOWNLOAD_STATUS = (
    (LOADING, 'Loading'),
    (ERROR, 'Error'),
    (DONE, 'Done'),
)


class CSVDownload(models.Model):
    name = models.CharField(max_length=255)
    url = models.URLField()
    status = models.CharField(max_length=20, choices=DOWNLOAD_STATUS, default=LOADING)
    status_message = models.TextField(null=True, blank=True, default=None)

    academy = models.ForeignKey(Academy, on_delete=models.CASCADE, null=True, blank=True, default=None)

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    finished_at = models.DateTimeField(auto_now=True, editable=False)


PENDING = 'PENDING'
UPLOAD_STATUS = (
    (PENDING, 'Pending'),
    (ERROR, 'Error'),
    (DONE, 'Done'),
)


class CSVUpload(models.Model):
    name = models.CharField(max_length=255)
    url = models.URLField()
    status = models.CharField(max_length=20, choices=UPLOAD_STATUS, default=PENDING)
    status_message = models.TextField(null=True, blank=True, default=None)
    log = models.CharField(max_length=50)
    academy = models.ForeignKey(Academy, on_delete=models.CASCADE, null=True, blank=True, default=None)
    hash = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    finished_at = models.DateTimeField(auto_now=True, editable=False)


class RepositorySubscription(models.Model):
    repository = models.URLField(max_length=255, help_text='Github repo where the event ocurred')
    token = models.CharField(max_length=255, unique=True)

    owner = models.ForeignKey(Academy, on_delete=models.CASCADE)

    shared_with = models.ManyToManyField(Academy, blank=True, related_name='repo_subscription')

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    def save(self, *args, **kwargs):
        if not self.pk:
            self.token = binascii.hexlify(os.urandom(20)).decode()

        return super().save(*args, **kwargs)


PENDING = 'PENDING'
DONE = 'DONE'
ERROR = 'ERROR'
WEBHOOK_STATUS = (
    (PENDING, 'Pending'),
    (DONE, 'Done'),
    (ERROR, 'Error'),
)


class StripeEvent(models.Model):
    stripe_id = models.CharField(max_length=32, null=True, default=None, blank=True, help_text='Stripe id')

    type = models.CharField(max_length=50, help_text='Stripe event type')
    status = models.CharField(max_length=9, choices=WEBHOOK_STATUS, default=PENDING)
    status_texts = models.JSONField(default=dict, blank=True)

    data = models.JSONField(default=dict, blank=True)
    request = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    def clean(self) -> None:
        if not self.data:
            self.data = {}

        if not self.request:
            self.request = {}

        return super().clean()

    def save(self, *args, **kwargs):
        self.full_clean()

        return super().save(*args, **kwargs)


class RepositoryWebhook(models.Model):

    webhook_action = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        default=None,
        help_text='The specific action that was triggered on github for this webhook')
    scope = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        default=None,
        help_text='The specific entity that triggered this webhook, for example: issues, issues_comment, etc.'
    )
    run_at = models.DateTimeField(help_text='Date/time that the webhook ran',
                                  blank=True,
                                  null=True,
                                  default=None)
    repository = models.URLField(max_length=255, help_text='Github repo where the event occured')

    payload = models.JSONField(
        help_text='Info that came on the request, it varies depending on the webhook type')

    academy_slug = models.SlugField()

    status = models.CharField(max_length=9, choices=WEBHOOK_STATUS, default=PENDING)
    status_text = models.CharField(max_length=255, default=None, null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True, editable=False)
    updated_at = models.DateTimeField(auto_now=True, editable=False)

    def __str__(self):
        return f'Webhook {self.webhook_action} {self.status} => {self.status_text}'

    def get_payload(self):
        return json.loads(self.payload)
