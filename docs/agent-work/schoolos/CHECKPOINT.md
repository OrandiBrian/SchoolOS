# SchoolOS checkpoint

2026-11-03. Work remains standalone: no DeepSeek or sub-agents. User authorized GitHub commits/pushes at tested milestones (AGENTS.md).

Phases 1–2 implemented: registration foundation and attendance. Read FOUNDATION_REPORT.md, ATTENDANCE_REPORT.md and README.md. Supported environment: .venv313, Python 3.13 / Django 5.2.18.

Validation: 54 tests pass; PostgreSQL-specific admission concurrency test skipped. Attendance's 13 tests pass. Migration drift check, CSS build and desktop/mobile browser checks pass, including simulated failed save. PostgreSQL runtime verification and live-pilot readiness remain pending.

Local preview at 127.0.0.1:8766 preserves its existing fictional database. Separate disposable attendance verification database/server at 127.0.0.1:8767. Processes are session-dependent. No production deployment or real-data import.

Next product phase: fee schedules/invoices/manual payments and individual instalment agreements. Review finance approval rules and immutable ledger design before implementation. Roster amendments and class transfers remain explicitly deferred; attendance snapshots preserve saved history.
