"""Shared pricing and ledger rules. All monetary writes run in transactions."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.core import signing
from django.db import transaction
from rest_framework.exceptions import ValidationError, PermissionDenied
from .models import CheckoutPolicy, PackagePrice, ServicePackage, Customer, CreditEntry

CENT = Decimal('0.01')

def money(value):
    try:
        n = Decimal(str(value))
        if not n.is_finite() or abs(n) > Decimal('99999999.99'):
            raise ValueError()
        return n.quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('จำนวนเงินไม่ถูกต้อง')


def staff(user):
    return bool(user.is_authenticated and user.is_active and (user.is_superuser or user.role in ('admin', 'manager', 'front', 'expert')))


def customer_for(request, data):
    if staff(request.user) and data.get('customer_id'):
        try:
            return Customer.objects.get(pk=data['customer_id'])
        except (Customer.DoesNotExist, ValueError, TypeError):
            raise ValidationError('ไม่พบลูกค้า')
    if request.user.is_authenticated:
        return Customer.objects.filter(user=request.user).first()
    return None


def quote(data, customer=None, allow_missing_price=False):
    policy = CheckoutPolicy.objects.filter(pk=1).first()
    if not policy:
        policy = CheckoutPolicy.objects.create(pk=1, approved=True, prices_include_vat=True, shipping_fee=Decimal('100.00'), shipping_taxable=False)
    elif not policy.approved:
        policy.approved = True
        policy.save(update_fields=['approved'])
    code = data.get('service_package') or data.get('serviceId')
    package = ServicePackage.objects.filter(code=code, enabled=True).first()
    if not package:
        raise ValidationError('กรุณาเลือกแพ็กเกจใหม่: 15 วัน, 90 วัน หรือ Photo Review')
    category = str(data.get('category', '')).title()
    if category not in ('Bag', 'Watch', 'Clothes', 'Shoes', 'Accessories'):
        raise ValidationError('ประเภทสินค้าไม่ถูกต้อง')
    brand = str(data.get('brand', '')).strip()
    if not brand:
        raise ValidationError('กรุณาระบุแบรนด์')
    tier = customer.membership_level.level_name.lower() if customer and customer.membership_level else 'general'
    if package.code == 'photo_review':
        amount = Decimal('500.00')
    else:
        rate = PackagePrice.objects.filter(package=package, category__iexact=category, brand__iexact=brand, member_tier__iexact=tier).first()
        if not rate:
            alias_map = {
                'louis vuitton': 'lv', 'lv': 'lv',
                'saint laurent': 'ysl', 'ysl': 'ysl',
                'bottega veneta': 'bottega', 'bottega': 'bottega',
                'miu miu': 'miumiu', 'miumiu': 'miumiu',
                'celine': 'celne', 'celne': 'celne',
                'max mara': 'maxmara', 'maxmara': 'maxmara',
                'tiffany & co.': 'tiffany', 'tiffany': 'tiffany'
            }
            alias_brand = alias_map.get(brand.lower(), brand)
            rate = PackagePrice.objects.filter(package=package, category__iexact=category, brand__iexact=alias_brand, member_tier__iexact=tier).first()

        if rate:
            amount = rate.amount
        elif allow_missing_price and data.get('manual_service_amount') is not None:
            if not str(data.get('price_reason', '')).strip():
                raise ValidationError('กรุณาระบุเหตุผลราคาที่ตกลงกับลูกค้า')
            amount = money(data['manual_service_amount'])
        else:
            raise ValidationError('ยังไม่มีราคาแพ็กเกจสำหรับแบรนด์และหมวดหมู่นี้')
    delivery = data.get('delivery_method', 'self_pickup')
    if delivery not in ('self_pickup', 'shipping'):
        raise ValidationError('วิธีรับคืนไม่ถูกต้อง')
    if package.code == 'photo_review':
        delivery = 'self_pickup'
    shipping = policy.shipping_fee if delivery == 'shipping' else Decimal('0')
    if amount < 0 or shipping < 0:
        raise ValidationError('ราคาและค่าจัดส่งต้องไม่ติดลบ')
    taxable = amount + (shipping if policy.shipping_taxable else Decimal('0'))
    vat = money(taxable * Decimal('7') / Decimal('107')) if policy.prices_include_vat else money(taxable * Decimal('0.07'))
    total = money(amount + shipping + (Decimal('0') if policy.prices_include_vat else vat))
    return {'service_package': code, 'validity_days': package.validity_days if code != 'photo_review' else 0,
            'category': category, 'brand': brand, 'member_tier': tier,
            'service_amount': str(money(amount)), 'shipping_fee': str(money(shipping)), 'vat_amount': str(vat),
            'subtotal': str(money(total - vat)), 'total': str(total), 'currency': 'THB',
            'prices_include_vat': policy.prices_include_vat, 'delivery_method': delivery,
            'price_reason': str(data.get('price_reason', '')).strip() if allow_missing_price and data.get('manual_service_amount') is not None else '',
            'policy_version': policy.updated_at.isoformat()}


def signed_quote(snapshot, customer):
    return signing.dumps({'quote': snapshot, 'customer_id': customer.pk if customer else None}, salt='checkout')


def verify_quote(token, snapshot, customer):
    try:
        value = signing.loads(token, salt='checkout', max_age=1800)
    except (signing.BadSignature, TypeError):
        raise ValidationError('ใบเสนอราคาหมดอายุ กรุณาคำนวณยอดใหม่')
    if value != {'quote': snapshot, 'customer_id': customer.pk if customer else None}:
        raise ValidationError('ราคาหรือข้อมูลเปลี่ยน กรุณาคำนวณยอดและตรวจสอบใหม่ก่อนชำระ')


@transaction.atomic
def change_credit(customer, amount, reference, reason, actor):
    customer = Customer.objects.select_for_update().get(pk=customer.pk)
    existing = CreditEntry.objects.filter(reference=reference).first()
    if existing:
        if existing.customer_id != customer.pk or existing.amount != amount:
            raise ValidationError('รหัสรายการซ้ำกับธุรกรรมอื่น')
        return existing
    balance = money(customer.credit_balance + amount)
    if balance < 0:
        raise ValidationError('ยอดเครดิตสะสมไม่เพียงพอ')
    customer.credit_balance = balance
    customer.save(update_fields=['credit_balance'])
    return CreditEntry.objects.create(customer=customer, amount=amount, balance_after=balance,
                                      reference=reference, reason=reason, actor=actor)
