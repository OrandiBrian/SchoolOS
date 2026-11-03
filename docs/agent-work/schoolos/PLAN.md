# FayBri SchoolOS — Lofty Creek pilot plan

Status: Phase 1 local foundation implemented and reviewed. See FOUNDATION_REPORT.md for evidence and pilot-readiness limitations.

Execution override: user explicitly requested standalone work in this chat, without DeepSeek or sub-agents. This supersedes the delegated workflow below for this project.
Updated: 2026-11-03. Target live pilot: 2027 school year (confirmed).

## Objective and evidence

Build a reusable school management platform with Lofty Creek Christian School as the first pilot. Workspace was empty when inspected. Existing records are mostly paper with some digital records. Approximate size reported as 80; interpretation as learners remains provisional. Learners currently have no unique admission numbers.

## Confirmed requirements

- 2026 grades: Playgroup, PP1, PP2, Grades 1–4; add Grade 5 in 2027.
- Some grades have one stream and others two. Configure groups by academic year.
- Staff: teachers, secretary, school head, directors, board of management, and non-teaching staff (watchmen, cooks, drivers, cleaners).
- Secretary and school head handle finance.
- Fees charged per term and vary by grade; transport billed separately.
- Transport is believed to be fixed-price initially; allow variable pricing.
- Cash, bank and M-Pesa payments; school owns a Paybill.
- Individually arranged instalments, discounts and bursaries are supported.
- Mixed phones and computers; school internet is reasonably reliable.
- Teachers enter attendance directly.

## Proposed architecture and shared contracts

Django, PostgreSQL, Django templates, HTMX and Tailwind. Use a modular application with one codebase and school-scoped records. A single-school-only design is simpler initially but would require retrofitting isolation later; build tenant boundaries from the outset.

- Each operational record belongs to a school. Server-side membership and permissions govern every read and write, including exports and background tasks. Never trust a submitted school identifier alone.
- Staff employment categories are separate from login permissions; a staff record does not require an account. Board members and directors need not be employees.
- Separate grade, academic year, term and class/stream. Annual enrolment preserves prior class history. Promotion is an explicit operation, not an overwrite.
- Learners receive a permanent, automatically generated school-unique admission number. Proposed display format: LCCS-000001, with configurable school prefix. Numbers do not encode grade or imply original admission year. Use a database uniqueness constraint and concurrency-safe allocation; never reuse numbers. Internal identifiers and permissions remain independent of these visible numbers.
- Guardians can link to multiple learners and learners to multiple guardians. Future parent access requires explicitly authorized links, not matching names or phone numbers alone.
- Existing paper records require duplicate review during onboarding; no automatic merging based only on names. Preserve original admission dates where known without inventing missing dates.
- Use decimal money values in KES. Issued invoices retain their prices when fee schedules change. Discounts and bursaries are recorded adjustments. Instalments schedule existing debts rather than generate duplicate charges.
- Payments can be allocated across siblings, charges or periods within the same school. Unallocated money remains credit. Corrections use audited reversals rather than deletion.
- Statement imports use duplicate detection; ambiguous transactions await review. Live Paybill integration is deferred until account details and integration permissions are established.

## Proposed access defaults — validate with school before live use

Secretary: learner records, invoices, payments and receipts. School head: oversight and approval of discounts, bursaries, reversals and opening-balance corrections. Teachers: assigned classes and attendance; academics later. Directors: authorized management and financial summaries. Board: selected summary reports initially. Non-teaching staff: records initially, task-specific access later.

Require individual accounts, additional verification for privileged accounts before live use, session expiry/revocation, HTTPS, secure sessions, audit records, backups and tested recovery. School Wi-Fi never grants additional trust. Network quality/security has not been assessed.

## Dependency-ordered phases

1. Foundation and registration: school setup, staff access, 2027 year/terms, configurable grades/streams, learners, permanent admission numbers, guardians, annual enrolment, manual onboarding and import validation. Responsive UI and fictional demonstration data.
2. Attendance (depends on 1): assigned-class daily register; present, absent, late, excused and unmarked states; review/submit, correction history and missing-register overview. Proposed frequency: once daily. Clear saved/unsaved feedback; no silent success on network failure. Full offline synchronization is outside the pilot.
3. Finance (depends on 1, follows 2): grade/term fee schedules, optional transport, invoices, assistance approvals, individually agreed instalment schedules, verified opening balances, cash/bank/M-Pesa entry, statement imports, allocations, receipts, statements, credits and audit history.
4. Pilot readiness (depends on 1–3): reconcile balances against files, validate permissions, train staff, confirm hosting and operating costs, verify backups/restoration and agree operational responsibilities.
5. Academics and parent access (after pilot): configurable learning areas and assessments, reviewed report cards, guardian accounts and notices.
6. Later operations: live M-Pesa integration, messaging, transport operations, events, inventory/library and eventually HR/payroll.

Each implementation phase requires a bounded brief and verified installed Flash routing before dispatch. Astra owns architecture and acceptance; one native astra_flash_builder owns implementation/testing within each phase. Do not deploy, auto-commit, push, run paid setup probes or use real school data without the appropriate authorization. Later phases are not ready-to-dispatch specifications.

## Acceptance gates

- Two-school tests prove isolation across pages, mutations, lookups and exports. Unauthorized role and guardian access is rejected.
- Concurrent learner creation cannot duplicate admission numbers. Numbers survive promotion and withdrawal; annual history remains intact.
- Registration supports one/two-stream grades, shared guardians, validation errors and duplicate-review workflows.
- Attendance rejects unauthorized classes and duplicate register entries; unmarked pupils never silently become present. Corrections are attributable and failed saves are visible.
- Finance tests cover partial payments, discounts, bursaries, credits, sibling allocation, duplicate imports, reversals and unchanged historical invoices. Statement balances reconcile.
- Phone and desktop workflows are usable. Required security and restore checks pass before live use.

## Remaining inputs and risks

Needed before pilot, not before foundation work: actual stream names, term dates, fee amounts, transport rules, blank school forms/receipts, learner/staff counts, Paybill statement format and account-reference practices, management approval and data-handling/software-ownership arrangements. Hosting and budget are not approved purchases. Earlier KES 50,000 budget context and KES 25,000 allocation were planning estimates, not verified production costs.

Primary risks: unauthorized access to children's records, incorrect migrated balances, duplicate payments/learners, shared-device sessions and premature financial reliance. Mitigate through isolation tests, review/reconciliation, audit trails, individual access and a restricted pilot. Use fictional data during development. No guarantee of an eight-week production rollout.
