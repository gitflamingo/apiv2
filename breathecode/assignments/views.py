from django.http import HttpResponseRedirect, StreamingHttpResponse
from breathecode.authenticate.actions import get_user_language
from breathecode.authenticate.models import ProfileAcademy
import logging, hashlib, os
from django.shortcuts import render
from django.utils import timezone
from django.db.models import Q
from rest_framework.views import APIView
from django.contrib.auth.models import AnonymousUser
from django.contrib import messages
from breathecode.utils.api_view_extensions.api_view_extensions import APIViewExtensions
from breathecode.utils import ValidationException, capable_of, localize_query, GenerateLookupsMixin, num_to_roman, response_207
from breathecode.admissions.models import Academy, CohortUser, Cohort
from breathecode.authenticate.models import Token
from rest_framework.exceptions import PermissionDenied
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework import status
from breathecode.utils import APIException
from breathecode.utils.service import Service
from .models import Task, FinalProject, UserAttachment
from .actions import deliver_task
from .caches import TaskCache
from .forms import DeliverAssigntmentForm
from slugify import slugify
from .serializers import (TaskGETSerializer, PUTTaskSerializer, PostTaskSerializer, TaskGETDeliverSerializer,
                          FinalProjectGETSerializer, PostFinalProjectSerializer, PUTFinalProjectSerializer,
                          UserAttachmentSerializer, TaskAttachmentSerializer)
from .actions import sync_cohort_tasks
import breathecode.assignments.tasks as tasks
from breathecode.utils.multi_status_response import MultiStatusResponse
from breathecode.utils.i18n import translation

logger = logging.getLogger(__name__)

MIME_ALLOW = [
    'image/png', 'image/svg+xml', 'image/jpeg', 'image/gif', 'video/quicktime', 'video/mp4', 'audio/mpeg',
    'application/pdf', 'image/jpg'
]

IMAGES_MIME_ALLOW = ['image/png', 'image/svg+xml', 'image/jpeg', 'image/jpg']

USER_ASSIGNMENTS_BUCKET = os.getenv('USER_ASSIGNMENTS_BUCKET', None)


class TaskTeacherView(APIView):

    def get(self, request, task_id=None, user_id=None):
        items = Task.objects.all()
        logger.debug(f'Found {items.count()} tasks')

        profile_ids = ProfileAcademy.objects.filter(user=request.user.id).values_list('academy__id',
                                                                                      flat=True)
        if not profile_ids:
            raise ValidationException(
                'The quest user must belong to at least one academy to be able to request student tasks',
                code=400,
                slug='without-profile-academy')

        items = items.filter(Q(cohort__academy__id__in=profile_ids) | Q(cohort__isnull=True))

        academy = request.GET.get('academy', None)
        if academy is not None:
            items = items.filter(Q(cohort__academy__slug__in=academy.split(',')) | Q(cohort__isnull=True))

        user = request.GET.get('user', None)
        if user is not None:
            items = items.filter(user__id__in=user.split(','))

        # tasks these cohorts (not the users, but the tasks belong to the cohort)
        cohort = request.GET.get('cohort', None)
        if cohort is not None:
            cohorts = cohort.split(',')
            ids = [x for x in cohorts if x.isnumeric()]
            slugs = [x for x in cohorts if not x.isnumeric()]
            items = items.filter(Q(cohort__slug__in=slugs) | Q(cohort__id__in=ids))

        # tasks from users that belong to these cohort
        stu_cohort = request.GET.get('stu_cohort', None)
        if stu_cohort is not None:
            ids = stu_cohort.split(',')

            stu_cohorts = stu_cohort.split(',')
            ids = [x for x in stu_cohorts if x.isnumeric()]
            slugs = [x for x in stu_cohorts if not x.isnumeric()]

            items = items.filter(
                Q(user__cohortuser__cohort__id__in=ids) | Q(user__cohortuser__cohort__slug__in=slugs),
                user__cohortuser__role='STUDENT',
            )

        edu_status = request.GET.get('edu_status', None)
        if edu_status is not None:
            items = items.filter(user__cohortuser__educational_status__in=edu_status.split(','))

        # tasks from users that belong to these cohort
        teacher = request.GET.get('teacher', None)
        if teacher is not None:
            teacher_cohorts = CohortUser.objects.filter(user__id__in=teacher.split(','),
                                                        role='TEACHER').values_list('cohort__id', flat=True)
            items = items.filter(user__cohortuser__cohort__id__in=teacher_cohorts,
                                 user__cohortuser__role='STUDENT').distinct()

        task_status = request.GET.get('task_status', None)
        if task_status is not None:
            items = items.filter(task_status__in=task_status.split(','))

        revision_status = request.GET.get('revision_status', None)
        if revision_status is not None:
            items = items.filter(revision_status__in=revision_status.split(','))

        task_type = request.GET.get('task_type', None)
        if task_type is not None:
            items = items.filter(task_type__in=task_type.split(','))

        items = items.order_by('created_at')

        serializer = TaskGETSerializer(items, many=True)
        return Response(serializer.data)


