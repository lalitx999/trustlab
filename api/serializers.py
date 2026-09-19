import base64
import uuid
from django.core.files.base import ContentFile
from rest_framework import serializers
from .models import (
    StaffUser, Branch, Brand, MembershipLevel, BrandPricing,
    ServiceType, Customer, Booking, BookingPhoto,
    Job, Certificate, CertificateSendLog, Contact, Partner
)

# Custom field to handle incoming Base64 image strings from frontend uploads
class Base64ImageField(serializers.ImageField):
    def to_internal_value(self, data):
        if isinstance(data, str) and data.startswith('data:image'):
            # format: data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA...
            try:
                fmt, imgstr = data.split(';base64,')
                ext = fmt.split('/')[-1]
                file_name = f"{uuid.uuid4()}.{ext}"
                data = ContentFile(base64.b64decode(imgstr), name=file_name)
            except Exception as e:
                raise serializers.ValidationError(f"Invalid base64 image data: {str(e)}")
        return super().to_internal_value(data)


class StaffUserSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='id', read_only=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True)

    class Meta:
        model = StaffUser
        fields = ['user_id', 'username', 'email', 'role', 'branch', 'full_name', 'phone', 'is_active', 'password']
        read_only_fields = ['user_id']

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        user = super().create(validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user



class BranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = Branch
        fields = '__all__'


class BrandSerializer(serializers.ModelSerializer):
    brand_id = serializers.IntegerField(source='id', read_only=True)

    class Meta:
        model = Brand
        fields = ['brand_id', 'brand_name', 'created_at']


class MembershipLevelSerializer(serializers.ModelSerializer):
    tier_key = serializers.CharField(source='level_name', read_only=True)
    discount_percent = serializers.DecimalField(source='discount_pct', max_digits=5, decimal_places=2, read_only=True)
    cert_price = serializers.DecimalField(source='certificate_price', max_digits=10, decimal_places=2, read_only=True)

    class Meta:
        model = MembershipLevel
        fields = ['id', 'tier_key', 'discount_percent', 'cert_price']


class BrandPricingSerializer(serializers.ModelSerializer):
    price_general = serializers.IntegerField(source='base_price', read_only=True)
    price_silver = serializers.IntegerField(source='price_5pct', read_only=True)
    price_platinum = serializers.IntegerField(source='price_15pct', read_only=True)
    price_partner = serializers.IntegerField(source='partner_price', read_only=True)

    class Meta:
        model = BrandPricing
        fields = ['id', 'category', 'brand', 'price_general', 'price_silver', 'price_platinum', 'price_partner']


class ServiceTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ServiceType
        fields = '__all__'


class CustomerSerializer(serializers.ModelSerializer):
    membership_level_name = serializers.CharField(source='membership_level.level_name', read_only=True)
    discount_pct = serializers.DecimalField(source='membership_level.discount_pct', max_digits=5, decimal_places=2, read_only=True)

    class Meta:
        model = Customer
        fields = [
            'id', 'full_name', 'phone_number', 'line_id', 'email',
            'membership_level', 'membership_level_name', 'discount_pct',
            'credit_balance', 'account_type', 'postpaid_enabled', 'credit_limit',
            'note', 'created_at'
        ]
        read_only_fields = ['id', 'credit_balance', 'created_at']


class BookingPhotoSerializer(serializers.ModelSerializer):
    class Meta:
        model = BookingPhoto
        fields = ['id', 'photo', 'photo_type', 'uploaded_at']


class BookingSerializer(serializers.ModelSerializer):
    inspection_result = serializers.CharField(source='job.result', read_only=True, default=None)
    photos = BookingPhotoSerializer(many=True, read_only=True)
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True)
    customer_email = serializers.CharField(source='customer.email', read_only=True, default='')
    customer_line = serializers.CharField(source='customer.line_id', read_only=True, default='')
    customer_type = serializers.SerializerMethodField()
    customer_credit_balance = serializers.SerializerMethodField()
    customer_discount_percent = serializers.SerializerMethodField()
    member_badge = serializers.SerializerMethodField()
    service_name = serializers.CharField(source='service_type.service_name', read_only=True)
    branch_name = serializers.CharField(source='branch.name', read_only=True)
    brand = serializers.CharField(source='brand_name', read_only=True)
    photo_count = serializers.SerializerMethodField()
    booking_id = serializers.SerializerMethodField()
    time_slot = serializers.SerializerMethodField()
    service_type = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            'id', 'booking_id', 'customer', 'customer_name', 'customer_phone',
            'customer_email', 'customer_line', 'customer_type', 'customer_credit_balance',
            'customer_discount_percent', 'member_badge',
            'branch', 'branch_name', 'booking_date', 'booking_time', 'time_slot',
            'service_type', 'service_name', 'status', 'photos', 'created_at',
            'service_package', 'price_snapshot', 'payment_status', 'payment_method', 'inspection_result',
            'category', 'brand_name', 'brand', 'model', 'note', 'photo_count',
            # Return shipping
            'delivery_method', 'shipping_fee',
            'return_address_name', 'return_phone', 'return_address_detail',
            'return_subdistrict', 'return_district', 'return_province', 'return_postal_code',
            # Cancel
            'cancel_reason', 'cancelled_at',
        ]
        read_only_fields = ['id', 'created_at', 'cancelled_at']

    def get_member_badge(self, obj):
        """Returns a normalized badge key for frontend rendering (corporate/partner/gold/silver/general)"""
        if not obj.customer:
            return 'general'
        cust = obj.customer
        # Check account type first
        if getattr(cust, 'account_type', 'standard') == 'corporate':
            return 'corporate'
        if cust.membership_level:
            level = cust.membership_level.level_name.lower()
            if 'partner' in level:
                return 'partner'
            elif 'gold' in level:
                return 'gold'
            elif 'silver' in level:
                return 'silver'
            elif 'platinum' in level:
                return 'platinum'
        return 'general'

    def get_category(self, obj):
        try:
            val = getattr(obj, 'category', None)
            if val:
                return val
        except Exception:
            pass
        return 'BAG'

    def get_customer_type(self, obj):
        if obj.customer and obj.customer.membership_level:
            return obj.customer.membership_level.level_name
        return 'ทั่วไป'

    def get_customer_credit_balance(self, obj):
        if obj.customer:
            return float(obj.customer.credit_balance or 0.0)
        return 0.0

    def get_customer_discount_percent(self, obj):
        if obj.customer and obj.customer.membership_level:
            return float(obj.customer.membership_level.discount_pct or 0.0)
        return 0.0

    def get_photo_count(self, obj):
        return obj.photos.count()

    def get_booking_id(self, obj):
        import datetime
        date_str = obj.booking_date.strftime('%y%m%d') if obj.booking_date else datetime.date.today().strftime('%y%m%d')
        return f"BK-{date_str}-{obj.id:03d}"

    def get_time_slot(self, obj):
        if obj.booking_time:
            return obj.booking_time.strftime('%H:%M:%S')
        return "10:30:00"

    def get_service_type(self, obj):
        if obj.service_package:
            return obj.service_package
        if not obj.service_type:
            return 'authentication'
        name = obj.service_type.service_name.lower()
        if 'certificate' in name and 'auth' in name:
            return 'auth_certificate'
        elif 'certificate' in name:
            return 'certificate_only'
        return 'authentication'


