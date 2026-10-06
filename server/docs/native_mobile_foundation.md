# PrimeTime Taxi v2 — native mobile server foundation

> Historical record of migration 0008. Current provider/client behavior is documented in [Direct APNs and native GPS](direct_apns_and_native_tracking.md). Migration 0009 and its native configuration supersede the limitations below.

Updated October 4, 2026. This change adds Django data and APIs for real driver GPS reports, Apple device registration, and pending notification events. The existing operations, authentication scheme, role permissions, and Flutter UI are preserved. No APNs provider, push delivery worker, native GPS collector, or fake location data is introduced.

## Migration and setup

The new migration is `server/core/migrations/0008_mobile_foundation.py`. It depends on the existing `0007_safetyalert_trip_cancellation_reason_trip_created_at_and_more` migration and the Django user model. It creates three tables:

| Model | Purpose and constraints |
| --- | --- |
| `DriverLocation` | One latest actual fix per shift; latitude/longitude ranges, non-negative accuracy/speed, nullable heading in `[0, 360)`; device timestamp and server receipt timestamp. |
| `PushDevice` | Multiple installations per account, scoped by installation UUID, APNs environment, and topic. Unique active installation owner and unique active token owner prevent cross-account collisions. Disabled rows retain their original owner. |
| `NotificationEvent` | Recipient-account notification intent for a trip assignment or safety alert. Subject-kind validation, recipient/subject deduplication, pending-event index, and a constraint that permits only `PENDING_APNS_INTEGRATION`. |

This is an additive schema migration. It does not modify existing drivers, vehicles, shifts, trips, alerts, roles, or passwords. It does not backfill coordinates, register devices, or create historical notification events. Existing trips and alerts generate no retroactive push intent.

From `/Users/gabriellorenzo/Development/PrimeTime-Taxi-v2`:

```sh
.venv/bin/python server/manage.py migrate
.venv/bin/python server/manage.py check
.venv/bin/python server/manage.py test core
```

Migration `0008` was applied to the local development database after an SQLite backup. Existing operations records matched that backup after migration, and all three new tables were empty. Other checkouts must still run the migration command above.

Restart the Django development process after updating the code, especially if it was started with `--noreload`. No new Python package is required. Existing Django REST Framework token authentication remains the authentication mechanism.

Migration rollback to `0007` drops the three new tables and their mobile data. It is not a data-preserving rollback. Back up the database first; no rollback was performed during implementation.

## Configuration

All configuration below is read by `server/config/settings.py` at process startup:

| Environment variable | Default | Meaning |
| --- | --- | --- |
| `GPS_ONLINE_SECONDS` | `60` | Maximum age of both the captured fix and server receipt for online status. |
| `GPS_OFFLINE_SECONDS` | `300` | Maximum age before an on-shift driver becomes offline; between the online and offline thresholds the driver is stale. |
| `GPS_MAX_FUTURE_SECONDS` | `30` | Allowed device-clock lead for a fix timestamp. |
| `APNS_ALLOWED_TOPICS` | Empty | Comma-separated allowlist of app bundle identifiers/APNs topics permitted at registration. Registration is rejected until the matching topic is configured. |
| `DJANGO_ALLOWED_HOSTS` | `localhost,127.0.0.1,[::1]` | Existing host allowlist; configure a reachable backend host for physical-device testing. |

GPS values must be integers, with `0 < GPS_ONLINE_SECONDS < GPS_OFFLINE_SECONDS` and a non-negative future tolerance. Invalid settings prevent normal startup. Threshold boundaries are inclusive: age 60 seconds is online with the default settings, and age 300 seconds is stale.

Example registration configuration, **only if this matches the native app's bundle identifier**:

```sh
APNS_ALLOWED_TOPICS=com.primetimetaxi.app .venv/bin/python server/manage.py runserver 127.0.0.1:8000
```

For physical devices, use a reachable HTTPS backend and the matching allowed host. A phone's `127.0.0.1` refers to the phone. Existing `API_BASE_URL` Flutter build configuration is unchanged. This work does not configure production hosting or weaken native transport security.

**No Apple credential is required or read by this foundation.** There is no private key, certificate, Team ID, Key ID, or APNs transport in the implementation. A future provider must load credentials from a secret manager or a private file outside the checkout. Do not add `.p8`/certificate material to source control. Configuring an allowed topic does not enable push delivery.

## GPS API

`POST /api/gps/` requires the existing `Authorization: Token <account-token>` header and an authenticated Driver role. Identity and vehicle association are derived from the account and shift; clients cannot supply a driver ID or car number.

