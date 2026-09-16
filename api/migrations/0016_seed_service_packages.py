from django.db import migrations

def seed(apps, schema_editor):
    Package = apps.get_model('api', 'ServicePackage')
    for code, name, days, order in [('cert_15d', 'ตรวจสินค้า + แท็ก + ใบรับรอง 15 วัน', 15, 1), ('cert_90d', 'ตรวจสินค้า + แท็ก + ใบรับรอง 90 วัน', 90, 2), ('photo_review', 'ตรวจผ่านรูปภาพ — 500 บาท ไม่มีใบรับรอง', 0, 3)]:
        Package.objects.get_or_create(code=code, defaults={'name': name, 'validity_days': days, 'sort_order': order})
    apps.get_model('api', 'CheckoutPolicy').objects.get_or_create(pk=1, defaults={'approved': False})

class Migration(migrations.Migration):
    dependencies = [('api', '0015_checkoutpolicy_servicepackage_and_more')]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
