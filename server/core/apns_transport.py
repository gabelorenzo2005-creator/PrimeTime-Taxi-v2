"""Direct APNs HTTP/2 transport. This module never logs credentials or device tokens."""
from dataclasses import dataclass
from datetime import datetime, timezone as datetime_timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
import time
import httpx
import jwt
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


@dataclass(frozen=True)
class APNsResult:
    status: int
    reason: str = ''
    apns_id: str = ''
    invalid_since_ms: int | None = None
    retry_after: int = 0


class APNsTransport:
    def __init__(self, client=None):
        if not settings.APNS_ENABLED:
            raise ImproperlyConfigured('Direct APNs delivery is disabled.')
        if not all([settings.APNS_TEAM_ID, settings.APNS_KEY_ID, settings.APNS_PRIVATE_KEY_PATH, settings.APNS_ALLOWED_TOPICS]):
            raise ImproperlyConfigured('APNs requires team ID, key ID, an allowed topic and an external private-key path.')
        path = Path(settings.APNS_PRIVATE_KEY_PATH).expanduser().resolve()
        if path.is_relative_to(settings.BASE_DIR.parent.resolve()):
            raise ImproperlyConfigured('Keep the APNs private key outside the project checkout.')
        try:
            self._key = path.read_bytes()
            # Validate the key without printing private material.
            jwt.encode({'iss': settings.APNS_TEAM_ID, 'iat': int(time.time())}, self._key, algorithm='ES256', headers={'kid': settings.APNS_KEY_ID})
        except Exception:
            raise ImproperlyConfigured('The APNs private key cannot be loaded or used for ES256.') from None
        self.client = client or httpx.Client(http2=True, timeout=settings.APNS_REQUEST_TIMEOUT_SECONDS, trust_env=False)
        self._owns_client = client is None
        self._jwt = None
        self._issued = 0

    def close(self):
        if self._owns_client:
            self.client.close()

    def send(self, *, token, environment, topic, apns_id, event_id, payload, expires_at):
        if environment not in ['sandbox', 'production'] or topic not in settings.APNS_ALLOWED_TOPICS:
            return APNsResult(400, 'UnconfiguredTarget')
        now = int(time.time())
        if self._jwt is None or now - self._issued >= 3000:
            self._jwt = jwt.encode({'iss': settings.APNS_TEAM_ID, 'iat': now}, self._key, algorithm='ES256', headers={'kid': settings.APNS_KEY_ID})
            self._issued = now
        host = 'api.sandbox.push.apple.com' if environment == 'sandbox' else 'api.push.apple.com'
        response = self.client.post(f'https://{host}/3/device/{token}', headers={
            'authorization': f'bearer {self._jwt}', 'apns-topic': topic,
            'apns-id': str(apns_id), 'apns-push-type': 'alert', 'apns-priority': '10',
            'apns-expiration': str(expires_at), 'apns-collapse-id': f'prime-event-{event_id}',
        }, json=payload)
        if response.http_version != 'HTTP/2':
            return APNsResult(503, 'HTTP2Required')
        try:
            data = response.json() if response.content else {}
        except ValueError:
            data = {}
        if not isinstance(data, dict):
            data = {}
        reason = str(data.get('reason', ''))[:100]
        if reason == 'ExpiredProviderToken':
            self._jwt = None
        retry_after = 0
        header = response.headers.get('retry-after', '')
        try:
            retry_after = max(0, min(86400, int(header)))
        except ValueError:
            try:
                retry_after = max(0, min(86400, int((parsedate_to_datetime(header) - datetime.now(datetime_timezone.utc)).total_seconds())))
            except (ValueError, TypeError):
                pass
        invalid = data.get('timestamp')
        if not isinstance(invalid, int) or isinstance(invalid, bool):
            invalid = None
        return APNsResult(response.status_code, reason, response.headers.get('apns-id', '')[:64], invalid, retry_after)
