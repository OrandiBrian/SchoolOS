# Foundation implementation review

2026-11-03. Completed directly by the root assistant following the user's explicit standalone instruction. No new sub-agents or DeepSeek requests were used.

Implemented the registration foundation: Django application/configuration/migration, scoped permissions, school and academic structures, staff and new account forms, teacher assignments, learners and permanent numbers, guardian links, annual enrolment, CSV preview/commit, fictional demo, responsive templates, local assets, README and browser smoke script.

Review corrected cross-school account enumeration/claiming; now school heads create new individual accounts. Corrected teacher assignment validation, duplicate assignment saves, guardian relink errors, invalid-date searches, malformed CSV rows, CSV field validation, unsafe implicit guardian matching, setup validation errors and current-year switching. Teacher reads require current active assigned enrolment. Admission creation through global admin is disabled so records use the allocation service. Added session inactivity expiry. Upgraded from Django 4.2 to Django 5.2.18 in Python 3.13 environment `.venv313`.

Evidence:
- Django 5.2: 42 tests discovered; 41 passed, one PostgreSQL concurrency test skipped under SQLite.
- `manage.py check`: no issues.
- `makemigrations --check --dry-run`: no changes.
- Existing local migrations applied; clean isolated QA database migrated successfully.
- `npm run css:build`: passed.
- Headless Chrome smoke verification covers login, local CSS/HTMX, dashboard, desktop learner list, mobile learner list and mobile registration. Initial mobile list expanded viewport; replaced it with mobile cards and rechecked.
- Final browser check passed: dashboard/list at 1440px and list/registration at exactly 390px, no document overflow. Visually inspected desktop dashboard and updated phone screenshots.
- After restricting global-admin learner creation, its two targeted admin-boundary tests passed again.

Accepted as a local development foundation, not a live-school release. PostgreSQL concurrency, production configuration, MFA/rate limits, audit trail and recovery remain unverified/unimplemented as detailed in README. Attendance and finance are next phases. Existing work and PLAN.md retained. No commits, deployments, or real school records.
