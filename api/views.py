import os
import datetime
import uuid
import decimal
from django.conf import settings
from django.shortcuts import get_object_or_404
from django.http import HttpResponse, FileResponse
from django.db.models import Q, Min
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from .permissions import IsStaff, IsAdministrator, IsFrontDesk, IsInspector
from rest_framework.response import Response
from rest_framework import status
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    StaffUser, Branch, Brand, MembershipLevel, BrandPricing,
    ServiceType, Customer, Booking, BookingPhoto,
    Job, Certificate, CertificateSendLog, Contact, Partner
)
from .serializers import (
    StaffUserSerializer, BranchSerializer, BrandSerializer, MembershipLevelSerializer,
    BrandPricingSerializer, ServiceTypeSerializer, CustomerSerializer,
    BookingSerializer, BookingPhotoSerializer, JobSerializer,
    CertificateSerializer, CertificateSendLogSerializer,
    ContactSerializer, PartnerSerializer
)
from .promptpay import generate_promptpay_payload, generate_qr_code_image
from .pdf_generator import generate_certificate_pdf


def resolve_booking_pk(pk):
    """Convert BK-XXXX formatted strings to integer PKs for DB queries."""
    if isinstance(pk, str) and pk.upper().startswith('BK-'):
        try:
            return int(pk.split('-')[-1])
        except (IndexError, ValueError):
            pass
    try:
        return int(pk)
    except (TypeError, ValueError):
        return pk


def resolve_job_pk(pk):
    """Convert TLXXXX-X-XXXX formatted strings to integer PKs for DB queries."""
    if isinstance(pk, str) and pk.upper().startswith('TL'):
        try:
            return int(pk.split('-')[-1])
        except (IndexError, ValueError):
            pass
    try:
        return int(pk)
    except (TypeError, ValueError):
        return pk



def resolve_certificate(pk):
    """Resolve Certificate by either its cert_code (e.g. TL-XXXX-XXXX) or integer ID."""
    if pk is None:
        from django.http import Http404
        raise Http404("Certificate not found")
    
    cert = Certificate.objects.filter(cert_code=pk).first()
    if cert:
        return cert
        
    try:
        return Certificate.objects.get(id=int(pk))
    except (ValueError, TypeError, Certificate.DoesNotExist):
        from django.http import Http404
        raise Http404("Certificate not found")



# ============================================================
# 1. ระบบยืนยันตัวตน (Authentication)
# ============================================================

@api_view(['POST'])
@permission_classes([AllowAny])
def auth_login(request):
    """
    Authenticates back-office staff.
    Returns JWT access & refresh token alongside the staff user profile.
    Matches expectations in app/login/page.tsx
    """
    username = request.data.get('username')
    password = request.data.get('password')
    
    if not username or not password:
        return Response(
            {"error": "กรุณากรอกชื่อผู้ใช้และรหัสผ่าน"},
            status=status.HTTP_400_BAD_REQUEST
        )
        
    try:
        user = StaffUser.objects.get(username=username)
    except StaffUser.DoesNotExist:
        return Response(
            {"error": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"},
            status=status.HTTP_401_UNAUTHORIZED
        )
        
    if not user.is_active or not user.check_password(password):
        return Response(
            {"error": "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"},
            status=status.HTTP_401_UNAUTHORIZED
        )
        
    refresh = RefreshToken.for_user(user)
    
    return Response({
        "data": {
            "token": str(refresh.access_token),
            "refresh": str(refresh),
            "user": StaffUserSerializer(user).data
        }
    }, status=status.HTTP_200_OK)


# ============================================================
# 2. งานตรวจสอบสินค้า (Jobs)
# ============================================================

class JobListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == 'POST':
            # Next.js walk-in can be created, let's keep IsAuthenticated for both back-office access
            return [IsStaff()]
        return [IsStaff()]

    def get(self, request):
        """Lists jobs. Can filter by status (e.g. in_progress, completed)"""
        jobs = Job.objects.select_related('customer', 'booking__branch', 'certificate').order_by('-created_at')
        status_filter = request.query_params.get('status')
        if status_filter:
            jobs = jobs.filter(status=status_filter)
        serializer = JobSerializer(jobs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        return Response({'error': 'กรุณาสร้าง Booking พร้อมราคายืนยัน แล้วรับงานผ่าน bookings/<id>/check-in'}, status=409)


@api_view(['POST'])
@permission_classes([IsStaff])
def customer_create(request):
    """Creates a new customer. Matches frontend expectations in walk-in/page.tsx"""
    full_name = request.data.get('full_name')
    phone = request.data.get('phone') or request.data.get('phone_number')
    email = request.data.get('email')
    line_id = request.data.get('line_id')
    note = request.data.get('note')
    
    # Clean phone number (keep only digits)
    if phone:
        phone = "".join(filter(str.isdigit, str(phone)))
        
    # Check if customer already exists by phone
    customer = None
    if phone:
        customer = Customer.objects.filter(phone_number=phone).first()
        
    if not customer:
        req_tier = request.data.get('membership_level') or request.data.get('membership_tier')
        membership = None
        if req_tier:
            membership = MembershipLevel.objects.filter(level_name__iexact=req_tier).first()
        if not membership:
            membership = MembershipLevel.objects.filter(level_name__iexact='General').first() or MembershipLevel.objects.first()
        
        customer = Customer.objects.create(
            full_name=full_name or 'Walk-in Customer',
            phone_number=phone or f"TEMP-{uuid.uuid4().hex[:8]}",
            email=email,
            line_id=line_id,
            membership_level=membership,
            note=note
        )
        
    return Response({
        "status": "success",
        "customer_id": customer.id,
        "customer": CustomerSerializer(customer).data
    }, status=status.HTTP_201_CREATED)




# ============================================================
# 3. ใบรับรองสินค้า (Certificates) & ตรวจสาธารณะ (Verify)
# ============================================================



@api_view(['GET'])
@permission_classes([IsStaff])
def certificate_detail(request, pk):
    """Retrieves specific certificate details by id or cert_code"""
    cert = resolve_certificate(pk)
    return Response(CertificateSerializer(cert, context={'request': request}).data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsInspector])
def certificate_photos_update(request, pk):
    """Saves selected photo arrangement/ids for a certificate"""
    cert = resolve_certificate(pk)
    photo_ids = request.data.get('photo_ids', [])
    try:
        cert.selected_photos = [int(pid) for pid in photo_ids]
        cert.save()
    except (ValueError, TypeError):
        return Response({"error": "Invalid photo IDs structure"}, status=status.HTTP_400_BAD_REQUEST)
    return Response(CertificateSerializer(cert, context={'request': request}).data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsStaff])
def certificate_send_logs(request, pk):
    """Fetches line/email transmission logs for a certificate"""
    cert = resolve_certificate(pk)
    logs = CertificateSendLog.objects.filter(certificate=cert).order_by('-sent_at')
    return Response(CertificateSendLogSerializer(logs, many=True).data, status=status.HTTP_200_OK)


