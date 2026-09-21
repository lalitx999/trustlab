"""Correct membership metadata; booking price snapshots remain unchanged."""
from decimal import Decimal, ROUND_HALF_UP
from django.db import migrations


def correct_discounts(apps, schema_editor):
    alias = schema_editor.connection.alias
    MembershipLevel = apps.get_model('api', 'MembershipLevel')
    PackagePrice = apps.get_model('api', 'PackagePrice')
    for tier, discount in [('general', 0), ('silver', 0), ('gold', 5), ('platinum', 15)]:
        MembershipLevel.objects.using(alias).filter(level_name__iexact=tier).update(discount_pct=discount)
    # Retain old override rows for compatibility, aligned with the general base.
    # Quotes derive from general at runtime, including after future base-price edits.
    for base in PackagePrice.objects.using(alias).filter(member_tier__iexact='general').iterator():
        for tier, factor in [('silver', '1'), ('gold', '0.95'), ('platinum', '0.85')]:
            amount = (base.amount * Decimal(factor)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            PackagePrice.objects.using(alias).filter(
                package_id=base.package_id, category__iexact=base.category,
                brand__iexact=base.brand, member_tier__iexact=tier,
            ).update(amount=amount)


class Migration(migrations.Migration):
    dependencies = [('api', '0018_booking_request_fingerprint')]
    operations = [migrations.RunPython(correct_discounts, migrations.RunPython.noop)]
