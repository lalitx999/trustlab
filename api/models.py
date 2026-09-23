from django.db import models
from django.contrib.auth.models import AbstractUser

# 1. Custom User Model for Staff Authentication
class StaffUser(AbstractUser):
    ROLE_CHOICES = [
        ('admin', 'Administrator'),
        ('manager', 'Manager'),
        ('expert', 'Expert Specialist'),
        ('front', 'Front Desk Staff'),
        ('customer', 'Customer'),
    ]
    role = models.CharField(max_length=15, choices=ROLE_CHOICES, default='front')
    branch = models.ForeignKey('Branch', on_delete=models.SET_NULL, null=True, blank=True)
    full_name = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    line_user_id = models.CharField(max_length=100, blank=True, null=True, unique=True)

    class Meta:
        db_table = 'staff_users'


# 2. Branch Model
class Branch(models.Model):
    name = models.CharField(max_length=100)
    address = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'branches'


# 2.5. Brand Model
class Brand(models.Model):
    brand_name = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.brand_name

    class Meta:
        db_table = 'brands'


# 3. Membership Levels (Reference: docs/sql.md)
class MembershipLevel(models.Model):
    level_name = models.CharField(max_length=50, unique=True) # Silver, Platinum, Gold, Partner
    level_type = models.CharField(max_length=50) # Customer Membership / Partner Membership
    entry_requirement = models.TextField()
    discount_pct = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    certificate_price = models.DecimalField(max_digits=10, decimal_places=2)
    general_benefits = models.TextField(null=True, blank=True)
    priority_service = models.TextField(null=True, blank=True)
    validity_period = models.CharField(max_length=50, null=True, blank=True)

    def __str__(self):
        return self.level_name

    class Meta:
        db_table = 'membership_levels'


# 4. Brand Pricing Matrix (Reference: docs/sql.md)
class BrandPricing(models.Model):
    CATEGORY_CHOICES = [
        ('Bag', 'Bag'),
        ('Clothes', 'Clothes'),
        ('Shoes', 'Shoes'),
        ('Accessories', 'Accessories'),
        ('Watch', 'Watch'),
    ]
    WATCH_TIERS = [
        ('Masterpiece', 'Masterpiece'),
        ('Luxury', 'Luxury'),
        ('Premium', 'Premium'),
    ]
    
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES)
    tier = models.CharField(max_length=20, choices=WATCH_TIERS, null=True, blank=True)
    brand = models.CharField(max_length=100)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    price_5pct = models.DecimalField(max_digits=10, decimal_places=2)  # Platinum Discount (5%)
    price_15pct = models.DecimalField(max_digits=10, decimal_places=2) # Gold Discount (15%)
    partner_price = models.DecimalField(max_digits=10, decimal_places=2) # Partner Rate
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        tier_str = f" ({self.tier})" if self.tier else ""
        return f"{self.brand} - {self.category}{tier_str}"

    class Meta:
        db_table = 'brand_pricing'
        unique_together = ('category', 'tier', 'brand')


# 5. Service Type
class ServiceType(models.Model):
    service_name = models.CharField(max_length=100, unique=True)
    service_name_th = models.CharField(max_length=100, blank=True, null=True)
    description = models.TextField()
    price_note = models.TextField()

    def __str__(self):
        return self.service_name

    class Meta:
        db_table = 'service_types'


# 6. Customer Profile
class Customer(models.Model):
    ACCOUNT_TYPE_CHOICES = [
        ('standard', 'Standard'),
        ('corporate', 'Corporate'),
    ]
    user = models.OneToOneField(StaffUser, on_delete=models.CASCADE, null=True, blank=True, related_name='customer_profile')
    full_name = models.CharField(max_length=255)
    phone_number = models.CharField(max_length=20, unique=True)
    line_id = models.CharField(max_length=100, blank=True, null=True)
    email = models.EmailField(blank=True, null=True)
    membership_level = models.ForeignKey(MembershipLevel, on_delete=models.SET_NULL, null=True)
    credit_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    # Corporate / Postpaid billing fields
    account_type = models.CharField(max_length=20, choices=ACCOUNT_TYPE_CHOICES, default='standard')
    postpaid_enabled = models.BooleanField(default=False, help_text="Allow corporate postpaid (inspect-now, pay-later)")
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, help_text="Maximum outstanding postpaid balance")
    note = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.full_name} ({self.phone_number})"

    class Meta:
        db_table = 'customers'