| JSON field | Required | Contract |
| --- | --- | --- |
| `shift_id` | Yes | ID of the authenticated driver's currently active shift. |
| `latitude` | Yes | Finite number, `-90` through `90`. |
| `longitude` | Yes | Finite number, `-180` through `180`. |
| `accuracy` | Yes | Finite, non-negative horizontal accuracy in metres. |
| `heading` | No | Degrees clockwise from true north, `0 <= heading < 360`; omit or send `null` if unavailable. |
| `speed` | No | Finite, non-negative metres per second; omit or send `null` if unavailable. |
| `timestamp` | Yes | Actual location-fix timestamp in ISO 8601 with `Z` or an explicit UTC offset. |

A report must refer to the driver's own active shift and have a fix timestamp at or after that shift's start. Reports for a completed or different shift are rejected even if the driver has since clocked in again. Future timestamps beyond the configured tolerance, naive timestamps, non-finite values, negative sentinel values, and unknown fields are rejected. Collect a fresh fix after clock-in rather than uploading a cached pre-shift location. Skip a fix whose horizontal accuracy is unavailable/negative; do not fabricate a valid accuracy or coordinate.

A successful request returns HTTP 200 with:

- `accepted`: whether this report created/replaced the latest fix.
- `reason`: `new_fix` or `older_or_duplicate_fix`.
- `location`: latest accepted coordinates, measurements, device `timestamp`, server `received_at`, `shift_id`, `vehicle_id`, and `car_number`.

A repeated/equal-timestamp or older fix returns `accepted: false` and the existing latest fix. It does not refresh `received_at`. Newer timestamps replace the single latest-per-shift row. This is current-position storage, not a breadcrumb history of every GPS sample. Shift locking coordinates ingestion with clock-out; conditional timestamp updates prevent older uploads from overwriting newer data. Existing database-lock conflicts are reported through the existing HTTP 409 handler.

Dispatcher, Admin, and IT are forbidden from submitting driver coordinates. Missing/expired credentials, inactive accounts, invalid roles, and required-password-change restrictions keep their existing behavior.

## Workspace contract

`GET /api/workspace/` retains its existing fields and adds:

- `gps_policy`: `online_seconds` and `offline_seconds`.
- `driver_locations`: one entry per role-scoped driver. Dispatcher, Admin, and IT see the fleet; a Driver sees only their own entry.

Each entry contains `driver_id`, `driver_name`, `call_number`, current `shift_id`, current `vehicle_id`, current `car_number`, `status`, `status_reason`, `fix_age_seconds`, `received_age_seconds`, and nullable `location`.

| State | Conditions / reason |
| --- | --- |
| `online` | Active shift, real fix for that shift, and both ages within the online threshold; `fresh_fix`. |
| `stale` | Active shift and a fix whose greater age is beyond the online threshold but within the offline threshold; `stale_fix`. |
| `offline` | No active shift (`off_shift`), active shift without a fix (`awaiting_fix`), fix too old (`fix_timeout`), or unlinked/deactivated/non-Driver account (`account_unavailable`). |

A recently uploaded old fix is still stale/offline because capture age matters as well as upload age. Clock-in alone never implies a working GPS connection. Ages are clamped at zero for the small permitted device-clock lead.

When off shift, the current shift/vehicle/car fields are null. `location` may contain the last known fix with **its own historical shift and car identifiers**, clearly associated with that older shift. A new active shift without a fresh fix has `location: null`; it never inherits a previous shift's coordinates. Always honor `status` and its reason rather than inferring online status solely from the existence of coordinates. Label future map markers with `call_number`; use the current car fields for the current assignment, and the nested historical fields only for last-known-location context.

Presence is computed at request time using the existing `server_time`, so it ages correctly without a scheduled task. The location query fetches only the latest applicable fix for each scoped driver, rather than loading all shift history into memory.

## Apple device registration API

All valid authenticated roles can register their own devices. Account ownership always comes from the authentication token. No account ID is accepted in the request.

`POST /api/devices/` accepts exactly:

| JSON field | Contract |
| --- | --- |
| `installation_id` | Random UUID generated and persisted by the native app for this installation. Reuse it for token refreshes. |
| `apns_token` | Actual APNs device-token bytes encoded as an even-length hexadecimal string. Variable lengths up to 512 hex characters are supported; normalize to lowercase. Do not use an APNs provider authentication JWT or a Firebase token. |
| `environment` | `sandbox` or `production`; must match the signed native build's APNs environment. |
| `topic` | App bundle identifier/APNs topic present in `APNS_ALLOWED_TOPICS`. |

