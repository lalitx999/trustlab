"""Apply the latest confirmed membership table, without rewriting past bills."""
from decimal import Decimal, ROUND_HALF_UP
from django.db import migrations


def update_program(apps, schema_editor):
    alias = schema_editor.connection.alias
    Level = apps.get_model('api', 'MembershipLevel')
    Rate = apps.get_model('api', 'PackagePrice')
    program = [
        ('silver', 0, 2000), ('platinum', 5, 1500),
        ('gold', 15, 1200), ('partner', None, 1000),
    ]
    for tier, discount, cert_price in program:
        values = {'certificate_price': cert_price}
        if discount is not None:
            values['discount_pct'] = discount
        Level.objects.using(alias).filter(level_name__iexact=tier).update(**values)
    for base in Rate.objects.using(alias).filter(member_tier__iexact='general').iterator():
        for tier, factor in [('silver', '1'), ('platinum', '0.95'), ('gold', '0.85')]:
            amount = (base.amount * Decimal(factor)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            Rate.objects.using(alias).filter(
                package_id=base.package_id, category__iexact=base.category,
                brand__iexact=base.brand, member_tier__iexact=tier,
            ).update(amount=amount)


class Migration(migrations.Migration):
    dependencies = [('api', '0019_correct_membership_discounts')]
    operations = [migrations.RunPython(update_program, migrations.RunPython.noop)]
