# Backend migration foundations — October 6, 2026

Scope: v2 server only. No Flutter presentation files, v1 files, Firebase services, production data, commits or deployments changed. Comparison uses the recovered implementation guide and current v2 code, not a complete audited v1 specification; full v1 parity cannot be certified yet.

## Implemented

- Searchable, paginated trip/call and shift history, including records older than the workspace's latest 100. Existing workspace and write APIs remain unchanged.
- A scheduled-reservation list using the existing rule: future pickup time and OPEN or ASSIGNED status. Create reservations using the existing POST /api/trips/ with pickup_time. No new reservation lifecycle or assignment rule.
- Append-only vehicle notes with server-assigned author, timestamp and protected vehicle reference. Existing Admin/IT company-record permissions govern both read and write. No concern severity, repair state, vehicle lockout or invented driver submission rights.
- Transactional audit records for API company-record creation/updates, trip creation/assignment/pickup/completion/cancellation, shift start/end, turn-in approve/reject and safety-alert creation/acknowledgement/resolution. Turn-in reviews retain actor, timestamp and before/after paid/cleared flags. Existing Admin/IT review permissions and unresolved-turn-in locks remain unchanged.
- Existing trip-assignment and safety-alert notification intent remains atomic with the operation and audit. APNs provider architecture unchanged; no extra event types, Firebase or delivery claims.

Audit records and notes have no mutation/delete API. This is application-level history, not a tamper-proof external ledger: trusted database administrators can change it. Existing Django-admin edits are not captured. Account lifecycle services accept an optional keyword-only actor for transactional audit; legacy callers without an actor retain their behavior and do not produce an attributed audit. These trusted Python services do not authorize API callers: existing admin authorization still applies. Authenticated password-change and logout APIs always create credential-free audit records in their existing transactions. Old records are not backfilled with guessed authors or actions. No passwords, push tokens or GPS coordinates are added to audit details. Record-edit audit stores field names only, not the original/new values; trips retain their existing current data.

## Additive APIs

All require the existing token authentication, expiry and forced-password-change checks. Developer dashboard preview does not change these permissions.

| Route | Access | Behavior |
| --- | --- | --- |
| GET /api/history/alerts/ and /api/history/alerts/{id}/ | all company roles; Driver own alerts only | paginated list/detail; q notes/kind/driver name/call; driver filter; since/until created_at |
| GET /api/history/trips/ | all company roles; Driver own trips only | all statuses; q searches pickup/dropoff/notes/call/car; driver, vehicle, status filters |
| GET /api/history/trips/{id}/ | same, scoped before lookup | trip record; other driver's record returns 404 |
| GET /api/history/shifts/ | all company roles; Driver own shifts only | q searches driver name/call/car; driver, vehicle filters |
| GET /api/history/shifts/{id}/ | same | shift record |
| GET /api/reservations/ | Dispatcher/Admin/IT | future OPEN/ASSIGNED; q pickup/dropoff/notes; driver, vehicle, status filters |
| GET /api/history/shifts/{id}/turn-in/ | own Driver or Admin/IT | shift-end and approve/reject audit history |
| GET/POST /api/vehicles/{id}/notes/ | Admin/IT | POST text (nonblank, max 5000); client author/vehicle cannot override server values; GET q text |
| GET /api/audit/ | Admin/IT | q action/subject type; no mutation API |

Lists return {count, page, page_size, results}. page defaults 1, page_size 50, maximum 100. Ordering is newest date then descending ID. since/until are inclusive ISO-8601 datetime filters on pickup_time (trips/reservations), start_time (shifts), or created_at (notes/audit/reviews). Invalid supported filters return 400. Unsupported query keys do not filter results. Driver filtering never expands ownership scope. Reservations are time-based: past-due open reservations appear in trip history/workspace rather than the future reservation list.

## Migration and configuration

Migration: core/0011_operational_history.py (depends on 0010_development_dashboard_access). Creates AuditRecord and VehicleNote, with indexed creation timestamps and protected foreign keys. Does not change existing rows or notification/GPS schema. Tested by migration to the isolated Django test database; NOT applied automatically to the existing local database.

After backing up the **v2** database, apply from the v2 root:

```sh
cd /Users/gabriellorenzo/Development/PrimeTime-Taxi-v2
.venv/bin/python server/manage.py migrate
```

Continuation adds alert-history routes and account-service/API audit support with no further migration. No new packages, environment variables, credentials or mobile capabilities. Existing APNs private configuration remains unchanged. No commands should target v1 or production. UI consumers can adopt these APIs separately.

## Remaining gaps / decisions

- Complete original v1 inventory and parity verification still required; recovered guide contains old session/turn-in assumptions superseded by newer explicit requirements and current code.
- Reservation editing, recurring bookings, customer/contact fields, no-show policy, reminder recipients/timing, timezone presentation and dispatch release rules need specifications. Existing future-trip behavior remains intact.
- Driver vehicle-concern submission/read permissions, concern categories/severity, repair acknowledgement/resolution ownership, and whether defects block vehicle assignment are unresolved. Current addition supports notes under existing record-manager permissions only.
- Turn-in calculations, deposits, tips, payment verification, rejection reason policy and correction workflow are unresolved. Approve still marks both paid and cleared; reject marks both false. No money is processed. Historic reviews before this migration have no reviewer history.
- Account creation/linking/password reset/deactivation remain in existing Django admin and core.services. Who may administer which roles, edit staff/superuser flags, approve accounts, or switch driver links requires explicit rules before adding mobile administration endpoints. Development-access flag is not exposed by new APIs.
- Django-admin audit integration and guaranteed actor attribution for all trusted account-service callers, immutable external retention/export, search export, richer indexed search and alert-history pagination remain future work.
- New notification kinds (reservation reminders, turn-in review, vehicle concerns, account administration) need recipient/content/retry rules; only existing assignment and safety events are generated. Android production push transport remains undecided without Firebase. Actual delivery requires configured direct APNs provider.

## Verification

New regression tests cover ownership, role boundaries, history beyond 100 records, filter validation, append-only note API, author spoofing protection, turn-in review history, and atomic rollback of notes/audit and trip/notification/audit. Run from the v2 root:

```sh
.venv/bin/python server/manage.py check
.venv/bin/python server/manage.py makemigrations --check --dry-run
.venv/bin/python server/manage.py test core --noinput
git diff --check
```

Explicit `core` test label matters when running manage.py from the project root: unlabeled discovery there finds zero tests. All APNs tests use mocked transport.