# 7. Booking System
class Booking(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
        ('completed', 'Completed'),
    ]
    DELIVERY_METHOD_CHOICES = [
        ('self_pickup', 'มารับด้วยตัวเอง'),
        ('shipping', 'จัดส่งพัสดุ'),
    ]
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='bookings')
    branch = models.ForeignKey(Branch, on_delete=models.PROTECT)
    booking_date = models.DateField()
    booking_time = models.TimeField()
    service_type = models.ForeignKey(ServiceType, on_delete=models.PROTECT)
    category = models.CharField(max_length=50, blank=True, default='BAG')
    brand_name = models.CharField(max_length=100, blank=True, default='')
    model = models.CharField(max_length=100, blank=True, default='')
    note = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    service_package = models.CharField(max_length=20, blank=True, default='')
    price_snapshot = models.JSONField(default=dict, blank=True)
    payment_status = models.CharField(max_length=20, default='unpaid')
    payment_method = models.CharField(max_length=20, blank=True, default='')
    payment_evidence = models.TextField(blank=True, default='')
    request_fingerprint = models.CharField(max_length=64, blank=True, default='')
    request_key = models.UUIDField(null=True, blank=True, unique=True)
    # Return shipping fields
    delivery_method = models.CharField(max_length=20, choices=DELIVERY_METHOD_CHOICES, default='self_pickup')
    shipping_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    return_address_name = models.CharField(max_length=255, blank=True, default='')
    return_phone = models.CharField(max_length=20, blank=True, default='')
    return_address_detail = models.TextField(blank=True, default='')
    return_subdistrict = models.CharField(max_length=100, blank=True, default='')
    return_district = models.CharField(max_length=100, blank=True, default='')
    return_province = models.CharField(max_length=100, blank=True, default='')
    return_postal_code = models.CharField(max_length=10, blank=True, default='')
    # Cancel fields
    cancel_reason = models.TextField(blank=True, null=True)
    cancelled_by = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='cancelled_bookings')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def customer_name(self):
        return self.customer.full_name if self.customer else ''

    @property
    def customer_email(self):
        return self.customer.email if self.customer else ''

    @property
    def customer_phone(self):
        return self.customer.phone_number if self.customer else ''

    @property
    def customer_line(self):
        return self.customer.line_id if self.customer else ''

    def __str__(self):
        return f"Booking #{self.id} - {self.customer.full_name if self.customer else ''}"

    class Meta:
        db_table = 'bookings'


# 8. Booking Photos (For camera scanning / upload queues)
class BookingPhoto(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='photos')
    photo = models.ImageField(upload_to='booking_photos/%Y/%m/%d/')
    photo_type = models.CharField(max_length=10, choices=[('customer', 'Customer'), ('staff', 'Staff')], default='staff')
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Photo #{self.id} for Booking #{self.booking.id}"

    class Meta:
        db_table = 'booking_photos'


# 9. Inspection Jobs (Checklist & Authentication Results)
class Job(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    RESULT_CHOICES = [
        ('authentic', 'Authentic'),
        ('fake', 'Fake'),
        ('inconclusive', 'Inconclusive'),
    ]
    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('credit_card', 'Credit Card'),
        ('transfer', 'Bank Transfer'),
        ('promptpay', 'PromptPay QR'),
        ('postpaid', 'Corporate Postpaid'),
    ]
    PAYMENT_STATUS_CHOICES = [
        ('unpaid', 'Unpaid'),
        ('paid', 'Paid'),
        ('invoiced', 'Invoiced (Postpaid)'),
    ]
    SHIPPING_STATUS_CHOICES = [
        ('not_applicable', 'มารับเอง'),
        ('pending_return', 'รอจัดส่งคืน'),
        ('ready_to_ship', 'เตรียมจัดส่งแล้ว'),
        ('shipped', 'จัดส่งแล้ว'),
        ('delivered', 'ลูกค้ารับแล้ว'),
    ]
    SERVICE_PACKAGE_CHOICES = [
        ('cert_15d', 'ตรวจสอบ + ใบรับรอง 15 วัน'),
        ('cert_90d', 'ตรวจสอบ + ใบรับรอง 90 วัน'),
        ('photo_review', 'ตรวจสอบผ่านรูปภาพ (Photo Review)'),
    ]
    
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE, null=True, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE)
    category = models.CharField(max_length=50) # e.g. Bag, Clothes, Shoes, Accessories, Watch
    brand = models.CharField(max_length=100)
    sub_category = models.CharField(max_length=100, blank=True, null=True)
    model = models.CharField(max_length=100)
    color = models.CharField(max_length=50)
    material = models.CharField(max_length=100, blank=True, default='')
    serial_number = models.CharField(max_length=100, blank=True, null=True)
    accessories = models.TextField(blank=True)  # List of received attachments (box, dustbag etc)
    notes = models.TextField(blank=True, null=True)
    expert_instruction = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    result = models.CharField(max_length=20, choices=RESULT_CHOICES, blank=True, null=True)
    queue_no = models.CharField(max_length=20)
    price_snapshot = models.JSONField(default=dict, blank=True)
    tag_code = models.CharField(max_length=100, blank=True, default='')
    result_recorded_by = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_jobs')
    expert_source = models.CharField(max_length=255, blank=True, default='')
    # Service Package (15-day cert / 90-day cert / photo review)
    service_package = models.CharField(max_length=20, choices=SERVICE_PACKAGE_CHOICES, default='cert_90d')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES)
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='unpaid')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    vat_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="VAT 7% amount")
    express_service = models.BooleanField(default=False)
    # Shipping return fields
    shipping_status = models.CharField(max_length=20, choices=SHIPPING_STATUS_CHOICES, default='not_applicable')
    tracking_number = models.CharField(max_length=100, blank=True, null=True)
    # Cancel fields
    cancel_reason = models.TextField(blank=True, null=True)
    cancelled_by = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='cancelled_jobs')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_approved_by = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_cancellations')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Job #{self.id} ({self.queue_no}) - {self.brand} {self.model}"

    class Meta:
        db_table = 'jobs'


