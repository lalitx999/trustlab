import os
import django
import sys

# Configure Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend_config.settings')
django.setup()

from api.models import (
    Brand, BrandPricing, MembershipLevel, ServiceType, Branch, StaffUser
)

def parse_sql_line(line):
    """
    Parses a single row of SQL insert values e.g., (1, 'Louis Vuitton', 'LV', NULL, ...)
    into a python list, handling quotes, escaping, and NULL values correctly.
    """
    line = line.strip()
    if line.startswith('('):
        line = line[1:]
    if line.endswith(',') or line.endswith(';'):
        line = line[:-1]
    if line.endswith(')'):
        line = line[:-1]
        
    items = []
    current = []
    in_quote = False
    quote_char = None
    escaped = False
    
    for char in line:
        if escaped:
            current.append(char)
            escaped = False
        elif char == '\\':
            escaped = True
        elif char in ("'", '"'):
            if in_quote:
                if char == quote_char:
                    in_quote = False
                else:
                    current.append(char)
            else:
                in_quote = True
                quote_char = char
        elif char == ',' and not in_quote:
            items.append(''.join(current).strip())
            current = []
        else:
            current.append(char)
    items.append(''.join(current).strip())
    
    # Clean up items
    cleaned = []
    for item in items:
        if item == 'NULL' or item == '':
            cleaned.append(None)
        elif item.isdigit():
            if item.startswith('0') and len(item) > 1:
                cleaned.append(item)
            else:
                cleaned.append(int(item))
        else:
            try:
                cleaned.append(float(item))
            except ValueError:
                cleaned.append(item)
    return cleaned