@api_view(['POST'])
def sync_cohort_tasks_view(request, cohort_id=None):
    item = Cohort.objects.filter(id=cohort_id).first()
    if item is None:
        raise ValidationException('Cohort not found')

    syncronized = sync_cohort_tasks(item)
    if len(syncronized) == 0:
        raise ValidationException('No tasks updated')

    serializer = TaskGETSerializer(syncronized, many=True)
    return Response(serializer.data, status=status.HTTP_200_OK)


class FinalProjectScreenshotView(APIView):
    """
    List all snippets, or create a new snippet.
    """

    def upload(self, request, update=False):
        from ..services.google_cloud import Storage

        files = request.data.getlist('file')
        names = request.data.getlist('name')
        result = {
            'data': [],
            'instance': [],
        }

        file = request.data.get('file')
        slugs = []

        for index in range(0, len(files)):
            file = files[index]
            if file.content_type not in IMAGES_MIME_ALLOW:
                raise ValidationException(
                    f'You can upload only files on the following formats: {",".join(IMAGES_MIME_ALLOW)}')

        for index in range(0, len(files)):
            file = files[index]
            name = names[index] if len(names) else file.name
            file_bytes = file.read()
            hash = hashlib.sha256(file_bytes).hexdigest()
            slug = slugify(name)

            slugs.append(slug)
            data = {
                'hash': hash,
                'mime': file.content_type,
            }

            # upload file section
            storage = Storage()
            cloud_file = storage.file(USER_ASSIGNMENTS_BUCKET, hash)
            cloud_file.upload(file, content_type=file.content_type)
            data['url'] = cloud_file.url()

        return data

    def post(self, request, user_id=None):
        files = self.upload(request)

        return Response(files)


