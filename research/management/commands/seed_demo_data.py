"""
Наполнение БД тестовыми пользователями, проектами и задачами.

Запуск локально:
    python manage.py seed_demo_data

Запуск в Docker:
    docker compose exec backend python manage.py seed_demo_data

Удалить старые demo-данные и создать заново:
    python manage.py seed_demo_data --reset

Пароль для всех demo-пользователей: 12345678 (можно изменить через --password)
"""

from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from research.models import (
    PlanTemplate,
    PlanTemplateStage,
    PlanTemplateTask,
    ProjectStatus,
    ResearchProject,
    ResearchStage,
    ReviewDecision,
    StageStatus,
    StageTask,
    SubmissionReview,
    SubmissionStatus,
    TaskStatus,
    TaskSubmission,
    TaskType,
)
from stud.models import (
    AcademicGroup,
    DegreeLevel,
    Department,
    EducationalProgram,
    EnrollmentStatus,
    StudentEnrollment,
)
from users.models import UserRole

User = get_user_model()

DEMO_PREFIX = "demo_"
DEFAULT_PASSWORD = "12345678"

USERS = {
    "head": {
        "username": f"{DEMO_PREFIX}head",
        "role": UserRole.HEAD,
        "email": "demo.head@studira.local",
        "last_name": "Кузнецов",
        "first_name": "Андрей",
        "middle_name": "Петрович",
    },
    "supervisors": [
        {
            "username": f"{DEMO_PREFIX}supervisor1",
            "role": UserRole.SUPERVISOR,
            "email": "demo.supervisor1@studira.local",
            "last_name": "Соколов",
            "first_name": "Дмитрий",
            "middle_name": "Игоревич",
        },
        {
            "username": f"{DEMO_PREFIX}supervisor2",
            "role": UserRole.SUPERVISOR,
            "email": "demo.supervisor2@studira.local",
            "last_name": "Морозова",
            "first_name": "Елена",
            "middle_name": "Александровна",
        },
    ],
    "students": [
        {
            "username": f"{DEMO_PREFIX}vinogradov",
            "role": UserRole.STUDENT,
            "email": "demo.vinogradov@studira.local",
            "last_name": "Виноградов",
            "first_name": "Артём",
            "middle_name": "Ярославович",
            "supervisor_idx": 0,
            "project": {
                "title": "Система планирования научно-исследовательских работ",
                "description": "Разработка веб-платформы для сопровождения магистерских исследований.",
                "keywords": "планирование, исследования, веб-система",
                "status": ProjectStatus.IN_PROGRESS,
                "completed_stages": 1,
            },
        },
        {
            "username": f"{DEMO_PREFIX}shishkin",
            "role": UserRole.STUDENT,
            "email": "demo.shishkin@studira.local",
            "last_name": "Шишкин",
            "first_name": "Максим",
            "middle_name": "Степанович",
            "supervisor_idx": 0,
            "project": {
                "title": "Анализ методов машинного обучения для прогнозирования нагрузки",
                "description": "Сравнительный анализ моделей и выбор подхода для прикладной задачи.",
                "keywords": "машинное обучение, прогнозирование, анализ данных",
                "status": ProjectStatus.IN_PROGRESS,
                "completed_stages": 0,
            },
        },
        {
            "username": f"{DEMO_PREFIX}egorova",
            "role": UserRole.STUDENT,
            "email": "demo.egorova@studira.local",
            "last_name": "Егорова",
            "first_name": "Варвара",
            "middle_name": "Игоревна",
            "supervisor_idx": 1,
            "project": {
                "title": "Информационная система учёта публикаций кафедры",
                "description": "Проектирование и прототипирование системы учёта научных публикаций.",
                "keywords": "публикации, учёт, информационная система",
                "status": ProjectStatus.APPROVED,
                "completed_stages": 0,
            },
        },
        {
            "username": f"{DEMO_PREFIX}timofeev",
            "role": UserRole.STUDENT,
            "email": "demo.timofeev@studira.local",
            "last_name": "Тимофеев",
            "first_name": "Илья",
            "middle_name": "Маркович",
            "supervisor_idx": 1,
            "project": {
                "title": "Модуль визуализации прогресса выполнения исследовательских задач",
                "description": "Разработка дашборда для студентов и научных руководителей.",
                "keywords": "визуализация, дашборд, исследовательские задачи",
                "status": ProjectStatus.PRE_DEFENSE,
                "completed_stages": 2,
            },
        },
    ],
}

STAGE_BLUEPRINT = [
    {
        "name": "Анализ литературы",
        "duration_days": 14,
        "tasks": [
            ("Обзор источников по теме", TaskType.FILE),
            ("Аннотированный список литературы", TaskType.FILE),
        ],
    },
    {
        "name": "Теоретическая часть",
        "duration_days": 21,
        "tasks": [
            ("Написание главы 1", TaskType.FILE),
            ("Подготовка презентации", TaskType.FILE),
        ],
    },
    {
        "name": "Практическая часть",
        "duration_days": 30,
        "tasks": [
            ("Реализация прототипа", TaskType.FILE),
            ("Публикация промежуточных результатов", TaskType.PUBLICATION),
        ],
    },
]


