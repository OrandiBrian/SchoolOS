# SchoolOS checkpoint

2026-11-04. Standalone only; no DeepSeek/sub-agents. User authorizes milestone GitHub commits/pushes (AGENTS.md).

Registration, attendance and manual finance milestones implemented. See respective REPORT.md files and README.md. Runtime: .venv313, Python 3.13 / Django 5.2.18.

83 tests discovered: 81 pass, 2 PostgreSQL concurrency checks skipped. Migration drift checks, CSS build, desktop/mobile/print browser finance workflow pass. No production deployment.

Existing preview 127.0.0.1:8766 uses /tmp/schoolos-standalone-qa.sqlite3, migrated without replacing records, with explicit fictional finance sample data. Separate disposable finance QA server uses port 8768 and /tmp/schoolos-finance-qa.sqlite3. Process lifetime is session-dependent. Credentials remain development-only; see README.

Next: review secretary/head usability, actual fee definitions and finance pilot gates. Statement import/reconciliation, exports/date-range reporting, refunds and bulk billing are not included. Academics/report cards and parent access remain later product phases. Run PostgreSQL concurrency and backup recovery before live data. Preserve attendance roster snapshots; within-year transfer/roster-amendment UI remains deferred.