class FinalProjectMeView(APIView):
    """
    List all snippets, or create a new snippet.
    """

    def get(self, request, project_id=None, user_id=None):
        if not user_id:
            user_id = request.user.id

        if project_id is not None:
            item = FinalProject.objects.filter(id=project_id, user__id=user_id).first()
            if item is None:
                raise ValidationException('Project not found', code=404, slug='project-not-found')

            serializer = FinalProjectGETSerializer(item, many=False)
            return Response(serializer.data)

        items = FinalProject.objects.filter(members__id=user_id)

        project_status = request.GET.get('project_status', None)
        if project_status is not None:
            items = items.filter(project_status__in=project_status.split(','))

        members = request.GET.get('members', None)
        if members is not None and isinstance(members, list):
            items = items.filter(members__id__in=members)

        revision_status = request.GET.get('revision_status', None)
        if revision_status is not None:
            items = items.filter(revision_status__in=revision_status.split(','))

        visibility_status = request.GET.get('visibility_status', None)
        if visibility_status is not None:
            items = items.filter(visibility_status__in=visibility_status.split(','))
        else:
            items = items.filter(visibility_status='PUBLIC')

        cohort = request.GET.get('cohort', None)
        if cohort is not None:
            if cohort == 'null':
                items = items.filter(cohort__isnull=True)
            else:
                cohorts = cohort.split(',')
                ids = [x for x in cohorts if x.isnumeric()]
                slugs = [x for x in cohorts if not x.isnumeric()]
                items = items.filter(Q(cohort__slug__in=slugs) | Q(cohort__id__in=ids))

        serializer = FinalProjectGETSerializer(items, many=True)
        return Response(serializer.data)

    def post(self, request, user_id=None):

        # only create tasks for yourself
        user_id = request.user.id

        payload = request.data

        if isinstance(request.data, list) == False:
            payload = [request.data]

        members_set = set(payload[0]['members'])
        members_set.add(user_id)
        payload[0]['members'] = list(members_set)

        serializer = PostFinalProjectSerializer(data=payload,
                                                context={
                                                    'request': request,
                                                    'user_id': user_id
                                                },
                                                many=True)
        if serializer.is_valid():
            serializer.save()
            # tasks.teacher_task_notification.delay(serializer.data['id'])
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def put(self, request, project_id=None):

        def update(_req, data, _id=None, only_validate=True):
            lang = get_user_language(request)

            if _id is None:
                raise ValidationException('Missing project id to update', slug='missing-project-id')

            item = FinalProject.objects.filter(id=_id).first()
            if item is None:
                raise ValidationException('Final Project not found', slug='project-not-found')

            if 'cohort' not in data:
                raise ValidationException(
                    translation(lang,
                                en='Final project cohort missing',
                                es='Falta la cohorte del proyecto final',
                                slug='cohort-missing'))
            project_cohort = Cohort.objects.filter(id=data['cohort']).first()
            staff = ProfileAcademy.objects.filter(~Q(role__slug='student'),
                                                  academy__id=project_cohort.academy.id,
                                                  user__id=request.user.id).first()

            if not item.members.filter(id=request.user.id).exists() and staff is None:
                raise ValidationException(
                    translation(lang,
                                en='You are not a member of this project',
                                es='No eres miembro de este proyecto',
                                slug='not-a-member'))

            serializer = PUTFinalProjectSerializer(item, data=data, context={'request': _req})
            if serializer.is_valid():
                if not only_validate:
                    serializer.save()
                return status.HTTP_200_OK, serializer.data
            return status.HTTP_400_BAD_REQUEST, serializer.errors

        if project_id is not None:
            code, data = update(request, request.data, project_id, only_validate=False)
            return Response(data, status=code)

        else:  # project_id is None:

            if isinstance(request.data, list) == False:
                raise ValidationException(
                    'You are trying to update many project at once but you didn\'t provide a list on the payload',
                    slug='update-without-list')

            for item in request.data:
                if 'id' not in item:
                    item['id'] = None
                code, data = update(request, item, item['id'], only_validate=True)
                if code != status.HTTP_200_OK:
                    return Response(data, status=code)

            updated_projects = []
            for item in request.data:
                code, data = update(request, item, item['id'], only_validate=False)
                if code == status.HTTP_200_OK:
                    updated_projects.append(data)

            return Response(updated_projects, status=status.HTTP_200_OK)


