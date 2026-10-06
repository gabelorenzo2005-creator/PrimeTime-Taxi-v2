# PrimeTime Taxi v2 — direct APNs and native GPS

Updated October 4, 2026. PrimeTime remains one Flutter application for iOS and Android, with Django as its application backend. No Firebase or FCM was introduced. Android supports ongoing driver tracking; it has no remote push provider. Existing operations, role permissions, GPS endpoints, device ownership protections and transactional event creation are preserved.

## Implementation and editable files

| Area | Project file |
|---|---|
| Direct HTTP/2 APNs transport and ES256 JWT authentication | `server/core/apns_transport.py` |
| Per-device attempts, leases, relevance checks and retries | `server/core/apns_delivery.py` |
| Bounded worker | `server/core/management/commands/send_apns_notifications.py` |
| Delivery schema | `server/core/models.py`, `server/core/migrations/0009_apns_delivery.py` |
| Shared location interface/native behavior | `app/lib/services/location_service.dart` |
| iOS registration forwarding | `app/lib/services/push_registration_service.dart`, `app/ios/Runner/AppDelegate.swift` |
| Shift hooks and tracking status | `app/lib/screens/operations_dashboard.dart` |
| Android permissions/service | `app/android/app/src/main/AndroidManifest.xml` |
| iOS capabilities/environment | `app/ios/Runner/Info.plist`, `Runner/Runner.entitlements`, `Runner.xcodeproj/project.pbxproj` |

## Migration and packages

`0009_apns_delivery` depends on `0008_mobile_foundation`. It adds `PushDelivery` and `PushAttempt`, uniqueness per event/device/revision and delivery/attempt number, a unique stable APNs request UUID, and a due-delivery index. It expands the NotificationEvent status constraint. Existing `PENDING_APNS_INTEGRATION` rows and the creation default remain compatible; the enabled worker now processes them. There is no data backfill or FCM migration.

Back up the database, then run from the project root:

```sh
.venv/bin/python -m pip install -r server/requirements.txt
.venv/bin/python server/manage.py migrate
.venv/bin/python server/manage.py check
```

The local database was backed up to this chat's `work/before-apns-delivery.sqlite3` before applying migration 0009. All existing operations and mobile records were preserved. Django added two content types and eight model permission records; the new delivery/attempt tables are empty. Other databases must run the migration themselves. Reversing 0009 loses attempt history and may violate the old event-status constraint after sending; use a verified backup for a full rollback.

New Python requirements: `httpx[http2]==0.28.1` and `PyJWT[crypto]==2.15.1`, including HTTP/2's `h2` and ES256's `cryptography` dependencies. Installing them does not enable sending.

| New direct Flutter package | Declared / locked | Purpose |
|---|---|---|
| geolocator | `^14.1.1` / `14.1.1` | Genuine native fixes and Android foreground service |
| permission_handler | `^12.0.1` / `12.0.3` | Runtime location/notification permissions |
| shared_preferences | `^2.5.3` / `2.5.5` | Installation UUID and Django device ID |

Run `flutter pub get` in `app`. The lockfile records the complete dependency graph. Native implementations include geolocator_android 5.1.1+1, geolocator_apple 2.3.14, permission_handler_android 13.0.1, permission_handler_apple 9.6.2, shared_preferences_android 2.4.28 and shared_preferences_foundation 2.5.7. Geolocator also brings package_info_plus 10.2.2 and uuid 4.6.0. Generated plugin registration files reflect these packages. No provider credentials are persisted by Flutter.

## Django APNs configuration

Supply these exclusively through a private process environment/service configuration. Keep the `.p8` key outside the repository and readable only by the worker account. The provider rejects private-key paths resolving inside the checkout. Signing material and `.env` files are ignored by Git. No Apple credentials were supplied or added during implementation.

