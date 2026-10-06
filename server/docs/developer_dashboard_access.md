# V2 developer dashboard access

Implemented October 6, 2026. This feature belongs only to `/Users/gabriellorenzo/Development/PrimeTime-Taxi-v2`. V1, Firebase, production accounts/data and deployment were not inspected or modified. No password was chosen automatically, and no developer account was silently seeded.

## Initialize Gabriel's local account

From a terminal:

```sh
cd /Users/gabriellorenzo/Development/PrimeTime-Taxi-v2
.venv/bin/python server/manage.py migrate
.venv/bin/python server/manage.py init_developer
```

The last command prompts for a new password twice, without echoing it. It applies Django's configured password validators and stores a Django password hash. Passwords are not accepted as command-line arguments or written into source files. Log in to v2 as **gabriellorenzo** using that password. Running the command again explicitly resets this account's password and revokes its existing tokens. An optional `--email YOUR_EMAIL` stores normal profile contact information; email never grants preview access.

The command creates/supports:

- Django User: Gabriel Lorenzo, active, staff and superuser.
- AccountProfile: role `IT` (display name Technician), required password change off after supplying the new local password, development-dashboard flag on.
- A linked development Driver record, if one is not already linked to this account. Its reserved local identifiers are call/license `DEV-GAB`, phone `DEV-GABRIEL`, and email `gabriel.lorenzo@development.invalid`. These are clearly identified development metadata, not operational credentials or GPS data. Replace contact/license details through normal v2 development administration if needed.

An existing linked Driver is reused without changing its fields. A reserved username belonging to another named account, another flagged developer account, or a conflicting Driver identity makes initialization fail. Its database transaction rolls back instead of taking over/reassigning another account or Driver. No other account is promoted. No vehicle, shift, trip, coordinate or notification is created.

Both the initialization command and preview API refuse access with `DEBUG=False`. Do not initialize or run this against production. Use the actual v2 Django development backend; setting a Flutter label cannot enable this feature.

## Use the dashboard selector

After the authorized account's workspace loads, the app shows **View Dashboard As** with Driver, Dispatcher, Admin and Technician choices. A development banner identifies the currently viewed dashboard and the account's actual Technician authorization. **Return to Technician** exits another dashboard's layout preview.

Every selection requests the server's read-only `GET /api/development/dashboard/?role=DRIVER|DISPATCHER|ADMIN|IT` endpoint. Preview workspaces use the appropriate dashboard data layout; Driver preview is scoped to the developer's linked Driver. The response still reports the authenticated role as IT. Returning to Technician uses its normal workspace again. Unsupported roles are rejected, and POST to this endpoint is not supported.

The stored role, Django privileges and session token are not changed by dashboard selection. This is a layout/data preview, not a second identity or operational authorization override. Driver-only shift/trip/GPS actions and Dispatcher-only dispatch actions still reject the Technician account through existing API role checks. Technician actions that are already permitted, such as managing fleet records or reviewing turn-ins, remain permitted. Those authorized normal actions can change v2 development data, so dashboard preview is not a sandbox for every operational button.

Driver preview never starts GPS for the Technician account. An existing Driver relationship does not bypass Driver role authorization. No location is fabricated to populate maps/status, and no native permission/signing configuration was changed by this feature.

## Security gates

`AccountProfile.development_dashboard_access` is an explicit, non-editable model flag. The migration defaults it to false; it is not exposed by normal record-update APIs or the profile inline's editable fields. A partial unique database constraint permits only one flagged account.

Server access additionally requires all of:

- `DEBUG=True`.
- Authenticated active user.
- Django staff AND superuser privileges.
- Stored Technician/IT role.
- Explicit development access flag.
- No outstanding forced password change.

Names/emails are not used by Flutter to authorize previews. Ordinary users, ordinary Technician accounts and unflagged superusers do not qualify. Session/login/workspace responses advertise the capability only when the complete server predicate succeeds. Cached session identity does not independently enable the selector; a fresh workspace and preview authorization are required. Server denial removes the preview control and restores the normal layout. Authentication, GPS, dispatch and payment authorization remain unchanged.

With `DEBUG=False`, the advertised capability is false and every preview role returns HTTP 403, even if a flagged staff/superuser record remains in the database. Ordinary sign-in/workspaces still operate using their normal permissions. This feature does not enable APNs, install Apple credentials, introduce Firebase, or provide Android remote push.

## Migration and changed files

Migration `0010_development_dashboard_access` adds the AccountProfile flag and `one_development_dashboard_account` constraint; it depends on `0009_apns_delivery`. It does not change existing roles, accounts, passwords or operating records. The local v2 database migration was applied after a private SQLite backup under the ignored `server/.local-backups/` directory. Existing record fingerprints matched afterward; every account's new flag remained off pending explicit initialization.

Feature files:

| File | Purpose |
|---|---|
| `server/core/models.py` and migration 0010 | Explicit sole-account access flag |
| `server/core/development_access.py` | Central DEBUG/account authorization predicate |
| `server/core/api.py`, `views.py`, `server/config/urls.py` | Capability responses and protected read-only preview endpoint |
| `server/core/management/commands/init_developer.py` | Local interactive account/password initialization |
| `app/lib/screens/operations_dashboard.dart` | Selector, active-mode banner and return control |
| `server/core/test_development_access.py` | DEBUG, role, ownership and initialization regressions |
| `app/test/development_dashboard_test.dart` | Ordinary-account denial, switching, GPS isolation and server denial |
| `.gitignore` | Keeps private local database backups out of Git |

Repaired `location_service.dart`, `RunnerDebug.entitlements`, and Debug `CODE_SIGN_ENTITLEMENTS = Runner/RunnerDebug.entitlements` were preserved. Previously unfinished session/turn-in work was retained, not reset.

## Validation

- Flutter analysis: no issues.
- Flutter tests: 17 passed.
- Django tests: 103 passed, including 11 new development-access tests.
- Django system check: passed.
- Django migration consistency check: no uncreated changes.
- Git whitespace check: passed.

Tests use isolated databases, mock HTTP responses and synthetic test passwords; no live account password or production service is contacted. No commit, push, app installation or deployment occurred. Native signing/physical-device behavior was not newly tested in this change.