class CohortTaskView(APIView, GenerateLookupsMixin):
    """
    List all snippets, or create a new snippet.
    """
    extensions = APIViewExtensions(cache=TaskCache, sort='-created_at', paginate=True)

    @capable_of('read_assignment')
    def get(self, request, cohort_id, academy_id):
        handler = self.extensions(request)
        cache = handler.cache.get()
        if cache is not None:
            return Response(cache, status=status.HTTP_200_OK)

        items = Task.objects.all()
        lookup = {}

        if isinstance(cohort_id, int) or cohort_id.isnumeric():
            lookup['cohort__id'] = cohort_id
        else:
            lookup['cohort__slug'] = cohort_id

        task_type = request.GET.get('task_type', None)
        if task_type is not None:
            lookup['task_type__in'] = task_type.split(',')

        task_status = request.GET.get('task_status', None)
        if task_status is not None:
            lookup['task_status__in'] = task_status.split(',')

        revision_status = request.GET.get('revision_status', None)
        if revision_status is not None:
            lookup['revision_status__in'] = revision_status.split(',')

        educational_status = request.GET.get('educational_status', None)
        if educational_status is not None:
            lookup['user__cohortuser__educational_status__in'] = educational_status.split(',')

        like = request.GET.get('like', None)
        if like is not None and like != 'undefined' and like != '':
            items = items.filter(Q(associated_slug__icontains=like) | Q(title__icontains=like))

        # tasks from users that belong to these cohort
        student = request.GET.get('student', None)
        if student is not None:
            lookup['user__cohortuser__user__id__in'] = student.split(',')
            lookup['user__cohortuser__role'] = 'STUDENT'

        if educational_status is not None or student is not None:
            items = items.distinct()

        items = items.filter(**lookup)
        items = handler.queryset(items)

        serializer = TaskGETSerializer(items, many=True)
        return handler.response(serializer.data)