| Environment variable | Default | Requirement |
|---|---|---|
| APNS_ENABLED | `0` | Exactly `1` enables provider initialization/sending |
| APNS_TEAM_ID | empty | Apple developer team ID |
| APNS_KEY_ID | empty | Apple provider key ID |
| APNS_PRIVATE_KEY_PATH | empty | Private external filesystem path to an ES256 `.p8` key |
| APNS_ALLOWED_TOPICS | empty | Comma-separated allowed bundle IDs matching native registration |
| APNS_MAX_ATTEMPTS | `5` | Positive attempt limit per device revision |
| APNS_EVENT_TTL_SECONDS | `3600` | Positive lifetime measured from event creation |
| APNS_REQUEST_TIMEOUT_SECONDS | `10` | Positive transport timeout |
| APNS_LEASE_SECONDS | `120` | Must exceed request timeout |

Existing GPS settings remain `GPS_ONLINE_SECONDS=60`, `GPS_OFFLINE_SECONDS=300` and `GPS_MAX_FUTURE_SECONDS=30`. They do not generate locations or heartbeats.

Provision an APNs authentication key authorized for the app and chosen environments, configure its IDs/private path externally, and restart workers after rotation. JWTs are cached in memory for 50 minutes; ExpiredProviderToken clears the cache for the next attempt. Avoid HTTP client request-URL debug logging: APNs request URLs contain device tokens.

Registrations retain explicit `sandbox` or `production` environments and allowed topics. The provider uses `api.sandbox.push.apple.com` or `api.push.apple.com` accordingly, with no environment fallback. A live worker needs outbound HTTPS/HTTP2 access to the appropriate Apple host. No Apple key belongs in the mobile app.

## Worker and event states

Once configured, run one bounded batch:

```sh
.venv/bin/python server/manage.py send_apns_notifications --limit 100
```

It exits after a batch. Arrange periodic execution with your existing service manager when ready; retries require later runs. No scheduler or live send was started here. Disabled/incomplete configuration fails before mutating events. Use a single worker with SQLite; production concurrent database execution was not exercised.

| Event state | Meaning |
|---|---|
| PENDING_APNS_INTEGRATION | Preserved default/legacy intent, eligible for the provider |
| PENDING | Supported queued state |
| WAITING_FOR_DEVICES | No usable devices, or cancelled revisions awaiting replacement |
| RETRY | Queued, leased or scheduled per-device work remains |
| ACCEPTED_BY_APNS | Remaining targets accepted by Apple without permanent failure |
| PARTIAL | At least one Apple acceptance and one permanent failure |
| FAILED | No acceptance and at least one terminal failure |
| SKIPPED | Intent is no longer relevant/authorized |
| EXPIRED | Event lifetime elapsed |

Apple acceptance is never called device receipt/display. Payloads use generic alert text and event/subject IDs, omitting addresses, safety notes and coordinates. Before claiming work, the provider checks active account, role, required password change, current assignment/ownership or unresolved safety alert. Assignment/safety hooks remain in their original Django transactions and retain deduplication.

A durable delivery record targets one device revision. Its stable apns-id and event collapse ID are reused across attempts. An unexpired lease prevents duplicate claims. Abandoned attempts become UNKNOWN; a late response cannot overwrite a newer attempt. Acceptance followed by a worker crash remains externally ambiguous, so exactly-once display is not promised.

Network errors, HTTP 429, server errors and provider authorization failures retry within the budget/TTL. Exponential delay starts at 60 seconds and caps at 3600; server errors wait at least 900 seconds. Retry-After may extend it. Batch selection skips future retries/device-less waiting events so newer work can proceed.

BadDeviceToken, DeviceTokenNotForTopic and HTTP 410 fail the attempt. Registration disabling requires the exact sent revision. An invalidation timestamp is checked against last registration: newer registrations or invalid/future timestamps remain active. Owner identity is never transferred. Terminal events are not automatically replayed to new devices; a device may join a still-pending/waiting/retrying event.

## Shared Flutter GPS