def send_line_flex_message(recipient_line_id, cert):
    """
    Sends a premium LINE Official Account Flex Message for certificate notifications.
    """
    import os
    import requests
    
    token = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN')
    if not token:
        print("⚠️ LINE Channel Access Token not configured. Simulating transmission.")
        return True
        
    status_label = {'authentic': 'AUTHENTIC – ผ่านเกณฑ์', 'fake': 'NOT AUTHENTICATED – ไม่ผ่านเกณฑ์การรับรองความแท้', 'inconclusive': 'UNABLE TO AUTHENTICATE – ข้อมูลหรือผลตรวจไม่เพียงพอที่จะสรุป'}.get(cert.cert_status, cert.cert_status.upper())
    status_color = "#10B981" # Green
    if cert.cert_status == 'fake':
        status_color = "#EF4444" # Red
    elif cert.cert_status == 'revoked':
        status_color = "#6B7280" # Gray
    elif cert.cert_status == 'expired':
        status_color = "#F59E0B" # Orange

    from django.conf import settings
    verify_url = f"{settings.PUBLIC_SITE_URL}/verify?id={cert.cert_code}"
    
    flex_contents = {
        "type": "bubble",
        "header": {
          "type": "box",
          "layout": "vertical",
          "contents": [
            {
              "type": "text",
              "text": "TRUST LAB THAILAND",
              "weight": "bold",
              "color": "#D4AF37",
              "size": "md"
            },
            {
              "type": "text",
              "text": "Luxury Authentication Results",
              "size": "xs",
              "color": "#aaaaaa"
            }
          ]
        },
        "body": {
          "type": "box",
          "layout": "vertical",
          "contents": [
            {
              "type": "text",
              "text": f"ใบรับรองผลเลขที่: {cert.cert_code}",
              "size": "xs",
              "color": "#888888",
              "margin": "sm"
            },
            {
              "type": "box",
              "layout": "vertical",
              "margin": "lg",
              "spacing": "sm",
              "contents": [
                {
                  "type": "box",
                  "layout": "baseline",
                  "spacing": "sm",
                  "contents": [
                    {
                      "type": "text",
                      "text": "แบรนด์ / Brand",
                      "color": "#aaaaaa",
                      "size": "sm",
                      "flex": 2
                    },
                    {
                      "type": "text",
                      "text": cert.job.brand if cert.job else "แบรนด์เนม",
                      "weight": "bold",
                      "size": "sm",
                      "color": "#333333",
                      "flex": 3
                    }
                  ]
                },
                {
                  "type": "box",
                  "layout": "baseline",
                  "spacing": "sm",
                  "contents": [
                    {
                      "type": "text",
                      "text": "รุ่น / Model",
                      "color": "#aaaaaa",
                      "size": "sm",
                      "flex": 2
                    },
                    {
                      "type": "text",
                      "text": cert.job.model if cert.job else "ทั่วไป",
                      "weight": "bold",
                      "size": "sm",
                      "color": "#333333",
                      "flex": 3
                    }
                  ]
                }
              ]
            },
            {
              "type": "box",
              "layout": "vertical",
              "margin": "xl",
              "backgroundColor": status_color,
              "cornerRadius": "md",
              "paddingAll": "md",
              "contents": [
                {
                  "type": "text",
                  "text": f"ผลการตรวจ: {status_label}",
                  "color": "#ffffff",
                  "weight": "bold",
                  "align": "center",
                  "size": "sm"
                }
              ]
            }
          ]
        },
        "footer": {
          "type": "box",
          "layout": "vertical",
          "spacing": "sm",
          "contents": [
            {
              "type": "button",
              "style": "primary",
              "color": "#111111",
              "height": "sm",
              "action": {
                "type": "uri",
                "label": "ตรวจสอบใบรับรองออนไลน์",
                "uri": verify_url
              }
            }
          ]
        }
    }
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    body = {
        "to": recipient_line_id,
        "messages": [
            {
                "type": "flex",
                "altText": f"แจ้งผลตรวจสินค้า {cert.job.brand if cert.job else 'แบรนด์เนม'}: {status_label}",
                "contents": flex_contents
            }
        ]
    }
    
    try:
        response = requests.post("https://api.line.me/v2/bot/message/push", headers=headers, json=body, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Error calling LINE OA Messaging API: {e}")
        return False


@api_view(['POST'])
@permission_classes([IsStaff])
def certificate_send(request, pk):
    """Dispatches certificate to client via LINE or Hostinger Email and records log"""
    cert = resolve_certificate(pk)
    method = str(request.data.get('method', 'email')).lower()
    recipient = str(request.data.get('recipient', '')).strip()

    # Dispatch LINE Flex Message if method is line
    if method == 'line' and recipient:
        send_line_flex_message(recipient, cert)
    elif method == 'email':
        from .emails import send_certificate_email
        send_certificate_email(cert, recipient)
    
    # Write sent log
    log = CertificateSendLog.objects.create(
        certificate=cert,
        method=method,
        recipient=recipient
    )
    return Response(CertificateSendLogSerializer(log).data, status=status.HTTP_201_CREATED)


@api_view(['POST'])
@permission_classes([IsAdministrator])
def certificate_revoke(request, pk):
    """Revokes a certificate with reason"""
    cert = resolve_certificate(pk)
    reason = request.data.get('reason', '')
    cert.cert_status = 'revoked'
    cert.revoke_reason = reason
    cert.save()
    return Response(CertificateSerializer(cert).data, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([IsAdministrator])
def certificate_expire(request, pk):
    """Marks a certificate as expired"""
    cert = resolve_certificate(pk)
    cert.cert_status = 'expired'
    from django.utils import timezone
    cert.expired_at = timezone.now()
    cert.save()
    return Response(CertificateSerializer(cert).data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def certificate_pdf_view(request, pk):
    """Serves ReportLab generated PDF certificate dynamically"""
    cert = resolve_certificate(pk)
    if cert.job.service_package == 'photo_review':
        return Response({'error': 'ไม่พบใบรับรอง'}, status=404)
    pdf_buffer = generate_certificate_pdf(cert)
    response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="certificate_{pk}.pdf"'
    return response


@api_view(['GET'])
@permission_classes([AllowAny])
def public_verify(request, pk):
    """
    Public Endpoint for verifying Certificate IDs.
    Also parses composite links like booking_id-queue_no (e.g. 12-A012).
    """
    cert = None
    if '-' in pk and not pk.upper().startswith('TL-'):
        try:
            booking_id, queue_no = pk.split('-', 1)
            cert = Certificate.objects.filter(
                job__booking_id=booking_id,
                job__queue_no=queue_no
            ).first()
        except ValueError:
            pass
    else:
        try:
            cert = resolve_certificate(pk)
        except Exception:
            pass

    if not cert or cert.job.service_package == 'photo_review':
        return Response(
            {"status": "not_found", "message": "ไม่พบหมายเลขใบรับรองในระบบ"},
            status=status.HTTP_404_NOT_FOUND
        )

    # Return standard verified layout schema
    return Response({
        "status": CertificateSerializer(cert).data["cert_status"],
        "data": CertificateSerializer(cert, context={'request': request}).data
    }, status=status.HTTP_200_OK)


# ============================================================
# 4. การจองคิว (Bookings)
# ============================================================



@api_view(['GET'])
@permission_classes([IsStaff])
def bookings_today(request):
    """Lists bookings for today (useful for staff checking camera scans)"""
    today = datetime.date.today()
    bookings = Booking.objects.filter(booking_date=today).order_by('booking_time')
    return Response(BookingSerializer(bookings, many=True).data, status=status.HTTP_200_OK)





@api_view(['GET'])
@permission_classes([IsStaff])
def booking_detail(request, pk):
    """Retrieves specific booking details"""
    pk = resolve_booking_pk(pk)
    booking = get_object_or_404(Booking, pk=pk)
    return Response(BookingSerializer(booking).data, status=status.HTTP_200_OK)


@api_view(['GET', 'POST'])
@permission_classes([IsStaff])
def booking_photos(request, pk):
    """GET details of uploaded photos or POST base64 uploads from camera scanner app"""
    pk = resolve_booking_pk(pk)
    booking = get_object_or_404(Booking, pk=pk)
    
    if request.method == 'POST':
        photos_data = request.data.get('photos', [])
        from .serializers import Base64ImageField
        for photo_b64 in photos_data:
            try:
                field = Base64ImageField()
                clean_img = field.to_internal_value(photo_b64)
                BookingPhoto.objects.create(booking=booking, photo=clean_img, photo_type='staff')
            except Exception:
                pass
        return Response({"status": "success"}, status=status.HTTP_201_CREATED)

    # GET photos
    photos = BookingPhoto.objects.filter(booking=booking).order_by('uploaded_at')
    customer_urls = []
    staff_urls = []
    for p in photos:
        if p.photo:
            uri = request.build_absolute_uri(p.photo.url)
            if p.photo_type == 'customer':
                customer_urls.append(uri)
            else:
                staff_urls.append(uri)
            
    return Response({
        "customer": customer_urls,
        "staff": staff_urls
    }, status=status.HTTP_200_OK)


@api_view(['GET', 'POST'])
@permission_classes([IsStaff])
def job_photos(request, pk):
    """GET flat list of job photos, or POST base64 uploads from camera scanner app / certificate manager"""
    job = get_object_or_404(Job, pk=resolve_job_pk(pk))
    
    if not job.booking:
        today = datetime.date.today()
        from .models import ServiceType
        service_type = ServiceType.objects.first()
        booking = Booking.objects.create(
            customer=job.customer,
            booking_date=today,
            booking_time=datetime.datetime.now().time(),
            service_type=service_type,
            status='completed'
        )
        job.booking = booking
        job.save()
        
    if request.method == 'POST':
        photos_data = request.data.get('photos', [])
        from .serializers import Base64ImageField
        for photo_b64 in photos_data:
            try:
                field = Base64ImageField()
                clean_img = field.to_internal_value(photo_b64)
                BookingPhoto.objects.create(booking=job.booking, photo=clean_img, photo_type='staff')
            except Exception:
                pass
        return Response({"status": "success"}, status=status.HTTP_201_CREATED)

    data = []
    if job.booking:
        photos = BookingPhoto.objects.filter(booking=job.booking).order_by('uploaded_at')
        for p in photos:
            if p.photo:
                data.append({
                    "photo_id": p.id,
                    "photo_url": request.build_absolute_uri(p.photo.url)
                })
    return Response(data, status=status.HTTP_200_OK)




# ============================================================
# 5. ลูกค้า สมาชิก และเครดิต (Customers & Members)
# ============================================================

@api_view(['GET'])
@permission_classes([IsStaff])
def customers_search(request):
    """Searches customers by phone number or name"""
    q = request.query_params.get('q', '')
    phone = request.query_params.get('phone', '')
    
    customers = Customer.objects.all()
    if phone:
        customers = customers.filter(phone_number=phone)
    elif q:
        customers = customers.filter(Q(full_name__icontains=q) | Q(phone_number__contains=q))
        
    customers = customers.select_related('membership_level').annotate(first_service_date=Min('job__created_at', filter=~Q(job__status='cancelled')))
    return Response(CustomerSerializer(customers, many=True).data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def public_customer_lookup(request):
    customer = Customer.objects.filter(user=request.user).first() if request.user.is_authenticated else None
    if not customer:
        return Response({'found': False})
    return Response({'found': True, 'customer': CustomerSerializer(customer).data,
                     'membership_tier': customer.membership_level.level_name if customer.membership_level else 'general'})


@api_view(['GET'])
@permission_classes([IsStaff])
def members_list(request):
    """Lists customers with active membership details"""
    customers = Customer.objects.exclude(membership_level=None).order_by('-credit_balance')
    if not customers.exists():
        customers = Customer.objects.all().order_by('full_name')
    customers = customers.select_related('membership_level').annotate(first_service_date=Min('job__created_at', filter=~Q(job__status='cancelled')))
    return Response(CustomerSerializer(customers, many=True).data, status=status.HTTP_200_OK)




# ============================================================
# 6. ข้อมูลตั้งต้นระบบและราคา (Master Data & Pricing)
# ============================================================

class ServiceTypeListCreateView(APIView):
    permission_classes = [IsAdministrator]

    def get(self, request):
        services = ServiceType.objects.all().order_by('id')
        return Response(ServiceTypeSerializer(services, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = ServiceTypeSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ServiceTypeDetailView(APIView):
    permission_classes = [IsAdministrator]

    def get_object(self, pk):
        return get_object_or_404(ServiceType, pk=pk)

    def get(self, request, pk):
        service = self.get_object(pk)
        return Response(ServiceTypeSerializer(service).data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        service = self.get_object(pk)
        serializer = ServiceTypeSerializer(service, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        service = self.get_object(pk)
        service.delete()
        return Response({"status": "success"}, status=status.HTTP_200_OK)



class BrandListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == 'GET':
            return [AllowAny()]
        return [IsStaff()]

    def get(self, request):
        brands = Brand.objects.all().order_by('brand_name')
        return Response(BrandSerializer(brands, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = BrandSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class BrandDeleteView(APIView):
    permission_classes = [IsAdministrator]

    def delete(self, request, pk):
        brand = get_object_or_404(Brand, pk=pk)
        brand.delete()
        return Response({"status": "success"}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def brand_pricing_query(request):
    """Queries product authentication price details according to category & brand"""
    category = request.query_params.get('category')
    brand = request.query_params.get('brand')

    # Map short category codes (B, W, C, S, A) or uppercase keys to DB values
    cat_map = {
        'B': 'Bag', 'BAG': 'Bag',
        'W': 'Watch', 'WATCH': 'Watch',
        'C': 'Clothes', 'CLOTHES': 'Clothes',
        'S': 'Shoes', 'SHOES': 'Shoes',
        'A': 'Accessories', 'ACCESSORIES': 'Accessories'
    }
    if category:
        category = cat_map.get(category.upper(), category)

    pricing = BrandPricing.objects.filter(
        category__iexact=category,
        brand__iexact=brand
    ).first()
    
    if pricing:
        return Response(BrandPricingSerializer(pricing).data, status=status.HTTP_200_OK)
        
    # Return placeholder fallback price in case brand pricing matrix isn't seeded
    return Response({
        "price_general": 1200,
        "price_silver": 1200,
        "price_gold": 1020,
        "price_platinum": 1140,
        "price_partner": 850,
        "is_fallback": True
    }, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def membership_pricing_list(request):
    """Lists discount parameters and certificate pricing configurations for members"""
    levels = MembershipLevel.objects.all().order_by('certificate_price')
    return Response(MembershipLevelSerializer(levels, many=True).data, status=status.HTTP_200_OK)


# ============================================================
# 7. Utilities & Public Pages (PromptPay, Contacts & Partners)
# ============================================================

@api_view(['GET'])
@permission_classes([AllowAny])
def public_qrcode_view(request):
    """
    Renders EMVCo-compliant PromptPay payment QR codes.
    Takes GET parameters 'text' (custom payload) or triggers automatic calculation.
    """
    text_param = request.query_params.get('text', '')
    amount_param = request.query_params.get('amount')
    
    # Parse payload
    payload = text_param
    if not payload:
        amount = float(amount_param) if amount_param else 0.00
        # Generate default merchant PromptPay payload using company Tax ID
        from .workflows import qr_image
        from django.conf import settings
        from .commerce import money
        qr_image(money(amount))  # Validate configured recipient and amount first.
        payload = generate_promptpay_payload(settings.PROMPTPAY_RECEIVER_ID, money(amount))
        
    qr_buffer = generate_qr_code_image(payload)
    return HttpResponse(qr_buffer.read(), content_type='image/png')


class PublicContactSubmitView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = ContactSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "success"}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class PublicPartnerSubmitView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        serializer = PartnerSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response({"status": "success"}, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


# Placeholder for reports






@api_view(['GET'])
@permission_classes([IsStaff])
def contacts_list(request):
    """Lists submitted contact messages for staff"""
    contacts = Contact.objects.all().order_by('-created_at')
    return Response(ContactSerializer(contacts, many=True).data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([IsStaff])
def partners_list(request):
    """Lists submitted partner proposals for staff"""
    partners = Partner.objects.all().order_by('-created_at')
    return Response(PartnerSerializer(partners, many=True).data, status=status.HTTP_200_OK)


@api_view(['PUT', 'DELETE'])
@permission_classes([IsStaff])
def contact_detail(request, pk):
    """Updates status or deletes a contact message"""
    contact = get_object_or_404(Contact, pk=pk)
    if request.method == 'PUT':
        status_val = request.data.get('status', 'read')
        contact.status = status_val
        contact.save()
        return Response({"status": "success", "message": "Contact updated"}, status=status.HTTP_200_OK)
    elif request.method == 'DELETE':
        contact.delete()
        return Response({"status": "success", "message": "Contact deleted"}, status=status.HTTP_200_OK)


@api_view(['PUT', 'DELETE'])
@permission_classes([IsStaff])
def partner_detail(request, pk):
    """Updates status or deletes a partner request"""
    partner = get_object_or_404(Partner, pk=pk)
    if request.method == 'PUT':
        status_val = request.data.get('status', 'approved')
        partner.status = status_val
        partner.save()
        return Response({"status": "success", "message": "Partner updated"}, status=status.HTTP_200_OK)
    elif request.method == 'DELETE':
        partner.delete()
        return Response({"status": "success", "message": "Partner deleted"}, status=status.HTTP_200_OK)




# ============================================================
# 8. การจัดการพนักงาน/บัญชีผู้ใช้ (Staff CRUD)
# ============================================================

class UserListCreateView(APIView):
    permission_classes = [IsAdministrator]

    def get(self, request):
        users = StaffUser.objects.all().order_by('id')
        serializer = StaffUserSerializer(users, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = StaffUserSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class UserDetailView(APIView):
    permission_classes = [IsAdministrator]

    def get_object(self, pk):
        return get_object_or_404(StaffUser, pk=pk)

    def get(self, request, pk):
        user = self.get_object(pk)
        return Response(StaffUserSerializer(user).data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        user = self.get_object(pk)
        serializer = StaffUserSerializer(user, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        user = self.get_object(pk)
        if user == request.user:
            return Response({"error": "ไม่สามารถลบบัญชีของตัวเองได้"}, status=status.HTTP_400_BAD_REQUEST)
        user.delete()
        return Response({"status": "success"}, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def branches_list(request):
    """Lists all service branches"""
    branches = Branch.objects.filter(is_active=True).order_by('id')

    data = []
    for b in branches:
        name_en = "Siam Square One" if b.id == 1 else ("Central Chidlom" if b.id == 2 else b.name)
        data.append({
            "id": b.id,
            "name": b.name,
            "nameEn": f"BKK - {name_en}",
            "details": "เปิดบริการทุกวัน 11:30 - 20:30 น.",
            "detailsEn": "Open daily 11:30 AM - 8:30 PM",
            "open_hours": "11:30 - 20:30 น.",
            "phone_number": "0640678666",
            "branch_id": b.id,
            "branch_name": b.name,
            "address": "เปิดบริการทุกวัน 11:30 - 20:30 น."
        })
    return Response(data, status=status.HTTP_200_OK)


@api_view(['GET'])
@permission_classes([AllowAny])
def public_booking_availability(request):
    """
    Returns available timeslots for a given date.
    Matches frontend page.tsx step 4 timeslot selector.
    """
    date_param = request.query_params.get('date') # YYYY-MM-DD
    
    slots = [
        {"slot": "11:30 - 13:00", "available": True, "capacity": 3},
        {"slot": "13:00 - 14:30", "available": True, "capacity": 3},
        {"slot": "14:30 - 16:00", "available": True, "capacity": 3},
        {"slot": "16:00 - 17:30", "available": True, "capacity": 3},
        {"slot": "17:30 - 19:00", "available": True, "capacity": 3}
    ]
    
    return Response(slots, status=status.HTTP_200_OK)


def num_to_thai_baht(number) -> str:
    """Converts numeric amount to official Thai Baht text representation."""
    try:
        amount = float(number)
    except (ValueError, TypeError):
        return ""

    if amount == 0:
        return "(ศูนย์บาทถ้วน)"

    digits = ["ศูนย์", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
    units = ["", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน", "ล้าน"]

    baht_part = int(abs(amount))
    satang_part = int(round((abs(amount) - baht_part) * 100))

    def convert_group(n):
        if n == 0:
            return ""
        s = str(n)
        length = len(s)
        res = []
        for i, ch in enumerate(s):
            digit = int(ch)
            idx = length - i - 1
            if digit != 0:
                if idx == 0 and digit == 1 and length > 1:
                    res.append("เอ็ด")
                elif idx == 1 and digit == 1:
                    res.append("สิบ")
                elif idx == 1 and digit == 2:
                    res.append("ยี่สิบ")
                else:
                    res.append(digits[digit] + units[idx])
        return "".join(res)

    def convert_int(n):
        if n == 0:
            return "ศูนย์"
        result = ""
        millions_groups = []
        while n > 0:
            millions_groups.append(n % 1000000)
            n //= 1000000
        for i, group in enumerate(millions_groups):
            group_str = convert_group(group)
            if group_str:
                if i > 0:
                    group_str += "ล้าน" * i
                result = group_str + result
        return result

    prefix = "ลบ" if amount < 0 else ""
    baht_text = convert_int(baht_part) + "บาท"

    if satang_part == 0:
        satang_text = "ถ้วน"
    else:
        satang_text = convert_group(satang_part) + "สตางค์"

    return f"({prefix}{baht_text}{satang_text})"


@api_view(['GET', 'POST'])
@permission_classes([AllowAny])
def public_invoice_preview(request):
    """
    Renders official Tax Invoice or Receipt from JSON payload POSTed or passed via GET.
    Supports POS Abbreviated Slip (80mm) and Full Tax Invoice A4 (Original & Copy 2 sets).
    """
    import json as _json

    is_slip = request.GET.get('slip') == '1'
    raw = request.POST.get('data') or request.data.get('data') or request.GET.get('data') or '{}'
    try:
        d = _json.loads(raw)
    except Exception:
        d = {}

    customer = d.get('customerData', {})
    product = d.get('productData', {})
    items = d.get('items', [])
    total_cost = float(d.get('totalCost', 0))
    discount = float(d.get('discount', 0))
    payment_method = d.get('paymentMethod', 'cash')
    payment_status = d.get('paymentStatus', 'paid')
    job_id = d.get('jobId', '')
    queue_no = d.get('queueNo', '')
    expert_note = d.get('expertNote', '')
    seller_name = d.get('sellerName', 'Trust Lab')
    ref_qt = d.get('refQt', f"QT{datetime.datetime.now().strftime('%Y%m%d')}")
    credit_days = d.get('creditDays', '-')
    due_date_str = d.get('dueDate', '-')

    now = datetime.datetime.now()
    date_str = now.strftime('%d/%m/%Y')
    time_str = now.strftime('%H:%M')

    cname = customer.get('name', '-')
    caddress = customer.get('address', '-')
    ctax_id = customer.get('taxId', '-')
    ccontact = customer.get('contactPerson', cname)
    cphone = customer.get('phone', '-')
    cemail = customer.get('email', '-')
    cmembership = customer.get('type', 'General')

    pbrand = product.get('brand', '-')
    pmodel = product.get('model', '-')
    pcategory = product.get('category', '-')
    pserial = product.get('serialNumber', '-')

    payment_label = {'cash': 'เงินสด', 'transfer': 'โอนเงิน', 'card': 'บัตรเครดิต', 'promptpay': 'PromptPay QR'}.get(payment_method, payment_method)

    # Calculate Tax Amounts (7% VAT)
    subtotal = total_cost + discount
    after_discount = total_cost
    vat_amount = round(after_discount * 7.0 / 107.0, 2)
    before_vat = round(after_discount - vat_amount, 2)

    baht_text = num_to_thai_baht(total_cost)
    raw_id = job_id or queue_no or '0001'
    clean_num = str(raw_id).split('-')[-1].strip()
    if clean_num.isdigit():
        clean_num = f"{int(clean_num):04d}"
    doc_inv_no = d.get('invNo') or d.get('invoiceNo') or f"INV-{now.strftime('%y%m')}-{clean_num}"
    doc_rc_no = d.get('rcNo') or d.get('receiptNo') or f"RC-{now.strftime('%y%m')}-{clean_num}"

    # Master Company Data
    COMP_NAME = "บริษัท เซอร์ติฟิเคชั่น แอนด์ อินสเปคชั่น (ไทยแลนด์) จำกัด (สำนักงานใหญ่)"
    COMP_ADDR_LINE1 = "388 อาคารสยามสแควร์วัน ห้อง MS1107 ชั้น 1 ถนนพระราม 1"
    COMP_ADDR_LINE2 = "แขวงปทุมวัน เขตปทุมวัน กรุงเทพมหานคร 10330"
    COMP_TAX_ID = "0105569150179"
    COMP_TEL = "0640678666"

    # Base64 Logo for 100% reliable image rendering in print & server preview
    import base64
    logo_src = "/logo-trust-lab.png"
    logo_candidates = [
        os.path.join(settings.BASE_DIR, 'assets', 'logo-trust-lab.png'),
        os.path.join(settings.BASE_DIR, '..', 'public', 'logo-trust-lab.png'),
        os.path.join(settings.BASE_DIR, 'public', 'logo-trust-lab.png'),
        '/app/assets/logo-trust-lab.png',
        '/app/public/logo-trust-lab.png'
    ]
    for lpath in logo_candidates:
        if os.path.exists(lpath):
            try:
                with open(lpath, 'rb') as f:
                    logo_src = 'data:image/png;base64,' + base64.b64encode(f.read()).decode()
                break
            except Exception:
                pass

    if is_slip:
        # ── ABBREVIATED TAX INVOICE / RECEIPT (80mm POS Slip) ───────────
        items_rows = ""
        for i, item in enumerate(items, 1):
            if not item:
                continue
            name = item.get('name', 'บริการตรวจสอบสินค้า')
            qty = item.get('quantity', 1)
            price = float(item.get('price', item.get('amount', 0)))
            amt = float(item.get('amount', price * qty))
            items_rows += f"""
            <div style="display:flex;justify-content:space-between;margin:3px 0;">
              <span>{name}</span>
              <span>{qty} x ฿{price:,.2f}</span>
              <span style="font-weight:700;">฿{amt:,.2f}</span>
            </div>"""

        if not items_rows:
            items_rows = f"""
            <div style="display:flex;justify-content:space-between;margin:3px 0;">
              <span>ตรวจสอบสินค้า ({pbrand} {pmodel})</span>
              <span>1</span>
              <span style="font-weight:700;">฿{total_cost:,.2f}</span>
            </div>"""

        html = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<title>ใบกำกับภาษีอย่างย่อ / ใบเสร็จรับเงิน - Trust Lab</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;600;700&display=swap');
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'IBM Plex Sans Thai',sans-serif; font-size:11px; background:#fff; width:302px; margin:0 auto; padding:12px; color:#111; }}
  .center {{ text-align:center; }}
  .logo-text {{ font-size:16px; font-weight:800; letter-spacing:2px; }}
  .sep {{ border-top:1px dashed #aaa; margin:8px 0; }}
  .row {{ display:flex; justify-content:space-between; margin:3px 0; }}
  .label {{ color:#555; }}
  .total-bar {{ background:#f3f4f6; color:#111827; border:1px solid #d1d5db; border-top:2px solid #111827; padding:6px 8px; font-size:13px; font-weight:700; display:flex; justify-content:space-between; margin-top:8px; border-radius:4px; }}
  .footer {{ font-size:9px; color:#666; text-align:center; margin-top:12px; }}
  @media print {{ @page {{ margin:0; size:80mm auto; }} body {{ padding:4px; }} }}
</style>
</head>
<body>
<div class="center">
  <img src="{logo_src}" alt="Trust Lab" style="height:32px;margin-bottom:4px;" />
  <div class="logo-text">TRUST LAB THAILAND</div>
</div>
<div class="sep"></div>
<div class="center" style="font-size:12px;font-weight:700;margin:4px 0;">ใบกำกับภาษีอย่างย่อ / ใบเสร็จรับเงิน</div>
<div class="row"><span class="label">เลขที่:</span><span style="font-weight:700;">{doc_rc_no}</span></div>
<div class="row"><span class="label">วันที่:</span><span>{date_str} {time_str}</span></div>
<div class="row"><span class="label">พนักงานขาย:</span><span>{seller_name}</span></div>
<div class="sep"></div>
<div class="row" style="font-weight:700;border-bottom:1px solid #ddd;padding-bottom:2px;">
  <span>รายการ</span><span>จำนวน</span><span>รวม</span>
</div>
{items_rows}
<div class="sep"></div>
<div class="row"><span class="label">รวมเป็นเงิน:</span><span>฿{subtotal:,.2f}</span></div>
<div class="row"><span class="label">ส่วนลด:</span><span>฿{discount:,.2f}</span></div>
<div class="row"><span class="label">จำนวนเงินหลังหักส่วนลด:</span><span>฿{after_discount:,.2f}</span></div>
<div class="row"><span class="label">ภาษีมูลค่าเพิ่ม 7%:</span><span>฿{vat_amount:,.2f}</span></div>

<div class="total-bar">
  <span>รวมทั้งสิ้น</span>
  <span>฿{total_cost:,.2f}</span>
</div>

<div class="sep"></div>
<div class="footer">
  ขอบคุณที่ใช้บริการ<br>
  THANK YOU
</div>
<script>window.onload = () => setTimeout(() => window.print(), 400);</script>
</body>
</html>"""
    else:
        # ── FULL TAX INVOICE A4 (Original & Copy 2 Sets) ─────────────────
        def render_a4_page(set_type_title, set_type_en):
            item_rows_a4 = ""
            if items:
                for idx, it in enumerate(items, 1):
                    if not it:
                        continue
                    iname = it.get('name', 'ตรวจสอบสินค้า')
                    iqty = it.get('quantity', 1)
                    iprice = float(it.get('price', it.get('amount', 0)))
                    idisc = float(it.get('discount', 0))
                    iamt = float(it.get('amount', iprice * iqty - idisc))
                    item_rows_a4 += f"""
                    <tr>
                      <td style="text-align:center;">{idx}</td>
                      <td>{iname} ({pbrand} {pmodel})</td>
                      <td style="text-align:center;">{iqty}</td>
                      <td style="text-align:right;">{iprice:,.2f}</td>
                      <td style="text-align:right;">{idisc:,.2f}</td>
                      <td style="text-align:right;font-weight:700;">{iamt:,.2f}</td>
                    </tr>"""
            else:
                item_rows_a4 = f"""
                <tr>
                  <td style="text-align:center;">1</td>
                  <td>บริการตรวจสอบสินค้า Luxury Product ({pbrand} {pmodel})</td>
                  <td style="text-align:center;">1</td>
                  <td style="text-align:right;">{subtotal:,.2f}</td>
                  <td style="text-align:right;">{discount:,.2f}</td>
                  <td style="text-align:right;font-weight:700;">{total_cost:,.2f}</td>
                </tr>"""

            return f"""
            <div class="page">
              <!-- Top Right Triangle Corner Banner -->
              <div class="top-corner"></div>

              <!-- Header Section -->
              <div class="header">
                <div class="company-brand">
                  <div style="display:flex;align-items:center;gap:10px;">
                    <img src="{logo_src}" alt="Logo" style="height:38px;" />
                    <div>
                      <div class="brand-title">TRUST LAB</div>
                      <div class="brand-slogan">VERIFY · INSPECT · ASSURE</div>
                    </div>
                  </div>
                  <div class="company-details">
                    <strong>{COMP_NAME}</strong><br>
                    {COMP_ADDR_LINE1}<br>
                    {COMP_ADDR_LINE2}<br>
                    เลขประจำตัวผู้เสียภาษี {COMP_TAX_ID}<br>
                    โทร. {COMP_TEL}
                  </div>
                </div>

                <div class="invoice-title-block">
                  <div class="inv-main-title">ใบกำกับภาษี</div>
                  <div class="inv-sub-title">{set_type_title}</div>
                  <div class="inv-en-title">TAX INVOICE ({set_type_en})</div>

                  <table class="doc-meta-table">
                    <tr><td>เลขที่</td><td>: {doc_inv_no}</td></tr>
                    <tr><td>วันที่</td><td>: {date_str}</td></tr>
                    <tr><td>เครดิต</td><td>: {credit_days}</td></tr>
                    <tr><td>ครบกำหนด</td><td>: {due_date_str}</td></tr>
                    <tr><td>ผู้ขาย</td><td>: {seller_name}</td></tr>
                    <tr><td>อ้างอิง</td><td>: {ref_qt}</td></tr>
                  </table>
                </div>
              </div>

              <!-- Customer Info Section -->
              <div class="customer-box">
                <div style="flex:1.2;">
                  <div class="cust-label">ลูกค้า</div>
                  <div class="cust-name">{cname}</div>
                  <div class="cust-info">{caddress}</div>
                   <div class="cust-info" style="margin-top:4px;"><strong>เลขประจำตัวผู้เสียภาษีลูกค้า:</strong> {ctax_id if ctax_id and ctax_id != '-' else '-'}</div>
                </div>
                <div style="flex:0.8;border-left:1px solid #e5e7eb;padding-left:16px;">
                  <div class="cust-info"><strong>ชื่อผู้ติดต่อ:</strong> {ccontact}</div>
                  <div class="cust-info"><strong>เบอร์โทร:</strong> {cphone}</div>
                  <div class="cust-info"><strong>อีเมล:</strong> {cemail}</div>
                </div>
              </div>

              <!-- Items Table -->
              <table class="items-table">
                <thead>
                  <tr>
                    <th style="width:40px;text-align:center;">#</th>
                    <th style="text-align:left;">รายละเอียด</th>
                    <th style="width:60px;text-align:center;">จำนวน</th>
                    <th style="width:100px;text-align:right;">ราคาต่อหน่วย</th>
                    <th style="width:90px;text-align:right;">ส่วนลด</th>
                    <th style="width:110px;text-align:right;">มูลค่า</th>
                  </tr>
                </thead>
                <tbody>
                  {item_rows_a4}
                </tbody>
              </table>

              <!-- Summary & Baht Text Section -->
              <div class="summary-wrapper">
                <div class="baht-text-box">
                  <div class="baht-text">{baht_text}</div>
                  <div class="note-box">
                    <strong>หมายเหตุ:</strong> {expert_note or '-'}
                  </div>
                </div>

                <table class="calc-table">
                  <tr><td>รวมเป็นเงิน</td><td style="text-align:right;">{subtotal:,.2f} บาท</td></tr>
                  <tr><td>ส่วนลด</td><td style="text-align:right;">{discount:,.2f} บาท</td></tr>
                  <tr><td>จำนวนเงินหลังหักส่วนลด</td><td style="text-align:right;">{after_discount:,.2f} บาท</td></tr>
                  <tr><td>ภาษีมูลค่าเพิ่ม 7%</td><td style="text-align:right;">{vat_amount:,.2f} บาท</td></tr>
                  <tr><td>ราคาไม่รวมภาษีมูลค่าเพิ่ม</td><td style="text-align:right;">{before_vat:,.2f} บาท</td></tr>
                  <tr class="grand-total-row">
                    <td>จำนวนเงินรวมทั้งสิ้น</td>
                    <td style="text-align:right;">{total_cost:,.2f} บาท</td>
                  </tr>
                </table>
              </div>

              <!-- Signatures Footer -->
              <div class="signatures-wrapper">
                <div class="thank-box" style="text-align:left;">
                  ขอบคุณที่ใช้บริการ<br>
                  <span>THANK YOU</span>
                </div>

                <div class="sig-box">
                  <div class="sig-line"></div>
                  <div class="sig-label">ผู้อนุมัติ</div>
                  <div class="sig-date">วันที่ ..... / ..... / ..........</div>
                </div>
              </div>

              <div class="bottom-watermark">
                TRUST LAB THAILAND · VERIFY · INSPECT · ASSURE
              </div>
            </div>"""

        html_original = render_a4_page("ต้นฉบับ", "ORIGINAL")
        html_copy = render_a4_page("คู่ฉบับ", "COPY")

        html = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<title>ใบกำกับภาษี {doc_inv_no} - Trust Lab</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@300;400;500;600;700;800&display=swap');
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'IBM Plex Sans Thai',sans-serif; background:#e5e7eb; color:#111827; -webkit-print-color-adjust:exact; print-color-adjust:exact; }}
  
  .page {{ background:#fff; width:210mm; min-height:297mm; margin:20px auto; padding:16mm 18mm; position:relative; box-shadow:0 10px 25px rgba(0,0,0,0.1); border-radius:2px; page-break-after:always; }}
  
  .top-corner {{ position:absolute; top:0; right:0; width:0; height:0; border-style:solid; border-width:0 70px 70px 0; border-color:transparent #111827 transparent transparent; }}

  .header {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:16px; border-bottom:1px solid #e5e7eb; padding-bottom:14px; }}
  .brand-title {{ font-size:20px; font-weight:800; letter-spacing:2px; color:#111; }}
  .brand-slogan {{ font-size:7px; font-weight:700; color:#6b7280; letter-spacing:1.5px; }}
  .company-details {{ font-size:10px; color:#374151; line-height:1.5; margin-top:8px; }}

  .invoice-title-block {{ text-align:right; margin-right:20px; }}
  .inv-main-title {{ font-size:22px; font-weight:800; color:#111; letter-spacing:2px; }}
  .inv-sub-title {{ font-size:14px; font-weight:700; color:#111; margin-top:-2px; }}
  .inv-en-title {{ font-size:8px; font-weight:700; color:#6b7280; letter-spacing:1px; margin-bottom:8px; }}

  .doc-meta-table {{ margin-left:auto; border-collapse:collapse; font-size:10.5px; }}
  .doc-meta-table td {{ padding:2px 4px; color:#374151; text-align:left; }}
  .doc-meta-table td:first-child {{ font-weight:700; color:#4b5563; }}

  .customer-box {{ display:flex; justify-content:space-between; background:#f9fafb; border:1px solid #e5e7eb; border-radius:8px; padding:12px 16px; margin-bottom:16px; gap:16px; }}
  .cust-label {{ font-size:8.5px; font-weight:700; color:#9ca3af; text-transform:uppercase; letter-spacing:1px; margin-bottom:2px; }}
  .cust-name {{ font-size:13px; font-weight:700; color:#111827; margin-bottom:4px; }}
  .cust-info {{ font-size:10.5px; color:#374151; line-height:1.5; }}

  .items-table {{ width:100%; border-collapse:collapse; margin-bottom:16px; }}
  .items-table thead tr {{ background:#f3f4f6; border-top:1px solid #d1d5db; border-bottom:1px solid #d1d5db; }}
  .items-table th {{ padding:8px 10px; font-size:10px; font-weight:700; color:#374151; text-transform:uppercase; }}
  .items-table tbody tr {{ border-bottom:1px solid #f3f4f6; }}
  .items-table td {{ padding:10px; font-size:11px; color:#1f2937; vertical-align:middle; }}

  .summary-wrapper {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:20px; gap:20px; }}
  .baht-text-box {{ flex:1; display:flex; flex-direction:column; justify-content:space-between; }}
  .baht-text {{ font-size:12px; font-weight:700; color:#111827; background:#f3f4f6; padding:8px 12px; border-radius:6px; border-left:4px solid #111827; margin-bottom:10px; }}
  .note-box {{ font-size:10px; color:#4b5563; line-height:1.5; background:#fffbeb; padding:8px 12px; border-radius:6px; border-left:3px solid #f59e0b; }}

  .calc-table {{ width:290px; border-collapse:collapse; font-size:11px; }}
  .calc-table td {{ padding:4px 0; color:#4b5563; }}
  .calc-table td:last-child {{ color:#111827; font-weight:600; }}
  .grand-total-row td {{ background:#f3f4f6; color:#111827 !important; font-size:13px; font-weight:800; padding:8px 10px; border-radius:4px; border:1px solid #e5e7eb; border-top:2px solid #111827; }}

  .signatures-wrapper {{ display:flex; justify-content:space-between; align-items:flex-end; margin-top:30px; padding-top:20px; border-top:1px solid #e5e7eb; text-align:center; }}
  .sig-box {{ width:180px; }}
  .sig-line {{ border-bottom:1px dashed #9ca3af; height:45px; margin-bottom:8px; }}
  .sig-label {{ font-size:10px; font-weight:600; color:#374151; }}
  .sig-date {{ font-size:9px; color:#9ca3af; margin-top:4px; }}
  .thank-box {{ font-size:11px; font-weight:700; color:#111827; line-height:1.4; }}
  .thank-box span {{ font-size:8px; color:#6b7280; letter-spacing:1px; }}

  .bottom-watermark {{ position:absolute; bottom:12mm; left:0; right:0; text-align:center; font-size:7.5px; font-weight:700; color:#9ca3af; letter-spacing:2px; }}

  @media print {{
    @page {{ size:A4; margin:0; }}
    body {{ background:#fff; }}
    .page {{ margin:0; width:100%; min-height:297mm; padding:16mm 18mm; box-shadow:none; border-radius:0; }}
  }}
</style>
</head>
<body>
{html_original}
{html_copy}
<script>window.onload = () => setTimeout(() => window.print(), 600);</script>
</body>
</html>"""

    return HttpResponse(html, content_type='text/html; charset=utf-8')








@api_view(['POST'])
@permission_classes([AllowAny])
def auth_line_login(request):
    """
    Exchanges LINE OAuth 2.0 authorization code for user profile
    and returns JWT token for the matched staff user.
    """
    code = request.data.get('code')
    redirect_uri = request.data.get('redirect_uri')
    
    if not code:
        return Response({"error": "ต้องการ authorization code"}, status=400)
        
    import os
    import requests
    from rest_framework_simplejwt.tokens import RefreshToken
    from .models import StaffUser

    # Default fallback credentials (can be overwritten via .env)
    line_client_id = os.environ.get('LINE_CLIENT_ID', '2006394541')
    line_client_secret = os.environ.get('LINE_CLIENT_SECRET', '')
    
    # 1. Exchange OAuth code for Access Token
    access_token = None
    line_user_id = None
    line_display_name = None
    
    if line_client_secret:
        try:
            token_res = requests.post("https://api.line.me/oauth2/v2.1/token", data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "client_id": line_client_id,
                "client_secret": line_client_secret
            }, timeout=10)
            if token_res.status_code == 200:
                access_token = token_res.json().get('access_token')
        except Exception as e:
            print(f"LINE Token Exchange Error: {e}")
            
    # 2. Get LINE user profile
    if access_token:
        try:
            profile_res = requests.get("https://api.line.me/v2/profile", headers={
                "Authorization": f"Bearer {access_token}"
            }, timeout=10)
            if profile_res.status_code == 200:
                profile_data = profile_res.json()
                line_user_id = profile_data.get('userId')
                line_display_name = profile_data.get('displayName')
        except Exception as e:
            print(f"LINE Profile Fetch Error: {e}")
            
    # 3. Match or fallback to default staff user for testing/sandbox
    staff_user = None
    if line_user_id:
        staff_user = StaffUser.objects.filter(line_user_id=line_user_id).first()
        
    if not staff_user or not staff_user.is_active or staff_user.role == 'customer':
        return Response({'error': 'ไม่พบบัญชีพนักงานที่เชื่อม LINE นี้'}, status=403)

    refresh = RefreshToken.for_user(staff_user)
    
    return Response({
        "token": str(refresh.access_token),
        "user": {
            "id": staff_user.id,
            "username": staff_user.username,
            "role": staff_user.role,
            "full_name": staff_user.full_name or staff_user.username,
            "line_user_id": staff_user.line_user_id,
            "line_display_name": line_display_name
        }
    }, status=200)


def send_wechat_group_notification(content_markdown):
    """
    Sends a WeChat Work group chat webhook notification.
    """
    import os
    import requests
    
    webhook_key = os.environ.get('WECHAT_WORK_WEBHOOK_KEY')
    if not webhook_key:
        print("⚠️ WeChat Work Webhook Key not configured. Simulating notification.")
        return True
        
    url = f"https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key={webhook_key}"
    headers = {"Content-Type": "application/json"}
    body = {
        "msgtype": "markdown",
        "markdown": {
            "content": content_markdown
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=body, timeout=10)
        return response.status_code == 200
    except Exception as e:
        print(f"Error calling WeChat Work Webhook: {e}")
        return False


@api_view(['POST'])
@permission_classes([AllowAny])
def auth_customer_register(request):
    """
    Registers a new customer account. Creates both a StaffUser (role='customer')
    and a corresponding Customer profile. Returns JWT tokens upon success.
    """
    username = request.data.get('username') or request.data.get('phone_number')
    phone_number = request.data.get('phone_number')
    password = request.data.get('password')
    full_name = request.data.get('full_name') or request.data.get('username')
    email = request.data.get('email')

    if not phone_number or not password or not username:
        return Response({"error": "กรุณากรอกข้อมูลที่จำเป็นให้ครบถ้วน (ชื่อผู้ใช้, เบอร์โทร, รหัสผ่าน)"}, status=400)

    from .models import StaffUser, Customer, MembershipLevel
    from rest_framework_simplejwt.tokens import RefreshToken

    # 1. Check if phone number already exists in Customer
    if Customer.objects.filter(phone_number=phone_number).exists():
        return Response({"error": "เบอร์โทรศัพท์นี้ถูกใช้งานในระบบแล้ว"}, status=400)

    # 2. Check if username already exists in StaffUser
    if StaffUser.objects.filter(username=username).exists():
        return Response({"error": "ชื่อผู้ใช้นี้ถูกใช้งานในระบบแล้ว"}, status=400)

    try:
        # 3. Create StaffUser
        user = StaffUser.objects.create_user(
            username=username,
            password=password,
            role='customer',
            full_name=full_name,
            phone=phone_number,
            email=email or ''
        )

        # 4. Fetch default membership level (e.g. General)
        general_level = MembershipLevel.objects.filter(level_name__iexact='General').first() or MembershipLevel.objects.first()

        # 5. Create Customer profile
        customer = Customer.objects.create(
            user=user,
            full_name=full_name,
            phone_number=phone_number,
            email=email or '',
            membership_level=general_level,
            credit_balance=0.00
        )

        # 6. Generate tokens
        refresh = RefreshToken.for_user(user)

        return Response({
            "status": "success",
            "token": str(refresh.access_token),
            "user": {
                "id": user.id,
                "username": user.username,
                "role": user.role,
                "full_name": user.full_name,
                "phone": user.phone,
                "email": user.email,
                "credit_balance": str(customer.credit_balance),
                "membership_level": customer.membership_level.level_name if customer.membership_level else 'General'
            }
        }, status=201)

    except Exception as e:
        return Response({"error": f"เกิดข้อผิดพลาดในการสมัครสมาชิก: {str(e)}"}, status=500)


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def customer_dashboard(request):
    """
    Fetches customer dashboard overview: profile info, wallet, active tier, and bookings history.
    """
    user = request.user
    from .models import Customer, Booking
    from .serializers import BookingSerializer

    customer = get_object_or_404(Customer, user=user)

    # Fetch booking history
    bookings = Booking.objects.filter(customer=customer).order_by('-booking_date', '-booking_time')
    bookings_serialized = BookingSerializer(bookings, many=True, context={'request': request}).data

    return Response({
        "profile": {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "full_name": user.full_name or customer.full_name,
            "phone": user.phone or customer.phone_number,
            "email": user.email or customer.email or '',
        },
        "wallet": {
            "credit_balance": str(customer.credit_balance),
            "membership_level": customer.membership_level.level_name if customer.membership_level else 'General',
            "discount_pct": customer.membership_level.discount_pct if customer.membership_level else 0.00
        },
        "bookings": bookings_serialized
    }, status=200)


@api_view(['PUT'])
@permission_classes([IsAuthenticated])
def customer_profile_update(request):
    """
    Updates the logged-in customer's details and/or password.
    """
    user = request.user
    from .models import Customer

    customer = get_object_or_404(Customer, user=user)

    full_name = request.data.get('full_name')
    email = request.data.get('email')
    password = request.data.get('password')

    if full_name:
        user.full_name = full_name
        customer.full_name = full_name
    if email is not None:
        user.email = email
        customer.email = email

    if password:
        user.set_password(password)

    user.save()
    customer.save()

    return Response({
        "status": "success",
        "message": "อัปเดตข้อมูลโปรไฟล์ส่วนตัวสำเร็จ",
        "profile": {
            "id": user.id,
            "username": user.username,
            "full_name": user.full_name,
            "phone": user.phone,
            "email": user.email,
        }
    }, status=200)