class TaskMeAttachmentView(APIView):
    """
    List all snippets, or create a new snippet.
    """

    @capable_of('read_assignment')
    def get(self, request, task_id, academy_id):

        item = Task.objects.filter(id=task_id).first()
        if item is None:
            raise ValidationException('Task not found', code=404, slug='task-not-found')

        allowed = item.user.id == request.user.id
        if not allowed:
            # request user belongs to the same academy as the cohort
            allowed = item.cohort.academy.id == int(academy_id)

        if not allowed:
            raise PermissionDenied(
                'Attachments can only be reviewed by their authors or the academy staff with read_assignment capability'
            )

        serializer = TaskAttachmentSerializer(item.attachments.all(), many=True)
        return Response(serializer.data)

    def upload(self, request, update=False, mime_allow=None):
        from ..services.google_cloud import Storage

        files = request.data.getlist('file')
        names = request.data.getlist('name')
        result = {
            'data': [],
            'instance': [],
        }

        file = request.data.get('file')
        slugs = []

        if not file:
            raise ValidationException('Missing file in request', code=400)

        if not len(files):
            raise ValidationException('empty files in request')

        if not len(names):
            for file in files:
                names.append(file.name)

        elif len(files) != len(names):
            raise ValidationException('numbers of files and names not match')

        if mime_allow is None:
            mime_allow = MIME_ALLOW

        # files validation below
        for index in range(0, len(files)):
            file = files[index]
            if file.content_type not in mime_allow:
                raise ValidationException(
                    f'You can upload only files on the following formats: {",".join(mime_allow)}')

        for index in range(0, len(files)):
            file = files[index]
            name = names[index] if len(names) else file.name
            file_bytes = file.read()
            hash = hashlib.sha256(file_bytes).hexdigest()
            slug = str(request.user.id) + '-' + slugify(name)

            slug_number = UserAttachment.objects.filter(slug__startswith=slug).exclude(hash=hash).count() + 1
            if slug_number > 1:
                while True:
                    roman_number = num_to_roman(slug_number, lower=True)
                    slug = f'{slug}-{roman_number}'
                    if not slug in slugs:
                        break
                    slug_number = slug_number + 1

            slugs.append(slug)
            data = {
                'hash': hash,
                'slug': slug,
                'mime': file.content_type,
                'name': name,
                'categories': [],
                'user': request.user.id,
            }

            media = UserAttachment.objects.filter(hash=hash, user__id=request.user.id).first()
            if media:
                data['id'] = media.id
                data['url'] = media.url

            else:
                # upload file section
                storage = Storage()
                cloud_file = storage.file(USER_ASSIGNMENTS_BUCKET, hash)
                cloud_file.upload(file, content_type=file.content_type)
                data['url'] = cloud_file.url()

            result['data'].append(data)

        from django.db.models import Q
        query = None
        datas_with_id = [x for x in result['data'] if 'id' in x]
        for x in datas_with_id:
            if query:
                query = query | Q(id=x['id'])
            else:
                query = Q(id=x['id'])

        if query:
            result['instance'] = UserAttachment.objects.filter(query)

        return result

    def put(self, request, task_id):

        item = Task.objects.filter(id=task_id, user__id=request.user.id).first()
        if item is None:
            raise ValidationException('Task not found', code=404, slug='task-not-found')

        # TODO: mime types are not being validated on the backend
        upload = self.upload(request, update=True, mime_allow=None)
        serializer = UserAttachmentSerializer(upload['instance'],
                                              data=upload['data'],
                                              context=upload['data'],
                                              many=True)

        if serializer.is_valid():
            serializer.save()

            for att in serializer.instance:
                item.attachments.add(att)
                item.save()

            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class TaskMeView(APIView):
    """
    List all snippets, or create a new snippet.
    """
    extensions = APIViewExtensions(cache=TaskCache, cache_per_user=True, paginate=True)

    def get(self, request, task_id=None, user_id=None):
        handler = self.extensions(request)
        cache = handler.cache.get()
        if cache is not None:
            return Response(cache, status=status.HTTP_200_OK)

        if not user_id:
            user_id = request.user.id

        if task_id is not None:
            item = Task.objects.filter(id=task_id, user__id=user_id).first()
            if item is None:
                raise ValidationException('Task not found', code=404, slug='task-not-found')

            serializer = TaskGETSerializer(item, many=False)
            return Response(serializer.data)

        items = Task.objects.filter(user__id=user_id)

        task_type = request.GET.get('task_type', None)
        if task_type is not None:
            items = items.filter(task_type__in=task_type.split(','))

        task_status = request.GET.get('task_status', None)
        if task_status is not None:
            items = items.filter(task_status__in=task_status.split(','))

        revision_status = request.GET.get('revision_status', None)
        if revision_status is not None:
            items = items.filter(revision_status__in=revision_status.split(','))

        cohort = request.GET.get('cohort', None)
        if cohort is not None:
            if cohort == 'null':
                items = items.filter(cohort__isnull=True)
            else:
                cohorts = cohort.split(',')
                ids = [x for x in cohorts if x.isnumeric()]
                slugs = [x for x in cohorts if not x.isnumeric()]
                items = items.filter(Q(cohort__slug__in=slugs) | Q(cohort__id__in=ids))

        a_slug = request.GET.get('associated_slug', None)
        if a_slug is not None:
            items = items.filter(associated_slug__in=[p.lower() for p in a_slug.split(',')])

        items = handler.queryset(items)

        serializer = TaskGETSerializer(items, many=True)
        return handler.response(serializer.data)

    def put(self, request, task_id=None):

        def update(_req, data, _id=None, only_validate=True):
            if _id is None:
                raise ValidationException('Missing task id to update', slug='missing=task-id')

            item = Task.objects.filter(id=_id).first()
            if item is None:
                raise ValidationException('Task not found', slug='task-not-found', code=404)
            serializer = PUTTaskSerializer(item, data=data, context={'request': _req})
            if serializer.is_valid():
                if not only_validate:
                    serializer.save()
                    if _req.user.id != item.user.id:
                        tasks.student_task_notification.delay(item.id)
                return status.HTTP_200_OK, serializer.data
            return status.HTTP_400_BAD_REQUEST, serializer.errors

        if task_id is not None:
            code, data = update(request, request.data, task_id, only_validate=False)
            return Response(data, status=code)

        else:  # task_id is None:

            if isinstance(request.data, list) == False:
                raise ValidationException(
                    'You are trying to update many tasks at once but you didn\'t provide a list on the payload',
                    slug='update-whout-list')

            for item in request.data:
                if 'id' not in item:
                    item['id'] = None
                code, data = update(request, item, item['id'], only_validate=True)
                if code != status.HTTP_200_OK:
                    return Response(data, status=code)

            updated_tasks = []
            for item in request.data:
                code, data = update(request, item, item['id'], only_validate=False)
                if code == status.HTTP_200_OK:
                    updated_tasks.append(data)

            return Response(updated_tasks, status=status.HTTP_200_OK)

    def post(self, request, user_id=None):

        # only create tasks for yourself
        if user_id is None:
            user_id = request.user.id

        payload = request.data

        if isinstance(request.data, list) == False:
            payload = [request.data]

        serializer = PostTaskSerializer(data=payload,
                                        context={
                                            'request': request,
                                            'user_id': user_id
                                        },
                                        many=True)
        if serializer.is_valid():
            serializer.save()
            # tasks.teacher_task_notification.delay(serializer.data['id'])
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, task_id=None):

        if task_id is not None:
            item = Task.objects.filter(id=task_id).first()
            if item is None:
                raise ValidationException('Task not found', code=404, slug='task-not-found')

            if item.user.id != request.user.id:
                raise ValidationException('Task not found for this user',
                                          code=400,
                                          slug='task-not-found-for-this-user')

            item.delete()

        else:  # task_id is None:
            ids = request.GET.get('id', '')
            if ids == '':
                raise ValidationException('Missing querystring propery id for bulk delete tasks',
                                          slug='missing-id')

            ids_to_delete = [
                int(id.strip()) if id.strip().isnumeric() else id.strip() for id in ids.split(',')
            ]

            all = Task.objects.filter(id__in=ids_to_delete)
            do_not_belong = all.exclude(user__id=request.user.id)
            belong = all.filter(user__id=request.user.id)

            responses = []

            for task in all:
                if task.id in ids_to_delete:
                    ids_to_delete.remove(task.id)

            if belong:
                responses.append(MultiStatusResponse(code=204, queryset=belong))

            if do_not_belong:
                responses.append(
                    MultiStatusResponse('Task not found for this user',
                                        code=400,
                                        slug='task-not-found-for-this-user',
                                        queryset=do_not_belong))

            if ids_to_delete:
                responses.append(
                    MultiStatusResponse('Task not found',
                                        code=404,
                                        slug='task-not-found',
                                        queryset=ids_to_delete))

            if do_not_belong or ids_to_delete:
                response = response_207(responses, 'associated_slug')
                belong.delete()
                return response

            belong.delete()

        return Response(None, status=status.HTTP_204_NO_CONTENT)


