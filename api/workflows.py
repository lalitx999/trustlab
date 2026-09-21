"""Meeting requirements: intake, approval, inspection, cancellation and dispatch."""
import base64
import hashlib
import json
import logging
import datetime
import io
import uuid
import zipfile

logger = logging.getLogger(__name__)
from django.conf import settings
from django.core import signing
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.exceptions import ValidationError, PermissionDenied
from rest_framework.response import Response
from .models import (Booking, BookingPhoto, Branch, Customer, Job, Certificate, ServiceType,
                     ServicePackage, PackagePrice, CheckoutPolicy, TopupRequest, CreditEntry,
                     WorkflowEvent, CancellationRequest, StaffUser)
from .permissions import IsStaff, IsAdministrator, IsFrontDesk, IsInspector
from .serializers import BookingSerializer, JobSerializer, CertificateSerializer, Base64ImageField
from .commerce import money, quote, signed_quote, verify_quote, customer_for, change_credit, staff
from .promptpay import generate_promptpay_payload, generate_qr_code_image


def record(request, action, booking=None, job=None, **detail):
    actor = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None
    if actor:
        WorkflowEvent.objects.create(actor=actor, action=action, booking=booking, job=job, detail=detail)


def pk_value(value):
    try:
        return int(str(value).split('-')[-1])
    except ValueError:
        raise ValidationError('รหัสรายการไม่ถูกต้อง')


def image_data(value):
    if not isinstance(value, str) or len(value) > 12 * 1024 * 1024:
        raise ValidationError('ภาพต้องมีขนาดไม่เกิน 8 MB')
    Base64ImageField().run_validation(value)
    return value


def qr_image(amount):
    receiver = getattr(settings, 'PROMPTPAY_RECEIVER_ID', '')
    if not receiver or len(receiver) not in (10, 13) or not receiver.isdigit():
        raise ValidationError('ยังไม่ได้ตั้งค่าบัญชีรับเงิน PromptPay')
    payload = generate_promptpay_payload(receiver, money(amount))
    return 'data:image/png;base64,' + base64.b64encode(generate_qr_code_image(payload).getvalue()).decode()


@api_view(['GET'])
@permission_classes([AllowAny])
def packages(request):
    return Response(list(ServicePackage.objects.filter(enabled=True).values('code', 'name', 'validity_days')))


@api_view(['POST'])
@permission_classes([AllowAny])
def checkout_quote(request):
    customer = customer_for(request, request.data)
    snapshot = quote(request.data, customer, allow_missing_price=IsFrontDesk().has_permission(request, None))
    return Response({**snapshot, 'quote_token': signed_quote(snapshot, customer)})


@api_view(['POST'])
@permission_classes([AllowAny])
def promptpay_quote(request):
    try:
        value = signing.loads(request.data.get('quote_token'), salt='checkout', max_age=1800)
    except (signing.BadSignature, TypeError):
        raise ValidationError('กรุณาคำนวณยอดใหม่ก่อนสร้าง QR')
    return Response({
        'qr_image': qr_image(value['quote']['total']),
        'amount': value['quote']['total'],
        'bank_name': 'กสิกรไทย (KBANK)',
        'account_name': 'บริษัท เซอร์ติฟิเคชั่น แอนด์ อินสเปคชั่น (ไทยแลนด์) จำกัด',
        'account_no': '123-4-56789-0 (รอเลขจริง)',
        'promptpay_no': '0105569150179'
    })


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def bookings(request):
    if request.method == 'GET':
        if not IsStaff().has_permission(request, None):
            raise PermissionDenied()
        return Response(BookingSerializer(Booking.objects.all().order_by('-created_at'), many=True, context={'request': request}).data)
    if staff(request.user) and not IsFrontDesk().has_permission(request, None):
        raise PermissionDenied()
    return create_booking(request)


