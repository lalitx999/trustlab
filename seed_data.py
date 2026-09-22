import os
import django
import sys

# Configure Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend_config.settings')
django.setup()

from api.models import (
    MembershipLevel, ServiceType, Branch, BrandPricing, StaffUser, Brand
)
from django.contrib.auth import get_user_model

def seed():
    print("🌱 Starting database seeding...")

    # 1. Seed Branch
    branch, created = Branch.objects.get_or_create(
        id=1,
        defaults={
            'name': 'BKK - Siam Square One',
            'address': 'Siam Square One, Bangkok',
            'is_active': True
        }
    )
    if created:
        print("  - Branch created: BKK - Siam Square One")
    else:
        print("  - Branch already exists")

    # 2. Seed Membership Levels
    membership_levels = [
        {
            'level_name': 'Silver',
            'level_type': 'Customer Membership',
            'entry_requirement': 'Free Membership',
            'discount_pct': 0.00,
            'certificate_price': 2000.00,
            'general_benefits': 'รับโปรโมชั่นสะสมแต้มและสิทธิพิเศษสำหรับสมาชิก เช่น ส่วนลดเดือนเกิด, ส่วนลดตามเทศกาล; สิทธิ์เข้าถึงโปรโมชั่นช่วงพิเศษ',
            'priority_service': '',
            'validity_period': ''
        },
        {
            'level_name': 'Platinum',
            'level_type': 'Customer Membership',
            'entry_requirement': 'ซื้อเครดิตตรวจ 3,000 THB',
            'discount_pct': 15.00,
            'certificate_price': 1500.00,
            'general_benefits': 'รับโปรโมชั่นและสิทธิพิเศษสำหรับสมาชิก',
            'priority_service': 'Priority Service สำหรับสมาชิก',
            'validity_period': '1 ปี'
        },
        {
            'level_name': 'Gold',
            'level_type': 'Customer Membership',
            'entry_requirement': 'ซื้อเครดิตตรวจ 6,000 THB',
            'discount_pct': 5.00,
            'certificate_price': 1200.00,
            'general_benefits': 'รับโปรโมชั่นและสิทธิพิเศษสำหรับสมาชิก',
            'priority_service': 'Priority Queue และ Fast Track Service',
            'validity_period': '1 ปี'
        },
        {
            'level_name': 'Partner',
            'level_type': 'Partner Membership',
            'entry_requirement': 'ซื้อเครดิตตรวจ 20,000 THB',
            'discount_pct': 0.00,
            'certificate_price': 1000.00,
            'general_benefits': 'โปรโมชั่นและสิทธิพิเศษสำหรับร้านค้า (ใช้ Partner Rate)',
            'priority_service': 'สิทธิ์เข้าร่วม Partner Program',
            'validity_period': '1 ปี'
        }
    ]
    
    for ml in membership_levels:
        level, created = MembershipLevel.objects.get_or_create(
            level_name=ml['level_name'],
            defaults=ml
        )
        if created:
            print(f"  - Membership Level created: {ml['level_name']}")

    # 3. Seed Service Types
    services = [
        {
            'service_name': 'Authentication Only',
            'service_name_th': 'ตรวจสอบสินค้า',
            'description': '- ตรวจสอบความแท้ของสินค้าโดยผู้เชี่ยวชาญ\n- รองรับการนำสินค้ามาตรวจที่สาขา เพื่อความแม่นยำ (เฉพาะแบรนด์/ประเภทที่รองรับ)\n- ไม่รวมใบรับรอง (Certificate)',
            'price_note': 'ราคาจะแตกต่างกันตามประเภทสินค้า แบรนด์ และระดับสมาชิก (อ้างอิง brand_pricing + membership_levels)'
        },
        {
            'service_name': 'Authentication + Certificate',
            'service_name_th': 'ตรวจสอบพร้อมออกใบรับรอง',
            'description': '- ตรวจสอบความแท้ของสินค้าโดยผู้เชี่ยวชาญ\n- ออก TRUST LAB Certificate พร้อม QR Verification และ Certificate ID\n- บันทึกผลการตรวจสอบในระบบ',
            'price_note': 'ค่าตรวจสอบ + ค่า Certificate เริ่มต้น 2,000 บาท ราคาขึ้นอยู่กับระดับสมาชิก (อ้างอิง membership_levels.certificate_price)'
        },
        {
            'service_name': 'Certificate Add-on',
            'service_name_th': 'เพิ่มใบรับรอง',
            'description': '- สำหรับสินค้าที่เคยผ่านการตรวจสอบกับ TRUST LAB แบบ Authentication Only\n- ขอออก Certificate ภายหลังได้ ภายใน 30 วัน นับจากวันที่ตรวจสอบ\n- หากเกิน 30 วัน ต้องนำสินค้ามาตรวจสอบใหม่',
            'price_note': 'ค่า Certificate เริ่มต้น 2,000 บาท ราคาขึ้นอยู่กับระดับสมาชิก (อ้างอิง membership_levels.certificate_price)'
        },
        {
            'service_name': 'Credit Top-up',
            'service_name_th': 'เติมเครดิตสมาชิก',
            'description': '- เติมเครดิตเข้าสู่บัญชีสมาชิกเพื่อใช้ชำระค่าบริการของ TRUST LAB\n- เครดิตสามารถใช้เป็นส่วนลดค่าตรวจสอบและค่า Certificate ตามสิทธิ์ของแต่ละระดับสมาชิก\n- เหมาะสำหรับลูกค้าประจำ ร้านค้า และพาร์ทเนอร์ที่ใช้บริการต่อเนื่อง',
            'price_note': 'เติมเครดิตเท่าไหร่ก็ได้ แต่ถ้าเติมครบยอดตามที่กำหนดจะได้เครดิตเพิ่ม'
        }
    ]

    for svc in services:
        service, created = ServiceType.objects.get_or_create(
            service_name=svc['service_name'],
            defaults=svc
        )
        if created:
            print(f"  - Service Type created: {svc['service_name']}")

    # 4. Seed full production Brand Pricing Matrix (96 records across BAG, CLOTHES, SHOES, ACCESSORIES, WATCH)
    pricings = [
        # BAG (1 - 20)
        ('Bag', None, 'Hermes', 1700, 1615, 1445, 1250),
        ('Bag', None, 'chanel', 1500, 1425, 1275, 1150),
        ('Bag', None, 'Delvaux', 1300, 1235, 1105, 950),
        ('Bag', None, 'dior', 1300, 1235, 1105, 950),
        ('Bag', None, 'miumiu', 1300, 1235, 1105, 950),
        ('Bag', None, 'celine', 1300, 1235, 1105, 950),
        ('Bag', None, 'loewe', 1300, 1235, 1105, 950),
        ('Bag', None, 'Goyard', 1300, 1235, 1105, 950),
        ('Bag', None, 'bvlgari', 1300, 1235, 1105, 950),
        ('Bag', None, 'gucci', 1200, 1140, 1020, 850),
        ('Bag', None, 'prada', 1200, 1140, 1020, 850),
        ('Bag', None, 'fendi', 1200, 1140, 1020, 850),
        ('Bag', None, 'balenciaga', 1200, 1140, 1020, 850),
        ('Bag', None, 'ysl', 1200, 1140, 1020, 850),
        ('Bag', None, 'Bottega', 1200, 1140, 1020, 850),
        ('Bag', None, 'lv', 1000, 950, 850, 650),
        ('Bag', None, 'Chloe', 1000, 950, 850, 650),
        ('Bag', None, 'Mcm', 1000, 950, 850, 650),
        ('Bag', None, 'Burberry', 1000, 950, 850, 650),
        ('Bag', None, 'Moynat', 1000, 950, 850, 650),

        # CLOTHES (21 - 36)
        ('Clothes', None, 'Lv', 1300, 1235, 1105, 850),
        ('Clothes', None, 'Gucci', 1300, 1235, 1105, 850),
        ('Clothes', None, 'Burberry', 1300, 1235, 1105, 850),
        ('Clothes', None, 'Balenciaga', 1300, 1235, 1105, 850),
        ('Clothes', None, 'Loewe', 1300, 1235, 1105, 850),
        ('Clothes', None, 'Hermes', 1300, 1235, 1105, 850),
        ('Clothes', None, 'Chanel', 1300, 1235, 1105, 850),
        ('Clothes', None, 'Dior', 1300, 1235, 1105, 850),
        ('Clothes', None, 'Prada', 1300, 1235, 1105, 850),
        ('Clothes', None, 'Miumiu', 1300, 1235, 1105, 850),
        ('Clothes', None, 'Fendi', 1300, 1235, 1105, 850),
        ('Clothes', None, 'Celne', 1300, 1235, 1105, 850),
        ('Clothes', None, 'Ysl', 1300, 1235, 1105, 850),
        ('Clothes', None, 'Maxmara', 1300, 1235, 1105, 850),
        ('Clothes', None, 'Canada goose', 1300, 1235, 1105, 850),
        ('Clothes', None, 'Moncler', 1300, 1235, 1105, 850),

        # SHOES (37 - 52)
        ('Shoes', None, 'Lv', 1300, 1235, 1105, 850),
        ('Shoes', None, 'Gucci', 1300, 1235, 1105, 850),
        ('Shoes', None, 'Burberry', 1300, 1235, 1105, 850),
        ('Shoes', None, 'Balenciaga', 1300, 1235, 1105, 850),
        ('Shoes', None, 'Loewe', 1300, 1235, 1105, 850),
        ('Shoes', None, 'Hermes', 1300, 1235, 1105, 850),
        ('Shoes', None, 'Chanel', 1300, 1235, 1105, 850),
        ('Shoes', None, 'Dior', 1300, 1235, 1105, 850),
        ('Shoes', None, 'Prada', 1300, 1235, 1105, 850),
        ('Shoes', None, 'Miumiu', 1300, 1235, 1105, 850),
        ('Shoes', None, 'Fendi', 1300, 1235, 1105, 850),
        ('Shoes', None, 'Celne', 1300, 1235, 1105, 850),
        ('Shoes', None, 'Ysl', 1300, 1235, 1105, 850),
        ('Shoes', None, 'Maxmara', 1300, 1235, 1105, 850),
        ('Shoes', None, 'Canada goose', 1300, 1235, 1105, 850),
        ('Shoes', None, 'Moncler', 1300, 1235, 1105, 850),

        # ACCESSORIES (53 - 69)
        ('Accessories', None, 'Harry Winston', 2500, 2375, 2125, 2000),
        ('Accessories', None, 'Graff', 2500, 2375, 2125, 2000),
        ('Accessories', None, 'Buccellati', 2500, 2375, 2125, 2000),
        ('Accessories', None, 'Chaumet', 2000, 1900, 1700, 1500),
        ('Accessories', None, 'Van Cleef & Arpels', 2000, 1900, 1700, 1500),
        ('Accessories', None, 'Boucheron', 2000, 1900, 1700, 1500),
        ('Accessories', None, 'Piaget', 2000, 1900, 1700, 1500),
        ('Accessories', None, 'Qeelin', 2000, 1900, 1700, 1500),
        ('Accessories', None, 'Cartier', 2000, 1900, 1700, 1500),
        ('Accessories', None, 'Bvlgari', 2000, 1900, 1700, 1500),
        ('Accessories', None, 'Chopard', 2000, 1900, 1700, 1500),
        ('Accessories', None, 'Tiffany & Co.', 2000, 1900, 1700, 1500),
        ('Accessories', None, 'Chanel', 1500, 1425, 1275, 1100),
        ('Accessories', None, 'Hermès', 1500, 1425, 1275, 1100),
        ('Accessories', None, 'Dior', 1500, 1425, 1275, 1100),
        ('Accessories', None, 'Louis Vuitton', 1500, 1425, 1275, 1100),
        ('Accessories', None, 'Gucci', 1500, 1425, 1275, 1100),

        # WATCH (70 - 96)
        ('Watch', 'Masterpiece', 'Patek Philippe Genève', 3000, 2850, 2550, 2500),
        ('Watch', 'Masterpiece', 'A. Lange & Söhne', 3000, 2850, 2550, 2500),
        ('Watch', 'Masterpiece', 'Vacheron Constantin', 3000, 2850, 2550, 2500),
        ('Watch', 'Masterpiece', 'Roger Dubuis', 3000, 2850, 2550, 2500),
        ('Watch', 'Masterpiece', 'Audemars Piguet', 3000, 2850, 2550, 2500),
        ('Watch', 'Masterpiece', 'Richard Mille', 3000, 2850, 2550, 2500),
        ('Watch', 'Luxury', 'Blancpain', 2000, 1900, 1700, 1500),
        ('Watch', 'Luxury', 'Breguet', 2000, 1900, 1700, 1500),
        ('Watch', 'Luxury', 'Rolex', 2000, 1900, 1700, 1500),
        ('Watch', 'Luxury', 'Jaeger-LeCoultre', 2000, 1900, 1700, 1500),
        ('Watch', 'Luxury', 'Girard-Perregaux', 2000, 1900, 1700, 1500),
        ('Watch', 'Luxury', 'Van Cleef & Arpels', 2000, 1900, 1700, 1500),
        ('Watch', 'Luxury', 'Piaget', 2000, 1900, 1700, 1500),
        ('Watch', 'Luxury', 'Glashütte Original', 2000, 1900, 1700, 1500),
        ('Watch', 'Premium', 'Cartier', 1500, 1425, 1275, 1200),
        ('Watch', 'Premium', 'Omega', 1500, 1425, 1275, 1200),
        ('Watch', 'Premium', 'IWC Schaffhausen', 1500, 1425, 1275, 1200),
        ('Watch', 'Premium', 'Breitling', 1500, 1425, 1275, 1200),
        ('Watch', 'Premium', 'Hublot', 1500, 1425, 1275, 1200),
        ('Watch', 'Premium', 'Panerai', 1500, 1425, 1275, 1200),
        ('Watch', 'Premium', 'Zenith', 1500, 1425, 1275, 1200),
        ('Watch', 'Premium', 'Chopard', 1500, 1425, 1275, 1200),
        ('Watch', 'Premium', 'Franck Muller', 1500, 1425, 1275, 1200),
        ('Watch', 'Premium', 'Longines', 1500, 1425, 1275, 1200),
        ('Watch', 'Premium', 'Tudor', 1500, 1425, 1275, 1200),
        ('Watch', 'Premium', 'Chanel', 1500, 1425, 1275, 1200),
        ('Watch', 'Premium', 'Hermès', 1500, 1425, 1275, 1200),
    ]

    for cat, tier, brand, base, p5, p15, partner in pricings:
        bp, created = BrandPricing.objects.update_or_create(
            category=cat,
            tier=tier,
            brand=brand,
            defaults={
                'base_price': base,
                'price_5pct': p5,
                'price_15pct': p15,
                'partner_price': partner
            }
        )
        if created:
            print(f"  - Brand Pricing created: {brand} ({cat})")
        else:
            print(f"  - Brand Pricing updated: {brand} ({cat})")


    # 4.5. Seed Brand table with all unique brand names
    unique_brands = set(p[2] for p in pricings)
    for b_name in sorted(unique_brands):
        b_obj, b_created = Brand.objects.get_or_create(brand_name=b_name)
        if b_created:
            print(f"  - Brand registered in DB: {b_name}")


    # 5. Seed default admin staff user
    User = get_user_model()
    if not User.objects.filter(username="admin").exists():
        admin_user = User.objects.create_superuser(
            username="admin",
            email="admin@trustlab.com",
            password="adminpassword",
            role="admin",
            branch=branch
        )
        print("  - Default Admin Superuser created: admin / adminpassword")
    else:
        print("  - Admin user already exists")

    print("✨ Database seeding completed successfully!")

if __name__ == '__main__':
    seed()
