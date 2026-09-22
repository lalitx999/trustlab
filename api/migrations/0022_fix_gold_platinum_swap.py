"""Fix Gold/Platinum discount swap: Gold=5%, Platinum=15% (per customer spec)."""
from decimal import Decimal, ROUND_HALF_UP
from django.db import migrations


def fix_gold_platinum_swap(apps, schema_editor):
    alias = schema_editor.connection.alias
    Level = apps.get_model('api', 'MembershipLevel')
    Rate = apps.get_model('api', 'PackagePrice')

    # Fix MembershipLevel discount percentages
    Level.objects.using(alias).filter(level_name__iexact='gold').update(discount_pct=5)
    Level.objects.using(alias).filter(level_name__iexact='platinum').update(discount_pct=15)

    # Fix PackagePrice rows derived from general base
    for base in Rate.objects.using(alias).filter(member_tier__iexact='general').iterator():
        for tier, factor in [('gold', Decimal('0.95')), ('platinum', Decimal('0.85'))]:
            amount = (base.amount * factor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            Rate.objects.using(alias).filter(
                package_id=base.package_id,
                category__iexact=base.category,
                brand__iexact=base.brand,
                member_tier__iexact=tier,
            ).update(amount=amount)


class Migration(migrations.Migration):
    dependencies = [('api', '0021_staffnotification')]
    operations = [migrations.RunPython(fix_gold_platinum_swap, migrations.RunPython.noop)]