The token is treated as opaque registration data; the API does not contact Apple or claim the token has been verified. Apple documents that [APNs device tokens have variable length](https://developer.apple.com/documentation/uikit/uiapplicationdelegate/application(_:didregisterforremotenotificationswithdevicetoken:)).

HTTP 201 creates a registration. HTTP 200 refreshes/reactivates that account's existing installation/environment/topic row and increments its revision. Other installations are untouched. HTTP 409 means another active registration owns the installation or token in that environment/topic; the API does not silently transfer it. Sandbox and production registrations are independent.

Registration responses include the server device `id`, installation UUID, environment, topic, active flag, revision, registration times, and disabled time. **Raw push tokens are never included in registration/list responses or workspace data.** Store the returned device ID locally for unregistering.

`GET /api/devices/` lists only the authenticated account's registrations, including disabled rows, using those same safe fields.

`DELETE /api/devices/{id}/` disables only a registration owned by the authenticated account. Other accounts receive HTTP 404. Repeated unregisters are harmless. Unregistering increments the revision once and records `disabled_at` without reassigning or deleting ownership history. It is allowed during a required password change; creating/refreshing registrations remains blocked by that restriction.

Native client lifecycle:

1. Authenticate, complete any required password change, and obtain the genuine APNs token through Apple's registration callback.
2. Register this installation. Re-register when Apple supplies a new token, using the same installation UUID.
3. Before sign-out/account switching, unregister **this device** while the old account is still authenticated. Do not unregister the account's other devices.
4. Sign out through the existing endpoint, then authenticate/register the new account. After unregistering the old account, the new owner gets a separate database row; old events remain associated with their original recipient.

The existing authentication token is still one token per account and expires after 12 hours. Multiple push registrations do not introduce independent authentication sessions or change account-wide logout/password-change token revocation. Registration itself does not log anyone in or authorize operations. Failed unregisters must be retried while the original account can still authenticate; do not silently steal a conflicting registration.

## Pending notification events

Successful trip assignment—including a driver's successful acceptance—creates one `TRIP_ASSIGNED` event for the assigned driver's account. A new safety alert creates `SAFETY_ALERT` events for the active Dispatcher, Admin, and IT accounts present at creation time. Events are recorded even when a recipient has no registered devices. No notification is generated for a failed assignment or failed safety-alert creation.

The event and its operation share a database transaction. An event write failure rolls back the corresponding operation. Recipient/kind/subject uniqueness makes repeated preparation idempotent. Each event refers to the original recipient and trip/alert, rather than embedding a mutable device token. Two devices do not create two duplicate account events; a future provider will handle eligible per-device fan-out separately.

Every event's status is `PENDING_APNS_INTEGRATION`. No code sends to Apple, schedules a delivery task, marks anything delivered, or exposes notification events as successful push delivery. The database also rejects a delivery status until an actual provider implementation and a corresponding schema change are added.

A future APNs implementation must add provider authentication, device fan-out and per-device attempts/results, retries, expiry, and invalid-token handling. It must recheck current account/role/device eligibility and subject relevance, use the registered environment/topic, and use the device revision to avoid disabling a newly rotated token after an older attempt fails. It must not replay an old account's events to a new device owner or send obsolete completed/cancelled trip/resolved-alert notifications without an explicit policy. Apple describes the actual provider request separately in [Sending notification requests to APNs](https://developer.apple.com/documentation/usernotifications/sending-notification-requests-to-apns).

The native app still needs the appropriate Apple push capability/provisioning, permission/registration callbacks, real location permissions and background location behavior, and authenticated API calls. These native changes are deliberately outside this server-only increment. Existing UI notification and alert behavior is unchanged.

## Code map and validation

| File relative to project | Responsibility |
| --- | --- |
| `server/core/models.py` | New location, registration, and notification-event models. |
| `server/core/migrations/0008_mobile_foundation.py` | Additive tables, constraints and index. |
| `server/core/mobile_serializers.py` | GPS/device validation and safe device responses. |
| `server/core/mobile_api.py` | GPS and own-device endpoints using existing permissions. |
| `server/core/locations.py` | Monotonic GPS ingestion and workspace presence. |
| `server/core/devices.py` | Collision-safe registration, rotation and unregister. |
| `server/core/notifications.py` | Pending event preparation, without delivery. |
| `server/core/operations.py` | Small hook after successful assignment. |
| `server/core/api.py` | Additive workspace data and transactional safety-event hook. |
| `server/config/urls.py` | Three new endpoint routes. |
| `server/config/settings.py` | GPS thresholds and topic allowlist. |
| `server/core/test_mobile.py` | New permissions, validation, lifecycle, model-constraint and rollback tests. |

All 54 backend tests passed (18 existing and 36 new). Django system checks and migration drift checks passed, and `git diff --check` found no whitespace errors. The existing tests are preserved. The expanded backend suite covers full GPS reports, missing optional measurements, invalid coordinates/timestamps, ownership and shift boundaries, monotonic updates, freshness, all operator roles, driver-only visibility, device rotation and multiple installations, cross-account conflicts, environment separation, owner-only unregister, pending-event deduplication and transactional rollback. Synthetic coordinates and push tokens are used only in isolated test databases; none are inserted into the application database.

No commits, deployments, Apple credentials, APNs network requests, native UI edits, or operations redesign are part of this change.