# 10. Certificates (Issued for Authentic Items)
class Certificate(models.Model):
    STATUS_CHOICES = [
        ('authentic', 'Authentic'),
        ('revoked', 'Revoked'),
        ('expired', 'Expired'),
    ]
    job = models.OneToOneField(Job, on_delete=models.CASCADE, related_name='certificate')
    expires_at = models.DateTimeField(null=True, blank=True)
    validity_days = models.PositiveIntegerField(null=True, blank=True)
    cert_code = models.CharField(max_length=50, unique=True, blank=True, null=True,
                                 help_text="Human-readable certificate reference e.g. TL-N955-HAJW")
    cert_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='authentic')
    revoke_reason = models.TextField(blank=True, null=True)
    expired_at = models.DateTimeField(null=True, blank=True)
    selected_photos = models.JSONField(default=list, blank=True,
                                       help_text="List of selected photo IDs for display on certificate")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Certificate {self.cert_code or self.id} for Job #{self.job.id} - {self.cert_status.upper()}"

    class Meta:
        db_table = 'certificates'


# 11. Certificate Send Logs (LINE / Email history)
class CertificateSendLog(models.Model):
    SEND_METHOD = [
        ('email', 'Email'),
        ('line', 'LINE OA'),
    ]
    certificate = models.ForeignKey(Certificate, on_delete=models.CASCADE, related_name='send_logs')
    method = models.CharField(max_length=10, choices=SEND_METHOD)
    recipient = models.CharField(max_length=255)
    sent_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Sent cert #{self.certificate.id} via {self.method} to {self.recipient}"

    class Meta:
        db_table = 'certificate_send_logs'


# 12. Contact Form Submissions
class Contact(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=50, blank=True)
    message = models.TextField()
    status = models.CharField(max_length=20, default='unread')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'contacts'


# 13. Partner Program Applications
class Partner(models.Model):
    business_name = models.CharField(max_length=255)
    contact_name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=50)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'partners'


# 14. Top-up Request
class TopupRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='topup_requests')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=50, default='promptpay') # promptpay, credit_card
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default='pending')
    evidence = models.TextField(blank=True, default='')
    slip_photo = models.ImageField(upload_to='slips/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    approved_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"Topup #{self.id} - {self.customer.full_name} (฿{self.amount})"

    class Meta:
        db_table = 'topup_requests'




class ServicePackage(models.Model):
    code = models.CharField(max_length=20, primary_key=True, choices=Job.SERVICE_PACKAGE_CHOICES)
    name = models.CharField(max_length=100)
    validity_days = models.PositiveIntegerField(default=0)
    sort_order = models.PositiveIntegerField(default=0)
    enabled = models.BooleanField(default=True)

    class Meta:
        ordering = ['sort_order']


class PackagePrice(models.Model):
    package = models.ForeignKey(ServicePackage, on_delete=models.PROTECT)
    category = models.CharField(max_length=20)
    brand = models.CharField(max_length=100)
    member_tier = models.CharField(max_length=50, default='general')
    amount = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['package', 'category', 'brand', 'member_tier'], name='unique_package_rate'),
                       models.CheckConstraint(condition=models.Q(amount__gte=0), name='package_rate_nonnegative')]


class CheckoutPolicy(models.Model):
    # Explicit approval is required before accepting payments with this policy.
    approved = models.BooleanField(default=False)
    prices_include_vat = models.BooleanField(default=True)
    shipping_taxable = models.BooleanField(default=True)
    shipping_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    updated_at = models.DateTimeField(auto_now=True)


class CreditEntry(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name='credit_entries')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    reference = models.CharField(max_length=120, unique=True)
    reason = models.TextField()
    actor = models.ForeignKey(StaffUser, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)


class WorkflowEvent(models.Model):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, null=True, blank=True)
    job = models.ForeignKey(Job, on_delete=models.CASCADE, null=True, blank=True)
    actor = models.ForeignKey(StaffUser, on_delete=models.PROTECT)
    action = models.CharField(max_length=50)
    detail = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)


class CancellationRequest(models.Model):
    booking = models.OneToOneField(Booking, on_delete=models.CASCADE)
    reason = models.TextField()
    status = models.CharField(max_length=20, default='pending')
    requested_by = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='cancellation_requests')
    reviewed_by = models.ForeignKey(StaffUser, on_delete=models.SET_NULL, null=True, blank=True, related_name='cancellation_reviews')
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    refund_status = models.CharField(max_length=20, default='not_required')
    refund_reference = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)


class StaffNotification(models.Model):
    """Pending staff notifications; dispatch is disabled until recipients are confirmed."""
    event_key = models.CharField(max_length=160)
    channel = models.CharField(max_length=20, choices=[('line', 'LINE'), ('wechat', 'WeChat')])
    event_type = models.CharField(max_length=40)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=32, default='awaiting_configuration')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['event_key', 'channel'], name='unique_staff_notification_event')]
