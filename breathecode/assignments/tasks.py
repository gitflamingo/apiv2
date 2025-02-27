import os
import logging
import re

from celery import shared_task, Task as CeleryTask
from breathecode.admissions.models import CohortUser

from breathecode.assignments.actions import task_is_valid_for_notifications, NOTIFICATION_STRINGS
import breathecode.notify.actions as actions
from breathecode.utils.service import Service
from .models import Task

# Get an instance of a logger
logger = logging.getLogger(__name__)


class BaseTaskWithRetry(CeleryTask):
    autoretry_for = (Exception, )
    #                                              seconds
    retry_kwargs = {'max_retries': 5, 'countdown': 60 * 5}
    retry_backoff = True


@shared_task(bind=True, base=BaseTaskWithRetry)
def student_task_notification(self, task_id):
    """Notify if the task was change"""
    logger.info('Starting student_task_notification')

    task = Task.objects.filter(id=task_id).first()
    if not task_is_valid_for_notifications(task):
        return

    language = task.cohort.language.lower()
    revision_status = task.revision_status
    subject = NOTIFICATION_STRINGS[language]['student']['subject'].format(title=task.title)
    details = NOTIFICATION_STRINGS[language]['student'][revision_status]

    actions.send_email_message('diagnostic', task.user.email, {
        'subject': subject,
        'details': details,
    })


@shared_task(bind=True, base=BaseTaskWithRetry)
def teacher_task_notification(self, task_id):
    """Notify if the task was change"""
    logger.info('Starting teacher_task_notification')

    url = os.getenv('TEACHER_URL')
    if not url:
        logger.error('TEACHER_URL is not set as environment variable')
        return

    url = re.sub('/$', '', url)

    task = Task.objects.filter(id=task_id).first()
    if not task_is_valid_for_notifications(task):
        return

    language = task.cohort.language.lower()
    subject = NOTIFICATION_STRINGS[language]['teacher']['subject'].format(first_name=task.user.first_name,
                                                                          last_name=task.user.last_name)

    details = NOTIFICATION_STRINGS[language]['teacher']['details'].format(
        first_name=task.user.first_name,
        last_name=task.user.last_name,
        title=task.title,
        url=f'{url}/cohort/{task.cohort.slug}/assignments')

    actions.send_email_message('diagnostic', task.user.email, {
        'subject': subject,
        'details': details,
    })


@shared_task(bind=False, base=BaseTaskWithRetry)
def set_cohort_user_assignments(task_id: int):
    logger.info('Executing set_cohort_user_assignments')

    def serialize_task(task):
        return {
            'id': task.id,
            'type': task.task_type,
        }

    task = Task.objects.filter(id=task_id).first()

    if not task:
        logger.error('Task not found')
        return

    cohort_user = CohortUser.objects.filter(cohort=task.cohort, user=task.user, role='STUDENT').first()

    if not cohort_user:
        logger.error('CohortUser not found')
        return

    user_history_log = cohort_user.history_log or {}
    user_history_log['delivered_assignments'] = user_history_log.get('delivered_assignments', [])
    user_history_log['pending_assignments'] = user_history_log.get('pending_assignments', [])

    user_history_log['pending_assignments'] = [
        x for x in user_history_log['pending_assignments'] if x['id'] != task.id
    ]

    user_history_log['delivered_assignments'] = [
        x for x in user_history_log['delivered_assignments'] if x['id'] != task.id
    ]

    if task.task_status == 'PENDING':
        user_history_log['pending_assignments'].append(serialize_task(task))

    if task.task_status == 'DONE':
        user_history_log['delivered_assignments'].append(serialize_task(task))

    cohort_user.history_log = user_history_log
    cohort_user.save()

    s = None
    try:
        if hasattr(task.user, 'credentialsgithub') and task.github_url:
            s = Service('rigobot', task.user.id)

        if s and task.task_status == 'DONE':
            response = s.post('/v1/finetuning/me/repository/',
                              json={
                                  'url': task.github_url,
                                  'watchers': task.user.credentialsgithub.username,
                              })
            data = response.json()
            task.rigobot_repository_id = data['id']

        elif s:
            response = s.put('/v1/finetuning/me/repository/',
                             json={
                                 'url': task.github_url,
                                 'activity_status': 'INACTIVE',
                             })
            data = response.json()
            task.rigobot_repository_id = data['id']

    except Exception:
        logger.error('App Rigobot not found')

    logger.info('History log saved')
