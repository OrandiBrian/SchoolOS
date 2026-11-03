import os
import secrets
import uuid
from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import (
    AcademicYear,
    AnnualEnrollment,
    Grade,
    Guardian,
    GuardianLink,
    Learner,
    LearningGroup,
    School,
    SchoolMembership,
    StaffRecord,
    TeacherClassAssignment,
    Term,
)
from core.services import create_learner


class Command(BaseCommand):
    help = "Create explicit, idempotent, entirely fictional SchoolOS demo data."

    def add_arguments(self, parser):
        parser.add_argument(
            "--password",
            help=(
                "Password for newly created demo accounts. Prefer DEMO_PASSWORD "
                "to avoid shell history."
            ),
        )
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Reset all fictional demo account passwords to the supplied password.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError(
                "Refusing demo data while DJANGO_DEBUG=false. Use a local "
                "development environment with fictional records."
            )
        supplied_password = options["password"] or os.environ.get("DEMO_PASSWORD")
        generated_password = None
        if not supplied_password:
            generated_password = secrets.token_urlsafe(18)
            supplied_password = generated_password
        if len(supplied_password) < 12:
            raise CommandError("The demo password must contain at least 12 characters.")

        created_users = []
        copied_learners = 0
        with transaction.atomic():
            school, _ = School.objects.get_or_create(
                name="Lofty Creek Demo School (Fictional)",
                defaults={
                    "admission_prefix": "LCCS",
                    "motto": "Learn with care",
                    "address": "Fictional demonstration campus",
                    "phone": "+254700000001",
                    "email": "office@demo.example.test",
                },
            )
            year_2026 = self._year(
                school,
                "2026",
                date(2026, 1, 5),
                date(2026, 10, 30),
                False,
            )
            year_2027 = self._year(
                school,
                "2027",
                date(2027, 1, 4),
                date(2027, 11, 26),
                True,
            )
            self._terms(year_2026, "2026")
            self._terms(year_2027, "2027")

            grades = {}
            for order, (code, name) in enumerate(
                [
                    ("PG", "Playgroup"),
                    ("PP1", "PP1"),
                    ("PP2", "PP2"),
                    ("G1", "Grade 1"),
                    ("G2", "Grade 2"),
                    ("G3", "Grade 3"),
                    ("G4", "Grade 4"),
                    ("G5", "Grade 5"),
                ],
                start=1,
            ):
                grades[code], _ = Grade.objects.get_or_create(
                    school=school,
                    code=code,
                    defaults={"name": name, "sort_order": order},
                )

            groups = {}
            for year in (year_2026, year_2027):
                for code, grade in grades.items():
                    if year.name == "2026" and code == "G5":
                        continue
                    stream_name = "A"
                    groups[(year.name, code, stream_name)], _ = (
                        LearningGroup.objects.get_or_create(
                            academic_year=year,
                            grade=grade,
                            name=stream_name,
                            defaults={"capacity": 30},
                        )
                    )
                if year == year_2027:
                    groups[(year.name, "G1", "B")], _ = (
                        LearningGroup.objects.get_or_create(
                            academic_year=year,
                            grade=grades["G1"],
                            name="B",
                            defaults={"capacity": 28},
                        )
                    )

            head_staff = self._staff(
                school, "Demo", "Head", StaffRecord.Category.HEAD, "DEMO-001"
            )
            secretary_staff = self._staff(
                school,
                "Demo",
                "Secretary",
                StaffRecord.Category.SECRETARY,
                "DEMO-002",
            )
            teacher_staff = self._staff(
                school, "Demo", "Teacher", StaffRecord.Category.TEACHER, "DEMO-003"
            )
            director_staff = self._staff(
                school,
                "Demo",
                "Director",
                StaffRecord.Category.DIRECTOR,
                "DEMO-004",
            )
            board_staff = self._staff(
                school, "Demo", "Board", StaffRecord.Category.BOARD, "DEMO-005"
            )
            self._staff(
                school,
                "Demo",
                "Cook",
                StaffRecord.Category.SUPPORT,
                "DEMO-006",
            )

            user_specs = [
                ("demo.head", "Demo", "Head", SchoolMembership.Role.HEAD, head_staff),
                (
                    "demo.secretary",
                    "Demo",
                    "Secretary",
                    SchoolMembership.Role.SECRETARY,
                    secretary_staff,
                ),
                (
                    "demo.teacher",
                    "Demo",
                    "Teacher",
                    SchoolMembership.Role.TEACHER,
                    teacher_staff,
                ),
                (
                    "demo.director",
                    "Demo",
                    "Director",
                    SchoolMembership.Role.DIRECTOR,
                    director_staff,
                ),
                (
                    "demo.board",
                    "Demo",
                    "Board",
                    SchoolMembership.Role.BOARD,
                    board_staff,
                ),
            ]
            memberships = {}
            for username, first_name, last_name, role, staff in user_specs:
                User = get_user_model()
                user, user_created = User.objects.get_or_create(
                    username=username,
                    defaults={"first_name": first_name, "last_name": last_name},
                )
                if user_created:
                    user.set_password(supplied_password)
                    user.full_clean()
                    user.save(update_fields=["password"])
                    created_users.append(username)
                elif options["reset_passwords"]:
                    user.set_password(supplied_password)
                    user.save(update_fields=["password"])
                membership, _ = SchoolMembership.objects.get_or_create(
                    school=school,
                    user=user,
                    defaults={"role": role, "staff_record": staff},
                )
                membership.role = role
                membership.staff_record = staff
                membership.active = True
                membership.full_clean()
                membership.save()
                memberships[role] = membership

            for group_key in [("2027", "PP1", "A"), ("2027", "G1", "A")]:
                TeacherClassAssignment.objects.get_or_create(
                    membership=memberships[SchoolMembership.Role.TEACHER],
                    learning_group=groups[group_key],
                )

            guardians = {}
            for index, (first_name, last_name, phone) in enumerate(
                [
                    ("Malaika", "Otieno", "+254700100001"),
                    ("Njeri", "Kamau", "+254700100002"),
                    ("Amani", "Mwangi", "+254700100003"),
                    ("Zuri", "Hassan", "+254700100004"),
                ],
                start=1,
            ):
                guardian, _ = Guardian.objects.get_or_create(
                    school=school,
                    phone=phone,
                    defaults={"first_name": first_name, "last_name": last_name},
                )
                guardians[index] = guardian

            learner_specs = [
                ("Amina", "Otieno", "2018-04-12", "female", "PP1", 1),
                ("Zawadi", "Otieno", "2020-08-21", "female", "PG", 1),
                ("Baraka", "Kamau", "2017-02-07", "male", "PP2", 2),
                ("Neema", "Kamau", "2016-11-16", "female", "G1", 2),
                ("Jabari", "Mwangi", "2015-06-04", "male", "G2", 3),
                ("Imani", "Mwangi", "2014-09-23", "female", "G3", 3),
                ("Tumaini", "Hassan", "2013-03-18", "female", "G4", 4),
                ("Faraji", "Hassan", "2012-12-02", "male", "G5", 4),
                ("Alika", "Njoroge", "2017-05-11", "female", "PP2", 2),
                ("Mosi", "Kiptoo", "2016-07-31", "male", "G1", 3),
                ("Sanaa", "Achieng", "2018-10-09", "female", "PP1", 1),
                ("Amani", "Mutiso", "2015-01-27", "male", "G2", 4),
            ]
            for index, spec in enumerate(learner_specs):
                first_name, last_name, birthday, gender, grade_code, guardian_key = (
                    spec
                )
                token = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"schoolos-demo:{school.name}:learner:{index + 1}",
                )
                learner = Learner.objects.filter(
                    school=school, creation_token=token
                ).first()
                if not learner:
                    learner, _ = create_learner(
                        school,
                        memberships[SchoolMembership.Role.HEAD].user,
                        {
                            "first_name": first_name,
                            "middle_name": "",
                            "last_name": last_name,
                            "preferred_name": "",
                            "date_of_birth": date.fromisoformat(birthday),
                            "gender": gender,
                            "admission_date": date(2027, 1, 4),
                            "status": Learner.Status.ACTIVE,
                            "notes": "Fictional demonstration record.",
                        },
                        creation_token=token,
                    )
                    copied_learners += 1
                AnnualEnrollment.objects.get_or_create(
                    learner=learner,
                    academic_year=year_2027,
                    defaults={
                        "learning_group": groups[("2027", grade_code, "A")],
                        "enrolled_on": date(2027, 1, 4),
                    },
                )
                if index in {2, 3, 4, 5}:
                    grade_2026 = {2: "PG", 3: "PP1", 4: "PP2", 5: "G1"}[index]
                    AnnualEnrollment.objects.get_or_create(
                        learner=learner,
                        academic_year=year_2026,
                        defaults={
                            "learning_group": groups[("2026", grade_2026, "A")],
                            "enrolled_on": date(2026, 1, 5),
                        },
                    )
                GuardianLink.objects.get_or_create(
                    learner=learner,
                    guardian=guardians[guardian_key],
                    defaults={
                        "relationship": "Guardian",
                        "is_primary": True,
                        "can_receive_school_communications": True,
                    },
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Demo ready for {school.name}: "
                f"{Learner.objects.filter(school=school).count()} learners, "
                f"{LearningGroup.objects.filter(academic_year=year_2027).count()} "
                "classes in 2027."
            )
        )
        self.stdout.write("Accounts: " + ", ".join(spec[0] for spec in user_specs))
        if created_users:
            self.stdout.write(
                f"Password for newly created accounts ({', '.join(created_users)}): "
                f"{supplied_password}"
            )
        if options["reset_passwords"]:
            self.stdout.write("Demo account passwords reset.")
        elif not created_users:
            self.stdout.write("Existing demo passwords were left unchanged.")

    def _year(self, school, name, starts_on, ends_on, is_current):
        year, _ = AcademicYear.objects.get_or_create(
            school=school,
            name=name,
            defaults={
                "starts_on": starts_on,
                "ends_on": ends_on,
                "is_current": is_current,
            },
        )
        if is_current and not year.is_current:
            AcademicYear.objects.filter(school=school, is_current=True).update(
                is_current=False
            )
            year.is_current = True
            year.save(update_fields=["is_current"])
        return year

    def _terms(self, year, prefix):
        term_data = [
            (f"{prefix} Term 1", date(int(prefix), 1, 4), date(int(prefix), 3, 27), 1),
            (f"{prefix} Term 2", date(int(prefix), 5, 4), date(int(prefix), 7, 31), 2),
            (f"{prefix} Term 3", date(int(prefix), 9, 7), date(int(prefix), 11, 26), 3),
        ]
        for name, starts_on, ends_on, sequence in term_data:
            Term.objects.get_or_create(
                academic_year=year,
                sequence=sequence,
                defaults={
                    "name": name,
                    "starts_on": max(starts_on, year.starts_on),
                    "ends_on": min(ends_on, year.ends_on),
                },
            )

    def _staff(self, school, first_name, last_name, category, employee_number):
        staff, _ = StaffRecord.objects.get_or_create(
            school=school,
            employee_number=employee_number,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "category": category,
                "active": True,
                "email": f"{last_name.lower()}@demo.example.test",
            },
        )
        return staff