The driver workspace starts tracking after Django confirms clock-in and permission is granted. Signing in again confirms an existing active shift before resuming. Dispatcher/Admin/IT do not collect GPS. Successful clock-out stops tracking before workspace refresh; a failed clock-out preserves tracking until the server confirms closure. Signing out/session loss stops local tracking but does not close the server shift.

The platform's actual latitude, longitude, accuracy, valid optional heading/speed and capture timestamp go to `/api/gps/`, with shift_id and existing Django authentication. Mocked fixes, invalid values, pre-shift timestamps and fixes beyond the server's default future tolerance are discarded. Android requests high accuracy about every 10 seconds; iOS timing is OS-controlled. Missing heading/speed is omitted.

Uploads are serialized. Only the latest unsent genuine fix is held in memory for the shift. Network failures retry every 15 seconds or with a newer fix, preserving the original capture time. No invented coordinate, extrapolation or fake heartbeat is sent. Authentication/server validation rejection stops tracking and asks for refresh/retry. Clock-out discards buffered fixes. An in-flight HTTP request can still finish after stop; Django enforces active shift ownership.

There is no durable offline location history or process-resurrection guarantee. Ordinary backgrounding uses Android's foreground service and iOS background location. Force-stop, OS termination, battery restrictions, revoked permission and network loss can interrupt reporting. After restart, sign in and confirm the shift again. Server online/stale/offline remains based on genuine capture/receipt timestamps.

## Android permissions and manual setup

The manifest declares INTERNET, ACCESS_COARSE_LOCATION, ACCESS_FINE_LOCATION, FOREGROUND_SERVICE, FOREGROUND_SERVICE_LOCATION, POST_NOTIFICATIONS and WAKE_LOCK. It declares non-exported `com.baseflow.geolocator.GeolocatorLocationService` with foregroundServiceType location.

Tracking starts from the visible authenticated workspace. The ongoing notification says “PrimeTime Taxi location tracking” and “Your location is shared while you are clocked in.” A wake lock supports collection. Stopping the stream ends tracking/service notification. Notification permission is requested where applicable and required by this app to start visible tracking.

ACCESS_BACKGROUND_LOCATION is not requested: the app starts its location foreground service while visible and keeps it running during backgrounding. No background-only entry point silently starts tracking.

1. Install the Android SDK/JDK required by the current Flutter/Gradle project. Keep compileSdk at least 35 for the permission plugin; existing Flutter SDK defaults remain.
2. Choose the production application ID and signing configuration when packaging. Existing example ID/debug signing settings were preserved.
3. Run with a reachable HTTPS backend using `flutter run --dart-define=API_BASE_URL=https://YOUR_BACKEND` in app. The existing LAN default is preserved, not a production endpoint.
4. On a physical device, grant location/notifications and check clock-in, visible notification, screen lock, switching apps, network recovery, permission revocation and clock-out against real `/api/gps/` records.

Android trip/safety remote push is unavailable. The local tracking notification is not a trip-alert delivery service.

## iOS capabilities and manual setup

Info.plist contains when-in-use/always location explanations, UIBackgroundModes location, and PrimeTimeAPNSEnvironment. Native settings enable automotive navigation, background updates, no automatic pause and a background indicator. The app requests When In Use then Always. If iOS defers/refuses Always, grant it in Settings and tap Retry GPS. iOS location and notification permissions are independent.

Runner has Push and Background Modes capability entries. Runner.entitlements uses `aps-environment=$(APS_ENVIRONMENT)`:

| Build configuration | APS_ENVIRONMENT entitlement | PRIMETIME_APNS_ENVIRONMENT registration |
|---|---|---|
| Debug | development | sandbox |
| Release/Profile | production | production |

These public build values are not credentials. A development provisioning profile used for Release/Profile requires development/sandbox together. Verify the built signed entitlement; never change only one side.