class TaskMeDeliverView(APIView):
    """
    List all snippets, or create a new snippet.
    """

    @capable_of('task_delivery_details')
    def get(self, request, task_id, academy_id):

        item = Task.objects.filter(id=task_id).first()
        if item is None:
            raise ValidationException('Task not found')

        serializer = TaskGETDeliverSerializer(item, many=False)
        return Response(serializer.data)


def deliver_assignment_view(request, task_id, token):

    if request.method == 'POST':
        _dict = request.POST.copy()
        form = DeliverAssigntmentForm(_dict)

        if 'github_url' not in _dict or _dict['github_url'] == '':
            messages.error(request, 'Github URL is required')
            return render(request, 'form.html', {'form': form})

        token = Token.objects.filter(key=_dict['token']).first()
        if token is None or token.expires_at < timezone.now():
            messages.error(request, f'Invalid or expired deliver token {_dict["token"]}')
            return render(request, 'form.html', {'form': form})

        task = Task.objects.filter(id=_dict['task_id']).first()
        if task is None:
            messages.error(request, 'Invalid task id')
            return render(request, 'form.html', {'form': form})

        deliver_task(
            task=task,
            github_url=_dict['github_url'],
            live_url=_dict['live_url'],
        )

        if 'callback' in _dict and _dict['callback'] != '':
            return HttpResponseRedirect(redirect_to=_dict['callback'] + '?msg=The task has been delivered')
        else:
            return render(request, 'message.html', {'message': 'The task has been delivered'})
    else:
        task = Task.objects.filter(id=task_id).first()
        if task is None:
            return render(request, 'message.html', {
                'message': f'Invalid assignment id {str(task_id)}',
            })

        _dict = request.GET.copy()
        _dict['callback'] = request.GET.get('callback', '')
        _dict['token'] = token
        _dict['task_name'] = task.title
        _dict['task_id'] = task.id
        form = DeliverAssigntmentForm(_dict)
    return render(
        request,
        'form.html',
        {
            'form': form,
            # 'heading': 'Deliver project assignment',
            'intro': 'Please fill the following information to deliver your assignment',
            'btn_lable': 'Deliver Assignment'
        })


