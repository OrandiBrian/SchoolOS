# FayBri SchoolOS

Local development foundation for Lofty Creek's 2027 pilot. Fictional demonstration data only; not approved for live school records.

## Run locally

Requires Python 3.10+ (tested with 3.13) and Node.js for rebuilding styles. On this workspace the supported environment is `.venv313`; the older `.venv` is retained but should not be used.

```sh
python3.13 -m venv .venv313
.venv313/bin/python -m pip install -r requirements.txt
.venv313/bin/python manage.py migrate
.venv313/bin/python manage.py seed_demo
.venv313/bin/python manage.py runserver 127.0.0.1:8000
```

The explicit demo command prints a randomly generated password for newly created accounts. Accounts: `demo.head`, `demo.secretary`, `demo.teacher`, `demo.director`, `demo.board`. Re-running preserves accounts and records. Use `DEMO_PASSWORD` and `--reset-passwords` only to intentionally reset fictional account passwords. Never seed a live database.

Demo includes 12 fictional learners, guardians, staff, 2026/2027 structures, and two Grade 1 streams in 2027. Term dates and fee-free dashboard counts are illustrative, not official school data.

SQLite is the local default. Set `DATABASE_URL=postgresql://...` for PostgreSQL. `.env.example` documents environment settings but `.env` is not automatically loaded; supply variables through your shell/service. Keep secrets out of source control.

## What works

- Role-based school selection, staff records, individual account creation by heads, role changes and teacher class assignments.
- School settings, academic years, terms, grades and streams.
- Learner registration/edit/search, permanent admission numbers, duplicate warnings, guardians, annual enrolments.
- CSV template, row validation, preview and explicit all-or-nothing import confirmation.
- Term fee schedules, immutable invoice amounts, manual payments/receipts, learner credits and statements, head-approved opening balances/assistance/reversals, and individual instalment agreements.
- Daily class attendance, partial drafts, complete submissions, school-head corrections with reasons, version conflict protection and attendance audit history.
- Responsive desktop/mobile interfaces and locally compiled CSS/vendored HTMX.

Imported guardian rows intentionally create separate records; matching contact details alone do not prove identity. Staff can explicitly choose a verified existing guardian from the learner screen. No parent login rights are granted by guardian records.

Head and secretary manage registration. Teachers read learners in current active assigned enrolments; directors and board see summary dashboards. Global Django admin is superuser-only. Create a superuser explicitly for initial non-demo school provisioning; ordinary staff should use the portal. New school memberships for existing cross-school users require platform administration, not a global account picker exposed to heads.

## Validation

```sh
.venv313/bin/python manage.py check
.venv313/bin/python manage.py makemigrations --check --dry-run
.venv313/bin/python manage.py test
npm ci
npm run css:build
```

Browser smoke check requires Chrome and Node with built-in WebSocket, a running fictional demo server, and the demo password supplied through `DEMO_PASSWORD`:

```sh
SCHOOLOS_QA_URL=http://127.0.0.1:8000 node scripts/browser_qa.mjs
```

It checks login, dashboard, learner list, registration layout and local assets at desktop and phone sizes; screenshots are under `docs/agent-work/schoolos/screenshots/`. It is not a full browser test of every workflow. Django tests exercise mutation and authorization paths.

## Before live use

PostgreSQL concurrent admission-number allocation has a dedicated test but is skipped under SQLite. Validate it against the intended database. This phase does not include the parent portal, live M-Pesa integration, MFA, login throttling, audit history outside attendance/finance, password recovery, production hosting or tested backup restoration. These remain required pilot-readiness work. Set strong secrets, explicit allowed hosts, HTTPS and `DJANGO_DEBUG=false` for any production configuration; only trust forwarded HTTPS headers from a configured trusted proxy. Do not expose the development server publicly.

Current annual enrolment is one record per learner/year; class transfers and withdrawal-history workflows need the attendance phase design. Actual stream names, term dates and school data remain to be supplied.

## Attendance workflow

Open Attendance and choose a date within the class academic year. Teachers can write assigned classes; the head can write all classes; the secretary can read; directors and board see aggregate counts only. Save draft allows unmarked pupils. Submit requires every pupil marked. Teachers cannot edit submitted registers; the head must supply a reason for corrections. Each save records actor, time, changes and version. Stale edits cannot silently overwrite newer saves.

Dates after today are blocked, including future 2027 demo dates. To explore before 2027, select a past date in the fictional 2026 academic year. Missing/draft totals are distinct from absences. Weekends/holidays are not automatically excluded until school calendars are supplied.

The eligible class list is frozen on first save. Later enrolment changes do not silently alter historical attendance. Roster amendments and within-year transfers remain deferred. Only dated withdrawals can be placed accurately in historical rosters. Network failure keeps entered values on the open page; this is not offline storage, and closing the page can lose unsaved work.

Extended browser QA: set `SCHOOLOS_ATTENDANCE_QA=1` against a disposable seeded demo database. It writes a draft, submission and head correction for 2026-10-16 in the first class and simulates a network failure. Run on a fresh demo database; it intentionally requires an untouched register.

## Fees and finance

The secretary and head can configure fees by grade/term, issue invoices, enter payments and agree instalments. Directors and board see totals only; teachers have no finance access. Opening balances, discounts, bursaries and reversals require explicit school-head approval. The head may approve their own request in this small-school workflow; an independent two-person approval rule is not enforced.

Tuition and optional transport are copied onto each invoice. Future schedule edits never change issued amounts. One active term invoice per learner prevents accidental duplicate billing. Request an invoice reversal to correct an issued invoice: the original remains, and allocated funds return to each payment’s credit owner before a replacement invoice is issued.

Record cash, bank or M-Pesa money already received. Bank/M-Pesa references are required, normalized to uppercase and unique per school/method, including reversed payments. Receipt numbers are permanent. Allocate up to available credit and invoice balance; a family payment can be split between learners’ invoices. Unallocated money belongs to a named learner, and statements separate debt from credit. Financial corrections retain history. No external payment is initiated.

Discounts/bursaries may reduce only the currently unpaid invoice amount. Approval rechecks the balance. Opening debit/credit requests require verified source records; opening credits are excluded from collection totals. Reversed payments retain their allocations in history but no longer settle invoices. Reversed assistance restores the charge. There are no financial delete/edit endpoints for posted transactions.

Instalment agreements total the invoice's current net charge, including amounts already paid. Payments count against earliest instalments first. New agreements are appended, not overwritten. Assistance or reversals that change the net charge flag the old agreement for revision. Agreements do not create extra debt.

### Fictional finance examples

After `seed_demo`, explicitly run:

```sh
.venv313/bin/python manage.py seed_finance_demo
```

This targets only `Lofty Creek Demo School (Fictional)`, refuses non-debug environments, and adds illustrative KES 15,000 tuition / KES 3,000 transport, three invoices, a sample bursary, payment and instalments. It is idempotent and does not represent actual school fees. No real funds move.

Browser QA for finance: `SCHOOLOS_FINANCE_QA=1 SCHOOLOS_QA_URL=http://127.0.0.1:8000 node scripts/browser_qa.mjs` against a disposable seeded demo. It creates a small fictional payment/discount/agreement, verifies mobile layouts and print styling, and saves screenshots. Do not run against real records.

Before financial pilot: run the PostgreSQL concurrency test, reconcile opening balances, confirm approval responsibilities, verify recovery/security and validate real fee schedules. This milestone excludes bank/Paybill statement imports, automated reconciliation, refunds, bulk invoicing, date-range reporting, route-based transport rates and live payment APIs. It is a school fee subledger, not a full accounting/payroll package.