1. Open `app/ios/Runner.xcworkspace`. Preserve the current bundle ID/team unless intentionally changing identity. Django's allowed topic must match the final bundle ID.
2. Select a team/profile supporting Push Notifications. Enable Push Notifications and Background Modes → Location updates for Runner. Enable push for the app identifier in your Apple account and refresh provisioning as required.
3. Match the profile to the two environment settings above. Keep the APNs provider key exclusively on Django's private host.
4. Run flutter pub get and resolve Swift packages. This project uses Swift Package Manager, not a Podfile. Its generated package currently requires iOS 17.0; retain a deployment target at least as high as the plugin/generated requirement. Existing recommended deployment settings were preserved.
5. permission_handler_apple 9.6.2 infers permissions from Info.plist for command-line SPM builds. For builds launched through Xcode.app, expose `PERMISSION_HANDLER_INFO_PLIST` with the absolute Runner/Info.plist path in the Xcode build environment as the plugin requires. For a GUI build, set this variable with `launchctl setenv PERMISSION_HANDLER_INFO_PLIST /Users/gabriellorenzo/Development/PrimeTime-Taxi-v2/app/ios/Runner/Info.plist`, then fully quit/reopen Xcode and resolve packages. On another machine, use that checkout's absolute path. Refresh this project's package/build cache after changing configuration. If switching to CocoaPods separately, enable PERMISSION_LOCATION=1 in plugin preprocessor definitions.
6. Use a reachable HTTPS API_BASE_URL and physical-device signing. No broad ATS exception was added for the preserved HTTP LAN default.
7. Allow native notification registration. Actual APNs bytes are forwarded as hex with bundle topic/environment. A persisted random installation UUID identifies the installation; it is never a push token. Native refresh callbacks, retries and app resume use the owner-protected registration API. Only installation/Django device IDs are persisted by this service.
8. Test physical-device background/locked-screen GPS, Always permission, offline recovery and clock-out. Separately configure the private Django provider and deliberately test an assignment/safety event. Inspect Apple acceptance and actual device behavior separately.

Sign-out waits for any in-flight registration, unregisters this device, then deletes the Django session token. A network failure aborts sign-out so switching accounts does not silently abandon the prior registration. Existing authentication/session behavior is otherwise preserved.

## Verification and limits

Validation: **71 backend tests and 11 Flutter tests passed; Flutter analysis reported no issues.**

APNs tests use mocked transports and ephemeral test-only ES256 keys. They never contact Apple. Tests cover device ownership/revisions, acceptance/idempotency, retry budgets/timing, timestamp invalidation, worker leases/late responses, payload privacy, missing credentials and HTTP/2 enforcement. Existing foundation/operations tests are retained.

Flutter tests cover original operations plus successful clock-in/clock-out tracking hooks, denied permission, genuine capture timestamps, mocked/pre-shift rejection, transient retries, stop/cancel and authentication rejection. Static analysis, plist/project syntax checks and Swift type checking passed.

Full native builds are unverified: Xcode package resolution was blocked by restricted Swift/Xcode cache access and simulator services; Android could not initialize its Gradle cache. No signed app was produced, installed or deployed. Provisioning, physical-device background behavior and configured live APNs delivery remain manual checks. No live push, commit or deployment occurred.

```sh
# Project root
.venv/bin/python server/manage.py test core
.venv/bin/python server/manage.py makemigrations --check --dry-run
# app directory
flutter analyze
flutter test
flutter build ios --no-codesign
flutter build apk --debug
```

References: [Apple token authentication](https://developer.apple.com/documentation/usernotifications/establishing-a-token-based-connection-to-apns), [Apple APNs responses](https://developer.apple.com/documentation/usernotifications/handling-error-responses-from-apns), [Android location foreground services](https://developer.android.com/develop/background-work/services/fgs/service-types#location), [geolocator](https://pub.dev/packages/geolocator), [permission_handler](https://pub.dev/packages/permission_handler).
