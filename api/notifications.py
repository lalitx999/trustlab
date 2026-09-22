"""Local outbox only. No network calls or external delivery are enabled here."""
from .models import StaffNotification


def queue_staff_notification(event_key, event_type, payload, channels=('line', 'wechat')):
    # Insert inside the business transaction: rolled-back work must not notify staff.
    for channel in channels:
        StaffNotification.objects.get_or_create(
            event_key=event_key, channel=channel,
            defaults={'event_type': event_type, 'payload': payload},
        )
