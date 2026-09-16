from django.urls import path
from .views import (
    auth_login, JobListCreateView, JobDetailView, job_photos,
    create_certificate, certificate_detail, certificate_photos_update, certificate_send_logs, certificate_send,
    certificate_revoke, certificate_expire, certificate_pdf_view,
    public_verify, BookingListCreateView, bookings_today,
    booking_detail, booking_photos, booking_cancel, customers_search,
    public_customer_lookup, members_list, members_credit, members_transactions,
    ServiceTypeListCreateView, brand_pricing_query, membership_pricing_list,
    public_qrcode_view, PublicContactSubmitView, PublicPartnerSubmitView,
    reports_daily_summary, reports_daily_summary_pdf, BrandListCreateView, BrandDeleteView, UserListCreateView,
    UserDetailView, ServiceTypeDetailView, customer_create, branches_list,
    public_booking_availability, public_invoice_preview, contacts_list, partners_list,
    contact_detail, partner_detail, generate_promptpay_qr, payments_webhook_promptpay, payments_charge, auth_line_login,
    auth_customer_register, customer_dashboard, customer_profile_update,
    customer_topup_initiate, customer_topup_submit_slip, customer_topup_charge_card
)

urlpatterns = [
    # 1. ระบบยืนยันตัวตน (Authentication)
    path('auth/login', auth_login, name='auth_login'),
    path('users', UserListCreateView.as_view(), name='users_list_create'),
    path('users/<int:pk>', UserDetailView.as_view(), name='user_detail_update_delete'),

    path('jobs', JobListCreateView.as_view(), name='jobs_list_create'),
    path('jobs/<str:pk>', JobDetailView.as_view(), name='job_detail_update'),
    path('jobs/<str:pk>/photos', job_photos, name='job_photos'),

    # 3. ใบรับรองสินค้า (Certificates) & ตรวจสาธารณะ (Verify)
    path('certificates', create_certificate, name='create_certificate'),
    path('certificates/<str:pk>', certificate_detail, name='certificate_detail'),
    path('certificates/<str:pk>/photos', certificate_photos_update, name='certificate_photos_update'),
    path('certificates/<str:pk>/send-logs', certificate_send_logs, name='certificate_send_logs'),
    path('certificates/<str:pk>/send', certificate_send, name='certificate_send'),
    path('certificates/<str:pk>/revoke', certificate_revoke, name='certificate_revoke'),
    path('certificates/<str:pk>/expire', certificate_expire, name='certificate_expire'),
    path('certificates/<str:pk>/pdf', certificate_pdf_view, name='certificate_pdf_view'),
    path('public/verify/<str:pk>', public_verify, name='public_verify'),

    # 4. การจองคิว (Bookings)
    path('bookings', BookingListCreateView.as_view(), name='bookings_list_create'),
    path('bookings/today', bookings_today, name='bookings_today'),
    path('bookings/<str:pk>/cancel', booking_cancel, name='booking_cancel'),
    path('bookings/<str:pk>', booking_detail, name='booking_detail'),
    path('bookings/<str:pk>/photos', booking_photos, name='booking_photos'),

    # 5. ลูกค้า สมาชิก และเครดิต (Customers & Members)
    path('customers', customer_create, name='customer_create'),
    path('customers/search', customers_search, name='customers_search'),
    path('public/customer-lookup', public_customer_lookup, name='public_customer_lookup'),
    path('members', members_list, name='members_list'),
    path('members/credit', members_credit, name='members_credit'),
    path('members/transactions', members_transactions, name='members_transactions'),

    # 6. ข้อมูลตั้งต้นระบบและราคา (Master Data & Pricing)
    path('services', ServiceTypeListCreateView.as_view(), name='services_list'),
    path('services/<int:pk>', ServiceTypeDetailView.as_view(), name='service_detail_update_delete'),
    path('brands', BrandListCreateView.as_view(), name='brands_list_create'),
    path('brands/<int:pk>', BrandDeleteView.as_view(), name='brand_delete'),
    path('brands/pricing', brand_pricing_query, name='brand_pricing_query'),
    path('membership-pricing', membership_pricing_list, name='membership_pricing_list'),
    path('branches', branches_list, name='branches_list'),
    path('public/booking-availability', public_booking_availability, name='public_booking_availability'),

    # 7. Utilities & Public Pages (PromptPay, Contacts & Partners)
    path('public/qrcode', public_qrcode_view, name='public_qrcode_view'),
    path('public/contacts', PublicContactSubmitView.as_view(), name='public_contact_submit'),
    path('public/partners', PublicPartnerSubmitView.as_view(), name='public_partner_submit'),
    path('contacts', contacts_list, name='contacts_list'),
    path('contacts/<int:pk>', contact_detail, name='contact_detail'),
    path('partners', partners_list, name='partners_list'),
    path('partners/<int:pk>', partner_detail, name='partner_detail'),
    path('reports/daily', reports_daily_summary, name='reports_daily_summary'),
    path('reports/daily/pdf', reports_daily_summary_pdf, name='reports_daily_summary_pdf'),
    path('public/invoice/preview', public_invoice_preview, name='public_invoice_preview'),
    path('payments/promptpay/generate', generate_promptpay_qr, name='generate_promptpay_qr'),
    path('payments/promptpay/webhook', payments_webhook_promptpay, name='payments_webhook_promptpay'),
    path('payments/charge', payments_charge, name='payments_charge'),
    path('auth/line-login', auth_line_login, name='auth_line_login'),
    
    # 8. Customer Portal Dashboard
    path('auth/customer/register', auth_customer_register, name='auth_customer_register'),
    path('customer/dashboard', customer_dashboard, name='customer_dashboard'),
    path('customer/profile', customer_profile_update, name='customer_profile_update'),
    
    # 9. Customer Credit Top-up System
    path('customer/topup/initiate', customer_topup_initiate, name='customer_topup_initiate'),
    path('customer/topup/submit-slip', customer_topup_submit_slip, name='customer_topup_submit_slip'),
    path('customer/topup/charge-card', customer_topup_charge_card, name='customer_topup_charge_card'),
]