def import_sql_data(file_path):
    print(f"📖 Reading SQL file: {file_path}")
    if not os.path.exists(file_path):
        print(f"❌ Error: File not found at {file_path}")
        return

    # Clear existing master records to prevent unique constraint violations with pre-seeded data
    print("🧹 Clearing existing Master Data records...")
    BrandPricing.objects.all().delete()
    Brand.objects.all().delete()
    MembershipLevel.objects.all().delete()
    ServiceType.objects.all().delete()
    StaffUser.objects.all().delete()

    # Keep track of active table parsing
    current_table = None

    with open(file_path, 'r', encoding='utf-8') as f:
        for line in f:
            stripped = line.strip()
            
            # Detect INSERT INTO statements
            if stripped.startswith('INSERT INTO'):
                if '`brands`' in stripped:
                    current_table = 'brands'
                    print("🚀 Parsing INSERTs for table: brands")
                elif '`brand_pricing`' in stripped:
                    current_table = 'brand_pricing'
                    print("🚀 Parsing INSERTs for table: brand_pricing")
                elif '`membership_pricing`' in stripped:
                    current_table = 'membership_pricing'
                    print("🚀 Parsing INSERTs for table: membership_pricing")
                elif '`services`' in stripped:
                    current_table = 'services'
                    print("🚀 Parsing INSERTs for table: services")
                elif '`users`' in stripped:
                    current_table = 'users'
                    print("🚀 Parsing INSERTs for table: users")
                else:
                    current_table = None
                continue
                
            # If we are parsing rows for an active table
            if current_table and stripped.startswith('('):
                try:
                    row_data = parse_sql_line(stripped)
                    
                    if current_table == 'brands':
                        # Schema: brand_id (0), brand_name (1), brand_code (2), logo_url (3), description (4), status (5)
                        brand_id = row_data[0]
                        brand_name = row_data[1]
                        
                        Brand.objects.update_or_create(
                            id=brand_id,
                            defaults={'brand_name': brand_name}
                        )
                        
                    elif current_table == 'brand_pricing':
                        # Schema: id (0), category_code (1), brand_name (2), price_general (3), price_silver (4), price_platinum (5), price_partner (6)
                        bp_id = row_data[0]
                        cat_code = row_data[1]  # 'BAG', 'CLOTHES', 'SHOES', 'ACCESSORIES', 'WATCH'
                        brand_name = row_data[2]
                        price_gen = row_data[3]
                        price_sil = row_data[4]
                        price_plat = row_data[5]
                        price_part = row_data[6]
                        
                        # Map MySQL category code to Django choice value
                        cat_map = {
                            'BAG': 'Bag',
                            'CLOTHES': 'Clothes',
                            'SHOES': 'Shoes',
                            'ACCESSORIES': 'Accessories',
                            'WATCH': 'Watch'
                        }
                        category = cat_map.get(cat_code, 'Bag')
                        
                        # Set default watch tier if it's WATCH (or keep None)
                        tier = None
                        
                        BrandPricing.objects.update_or_create(
                            id=bp_id,
                            defaults={
                                'category': category,
                                'tier': tier,
                                'brand': brand_name,
                                'base_price': price_gen,
                                'price_5pct': price_sil,
                                'price_15pct': price_plat,
                                'partner_price': price_part
                            }
                        )
                        
                    elif current_table == 'membership_pricing':
                        # Schema: id (0), tier_key (1), tier_label (2), discount_percent (3), cert_price (4), topup_threshold (5)
                        mp_id = row_data[0]
                        tier_key = row_data[1] # 'general', 'silver', 'platinum', 'gold', 'partner', 'corporate'
                        tier_label = row_data[2]
                        discount = row_data[3]
                        cert_price = row_data[4]
                        topup = row_data[5]
                        
                        # Map MySQL keys to our Level Names (Capitalized)
                        level_map = {
                            'general': 'General',
                            'silver': 'Silver',
                            'platinum': 'Platinum',
                            'gold': 'Gold',
                            'partner': 'Partner',
                            'corporate': 'Corporate'
                        }
                        level_name = level_map.get(tier_key, tier_key.capitalize())
                        
                        MembershipLevel.objects.update_or_create(
                            level_name=level_name,
                            defaults={
                                'level_type': 'Customer Membership' if tier_key != 'partner' and tier_key != 'corporate' else 'Partner Membership',
                                'entry_requirement': f"ซื้อเครดิตสะสม {topup} THB" if topup > 0 else "สมัครฟรี",
                                'discount_pct': discount,
                                'certificate_price': cert_price,
                                'general_benefits': f"ระดับสิทธิ์ {tier_label}",
                                'validity_period': '1 ปี' if topup > 0 else ''
                            }
                        )
                        
                    elif current_table == 'services':
                        # Schema: service_id (0), service_code (1), service_name (2), description (3), price (4), status (5)
                        svc_id = row_data[0]
                        svc_code = row_data[1]
                        svc_name = row_data[2]
                        svc_desc = row_data[3] or ''
                        svc_price = row_data[4]
                        
                        # Map specific Thai translations we had
                        svc_th_map = {
                            'Authentication': 'ตรวจสอบสินค้า',
                            'Authentication + Certificate': 'ตรวจสอบพร้อมออกใบรับรอง',
                            'Certificate Only': 'เพิ่มใบรับรอง (แอดออน)'
                        }
                        svc_th = svc_th_map.get(svc_name, svc_name)
                        
                        ServiceType.objects.update_or_create(
                            id=svc_id,
                            defaults={
                                'service_name': svc_name,
                                'service_name_th': svc_th,
                                'description': svc_desc or f"บริการ {svc_name} ราคามาตรฐาน {svc_price} บาท",
                                'price_note': f"ราคาตั้งต้น {svc_price} THB"
                            }
                        )
                        
                    elif current_table == 'users':
                        # Schema: user_id (0), username (1), password_hash (2), full_name (3), email (4), phone (5), role (6), branch_id (7), status (8)
                        user_id = row_data[0]
                        username = row_data[1]
                        full_name = row_data[3]
                        email = row_data[4]
                        phone = row_data[5]
                        role = row_data[6]
                        branch_id = row_data[7]
                        status_val = row_data[8]
                        
                        # Get branch
                        branch = Branch.objects.filter(id=branch_id).first()
                        
                        # Create or update user
                        user, created = StaffUser.objects.update_or_create(
                            id=user_id,
                            defaults={
                                'username': username,
                                'email': email or f"{username}@trustlab.com",
                                'full_name': full_name,
                                'phone': phone,
                                'role': role,
                                'branch': branch,
                                'is_active': status_val == 'active',
                                'is_staff': True,
                                'is_superuser': role == 'admin'
                            }
                        )
                        
                        # Set default passwords for local developer convenience
                        pwd = "adminpassword" if username == "admin" else "password123"
                        user.set_password(pwd)
                        user.save()
                        
                except Exception as e:
                    print(f"⚠️ Error parsing line '{stripped[:50]}...': {e}")
                    
            # Stop table parsing if line ends with a semicolon and doesn't start with (
            if stripped.endswith(';') and not stripped.startswith('('):
                current_table = None

    print("✨ SQL Data import completed successfully!")

if __name__ == '__main__':
    sql_file = "u239440273_trustlabb (1).sql"
    if not os.path.exists(sql_file):
        sql_file = "/Users/tanchonl/Documents/trustlab/trustlab/public/u239440273_trustlabb (1).sql"
    import_sql_data(sql_file)