class SubtaskMeView(APIView):
    """
    List all snippets, or create a new snippet.
    """

    def get(self, request, task_id):

        item = Task.objects.filter(id=task_id, user__id=request.user.id).first()
        if item is None:
            raise ValidationException('Task not found', code=404, slug='task-not-found')

        return Response(item.subtasks)

    def put(self, request, task_id):

        item = Task.objects.filter(id=task_id, user__id=request.user.id).first()
        if item is None:
            raise ValidationException('Task not found', code=404, slug='task-not-found')

        if not isinstance(request.data, list):
            raise ValidationException('Subtasks json must be an array of tasks',
                                      code=404,
                                      slug='json-as-array')

        subtasks_ids = []
        for t in request.data:
            if not 'id' in t:
                raise ValidationException('All substasks must have a unique id',
                                          code=404,
                                          slug='missing-subtask-unique-id')
            else:
                try:
                    found = subtasks_ids.index(t['id'])
                    raise ValidationException(
                        f'Duplicated subtask id {t["id"]} for the assignment on position {found}',
                        code=404,
                        slug='duplicated-subtask-unique-id')
                except Exception:
                    subtasks_ids.append(t['id'])

            if not 'status' in t:
                raise ValidationException('All substasks must have a status',
                                          code=404,
                                          slug='missing-subtask-status')
            elif t['status'] not in ['DONE', 'PENDING']:
                raise ValidationException('Subtask status must be DONE or PENDING, received: ' + t['status'])

            if not 'label' in t:
                raise ValidationException('All substasks must have a label',
                                          code=404,
                                          slug='missing-task-label')

        item.subtasks = request.data
        item.save()

        return Response(item.subtasks)


class MeCodeRevisionView(APIView):

    def get(self, request, task_id=None):
        lang = get_user_language(request)
        params = {}
        for key in request.GET.keys():
            params[key] = request.GET.get(key)

        if task_id and not (task := Task.objects.filter(id=task_id, user__id=request.user.id).first()):
            raise ValidationException('Task not found', code=404, slug='task-not-found')

        elif not hasattr(request.user, 'credentialsgithub'):
            raise ValidationException(translation(lang,
                                                  en='You need to connect your Github account first',
                                                  es='Necesitas conectar tu cuenta de Github primero',
                                                  slug='github-account-not-connected'),
                                      code=400)

        if task_id and task:
            params['repo'] = task.github_url

        params['github_username'] = request.user.credentialsgithub.username

        s = Service('rigobot', request.user.id)
        response = s.get('/v1/finetuning/me/coderevision', params=params, stream=True)
        resource = StreamingHttpResponse(
            response.raw,
            status=response.status_code,
            reason=response.reason,
        )

        header_keys = [
            x for x in response.headers.keys() if x != 'Transfer-Encoding' and x != 'Content-Encoding'
            and x != 'Keep-Alive' and x != 'Connection'
        ]

        for header in header_keys:
            resource[header] = response.headers[header]

        return resource

    def post(self, request, task_id):
        lang = get_user_language(request)
        params = {}
        for key in request.GET.keys():
            params[key] = request.GET.get(key)

        item = Task.objects.filter(id=task_id, user__id=request.user.id).first()
        if item is None:
            raise ValidationException('Task not found', code=404, slug='task-not-found')

        elif not hasattr(request.user, 'credentialsgithub'):
            raise ValidationException(translation(lang,
                                                  en='You need to connect your Github account first',
                                                  es='Necesitas conectar tu cuenta de Github primero',
                                                  slug='github-account-not-connected'),
                                      code=400)

        params['github_username'] = request.user.credentialsgithub.username
        params['repo'] = item.github_url

        s = Service('rigobot', request.user.id)
        response = s.post('/v1/finetuning/coderevision/', data=request.data, stream=True, params=params)
        resource = StreamingHttpResponse(
            response.raw,
            status=response.status_code,
            reason=response.reason,
        )

        header_keys = [
            x for x in response.headers.keys() if x != 'Transfer-Encoding' and x != 'Content-Encoding'
            and x != 'Keep-Alive' and x != 'Connection'
        ]

        for header in header_keys:
            resource[header] = response.headers[header]

        return resource