class JobSerializer(serializers.ModelSerializer):
    job_id = serializers.SerializerMethodField()
    customer_name = serializers.CharField(source='customer.full_name', read_only=True)
    customer_phone = serializers.CharField(source='customer.phone_number', read_only=True)
    brand_name = serializers.CharField(source='brand', read_only=True)
    certificate_id = serializers.SerializerMethodField()
    cert_status = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category', read_only=True)
    photos = serializers.SerializerMethodField()
    branch_name = serializers.SerializerMethodField()
    expert_name = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = [
            'id', 'job_id', 'booking', 'customer', 'customer_name', 'customer_phone',
            'category', 'category_name', 'brand', 'brand_name', 'sub_category', 'model', 'color', 'material',
            'serial_number', 'accessories', 'notes', 'expert_instruction',
            'status', 'result', 'queue_no', 'payment_method', 'payment_status',
            'price', 'express_service', 'created_at', 'updated_at',
            'service_package', 'price_snapshot', 'vat_amount', 'tag_code', 'shipping_status', 'tracking_number', 'expert_source',
            'certificate_id', 'cert_status', 'photos', 'branch_name', 'expert_name'
        ]
        read_only_fields = ['id', 'queue_no', 'created_at', 'updated_at']

    def get_branch_name(self, obj):
        if obj.booking and obj.booking.branch:
            return obj.booking.branch.name
        return "สาขาหลัก (Headquarters - Bangkok)"

    def get_expert_name(self, obj):
        if obj.result_recorded_by:
            return obj.result_recorded_by.full_name or obj.result_recorded_by.username
        if obj.expert_source:
            return obj.expert_source
        return "สถาบันตรวจวิเคราะห์ TRUST LAB (Senior Specialist)"

    def get_photos(self, obj):
        if not obj.booking:
            return []
        photos = obj.booking.photos.all()
        request = self.context.get('request')
        return BookingPhotoSerializer(photos, many=True, context={'request': request}).data

    def get_job_id(self, obj):
        import datetime
        date_str = obj.created_at.strftime('%y%m') if obj.created_at else datetime.date.today().strftime('%y%m')
        cat_code = {
            'Bag': 'B',
            'Watch': 'W',
            'Accessories': 'A',
            'Shoes': 'S',
            'Clothes': 'C'
        }.get(obj.category, 'B')
        return f"TL{date_str}-{cat_code}-{obj.id:04d}"

    def get_certificate_id(self, obj):
        try:
            return obj.certificate.cert_code or obj.certificate.id
        except Certificate.DoesNotExist:
            return None

    def get_cert_status(self, obj):
        try:
            return obj.certificate.cert_status
        except Certificate.DoesNotExist:
            return None