class Command(BaseCommand):
    help = "Create demo users, projects, stages and tasks for system testing"

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Delete existing demo data (users with demo_ prefix) before seeding",
        )
        parser.add_argument(
            "--password",
            default=DEFAULT_PASSWORD,
            help=f"Password for all demo users (default: {DEFAULT_PASSWORD})",
        )

    def handle(self, *args, **options):
        password = options["password"]
        if options["reset"]:
            self._reset_demo_data()

        with transaction.atomic():
            head = self._ensure_user(USERS["head"], password)
            supervisors = [
                self._ensure_user(data, password) for data in USERS["supervisors"]
            ]
            department = self._ensure_department(head)
            program = self._ensure_program(department)
            group = self._ensure_group(program)
            template = self._ensure_plan_template(supervisors[0])

            created_projects = 0
            created_tasks = 0
            done_tasks = 0

            for student_data in USERS["students"]:
                student = self._ensure_user(student_data, password)
                supervisor = supervisors[student_data["supervisor_idx"]]
                enrollment = self._ensure_enrollment(student, group, supervisor)
                project, tasks_stats = self._ensure_project(
                    enrollment=enrollment,
                    supervisor=supervisor,
                    project_data=student_data["project"],
                    reviewer=supervisor,
                )
                created_projects += 1
                created_tasks += tasks_stats["total"]
                done_tasks += tasks_stats["done"]

        self.stdout.write(self.style.SUCCESS("\nDemo data ready.\n"))
        self.stdout.write(f"Department: {department.name}")
        self.stdout.write(f"Group: {group.name}")
        self.stdout.write(f"Plan template: {template.name}")
        self.stdout.write(f"Projects: {created_projects}")
        self.stdout.write(f"Tasks: {created_tasks} ({done_tasks} completed)\n")
        self.stdout.write(f"Password for all demo users: {password}\n")
        self.stdout.write("Accounts:")
        self.stdout.write(f"  - {head.username} ({UserRole.HEAD.label})")
        for supervisor in supervisors:
            self.stdout.write(f"  - {supervisor.username} ({UserRole.SUPERVISOR.label})")
        for student_data in USERS["students"]:
            self.stdout.write(
                f"  - {student_data['username']} ({UserRole.STUDENT.label})"
            )

    def _reset_demo_data(self):
        demo_users = User.objects.filter(username__startswith=DEMO_PREFIX)
        user_ids = list(demo_users.values_list("id", flat=True))

        ResearchProject.objects.filter(enrollment__student_id__in=user_ids).delete()
        StudentEnrollment.objects.filter(student_id__in=user_ids).delete()
        PlanTemplate.objects.filter(created_by_id__in=user_ids).delete()
        Department.objects.filter(head_id__in=user_ids).update(head=None)

        deleted_count, _ = demo_users.delete()
        self.stdout.write(
            self.style.WARNING(f"Removed {deleted_count} demo users and related data.")
        )

    def _ensure_user(self, data: dict, password: str) -> User:
        user, created = User.objects.get_or_create(
            username=data["username"],
            defaults={
                "email": data["email"],
                "first_name": data["first_name"],
                "last_name": data["last_name"],
                "middle_name": data["middle_name"],
                "role": data["role"],
            },
        )
        if created:
            user.set_password(password)
            user.save()
            self.stdout.write(f"Created user: {user.username}")
        else:
            user.email = data["email"]
            user.first_name = data["first_name"]
            user.last_name = data["last_name"]
            user.middle_name = data["middle_name"]
            user.role = data["role"]
            user.set_password(password)
            user.save(update_fields=[
                "email", "first_name", "last_name", "middle_name", "role", "password",
            ])
            self.stdout.write(f"Updated user: {user.username}")
        return user

    def _ensure_department(self, head: User) -> Department:
        department, _ = Department.objects.get_or_create(
            name="Кафедра информационных систем (demo)",
            defaults={
                "description": "Тестовая кафедра для демонстрации Studira",
                "head": head,
            },
        )
        if department.head_id != head.id:
            department.head = head
            department.save(update_fields=["head"])
        return department

    def _ensure_program(self, department: Department) -> EducationalProgram:
        program, _ = EducationalProgram.objects.get_or_create(
            short_name="ИСТ-demo",
            defaults={
                "full_name": "Информационные системы и технологии (demo)",
                "degree_level": DegreeLevel.MAGISTR,
                "department": department,
            },
        )
        return program

    def _ensure_group(self, program: EducationalProgram) -> AcademicGroup:
        today = date.today()
        group, _ = AcademicGroup.objects.get_or_create(
            name="ИСТ-241-demo",
            defaults={
                "program": program,
                "start_date": date(today.year - 1, 9, 1),
                "end_date": date(today.year + 1, 6, 30),
            },
        )
        return group

    def _ensure_enrollment(
        self,
        student: User,
        group: AcademicGroup,
        supervisor: User,
    ) -> StudentEnrollment:
        today = date.today()
        enrollment, _ = StudentEnrollment.objects.get_or_create(
            student=student,
            defaults={
                "group": group,
                "supervisor": supervisor,
                "start_date": date(today.year - 1, 9, 1),
                "status": EnrollmentStatus.ACTIVE,
            },
        )
        if enrollment.group_id != group.id or enrollment.supervisor_id != supervisor.id:
            enrollment.group = group
            enrollment.supervisor = supervisor
            enrollment.status = EnrollmentStatus.ACTIVE
            enrollment.save(update_fields=["group", "supervisor", "status"])
        return enrollment

    def _ensure_plan_template(self, supervisor: User) -> PlanTemplate:
        template, created = PlanTemplate.objects.get_or_create(
            name="Стандартный план магистерского исследования (demo)",
            defaults={
                "description": "Шаблон этапов и задач для тестирования системы",
                "created_by": supervisor,
                "is_system": False,
            },
        )
        if created:
            for stage_idx, stage_data in enumerate(STAGE_BLUEPRINT, start=1):
                stage = PlanTemplateStage.objects.create(
                    template=template,
                    name=stage_data["name"],
                    order=stage_idx,
                    duration_days=stage_data["duration_days"],
                )
                for task_idx, (title, task_type) in enumerate(stage_data["tasks"], start=1):
                    PlanTemplateTask.objects.create(
                        stage=stage,
                        title=title,
                        order=task_idx,
                        task_type=task_type,
                    )
        return template

    def _ensure_project(
        self,
        enrollment: StudentEnrollment,
        supervisor: User,
        project_data: dict,
        reviewer: User,
    ) -> tuple[ResearchProject, dict]:
        today = date.today()
        project, created = ResearchProject.objects.get_or_create(
            enrollment=enrollment,
            defaults={
                "supervisor": supervisor,
                "title": project_data["title"],
                "description": project_data["description"],
                "keywords": project_data["keywords"],
                "start_date": today - timedelta(days=60),
                "status": project_data["status"],
            },
        )
        if not created:
            project.supervisor = supervisor
            project.title = project_data["title"]
            project.description = project_data["description"]
            project.keywords = project_data["keywords"]
            project.status = project_data["status"]
            project.save()

        if project.stages.exists():
            stats = {
                "total": StageTask.objects.filter(stage__project=project).count(),
                "done": StageTask.objects.filter(
                    stage__project=project, status=TaskStatus.DONE
                ).count(),
            }
            return project, stats

        completed_stages = project_data["completed_stages"]
        cursor = project.start_date
        total_tasks = 0
        done_tasks = 0

        for stage_idx, stage_data in enumerate(STAGE_BLUEPRINT, start=1):
            stage_start = cursor
            stage_deadline = cursor + timedelta(days=stage_data["duration_days"])
            cursor = stage_deadline + timedelta(days=1)

            if stage_idx <= completed_stages:
                stage_status = StageStatus.COMPLETED
            elif stage_idx == completed_stages + 1:
                stage_status = StageStatus.IN_PROGRESS
            else:
                stage_status = StageStatus.PENDING

            stage = ResearchStage.objects.create(
                project=project,
                name=stage_data["name"],
                order=stage_idx,
                start_date=stage_start,
                deadline=stage_deadline,
                status=stage_status,
            )

            for task_idx, (title, task_type) in enumerate(stage_data["tasks"], start=1):
                if stage_status == StageStatus.COMPLETED:
                    task_status = TaskStatus.DONE
                elif stage_status == StageStatus.IN_PROGRESS and task_idx == 1:
                    task_status = TaskStatus.IN_PROGRESS
                elif stage_status == StageStatus.IN_PROGRESS and task_idx > 1:
                    task_status = TaskStatus.TODO
                else:
                    task_status = TaskStatus.TODO

                task = StageTask.objects.create(
                    stage=stage,
                    title=title,
                    description=f"Тестовая задача: {title}",
                    deadline=stage_deadline,
                    task_type=task_type,
                    status=task_status,
                )
                total_tasks += 1

                if task_status == TaskStatus.DONE:
                    done_tasks += 1
                    self._create_approved_submission(task, reviewer)

        return project, {"total": total_tasks, "done": done_tasks}

    def _create_approved_submission(self, task: StageTask, reviewer: User) -> None:
        submission = TaskSubmission.objects.create(
            task=task,
            text=f"Тестовая сдача по задаче «{task.title}».",
            file=ContentFile(
                f"Demo submission for task #{task.id}\n".encode("utf-8"),
                name=f"demo_task_{task.id}.txt",
            ),
            status=SubmissionStatus.APPROVED,
            created_at=timezone.now() - timedelta(days=3),
        )
        SubmissionReview.objects.create(
            reviewer=reviewer,
            submission=submission,
            decision=ReviewDecision.APPROVED,
            comment="Принято. Тестовая проверка.",
        )
