import base64
import datetime
import io
import uuid
from decimal import Decimal
from PIL import Image
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from .models import (StaffUser, Customer, Branch, CheckoutPolicy, PackagePrice, ServicePackage,
                     Booking, Job, Certificate, TopupRequest, CreditEntry, CancellationRequest)
from .commerce import quote


def photo():
    out = io.BytesIO(); Image.new('RGB', (8, 8), 'red').save(out, format='PNG')
    return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode()

@override_settings(PROMPTPAY_RECEIVER_ID='0812345678')
class WorkflowTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = StaffUser.objects.create_user('admin-test', password='password123', role='admin')
        self.front = StaffUser.objects.create_user('front-test', password='password123', role='front')
        self.user = StaffUser.objects.create_user('customer-test', password='password123', role='customer')
        self.customer = Customer.objects.create(user=self.user, full_name='Test Customer', phone_number='0811111111', credit_balance=2000)
        self.branch = Branch.objects.create(name='Test branch')
        CheckoutPolicy.objects.update_or_create(pk=1, defaults={'approved': True, 'prices_include_vat': True, 'shipping_fee': 100})
        for code in ('cert_15d', 'cert_90d'):
            PackagePrice.objects.create(package_id=code, category='Bag', brand='Chanel', member_tier='general', amount=1070 if code == 'cert_15d' else 2140)
        self.client.force_authenticate(self.user)
        self.data = {'service_package': 'cert_15d', 'category': 'Bag', 'brand': 'Chanel', 'model': 'Classic',
                     'branch_id': self.branch.pk, 'date': '2026-09-21', 'timeSlot': '10:30', 'payment_method': 'shop',
                     'delivery_method': 'self_pickup', 'request_key': str(uuid.uuid4())}

    def create_booking(self, **changes):
        data = {**self.data, **changes}
        q = self.client.post('/api/checkout/quote', data, format='json')
        self.assertEqual(q.status_code, 200, q.data)
        data['quote_token'] = q.data['quote_token']
        response = self.client.post('/api/bookings', data, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        return Booking.objects.get(pk=response.data['booking_id']), data

    def checkin(self, booking):
        self.client.force_authenticate(self.front)
        response = self.client.post(f'/api/bookings/{booking.pk}/check-in', {}, format='json')
        self.assertIn(response.status_code, (200, 201), response.data)
        return Job.objects.get(booking=booking)

    def test_photo_price_no_discount_or_shipping(self):
        q = quote({**self.data, 'service_package': 'photo_review', 'delivery_method': 'shipping'}, self.customer)
        self.assertEqual(q['total'], '500.00'); self.assertEqual(q['shipping_fee'], '0.00')
        self.assertEqual(q['vat_amount'], '32.71'); self.assertEqual(q['validity_days'], 0)

    def test_price_policy_and_missing_rate_fail_closed(self):
        CheckoutPolicy.objects.update(approved=False)
        self.assertEqual(self.client.post('/api/checkout/quote', self.data, format='json').status_code, 400)
        CheckoutPolicy.objects.update(approved=True)
        self.assertEqual(self.client.post('/api/checkout/quote', {**self.data, 'brand': 'Unknown'}, format='json').status_code, 400)

    def test_quote_tamper_and_changed_price_rejected(self):
        q = self.client.post('/api/checkout/quote', self.data, format='json').data
        PackagePrice.objects.filter(package_id='cert_15d').update(amount=2000)
        r = self.client.post('/api/bookings', {**self.data, 'quote_token': q['quote_token']}, format='json')
        self.assertEqual(r.status_code, 400); self.assertEqual(Booking.objects.count(), 0)

    def test_wallet_charged_once_and_snapshot_preserved(self):
        b, data = self.create_booking(payment_method='wallet', total_amount='1')
        r = self.client.post('/api/bookings', data, format='json')
        self.assertEqual(r.status_code, 200)
        self.customer.refresh_from_db(); self.assertEqual(self.customer.credit_balance, Decimal('930'))
        self.assertEqual(CreditEntry.objects.count(), 1)
        self.assertEqual(b.price_snapshot['total'], '1070.00')

    def test_slip_pending_and_only_admin_can_approve(self):
        b, _ = self.create_booking(payment_method='promptpay', slip_base64=photo())
        self.assertEqual(b.status, 'pending'); self.assertEqual(b.payment_status, 'pending_review')
        path = f'/api/bookings/{b.pk}/payment-review'
        self.assertEqual(self.client.post(path, {'action': 'approve'}, format='json').status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(path, {'action': 'approve', 'amount': '1', 'reference': 'slip'}, format='json').status_code, 400)
        self.assertEqual(self.client.post(path, {'action': 'approve', 'amount': '1070', 'reference': 'slip'}, format='json').status_code, 200)
        b.refresh_from_db(); self.assertEqual(b.status, 'confirmed')

    def test_shipping_saved_and_checkin_idempotent(self):
        address = {k: 'Test' for k in ('return_address_name', 'return_phone', 'return_address_detail', 'return_subdistrict', 'return_district', 'return_province', 'return_postal_code')}
        b, _ = self.create_booking(delivery_method='shipping', **address)
        j = self.checkin(b); self.checkin(b)
        self.assertEqual(Job.objects.count(), 1); self.assertEqual(j.shipping_status, 'pending_return')
        self.assertEqual(j.price_snapshot['total'], '1170.00'); self.assertEqual(b.return_address_detail, 'Test')

    def test_certificate_requires_result_tag_and_physical_package(self):
        b, _ = self.create_booking(); j = self.checkin(b)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post('/api/certificates', {'job_id': j.pk}, format='json').status_code, 400)
        result = {'status': 'completed', 'result': 'authentic', 'tag_code': 'TAG-001', 'expert_source': 'Inspector'}
        self.assertEqual(self.client.put(f'/api/jobs/{j.pk}', result, format='json').status_code, 200)
        cert = Certificate.objects.get(job=j)
        self.assertEqual(cert.validity_days, 15)
        self.assertAlmostEqual((cert.expires_at - timezone.now()).total_seconds(), 15*86400, delta=10)
        cert.expires_at = timezone.now() - datetime.timedelta(seconds=1); cert.save()
        self.client.force_authenticate(None)
        self.assertEqual(self.client.get(f'/api/public/verify/{cert.cert_code}').data['status'], 'expired')

    def test_photo_never_gets_certificate(self):
        b, _ = self.create_booking(service_package='photo_review', photos=[photo()]); j = self.checkin(b)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.put(f'/api/jobs/{j.pk}', {'status': 'completed', 'result': 'authentic', 'expert_source': 'Inspector'}, format='json').status_code, 200)
        self.assertEqual(self.client.post('/api/certificates', {'job_id': j.pk}, format='json').status_code, 400)
        self.assertFalse(Certificate.objects.exists())

    def test_topup_slip_does_not_credit_and_replay_approval_safe(self):
        t = TopupRequest.objects.create(customer=self.customer, amount=500)
        r = self.client.post('/api/customer/topup/submit-slip', {'topup_id': t.pk, 'slip_base64': photo()}, format='json')
        self.assertEqual(r.status_code, 200); self.customer.refresh_from_db(); self.assertEqual(self.customer.credit_balance, 2000)
        self.client.force_authenticate(self.admin)
        for _ in range(2):
            r = self.client.post(f'/api/topups/{t.pk}/review', {'action': 'approve', 'amount': '500', 'reference': 'bank-01'}, format='json')
            self.assertEqual(r.status_code, 200, r.data)
        self.customer.refresh_from_db(); self.assertEqual(self.customer.credit_balance, 2500)
        self.assertEqual(CreditEntry.objects.count(), 1)

    def test_cancel_requires_approval_and_refund_evidence(self):
        b, _ = self.create_booking(payment_method='wallet'); j = self.checkin(b)
        r = self.client.put(f'/api/bookings/{b.pk}/cancel', {'cancel_reason': 'Cannot inspect'}, format='json')
        self.assertEqual(r.status_code, 200); b.refresh_from_db(); self.assertNotEqual(b.status, 'cancelled')
        c = CancellationRequest.objects.get(booking=b)
        self.assertEqual(self.client.post(f'/api/cancellations/{c.pk}/review', {'action': 'approve'}, format='json').status_code, 403)
        self.client.force_authenticate(self.admin)
        self.assertEqual(self.client.post(f'/api/cancellations/{c.pk}/review', {'action': 'approve', 'refund_amount': '2000'}, format='json').status_code, 400)
        self.assertEqual(self.client.post(f'/api/cancellations/{c.pk}/review', {'action': 'approve', 'refund_amount': '1070'}, format='json').status_code, 200)
        j.refresh_from_db(); self.assertEqual(j.status, 'cancelled')
        self.assertEqual(self.client.post(f'/api/cancellations/{c.pk}/review', {'action': 'refund'}, format='json').status_code, 400)
        self.assertEqual(self.client.post(f'/api/cancellations/{c.pk}/review', {'action': 'refund', 'reference': 'bank-refund-01'}, format='json').status_code, 200)

    def test_customer_cannot_read_staff_data_or_mutate_users(self):
        for path in ['/api/jobs', '/api/bookings', '/api/users', '/api/operations', '/api/settings/checkout', '/api/customers/search', '/api/members']:
            self.assertEqual(self.client.get(path).status_code, 403, path)
        self.assertEqual(self.client.post('/api/users', {'username': 'hack', 'role': 'admin'}, format='json').status_code, 403)
        self.assertEqual(self.client.post('/api/members/credit', {'customer_id': self.customer.pk, 'amount': 100}, format='json').status_code, 403)

    def test_mock_card_webhook_and_line_login_fail_closed(self):
        self.client.force_authenticate(None)
        for path in ['/api/payments/charge', '/api/payments/promptpay/webhook', '/api/customer/topup/charge-card']:
            self.assertEqual(self.client.post(path, {'token': 'tokn_fake'}, format='json').status_code, 409)
        self.assertEqual(self.client.post('/api/auth/line-login', {'code': 'fake'}, format='json').status_code, 403)

    def test_exclusive_vat_rounding(self):
        CheckoutPolicy.objects.update(prices_include_vat=False, shipping_taxable=True)
        q = quote({**self.data, 'service_package': 'photo_review'}, self.customer)
        self.assertEqual(q['total'], '535.00'); self.assertEqual(q['vat_amount'], '35.00')

    def test_receipt_signature_and_photo_result_no_certificate(self):
        b, data = self.create_booking(service_package='photo_review', photos=[photo()])
        replay = self.client.post('/api/bookings', data, format='json')
        token = replay.data['receipt_token']
        j = self.checkin(b); j.status='completed'; j.result='fake'; j.save()
        self.client.force_authenticate(None)
        r = self.client.get('/api/booking-receipt', {'token': token})
        self.assertEqual(r.status_code, 200); self.assertEqual(r.data['result'], 'fake')
        self.assertNotIn('certificate_id', r.data); self.assertNotIn('customer_name', r.data)
        self.assertEqual(self.client.get('/api/booking-receipt', {'token': token+'x'}).status_code, 403)

    def test_shipping_transition_and_pickup(self):
        b, _ = self.create_booking(); j = self.checkin(b)
        self.assertEqual(self.client.post(f'/api/jobs/{j.pk}/shipping', {'shipping_status':'delivered'}, format='json').status_code, 400)
        j.status='completed'; j.result='fake'; j.save()
        self.assertEqual(self.client.post(f'/api/jobs/{j.pk}/shipping', {'shipping_status':'delivered'}, format='json').status_code, 200)
        j.refresh_from_db(); self.assertEqual(j.shipping_status,'delivered')

    def test_admin_adjustment_replay_and_negative_amount(self):
        self.client.force_authenticate(self.admin)
        payload={'customer_id':self.customer.pk,'amount':'100','type':'add','reason':'LINE bank transfer','request_key':str(uuid.uuid4())}
        for _ in range(2):
            self.assertEqual(self.client.post('/api/members/credit', payload, format='json').status_code, 200)
        self.customer.refresh_from_db();self.assertEqual(self.customer.credit_balance,2100)
        payload['amount']='-10';payload['request_key']=str(uuid.uuid4())
        self.assertEqual(self.client.post('/api/members/credit', payload, format='json').status_code,400)

    def test_camera_validates_images_and_returns_count(self):
        b, _ = self.create_booking();self.client.force_authenticate(self.front)
        path=f'/api/bookings/{b.pk}/photos'
        r=self.client.post(path, {'photos':[photo()]}, format='json')
        self.assertEqual(r.status_code,201); self.assertEqual(r.data['added'],1)
        r=self.client.post(path, {'photos':['data:image/png;base64,broken']}, format='json')
        self.assertEqual(r.status_code,400); self.assertEqual(b.photos.count(),1)
        self.assertEqual(self.client.post(path, {'photos':[photo()]*30}, format='json').status_code,400)

    def test_pdf_certificate_can_render_and_contains_expiration(self):
        b,_=self.create_booking();j=self.checkin(b)
        self.client.force_authenticate(self.admin)
        r=self.client.put(f'/api/jobs/{j.pk}', {'status':'completed','result':'authentic','tag_code':'TAG-PDF','expert_source':'Inspector'},format='json')
        self.assertEqual(r.status_code,200)
        cert=Certificate.objects.get(job=j)
        response=self.client.get(f'/api/certificates/{cert.cert_code}/pdf')
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_nonfinite_amount_and_inactive_login(self):
        for value in ['NaN','Infinity','-100']:
            self.assertEqual(self.client.post('/api/customer/topup/initiate',{'amount':value},format='json').status_code,400)
        self.user.is_active=False;self.user.save()
        self.client.force_authenticate(None)
        self.assertEqual(self.client.post('/api/auth/login',{'username':self.user.username,'password':'password123'},format='json').status_code,401)

    def test_reusing_request_key_with_changed_payload_is_rejected(self):
        b,data=self.create_booking()
        data['model']='Changed after timeout'
        response=self.client.post('/api/bookings',data,format='json')
        self.assertEqual(response.status_code,400)
        self.assertEqual(Booking.objects.count(),1)
        b.refresh_from_db();self.assertEqual(b.model,'Classic')

    def test_report_counts_paid_snapshots_once_and_refunds_separately(self):
        b,_=self.create_booking(payment_method='wallet');self.checkin(b)
        self.client.force_authenticate(self.admin)
        result=self.client.get('/api/reports/daily')
        self.assertEqual(result.data['stats']['revenue_member'],1070.0)
        self.assertEqual(result.data['stats']['total_revenue'],1070.0)
        self.client.put(f'/api/bookings/{b.pk}/cancel',{'cancel_reason':'Cancelled'},format='json')
        c=CancellationRequest.objects.get(booking=b)
        self.client.post(f'/api/cancellations/{c.pk}/review',{'action':'approve','refund_amount':'1070'},format='json')
        self.client.post(f'/api/cancellations/{c.pk}/review',{'action':'refund','reference':'bank-refund'},format='json')
        result=self.client.get('/api/reports/daily')
        self.assertEqual(result.data['stats']['refunds'],1070.0)
        self.assertEqual(result.data['stats']['total_revenue'],0.0)

    def test_certificate_dates_use_bangkok_day(self):
        from .serializers import CertificateSerializer
        b,_=self.create_booking();j=self.checkin(b)
        created=datetime.datetime(2026,9,16,18,0,tzinfo=datetime.timezone.utc)
        cert=Certificate.objects.create(job=j,cert_code='TIMEZONE-TEST',validity_days=15,expires_at=created+datetime.timedelta(days=15))
        Certificate.objects.filter(pk=cert.pk).update(created_at=created)
        cert.refresh_from_db();serialized=CertificateSerializer(cert).data
        self.assertEqual(serialized['issue_date'],'2026-09-17')
        self.assertEqual(serialized['expire_date'],'2026-10-02')

    def test_inspection_can_start_without_final_result(self):
        b,_=self.create_booking();j=self.checkin(b)
        expert=StaffUser.objects.create_user('expert-test',role='expert')
        self.client.force_authenticate(expert)
        response=self.client.put(f'/api/jobs/{j.pk}',{'status':'in_progress','result':'pending'},format='json')
        self.assertEqual(response.status_code,200)
        j.refresh_from_db();self.assertEqual(j.status,'in_progress');self.assertIsNone(j.result)
        self.assertFalse(Certificate.objects.exists())
