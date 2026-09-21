"""Shared pricing and ledger rules. All monetary writes run in transactions."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.core import signing
from django.db import transaction
from rest_framework.exceptions import ValidationError, PermissionDenied
from .models import CheckoutPolicy, PackagePrice, ServicePackage, Customer, CreditEntry, BrandPricing

CENT = Decimal('0.01')
MEMBER_PRICE_FACTORS = {
    'general': Decimal('1'), 'silver': Decimal('1'),
    'gold': Decimal('0.95'), '5pct': Decimal('0.95'),
    'platinum': Decimal('0.85'), '15pct': Decimal('0.85'),
}

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
    req_tier = data.get('membership_level') or data.get('membership_tier') or data.get('membership_level_name')
    if req_tier:
        tier = str(req_tier).strip().lower()
    elif customer and customer.membership_level:
        tier = customer.membership_level.level_name.lower()
    else:
        tier = 'general'
    if package.code == 'photo_review':
        amount = Decimal('500.00')
    else:
        # Standard memberships always derive from the general package price.
        # Keep the actual tier in the booking snapshot; old tier overrides are not used.
        factor = MEMBER_PRICE_FACTORS.get(tier)
        pricing_tier = 'general' if factor is not None else tier
        # 1. Look in PackagePrice (exact or alias match)
        rate = PackagePrice.objects.filter(package=package, category__iexact=category, brand__iexact=brand, member_tier__iexact=pricing_tier).first()
        
        alias_map = {
            'louis vuitton': ['lv', 'louis vuitton'],
            'lv': ['louis vuitton', 'lv'],
            'saint laurent': ['ysl', 'saint laurent'],
            'ysl': ['saint laurent', 'ysl'],
            'bottega veneta': ['bottega', 'bottega veneta'],
            'bottega': ['bottega veneta', 'bottega'],
            'miu miu': ['miumiu', 'miu miu'],
            'miumiu': ['miu miu', 'miumiu'],
            'celine': ['celne', 'celine'],
            'celne': ['celine', 'celne'],
            'max mara': ['maxmara', 'max mara'],
            'maxmara': ['max mara', 'maxmara'],
            'tiffany & co.': ['tiffany', 'tiffany & co.'],
            'tiffany': ['tiffany & co.', 'tiffany']
        }
        
        if not rate:
            possible_brands = alias_map.get(brand.lower(), [brand])
            for b in possible_brands:
                rate = PackagePrice.objects.filter(package=package, category__iexact=category, brand__iexact=b, member_tier__iexact=pricing_tier).first()
                if rate:
                    break

        # 2. Fallback to general member tier in PackagePrice if specific tier not found
        if not rate and pricing_tier != 'general':
            possible_brands = [brand] + alias_map.get(brand.lower(), [])
            for b in possible_brands:
                rate = PackagePrice.objects.filter(package=package, category__iexact=category, brand__iexact=b, member_tier='general').first()
                if rate:
                    break

        # 3. Fallback to BrandPricing master table
        found_bp_price = None
        if not rate:
            possible_brands = [brand] + alias_map.get(brand.lower(), [])
            bp = None
            for b in possible_brands:
                bp = BrandPricing.objects.filter(category__iexact=category, brand__iexact=b).first()
                if bp:
                    break
            if not bp:
                for b in possible_brands:
                    bp = BrandPricing.objects.filter(brand__iexact=b).first()
                    if bp:
                        break

            if bp:
                if tier in ('partner', 'corporate'):
                    base_amt = bp.partner_price
                else:
                    base_amt = bp.base_price

                if package.code == 'cert_90d':
                    found_bp_price = max(Decimal('3000.00'), Decimal(str(base_amt)) + Decimal('1500.00'))
                else:
                    found_bp_price = Decimal(str(base_amt))

        if rate:
            amount = money(rate.amount * factor) if factor is not None else rate.amount
        elif found_bp_price is not None:
            amount = money(found_bp_price * factor) if factor is not None else found_bp_price
        elif allow_missing_price and data.get('manual_service_amount') is not None:
            if not str(data.get('price_reason', '')).strip():
                raise ValidationError('กรุณาระบุเหตุผลราคาที่ตกลงกับลูกค้า')
            amount = money(data['manual_service_amount'])
        else:
            # 4. Default Category Fallback for custom/unlisted brands
            default_base = Decimal('1500.00') if category == 'Watch' else Decimal('1000.00')
            if tier in ('partner', 'corporate'):
                default_base = money(default_base * Decimal('0.75'))

            if package.code == 'cert_90d':
                amount = max(Decimal('3000.00'), default_base + Decimal('1500.00'))
            else:
                amount = default_base
            if factor is not None:
                amount = money(amount * factor)
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