class AcademyTaskCodeRevisionView(APIView):

    @capable_of('read_assignment')
    def get(self, request, academy_id, task_id=None):
        if task_id and not (task := Task.objects.filter(id=task_id, cohort__academy__id=academy_id).first()):
            raise ValidationException('Task not found', code=404, slug='task-not-found')

        params = {}
        for key in request.GET.keys():
            params[key] = request.GET.get(key)

        if task_id:
            params['repo'] = task.github_url

        s = Service('rigobot')
        response = s.get('/v1/finetuning/coderevision', params=params, stream=True)
        resource = StreamingHttpResponse(
            response.raw,
            status=response.status_code,
            reason=response.reason,
        )

        header_keys = [
            x for x in response.headers.keys() if x != 'Transfer-Encoding' and x != 'Content-Encoding'
            and x != 'Keep-Alive' and x != 'Connection'
        ]

        for header in header_keys:
            resource[header] = response.headers[header]

        return resource


class MeCodeRevisionRateView(APIView):

    def post(self, request, coderevision_id):
        s = Service('rigobot', request.user.id)
        response = s.post(f'/v1/finetuning/rate/coderevision/{coderevision_id}',
                          data=request.data,
                          stream=True)
        resource = StreamingHttpResponse(
            response.raw,
            status=response.status_code,
            reason=response.reason,
        )

        header_keys = [
            x for x in response.headers.keys() if x != 'Transfer-Encoding' and x != 'Content-Encoding'
            and x != 'Keep-Alive' and x != 'Connection'
        ]

        for header in header_keys:
            resource[header] = response.headers[header]

        return resource


class MeCommitFileView(APIView):

    def get(self, request, commitfile_id=None, task_id=None):
        lang = get_user_language(request)
        params = {}
        for key in request.GET.keys():
            params[key] = request.GET.get(key)

        s = Service('rigobot', request.user.id)
        url = '/v1/finetuning/commitfile'
        task = None
        if commitfile_id is not None:
            url = f'{url}/{commitfile_id}'

        elif not (task := Task.objects.filter(id=task_id, user__id=request.user.id).first()):
            raise ValidationException(translation(lang,
                                                  en='Task not found',
                                                  es='Tarea no encontrada',
                                                  slug='task-not-found'),
                                      code=404)

        elif not hasattr(task.user, 'credentialsgithub'):
            raise ValidationException(translation(lang,
                                                  en='You need to connect your Github account first',
                                                  es='Necesitas conectar tu cuenta de Github primero',
                                                  slug='github-account-not-connected'),
                                      code=400)

        else:
            params['repo'] = task.github_url
            params['watcher'] = task.user.credentialsgithub.username

        response = s.get(url, params=params, stream=True)
        resource = StreamingHttpResponse(
            response.raw,
            status=response.status_code,
            reason=response.reason,
        )

        header_keys = [
            x for x in response.headers.keys() if x != 'Transfer-Encoding' and x != 'Content-Encoding'
            and x != 'Keep-Alive' and x != 'Connection'
        ]

        for header in header_keys:
            resource[header] = response.headers[header]

        return resource
