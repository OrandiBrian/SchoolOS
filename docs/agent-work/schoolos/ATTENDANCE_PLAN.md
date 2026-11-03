# Phase 2: daily attendance

One register per class/date. Teachers write drafts only for assigned classes; head can write any class. Secretary reads registers; directors/board see aggregate overview only. Dates must fall within the class academic year and cannot be in the future (Nairobi date). Weekends are not automatically excluded: school-day calendar remains configurable later.

Draft saves may leave pupils unmarked. Submission requires all pupils marked present, absent, late or excused. Submitted records are read-only for teachers; head corrections require a reason. Every successful save records actor, timestamp and before/after changes. Version checks reject stale concurrent edits. Snapshot the eligible roster on first save; later enrolment edits never silently rewrite a register. No automatic present defaults. Show missing/draft/submitted registers and absences separately.

Snapshot eligibility: enrolment started on/before date; withdrawal is exclusive of its date; withdrawn records without a withdrawal date excluded. Preserve historic completed enrolments. Class transfers within a year and roster-amendment workflow are deferred; snapshots remain intact. No offline persistence of children's data. Show unsaved/saving/saved state and leave values intact on rejected submissions. Network failures must not imply success.

Validate tenant and role boundaries, future/out-of-year dates, eligible roster, status validation, submission completeness, corrections/audit, stale edits, revocation, and mobile browser workflow. Run full regression suite, then commit/push tested milestone. No production deployment.