class CertificateSerializer(serializers.ModelSerializer):
    certificate_id = serializers.CharField(source='cert_code', read_only=True)
    cert_status = serializers.SerializerMethodField()
    brand_name = serializers.CharField(source='job.brand', read_only=True)
    model = serializers.CharField(source='job.model', read_only=True)
    category_name = serializers.CharField(source='job.category', read_only=True)
    product_category_id = serializers.SerializerMethodField()
    issue_date = serializers.SerializerMethodField()
    expire_date = serializers.SerializerMethodField()
    photos = serializers.SerializerMethodField()
    all_photos = serializers.SerializerMethodField()
    branch_name = serializers.SerializerMethodField()
    expert_name = serializers.SerializerMethodField()

    class Meta:
        model = Certificate
        fields = [
            'id', 'certificate_id', 'job', 'cert_status', 'revoke_reason', 'expired_at',
            'created_at', 'updated_at', 'brand_name', 'model', 'category_name',
            'product_category_id', 'issue_date', 'expire_date', 'photos', 'all_photos',
            'branch_name', 'expert_name'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_branch_name(self, obj):
        if obj.job and obj.job.booking and obj.job.booking.branch:
            return obj.job.booking.branch.name
        return "สาขาหลัก (Headquarters - Bangkok)"

    def get_expert_name(self, obj):
        return "สถาบันตรวจวิเคราะห์ TRUST LAB (Senior Specialist)"

    def get_product_category_id(self, obj):
        mapping = {
            'Bag': 1,
            'Watch': 2,
            'Clothes': 3,
            'Shoes': 4,
            'Accessories': 5
        }
        return mapping.get(obj.job.category, 5)

    def get_issue_date(self, obj):
        from django.utils import timezone
        return timezone.localtime(obj.created_at).date().isoformat() if obj.created_at else None

    def get_cert_status(self, obj):
        from django.utils import timezone
        if obj.cert_status == 'authentic' and obj.expires_at and timezone.now() >= obj.expires_at:
            return 'expired'
        return obj.cert_status

    def get_expire_date(self, obj):
        if obj.expires_at:
            from django.utils import timezone
            return timezone.localtime(obj.expires_at).date().isoformat()
        if obj.expired_at:
            return obj.expired_at.date().isoformat()
        if obj.created_at:
            dt = obj.created_at
            month = dt.month + 6
            year = dt.year
            if month > 12:
                month -= 12
                year += 1
            import datetime
            try:
                expire_dt = datetime.date(year, month, dt.day)
            except ValueError:
                if month == 2:
                    is_leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                    expire_dt = datetime.date(year, month, 29 if is_leap else 28)
                elif month in (4, 6, 9, 11):
                    expire_dt = datetime.date(year, month, 30)
                else:
                    expire_dt = datetime.date(year, month, 31)
            return expire_dt.isoformat()
        return None

    def get_photos(self, obj):
        request = self.context.get('request')
        selected_ids = obj.selected_photos or []
        
        photos_map = {}
        all_bps = []
        if obj.job.booking:
            all_bps = list(obj.job.booking.photos.all())
            for bp in all_bps:
                if bp.photo:
                    url = bp.photo.url
                    if request:
                        url = request.build_absolute_uri(url)
                    photos_map[bp.id] = url
        
        if not selected_ids:
            fallback = [bp for bp in all_bps if bp.photo_type == 'staff'][:3]
            if not fallback:
                fallback = all_bps[:3]
            selected_ids = [bp.id for bp in fallback]
            
        ordered_photos = []
        for pid in selected_ids:
            if pid in photos_map:
                ordered_photos.append(photos_map[pid])
        return ordered_photos

    def get_all_photos(self, obj):
        request = self.context.get('request')
        selected_ids = obj.selected_photos or []
        
        all_bps = []
        if obj.job.booking:
            all_bps = list(obj.job.booking.photos.all().order_by('uploaded_at'))
            
        if not selected_ids:
            fallback = [bp for bp in all_bps if bp.photo_type == 'staff'][:3]
            if not fallback:
                fallback = all_bps[:3]
            selected_ids = [bp.id for bp in fallback]
            
        all_photos = []
        for bp in all_bps:
            if bp.photo:
                    url = bp.photo.url
                    if request:
                        url = request.build_absolute_uri(url)
                    
                    is_selected = 1 if bp.id in selected_ids else 0
                    display_order = selected_ids.index(bp.id) if bp.id in selected_ids else 99
                    
                    all_photos.append({
                        "photo_id": bp.id,
                        "url": url,
                        "source": bp.photo_type,
                        "selected_for_cert": is_selected,
                        "display_order": display_order
                    })
        return all_photos


class CertificateSendLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = CertificateSendLog
        fields = '__all__'


class ContactSerializer(serializers.ModelSerializer):
    class Meta:
        model = Contact
        fields = '__all__'


class PartnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Partner
        fields = '__all__'
