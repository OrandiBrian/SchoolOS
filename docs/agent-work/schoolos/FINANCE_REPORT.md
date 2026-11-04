# Finance milestone — 2026-11-04

Implemented directly, without DeepSeek or sub-agents. Source lives in the finance Django app; two migrations create financial records and add invoice-reversal support. Navigation integrates finance and learner statements with existing records.

Delivered: grade/term tuition and transport schedules; invoice amount snapshots; unique numbered receipts; manual cash/bank/M-Pesa payments; allocation across learner invoices; named-owner unallocated credit; printable receipts/invoices/statements; head-reviewed discounts, bursaries, opening debit/credit, invoice/payment/assistance reversals; individual instalment revisions with overdue amounts; school aggregate dashboard and financial event history. Approval form fields adapt to request type. Monetary services refresh authorization and serialize on the school row inside database transactions. Duplicate tokens/references, over-allocation and cross-school objects are rejected.

Validation:
- Full suite: 83 discovered, 81 passed, two PostgreSQL-only concurrency checks skipped (admission numbering and simultaneous credit allocation).
- Migration drift check, Django checks and Tailwind build passed.
- Clean isolated SQLite database migration and fictional seeding passed; seed idempotency is tested.
- Browser workflow passed: payment with allocation and remaining credit; head-approved discount; instalment agreement; phone receipt/statement at 390px; desktop overview; print receipt; conditional approval fields. Actual screenshots reviewed. An initial label assertion was updated for CSS uppercase text.
- Regression coverage includes price snapshots, duplicate invoices/references/tokens, Decimal precision, rejected/stale approvals, pending versus applied balances, payment and invoice reversal reconciliation, siblings, opening-credit collection exclusion, instalment overdue/revision, inactive users, roles, tenancy and CSRF.

Existing local preview database was migrated in place and its records preserved. Explicit fictional finance examples were added only to its named fictional school. No real payment APIs or external financial actions occurred.

Limits: PostgreSQL row locking has not been executed locally; required before real money records. No live deployment, statement imports/reconciliation, refunds, batch billing, rate-by-route transport, comprehensive general ledger, date-range reporting or independent two-person approval enforcement. Security/backup gates in README remain. Financial audit history is append-only through application workflows; it is not cryptographically tamper-proof against database administrators.
