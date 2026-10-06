from datetime import timedelta
from django.conf import settings
from django.db.models import Q, Exists, OuterRef
from django.utils import timezone
from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ImproperlyConfigured
from core.apns_transport import APNsTransport
from core.apns_delivery import process_event, TERMINAL_EVENTS
from core.models import NotificationEvent, PushDevice


class Command(BaseCommand):
    help = 'Process one bounded batch of pending direct-APNs events. Run periodically with an external scheduler.'
    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=100)
    def handle(self, *args, **options):
        if not settings.APNS_ENABLED:
            raise CommandError('APNs is disabled; no events were sent or changed.')
        if options['limit'] < 1:
            raise CommandError('Limit must be positive.')
        try:
            transport = APNsTransport()
        except ImproperlyConfigured as error:
            raise CommandError(str(error)) from None
        try:
            now = timezone.now()
            active_devices = PushDevice.objects.filter(user_id=OuterRef('recipient_id'), is_active=True, topic__in=settings.APNS_ALLOWED_TOPICS)
            # Waiting accounts and future retries must not consume every batch slot.
            eligible = (Q(created_at__lte=now - timedelta(seconds=settings.APNS_EVENT_TTL_SECONDS))
                        | Q(status__in=['PENDING_APNS_INTEGRATION', 'PENDING'])
                        | Q(status='WAITING_FOR_DEVICES', has_device=True)
                        | Q(status='RETRY', deliveries__status__in=['PENDING', 'RETRY'], deliveries__next_attempt_at__lte=now)
                        | Q(status='RETRY', deliveries__status='SENDING', deliveries__lease_until__lte=now))
            ids = (NotificationEvent.objects.exclude(status__in=TERMINAL_EVENTS)
                   .annotate(has_device=Exists(active_devices)).filter(eligible)
                   .order_by('created_at', 'id').values_list('pk', flat=True).distinct()[:options['limit']])
            for pk in list(ids):
                status = process_event(pk, transport)
                self.stdout.write(f'Event {pk}: {status}')
        finally:
            transport.close()
