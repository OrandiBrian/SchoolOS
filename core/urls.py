from django.contrib.auth.views import LogoutView
from django.urls import path

from . import views

urlpatterns = [
    path("login/", views.SchoolOSLoginView.as_view(), name="login"),
    path(
        "logout/",
        LogoutView.as_view(next_page="login"),
        name="logout",
    ),
    path("school/select/", views.select_school, name="select_school"),
    path("", views.dashboard, name="dashboard"),
    path("learners/", views.learner_list, name="learner_list"),
    path("learners/new/", views.learner_create, name="learner_create"),
    path("learners/duplicate-check/", views.duplicate_check, name="duplicate_check"),
    path("learners/<int:pk>/", views.learner_detail, name="learner_detail"),
    path("learners/<int:pk>/edit/", views.learner_edit, name="learner_edit"),
    path(
        "learners/<int:pk>/guardians/add/",
        views.guardian_add,
        name="guardian_add",
    ),
    path(
        "learners/<int:pk>/guardians/<int:link_pk>/unlink/",
        views.guardian_unlink,
        name="guardian_unlink",
    ),
    path(
        "learners/<int:pk>/enrol/",
        views.enrollment_add,
        name="enrollment_add",
    ),
    path("imports/learners/", views.import_upload, name="import_upload"),
    path(
        "imports/learners/template/",
        views.import_template,
        name="import_template",
    ),
    path(
        "imports/learners/<uuid:token>/",
        views.import_preview,
        name="import_preview",
    ),
    path("settings/school/", views.school_settings, name="school_settings"),
    path("academics/", views.academics, name="academics"),
    path(
        "academics/years/new/",
        views.academic_year_create,
        name="academic_year_create",
    ),
    path(
        "academics/years/<int:year_pk>/terms/new/",
        views.term_create,
        name="term_create",
    ),
    path("academics/grades/new/", views.grade_create, name="grade_create"),
    path(
        "academics/years/<int:year_pk>/groups/new/",
        views.group_create,
        name="group_create",
    ),
    path("staff/", views.staff_list, name="staff_list"),
    path("staff/new/", views.staff_create, name="staff_create"),
    path("staff/<int:pk>/edit/", views.staff_edit, name="staff_edit"),
    path("access/new/", views.membership_create, name="membership_create"),
    path("access/<int:pk>/edit/", views.membership_edit, name="membership_edit"),
    path("access/<int:pk>/classes/", views.teacher_classes, name="teacher_classes"),
]