def create_booking(request):
    with transaction.atomic():
        data = request.data
        try:
            key = uuid.UUID(str(data.get('request_key', '')))
        except ValueError:
            raise ValidationError('กรุณาส่งรหัสรายการ request_key')
        fingerprint = hashlib.sha256(json.dumps({k: v for k, v in data.items() if k != 'quote_token'}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        customer = customer_for(request, data)
        # Serialize intake retries for an authenticated customer, then use a DB unique key.
        if customer:
            Customer.objects.select_for_update().get(pk=customer.pk)
        branch_id = data.get('branch_id')
        branch = Branch.objects.filter(pk=branch_id, is_active=True).first() if branch_id else None
        if not branch:
            branch = Branch.objects.filter(is_active=True).first() or Branch.objects.first()
        if not branch:
            branch = Branch.objects.create(name='สาขาหลัก (Head Office)', is_active=True)

        previous = Booking.objects.filter(request_key=key).first()
        if previous:
            if previous.request_fingerprint != fingerprint:
                raise ValidationError('รหัสรายการนี้บันทึกข้อมูลชุดอื่นแล้ว กรุณาตรวจรายการเดิมก่อนสร้างใหม่')
            if customer and previous.customer_id != customer.pk:
                raise PermissionDenied()
            return Response({'booking_id': previous.pk, 'status': previous.status, 'payment_status': previous.payment_status,
                             'receipt_token': signing.dumps({'booking_id': previous.pk, 'request_key': str(previous.request_key)}, salt='receipt')})
        is_frontdesk = IsFrontDesk().has_permission(request, None)
        snapshot = quote(data, customer, allow_missing_price=is_frontdesk)
        if not is_frontdesk or data.get('quote_token'):
            try:
                verify_quote(data.get('quote_token'), snapshot, customer)
            except Exception:
                if not is_frontdesk:
                    raise

        if not customer:
            name = str(data.get('customerName', '')).strip()
            phone = ''.join(c for c in str(data.get('phone', '')) if c.isdigit())
            if not name or len(phone) < 9:
                raise ValidationError('กรุณาระบุชื่อและเบอร์โทรให้ครบ')
            customer = Customer.objects.filter(phone_number=phone).first()
            if not customer:
                req_tier = data.get('membership_level') or data.get('membership_tier')
                membership = None
                if req_tier:
                    from .models import MembershipLevel
                    membership = MembershipLevel.objects.filter(level_name__iexact=req_tier).first()
                if not membership:
                    from .models import MembershipLevel
                    membership = MembershipLevel.objects.filter(level_name__iexact='General').first() or MembershipLevel.objects.first()
                customer = Customer.objects.create(full_name=name, phone_number=phone, email=data.get('email') or None, line_id=data.get('line_id') or None, membership_level=membership, note=data.get('customer_note', ''))

        try:
            date = datetime.date.fromisoformat(data.get('date', ''))
            ts_raw = str(data.get('timeSlot', '')).split('-')[0].strip()
            if len(ts_raw) == 5:
                ts_raw += ':00'
            time = datetime.time.fromisoformat(ts_raw)
        except (ValueError, TypeError):
            raise ValidationError('กรุณาระบุวันและเวลานัดหมาย')
        if date < timezone.localdate() and not staff(request.user):
            raise ValidationError('วันนัดหมายต้องไม่เป็นวันที่ผ่านมาแล้ว')
        if not str(data.get('model', '')).strip():
            raise ValidationError('กรุณาระบุรุ่นสินค้า')
        address_fields = ['return_address_name', 'return_phone', 'return_address_detail', 'return_subdistrict', 'return_district', 'return_province', 'return_postal_code']
        address = {k: str(data.get(k, '')).strip() for k in address_fields}
        for k, value in address.items():
            limit = Booking._meta.get_field(k).max_length or 2000
            if len(value) > limit:
                raise ValidationError('ข้อมูลที่อยู่ยาวเกินกำหนด')
        if snapshot['delivery_method'] == 'shipping' and not all(address.values()):
            raise ValidationError('กรุณากรอกที่อยู่ส่งคืนให้ครบ')
        payment = data.get('payment_method', 'shop')
        allowed = ('shop', 'promptpay', 'wallet', 'cash', 'credit_card', 'transfer') if IsFrontDesk().has_permission(request, None) else ('shop', 'promptpay', 'wallet')
        if payment not in allowed:
            raise ValidationError('ไม่รองรับช่องทางชำระนี้')
        if payment == 'wallet' and not request.user.is_authenticated:
            raise PermissionDenied('กรุณาเข้าสู่ระบบก่อนใช้เครดิต')
        evidence = image_data(data.get('slip_base64')) if data.get('slip_base64') and payment in ('promptpay', 'transfer') else ''
        if payment == 'promptpay' and not evidence and not is_frontdesk:
            raise ValidationError('กรุณาแนบสลิปชำระเงิน')
        is_paid_initial = bool(data.get('mark_paid') or data.get('paid') or payment == 'wallet')
        payment_status_val = 'pending_review' if evidence else ('paid' if is_paid_initial else 'unpaid')
        booking_status_val = 'confirmed' if is_paid_initial else 'pending'

        # Resolve the required FK for every intake, including an empty service catalog.
        service, _ = ServiceType.objects.get_or_create(
            service_name=snapshot['service_package'],
            defaults={'description': 'Inspection Service'},
        )

        booking = Booking.objects.create(customer=customer, branch=branch, booking_date=date, booking_time=time,
            service_type=service, service_package=snapshot['service_package'], category=snapshot['category'],
            brand_name=snapshot['brand'], model=data['model'], note=data.get('note', ''),
            price_snapshot=snapshot, delivery_method=snapshot['delivery_method'], shipping_fee=snapshot['shipping_fee'],
            payment_method=payment, payment_evidence=evidence, request_key=key, request_fingerprint=fingerprint,
            payment_status=payment_status_val, status=booking_status_val, **address)
        if payment == 'wallet':
            change_credit(customer, -money(snapshot['total']), f'booking:{booking.pk}', 'ชำระค่าบริการ', request.user)
            record(request, 'wallet_payment', booking=booking, amount=snapshot['total'])

        if is_paid_initial:
            try:
                from .emails import send_payment_confirmation_email
                send_payment_confirmation_email(booking)
            except Exception as e:
                logger.warning(f"Payment confirmation email error: {e}")

        photos = data.get('photos', [])
        if not isinstance(photos, list) or len(photos) > 20:
            raise ValidationError('แนบภาพได้สูงสุด 20 ภาพ')
        if snapshot['service_package'] == 'photo_review' and not photos:
            raise ValidationError('Photo Review ต้องแนบภาพสินค้า')
        for photo in photos:
            image_data(photo)
            BookingPhoto.objects.create(booking=booking, photo=Base64ImageField().run_validation(photo), photo_type='customer')
        return Response({'booking_id': booking.pk, 'status': booking.status, 'payment_status': booking.payment_status, 'quote': snapshot,
                         'receipt_token': signing.dumps({'booking_id': booking.pk, 'request_key': str(booking.request_key)}, salt='receipt')}, status=201)


@api_view(['POST'])
@permission_classes([IsFrontDesk])
@transaction.atomic
def check_in(request, pk):
    return receive_booking(request, pk)


def receive_booking(request, pk):
    booking = get_object_or_404(Booking.objects.select_for_update(), pk=pk_value(pk))
    if booking.status == 'cancelled':
        raise ValidationError('รายการถูกยกเลิกแล้ว')
    existing = Job.objects.filter(booking=booking).first()
    if existing:
        for f in ('serial_number', 'color', 'material', 'accessories', 'notes', 'expert_instruction'):
            if f in request.data:
                setattr(existing, f, str(request.data[f]).strip())
        if 'brand' in request.data or 'brand_name' in request.data:
            existing.brand = str(request.data.get('brand') or request.data.get('brand_name')).strip()
        if 'model' in request.data:
            existing.model = str(request.data['model']).strip()
        existing.save()
        return Response(JobSerializer(existing).data)
    if not booking.price_snapshot or not booking.service_package:
        raise ValidationError('รายการเดิมต้องตรวจทานแพ็กเกจและราคาใหม่ก่อนรับงาน')
    # Lock branch while allocating a unique daily queue (all new check-ins use this path).
    Branch.objects.select_for_update().get(pk=booking.branch_id)
    count = Job.objects.filter(created_at__date=timezone.localdate()).count()
    tag_code_val = str(request.data.get('tag_code') or request.data.get('cert_code') or '').strip()
    job = Job.objects.create(booking=booking, customer=booking.customer, category=booking.category,
        brand=request.data.get('brand', booking.brand_name), model=request.data.get('model', booking.model), color=request.data.get('color', ''),
        serial_number=request.data.get('serial_number', ''), tag_code=tag_code_val,
        material=request.data.get('material', ''), sub_category=request.data.get('sub_category', ''),
        accessories=request.data.get('accessories', ''), notes=request.data.get('note', booking.note),
        expert_instruction=request.data.get('expert_instruction', ''), queue_no=f'{booking.branch_id}-{count + 1:03}',
        service_package=booking.service_package, price_snapshot=booking.price_snapshot,
        price=booking.price_snapshot['total'], vat_amount=booking.price_snapshot['vat_amount'],
        payment_method=booking.payment_method, payment_status=booking.payment_status,
        shipping_status='pending_return' if booking.delivery_method == 'shipping' else 'not_applicable')
    record(request, 'check_in', booking=booking, job=job)
    return Response(JobSerializer(job).data, status=201)


def issue(job, custom_code=None):
    if job.service_package not in ('cert_15d', 'cert_90d') or job.status != 'completed' or not job.result:
        raise ValidationError('ออกใบรับรองได้เฉพาะงานตรวจสินค้าจริงที่ตรวจเสร็จแล้ว')
    days = 15 if job.service_package == 'cert_15d' else 90
    if job.price_snapshot and isinstance(job.price_snapshot, dict) and job.price_snapshot.get('validity_days'):
        try:
            days = int(job.price_snapshot['validity_days'])
        except (ValueError, TypeError):
            pass
    code_to_use = custom_code or job.tag_code or f'TL-{uuid.uuid4().hex[:12].upper()}'
    cert_status = 'authentic' if job.result == 'authentic' else 'unauthentic'
    cert, created = Certificate.objects.get_or_create(job=job, defaults={
        'cert_code': code_to_use,
        'cert_status': cert_status,
        'validity_days': days,
        'expires_at': timezone.now() + datetime.timedelta(days=days)
    })
    if not created:
        if cert.cert_status != cert_status:
            cert.cert_status = cert_status
            cert.save(update_fields=['cert_status'])
        if (custom_code or job.tag_code):
            target = custom_code or job.tag_code
            if target and cert.cert_code != target:
                cert.cert_code = target
                cert.save(update_fields=['cert_code'])
    return cert


@api_view(['POST'])
@permission_classes([IsInspector])
@transaction.atomic
def certificate_create(request):
    job_id = request.data.get('job_id')
    if not job_id:
        raise ValidationError('กรุณาระบุ job_id')
    job = get_object_or_404(Job.objects.select_for_update(), pk=pk_value(job_id))
    cert = issue(job, custom_code=request.data.get('cert_code'))
    record(request, 'issue_certificate', job=job, cert_code=cert.cert_code)
    return Response(CertificateSerializer(cert).data, status=201)


@api_view(['PUT', 'POST'])
@permission_classes([IsStaff])
@transaction.atomic
def job_update(request, pk):
    try:
        val = pk_value(pk)
        job = Job.objects.select_for_update().filter(pk=val).first()
    except Exception:
        job = None
    if not job:
        raise ValidationError('ไม่พบรายการสั่งงานนี้')
    if job.booking_id:
        Booking.objects.select_for_update().filter(pk=job.booking_id).first()
    if job.status == 'cancelled':
        raise ValidationError('งานถูกยกเลิกแล้ว')
    result = request.data.get('result', job.result)
    if result == 'pending':
        result = None
    state = request.data.get('status', job.status)
    if state not in ('pending', 'in_progress', 'completed') or result not in (None, '', 'authentic', 'fake', 'inconclusive'):
        raise ValidationError('สถานะหรือผลตรวจไม่ถูกต้อง; กรณีตรวจไม่ได้ให้ขอยกเลิก')
    if state == 'completed' and result not in ('authentic', 'fake', 'inconclusive'):
        raise ValidationError('กรุณาระบุผลตรวจ')
    if hasattr(job, 'certificate') and (result != job.result or state != job.status):
        raise ValidationError('งานมีใบรับรองแล้ว กรุณาเพิกถอนและตรวจทานก่อนเปลี่ยนผล')
    if request.data.get('payment_status') and request.data['payment_status'] != job.payment_status:
        raise ValidationError('กรุณารับชำระผ่านหน้าตรวจการเงิน')
    job.expert_instruction = str(request.data.get('expert_instruction', job.expert_instruction or ''))
    job.status, job.result = state, result
    if 'tag_code' in request.data:
        job.tag_code = str(request.data.get('tag_code', job.tag_code)).strip()
    
    expert_id = request.data.get('expert_id')
    if expert_id:
        try:
            eid = int(str(expert_id).split('-')[-1])
            expert_user = StaffUser.objects.filter(pk=eid).first()
            if expert_user:
                job.result_recorded_by = expert_user
                job.expert_source = expert_user.full_name or expert_user.username
        except (ValueError, TypeError):
            pass
    elif request.data.get('expert_source'):
        job.expert_source = str(request.data['expert_source']).strip()
    elif not job.result_recorded_by:
        job.result_recorded_by = request.user

    job.save()
    if state == 'completed' and result in ('authentic', 'fake') and job.service_package != 'photo_review':
        issue(job)
    if state == 'completed':
        from .emails import send_inspection_result_email
        send_inspection_result_email(job)
    record(request, 'inspection', job=job, result=result, status=state, expert_source=job.expert_source)
    if job.booking and state == 'completed':
        job.booking.status = 'completed'
        job.booking.save(update_fields=['status'])
    return Response(JobSerializer(job, context={'request': request}).data)


@api_view(['GET'])
@permission_classes([IsStaff])
def operations(request):
    result = {'role': 'admin' if request.user.is_superuser else request.user.role, 'bookings': BookingSerializer(Booking.objects.select_related('customer').order_by('-created_at')[:200], many=True).data,
              'jobs': JobSerializer(Job.objects.select_related('booking').order_by('-created_at')[:200], many=True).data,
              'cancellations': list(CancellationRequest.objects.order_by('-created_at')[:200].values())}
    if IsAdministrator().has_permission(request, None):
        result['topups'] = list(TopupRequest.objects.filter(status='pending').values('id', 'customer_id', 'customer__full_name', 'amount'))
    return Response(result)


@api_view(['GET', 'POST'])
@permission_classes([IsAdministrator])
@transaction.atomic
def payment_review(request, pk):
    booking = get_object_or_404(Booking.objects.select_for_update(), pk=pk)
    if request.method == 'GET':
        return Response({'evidence': booking.payment_evidence, 'quote': booking.price_snapshot})
    if booking.status == 'cancelled' or not booking.price_snapshot:
        raise ValidationError('ไม่สามารถรับชำระรายการนี้')
    if booking.payment_status == 'paid':
        return Response({'status': 'paid'})
    action = request.data.get('action')
    reference = str(request.data.get('reference', '')).strip()
    if action not in ('approve', 'reject') or not reference:
        raise ValidationError('กรุณาระบุผลและเลขอ้างอิง/เหตุผล')
    if action == 'approve' and booking.payment_method not in ('promptpay', 'transfer'):
        raise ValidationError('รายการหน้าร้านให้ใช้บันทึกเงินสด/EDC')
    if action == 'approve' and money(request.data.get('amount')) != money(booking.price_snapshot['total']):
        raise ValidationError('ยอดที่ตรวจสอบไม่ตรงกับยอดรายการ')
    booking.payment_status = 'paid' if action == 'approve' else 'rejected'
    if action == 'approve' and booking.status == 'pending':
        booking.status = 'confirmed'
    booking.save()
    Job.objects.filter(booking=booking).update(payment_status=booking.payment_status)
    record(request, 'payment_' + action, booking=booking, reference=reference, amount=booking.price_snapshot['total'])
    return Response({'status': booking.payment_status})


@api_view(['POST'])
@permission_classes([IsFrontDesk])
@transaction.atomic
def counter_payment(request, pk):
    return receive_payment(request, pk)


def receive_payment(request, pk):
    booking = get_object_or_404(Booking.objects.select_for_update(), pk=pk)
    if booking.payment_status == 'paid':
        return Response({'status': 'paid'})
    method = request.data.get('method')
    reference = str(request.data.get('reference', '')).strip()
    if method not in ('cash', 'credit_card', 'transfer', 'promptpay') or not reference or booking.status == 'cancelled' or not booking.price_snapshot:
        raise ValidationError('เลือกช่องทางรับเงินพร้อมเลขอ้างอิงรายการ')
    if money(request.data.get('amount')) != money(booking.price_snapshot['total']):
        raise ValidationError('ยอดรับชำระไม่ตรง')
    if booking.payment_status == 'pending_review' and not IsAdministrator().has_permission(request, None):
        raise PermissionDenied('รายการแนบสลิปออนไลน์ต้องให้ผู้ดูแลตรวจสอบก่อน')
    booking.payment_status, booking.payment_method = 'paid', method
    if booking.status == 'pending':
        booking.status = 'confirmed'
    booking.save()
    Job.objects.filter(booking=booking).update(payment_status='paid', payment_method=method)
    record(request, 'counter_payment', booking=booking, method=method, reference=reference)
    from .emails import send_payment_confirmation_email
    send_payment_confirmation_email(booking)
    return Response({'status': 'paid'})


@api_view(['PUT', 'POST'])
@permission_classes([IsFrontDesk])
@transaction.atomic
def cancel_request(request, pk):
    booking = get_object_or_404(Booking.objects.select_for_update(), pk=pk_value(pk))
    reason = str(request.data.get('cancel_reason', '')).strip()
    if not reason or booking.status == 'cancelled':
        raise ValidationError('กรุณาระบุเหตุผล/ตรวจสอบสถานะรายการ')
    item, _ = CancellationRequest.objects.get_or_create(booking=booking, defaults={'reason': reason, 'requested_by': request.user})
    record(request, 'cancel_requested', booking=booking, reason=reason)
    return Response({'id': item.pk, 'status': item.status, 'message': 'ส่งคำขอแล้ว รอ Admin อนุมัติ'})


@api_view(['POST'])
@permission_classes([IsAdministrator])
@transaction.atomic
def cancel_review(request, pk):
    item = get_object_or_404(CancellationRequest.objects.select_for_update(), pk=pk)
    booking = Booking.objects.select_for_update().get(pk=item.booking_id)
    action = request.data.get('action')
    if action == 'refund':
        if item.status != 'approved' or item.refund_status not in ('pending', 'paid_out'):
            raise ValidationError('ยังไม่มีรายการคืนเงินที่อนุมัติ')
        if item.refund_status == 'paid_out':
            return Response({'status': 'paid_out'})
        reference = str(request.data.get('reference', '')).strip()
        if not reference:
            raise ValidationError('กรุณาระบุเลขอ้างอิงหลักฐานคืนเงิน')
        item.refund_status, item.refund_reference = 'paid_out', reference
        item.save()
        record(request, 'refund_paid_out', booking=booking, reference=reference, amount=str(item.refund_amount))
        return Response({'status': 'paid_out'})
    if item.status != 'pending':
        return Response({'status': item.status})
    if action not in ('approve', 'reject'):
        raise ValidationError('คำสั่งไม่ถูกต้อง')
    amount = money(request.data.get('refund_amount', 0))
    maximum = money(booking.price_snapshot.get('total', 0)) if booking.payment_status == 'paid' else money(0)
    if amount < 0 or amount > maximum:
        raise ValidationError('ยอดคืนต้องไม่เกินยอดชำระจริง')
    item.status, item.reviewed_by = ('approved' if action == 'approve' else 'rejected'), request.user
    if action == 'approve':
        item.refund_amount = amount
        item.refund_status = 'pending' if amount else 'not_required'
        booking.status, booking.cancel_reason = 'cancelled', item.reason
        booking.cancelled_by, booking.cancelled_at = request.user, timezone.now()
        booking.save()
        Job.objects.filter(booking=booking).update(status='cancelled', cancel_reason=item.reason, cancelled_by=request.user,
                                                   cancel_approved_by=request.user, cancelled_at=timezone.now())
        Certificate.objects.filter(job__booking=booking).update(cert_status='revoked', revoke_reason=item.reason)
    item.save()
    record(request, 'cancel_' + action, booking=booking, refund_amount=str(amount))
    return Response({'status': item.status})


@api_view(['POST'])
@permission_classes([IsFrontDesk])
@transaction.atomic
def shipping_update(request, pk):
    job = get_object_or_404(Job.objects.select_for_update(), pk=pk_value(pk))
    if job.status not in ('completed', 'cancelled'):
        raise ValidationError('งานยังไม่พร้อมคืนสินค้า')
    if job.service_package == 'photo_review':
        raise ValidationError('Photo Review ไม่มีการส่งคืนสินค้า')
    new = request.data.get('shipping_status')
    transitions = {'not_applicable': ['delivered'], 'pending_return': ['ready_to_ship'], 'ready_to_ship': ['shipped'], 'shipped': ['delivered'], 'delivered': []}
    if new == job.shipping_status:
        return Response({'status': new})
    if new not in transitions.get(job.shipping_status, []):
        raise ValidationError('ลำดับสถานะส่งคืนไม่ถูกต้อง')
    tracking = str(request.data.get('tracking_number', job.tracking_number or '')).strip()
    if new == 'shipped' and not tracking:
        raise ValidationError('กรุณาระบุเลขพัสดุหรืออ้างอิงการจัดส่ง')
    job.shipping_status, job.tracking_number = new, tracking
    job.save()
    record(request, 'shipping', job=job, status=new, tracking_number=tracking)
    return Response({'status': new})


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def topup_initiate(request):
    customer = get_object_or_404(Customer, user=request.user)
    amount = money(request.data.get('amount'))
    if amount < 100 or request.data.get('payment_method', 'promptpay') != 'promptpay':
        raise ValidationError('เติมขั้นต่ำ 100 บาท ผ่าน PromptPay')
    qr = qr_image(amount)
    topup = TopupRequest.objects.create(customer=customer, amount=amount)
    return Response({'topup_id': topup.pk, 'amount': str(amount), 'qr_image': qr, 'payment_method': 'promptpay'}, status=201)


@api_view(['POST'])
@permission_classes([IsAuthenticated])
@transaction.atomic
def topup_slip(request):
    topup = get_object_or_404(TopupRequest.objects.select_for_update(), pk=request.data.get('topup_id'), customer__user=request.user)
    if topup.status != 'pending':
        raise ValidationError('รายการถูกตรวจสอบแล้ว')
    topup.evidence = image_data(request.data.get('slip_base64'))
    topup.save(update_fields=['evidence'])
    return Response({'status': 'pending', 'message': 'รับสลิปแล้ว รอผู้ดูแลตรวจสอบก่อนเพิ่มเครดิต'})


@api_view(['GET', 'POST'])
@permission_classes([IsAdministrator])
@transaction.atomic
def topup_review(request, pk):
    topup = get_object_or_404(TopupRequest.objects.select_for_update(), pk=pk)
    if request.method == 'GET':
        return Response({'evidence': topup.evidence, 'amount': str(topup.amount)})
    if topup.status != 'pending':
        return Response({'status': topup.status})
    action = request.data.get('action')
    reference = str(request.data.get('reference', '')).strip()
    if action not in ('approve', 'reject') or not reference:
        raise ValidationError('กรุณาระบุผลและเลขอ้างอิง/เหตุผล')
    if action == 'approve':
        if not topup.evidence or money(request.data.get('amount')) != topup.amount:
            raise ValidationError('กรุณาตรวจหลักฐานและยอดให้ตรง')
        change_credit(topup.customer, topup.amount, f'topup:{topup.pk}', reference, request.user)
        topup.approved_at = timezone.now()
    topup.status = 'approved' if action == 'approve' else 'rejected'
    topup.save()
    record(request, 'topup_' + action, topup_id=topup.pk, reference=reference)
    return Response({'status': topup.status})


@api_view(['POST'])
@permission_classes([IsAdministrator])
def credit_adjust(request):
    customer = get_object_or_404(Customer, pk=request.data.get('customer_id'))
    amount = money(request.data.get('amount'))
    reason = str(request.data.get('reason', '')).strip()
    try:
        key = uuid.UUID(str(request.data.get('request_key', '')))
    except ValueError:
        raise ValidationError('กรุณาระบุรหัสรายการ')
    if amount <= 0 or not reason or request.data.get('type') not in ('add', 'deduct'):
        raise ValidationError('ระบุจำนวนเงินบวก เหตุผล และประเภทปรับยอด')
    entry = change_credit(customer, amount if request.data['type'] == 'add' else -amount, f'adjust:{key}', reason, request.user)
    return Response({'credit_balance': str(entry.balance_after)})


@api_view(['POST'])
@permission_classes([AllowAny])
def disabled_payment(request):
    return Response({'error': 'ช่องทางนี้ยังไม่เปิดใช้งาน กรุณาใช้ QR พร้อมส่งสลิปให้ผู้ดูแลตรวจสอบ'}, status=409)


@api_view(['GET', 'PUT'])
@permission_classes([IsAdministrator])
@transaction.atomic
def pricing_settings(request):
    policy, _ = CheckoutPolicy.objects.get_or_create(pk=1)
    if request.method == 'PUT':
        d = request.data
        for field in ('approved', 'prices_include_vat', 'shipping_taxable'):
            if field in d:
                if not isinstance(d[field], bool):
                    raise ValidationError('ค่าการตั้งค่าไม่ถูกต้อง')
                setattr(policy, field, d[field])
        if 'shipping_fee' in d:
            fee = money(d['shipping_fee'])
            if fee < 0:
                raise ValidationError('ค่าส่งต้องไม่ติดลบ')
            policy.shipping_fee = fee
        policy.save()
        if d.get('rate'):
            r = d['rate']
            package = get_object_or_404(ServicePackage, code=r.get('package'))
            if package.code == 'photo_review':
                raise ValidationError('Photo Review ใช้ราคา 500 คงที่')
            amount = money(r.get('amount'))
            if amount < 0 or r.get('category') not in ('Bag', 'Watch', 'Clothes', 'Shoes', 'Accessories') or not str(r.get('brand', '')).strip():
                raise ValidationError('ราคา ประเภท หรือแบรนด์ไม่ถูกต้อง')
            PackagePrice.objects.update_or_create(package=package, category=r['category'], brand=r['brand'].strip(),
                member_tier=str(r.get('member_tier', 'general')).strip().lower(), defaults={'amount': amount})
        if d.get('package'):
            p = d['package']
            package = get_object_or_404(ServicePackage, code=p.get('code'))
            days = p.get('validity_days')
            if package.code == 'photo_review' or not isinstance(days, int) or days < 1 or days > 365:
                raise ValidationError('อายุรับรองต้องเป็นจำนวนวัน 1–365 สำหรับแพ็กเกจตรวจจริง')
            package.validity_days = days
            package.save()
        record(request, 'pricing_update', approved=policy.approved)
    return Response({'policy': {'approved': policy.approved, 'prices_include_vat': policy.prices_include_vat,
                     'shipping_taxable': policy.shipping_taxable, 'shipping_fee': str(policy.shipping_fee)},
                     'rates': list(PackagePrice.objects.values()), 'packages': list(ServicePackage.objects.values())})


@api_view(['GET'])
@permission_classes([IsStaff])
def photo_export(request, pk):
    job = get_object_or_404(Job, pk=pk_value(pk))
    if not job.booking:
        raise ValidationError('ไม่พบภาพของงานนี้')
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('job.txt', f'Job {job.pk}\n{job.brand} {job.model}\nSerial: {job.serial_number or "-"}\n')
        for photo in job.booking.photos.all():
            with photo.photo.open('rb') as source:
                archive.writestr(f'{photo.photo_type}-{photo.pk}.{photo.photo.name.rsplit(".", 1)[-1]}', source.read())
    response = HttpResponse(buffer.getvalue(), content_type='application/zip')
    response['Content-Disposition'] = f'attachment; filename="job-{job.pk}-photos.zip"'
    return response


@api_view(['GET'])
@permission_classes([IsFrontDesk])
def shipping_label(request, pk):
    from .documents import return_label
    job = get_object_or_404(Job, pk=pk_value(pk))
    response = HttpResponse(return_label(job), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="job-{job.pk}-label.pdf"'
    return response


@api_view(['GET'])
@permission_classes([IsStaff])
def credit_history(request):
    rows = CreditEntry.objects.select_related('customer').order_by('-created_at')[:200]
    return Response([{'transaction_id': x.reference, 'full_name': x.customer.full_name, 'phone': x.customer.phone_number,
                      'description': x.reason, 'amount': str(abs(x.amount)), 'balance_after': str(x.balance_after),
                      'type': 'topup' if x.amount > 0 else 'deduct', 'created_at': x.created_at.isoformat()} for x in rows])


@api_view(['GET'])
@permission_classes([AllowAny])
def booking_receipt(request):
    try:
        signed = signing.loads(request.query_params.get('token'), salt='receipt', max_age=180*86400)
    except (signing.BadSignature, TypeError):
        raise PermissionDenied('ลิงก์ไม่ถูกต้องหรือหมดอายุ กรุณาติดต่อเจ้าหน้าที่')
    booking = get_object_or_404(Booking, pk=signed['booking_id'], request_key=signed['request_key'])
    job = Job.objects.filter(booking=booking).first()
    result = job.result if job and job.status == 'completed' else None
    # Receipt never discloses customer PII, other customers' data or photo-review certificate IDs.
    return Response({'booking_id': booking.pk, 'status': booking.status, 'payment_status': booking.payment_status,
                     'service_package': booking.service_package, 'result': result, 'total': booking.price_snapshot.get('total'),
                     'shipping_status': job.shipping_status if job else None})


@api_view(['GET', 'POST'])
@permission_classes([IsStaff])
@transaction.atomic
def camera_photos(request, pk):
    booking = get_object_or_404(Booking.objects.select_for_update(), pk=pk_value(pk))
    if request.method == 'GET':
        return Response({kind: [request.build_absolute_uri(p.photo.url) for p in booking.photos.filter(photo_type=kind)] for kind in ('customer', 'staff')})
    photos = request.data.get('photos', [])
    if not isinstance(photos, list) or not photos or len(photos) + booking.photos.filter(photo_type='staff').count() > 30:
        raise ValidationError('แนบภาพเจ้าหน้าที่ได้สูงสุด 30 ภาพต่อรายการ')
    if sum(len(p) for p in photos if isinstance(p, str)) > 40 * 1024 * 1024:
        raise ValidationError('ภาพรวมเกิน 30 MB กรุณาแบ่งอัปโหลดเป็นชุดเล็ก')
    decoded = [Base64ImageField().run_validation(image_data(p)) for p in photos]
    for value in decoded:
        BookingPhoto.objects.create(booking=booking, photo=value, photo_type='staff')
    record(request, 'photos_added', booking=booking, count=len(decoded))
    return Response({'added': len(decoded)}, status=201)


def daily_stats():
    today = timezone.localdate()
    jobs = Job.objects.filter(created_at__date=today)
    stats = {'total_jobs': jobs.count(), 'completed_jobs': jobs.filter(status='completed').count(),
             'authentic_jobs': jobs.filter(result='authentic').count(), 'fake_jobs': jobs.filter(result='fake').count(),
             'inconclusive_jobs': jobs.filter(result='inconclusive').count()}
    amounts = {k: money(0) for k in ('revenue_cash', 'revenue_transfer', 'revenue_card', 'revenue_promptpay', 'revenue_member')}
    mapping = {'cash': 'revenue_cash', 'transfer': 'revenue_transfer', 'credit_card': 'revenue_card', 'promptpay': 'revenue_promptpay', 'wallet': 'revenue_member', 'credit_balance': 'revenue_member'}
    paid_events = WorkflowEvent.objects.filter(created_at__date=today, action__in=['wallet_payment', 'counter_payment', 'payment_approve']).select_related('booking')
    seen = set()
    for event in paid_events:
        b = event.booking
        if b and b.pk not in seen and b.payment_method in mapping:
            amounts[mapping[b.payment_method]] += money(b.price_snapshot['total'])
            seen.add(b.pk)
    # Legacy rows have no payment timestamp: keep their existing received-day convention,
    # but never count unpaid jobs or duplicate a new workflow booking.
    for job in jobs.filter(payment_status='paid', price_snapshot={}):
        if job.payment_method in mapping:
            amounts[mapping[job.payment_method]] += job.price
    refunds = sum((money(e.detail.get('amount', 0)) for e in WorkflowEvent.objects.filter(created_at__date=today, action='refund_paid_out')), money(0))
    gross = sum(amounts.values(), money(0))
    stats.update({k: float(v) for k, v in amounts.items()})
    stats.update(gross_revenue=float(gross), refunds=float(refunds), total_revenue=float(gross-refunds))
    return today, stats


@api_view(['GET'])
@permission_classes([IsStaff])
def daily_report(request):
    today, stats = daily_stats()
    return Response({'date': today.strftime('%d/%m/%Y'), 'stats': stats})


@api_view(['GET'])
@permission_classes([IsStaff])
def daily_report_pdf(request):
    from .pdf_generator import generate_daily_report_pdf
    today, stats = daily_stats()
    response = HttpResponse(generate_daily_report_pdf(stats, today.strftime('%d/%m/%Y')).getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="daily-report-{today.isoformat()}.pdf"'
    return response


def walkin_detail(booking, request):
    job = Job.objects.filter(booking=booking).first()
    return {'booking': BookingSerializer(booking, context={'request': request}).data,
            'job': JobSerializer(job, context={'request': request}).data if job else None,
            'cancellation': CancellationRequest.objects.filter(booking=booking).values('id', 'status', 'reason', 'refund_status', 'refund_amount').first()}


@api_view(['GET', 'POST', 'PUT'])
@permission_classes([IsFrontDesk])
@transaction.atomic
def walkin(request):
    """One counter transaction: intake, queue and optional verified payment."""
    if request.method == 'GET':
        if request.query_params.get('booking_id'):
            booking = get_object_or_404(Booking, pk=pk_value(request.query_params['booking_id']))
            return Response(walkin_detail(booking, request))
        rows = Booking.objects.select_related('customer', 'branch', 'service_type').order_by('-created_at')[:100]
        return Response([walkin_detail(booking, request) for booking in rows])
    data = request.data
    if data.get('booking_id'):
        booking = get_object_or_404(Booking.objects.select_for_update(), pk=pk_value(data['booking_id']))
        if booking.status == 'cancelled':
            raise ValidationError('รายการนี้ถูกยกเลิกแล้ว')
        
        # Update customer details if provided
        if booking.customer:
            c = booking.customer
            c_changed = False
            if 'customer_name' in data and data['customer_name']:
                c.full_name = str(data['customer_name']).strip()
                c_changed = True
            if 'customer_phone' in data and data['customer_phone']:
                c.phone_number = str(data['customer_phone']).strip()
                c_changed = True
            if 'customer_email' in data:
                c.email = str(data['customer_email']).strip() or None
                c_changed = True
            if c_changed:
                c.save()

        # Update booking product details if provided
        b_changed = False
        if 'brand' in data or 'brand_name' in data:
            booking.brand_name = str(data.get('brand') or data.get('brand_name')).strip()
            b_changed = True
        if 'model' in data:
            booking.model = str(data['model']).strip()
            b_changed = True
        if 'category' in data:
            booking.category = str(data['category']).strip()
            b_changed = True
        if 'note' in data:
            booking.note = str(data['note']).strip()
            b_changed = True
        if b_changed:
            booking.save()
    else:
        response = create_booking(request)
        booking = Booking.objects.select_for_update().get(pk=response.data['booking_id'])

    if data.get('action') == 'update_only' or request.method == 'PUT':
        job = Job.objects.filter(booking=booking).first()
        if not job:
            Branch.objects.select_for_update().get(pk=booking.branch_id)
            count = Job.objects.filter(created_at__date=timezone.localdate()).count()
            tag_val = str(data.get('tag_code') or data.get('cert_code') or '').strip()
            job = Job.objects.create(
                booking=booking, customer=booking.customer, category=data.get('category', booking.category),
                brand=data.get('brand') or booking.brand_name, model=data.get('model', booking.model),
                color=str(data.get('color', '')).strip(), serial_number=str(data.get('serial_number', '')).strip(),
                tag_code=tag_val,
                material=str(data.get('material', '')).strip(), accessories=str(data.get('accessories', '')).strip(),
                notes=str(data.get('note', booking.note)).strip(), expert_instruction=str(data.get('expert_instruction', '')).strip(),
                queue_no=f'{booking.branch_id}-{count + 1:03}', service_package=booking.service_package,
                price_snapshot=booking.price_snapshot or {}, price=booking.price_snapshot.get('total', 0) if booking.price_snapshot else 0,
                vat_amount=booking.price_snapshot.get('vat_amount', 0) if booking.price_snapshot else 0,
                payment_method=booking.payment_method, payment_status=booking.payment_status,
                shipping_status='pending_return' if booking.delivery_method == 'shipping' else 'not_applicable'
            )
        else:
            for f in ('serial_number', 'tag_code', 'color', 'material', 'accessories', 'notes', 'expert_instruction'):
                if f in data:
                    setattr(job, f, str(data[f]).strip())
            if 'cert_code' in data and data['cert_code']:
                job.tag_code = str(data['cert_code']).strip()
            if 'brand' in data or 'brand_name' in data:
                job.brand = str(data.get('brand') or data.get('brand_name')).strip()
            if 'model' in data:
                job.model = str(data['model']).strip()
            if 'category' in data:
                job.category = str(data['category']).strip()
            job.save()

            if job.tag_code:
                cert = Certificate.objects.filter(job=job).first()
                if cert and cert.cert_code != job.tag_code:
                    cert.cert_code = job.tag_code
                    cert.save(update_fields=['cert_code'])
        booking.refresh_from_db()
        return Response(walkin_detail(booking, request), status=200)

    receive_booking(request, booking.pk)
    if data.get('mark_paid') is True and booking.payment_status != 'paid':
        receive_payment(request, booking.pk)
    booking.refresh_from_db()
    return Response(walkin_detail(booking, request), status=200)


@api_view(['POST'])
@permission_classes([IsFrontDesk])
def walkin_qr(request):
    booking = get_object_or_404(Booking, pk=pk_value(request.data.get('booking_id')))
    if booking.status == 'cancelled' or booking.payment_status == 'paid' or not booking.price_snapshot:
        raise ValidationError('รายการนี้ไม่อยู่ในสถานะรับชำระ')
    return Response({'qr_image': qr_image(booking.price_snapshot['total']), 'amount': booking.price_snapshot['total']})
