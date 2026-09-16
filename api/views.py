import datetime
import uuid
import decimal
from django.shortcuts import get_object_or_404
from django.http import HttpResponse, FileResponse
from django.db.models import Q
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
        jobs = Job.objects.all().order_by('-created_at')
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
        
    status_label = cert.cert_status.upper()
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
    """Simulates sending the certificate to client via LINE / Email and logs it"""
    cert = resolve_certificate(pk)
    method = request.data.get('method', 'email')
    recipient = request.data.get('recipient', '')

    # Dispatch LINE Flex Message if method is line
    if method == 'line' and recipient:
        send_line_flex_message(recipient, cert)
    
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
        "price_silver": 1140,
        "price_platinum": 1020,
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
            "details": "เปิดบริการทุกวัน 10:00 - 20:00 น.",
            "detailsEn": "Open daily 10:00 AM - 8:00 PM",
            "branch_id": b.id,
            "branch_name": b.name,
            "address": "เปิดบริการทุกวัน 10:00 - 20:00 น."
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
        {"slot": "10:30 - 12:00", "available": True, "capacity": 3},
        {"slot": "13:00 - 14:30", "available": True, "capacity": 3},
        {"slot": "14:30 - 16:00", "available": True, "capacity": 3},
        {"slot": "16:00 - 17:30", "available": True, "capacity": 3},
        {"slot": "17:30 - 19:00", "available": True, "capacity": 3}
    ]
    
    return Response(slots, status=status.HTTP_200_OK)


@api_view(['POST'])
@permission_classes([AllowAny])
def public_invoice_preview(request):
    """
    Renders an HTML invoice or cashier slip from a JSON payload POSTed via form.
    Accepts: form field `data` = JSON string with invoice details.
    Returns: HTML page with auto-print trigger.
    """
    import json as _json

    is_slip = request.GET.get('slip') == '1'
    raw = request.POST.get('data') or request.data.get('data') or '{}'
    try:
        d = _json.loads(raw)
    except Exception:
        d = {}

    customer = d.get('customerData', {})
    product = d.get('productData', {})
    items = d.get('items', [])
    total_cost = d.get('totalCost', 0)
    payment_method = d.get('paymentMethod', 'cash')
    payment_status = d.get('paymentStatus', 'paid')
    job_id = d.get('jobId', '')
    queue_no = d.get('queueNo', '')
    expert_note = d.get('expertNote', '')
    express = d.get('expressService', False)

    now = datetime.datetime.now()
    date_str = now.strftime('%d/%m/%Y')
    time_str = now.strftime('%H:%M')

    cname = customer.get('name', '-')
    cphone = customer.get('phone', '-')
    cmembership = customer.get('type', 'General')
    pbrand = product.get('brand', '-')
    pmodel = product.get('model', '-')
    pcategory = product.get('category', '-')
    pcolor = product.get('color', '-')
    pserial = product.get('serialNumber', '-')

    payment_label = {'cash': 'เงินสด', 'transfer': 'โอนเงิน', 'card': 'บัตรเครดิต'}.get(payment_method, payment_method)
    status_label = '✓ ชำระแล้ว' if payment_status == 'paid' else '⏳ ค้างชำระ'
    status_color = '#16a34a' if payment_status == 'paid' else '#dc2626'

    items_html = ''
    for item in items:
        if not item:
            continue
        name = item.get('name', '')
        amount = item.get('amount', 0)
        color = '#16a34a' if amount < 0 else '#111827'
        sign = '' if amount < 0 else ''
        items_html += f'''
        <tr>
          <td style="padding:6px 0;font-size:12px;color:#374151;">{name}</td>
          <td style="padding:6px 0;font-size:12px;color:{color};text-align:right;font-weight:700;">{sign}฿{abs(amount):,.0f}</td>
        </tr>'''

    ref_no = f"TL-{now.strftime('%Y%m%d')}-{job_id or queue_no or '????'}"

    if is_slip:
        # ── CASHIER SLIP (narrow 80mm style) ─────────────────────────────
        html = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<title>สลิปใบเสร็จ - TrustLab</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@400;600;700&display=swap');
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'IBM Plex Sans Thai',sans-serif; font-size:11px; background:#fff; width:302px; margin:0 auto; padding:12px; color:#111; }}
  .center {{ text-align:center; }}
  .logo {{ font-size:18px; font-weight:700; letter-spacing:3px; }}
  .sep {{ border-top:1px dashed #aaa; margin:8px 0; }}
  .row {{ display:flex; justify-content:space-between; margin:3px 0; }}
  .label {{ color:#555; }}
  .total-row {{ display:flex; justify-content:space-between; margin:4px 0; font-size:15px; font-weight:700; border-top:1px solid #000; padding-top:6px; margin-top:6px; }}
  .status {{ font-size:11px; font-weight:700; color:{status_color}; }}
  .footer {{ font-size:9px; color:#888; text-align:center; margin-top:10px; }}
  @media print {{ @page {{ margin:0; size:80mm auto; }} body {{ padding:4px; }} }}
</style>
</head>
<body>
<div class="center">
  <div class="logo">TRUSTLAB</div>
  <div style="font-size:9px;color:#888;">ใบเสร็จรับเงิน / Receipt</div>
  <div style="font-size:9px;color:#888;">{date_str} {time_str}</div>
</div>
<div class="sep"></div>
<div class="row"><span class="label">เลขที่:</span><span style="font-weight:700">{ref_no}</span></div>
<div class="row"><span class="label">คิวที่:</span><span style="font-weight:700">{queue_no or '-'}</span></div>
<div class="row"><span class="label">ลูกค้า:</span><span>{cname}</span></div>
<div class="row"><span class="label">ระดับ:</span><span>{cmembership}</span></div>
<div class="sep"></div>
<div class="row"><span class="label">สินค้า:</span><span style="font-weight:700">{pbrand} {pmodel}</span></div>
<div class="row"><span class="label">ประเภท:</span><span>{pcategory}</span></div>
{'<div class="row"><span class="label">S/N:</span><span>' + pserial + '</span></div>' if pserial and pserial != '-' else ''}
<div class="sep"></div>
{''.join([f'<div class="row"><span>{i.get("name","")}</span><span style="font-weight:700">฿{abs(i.get("amount",0)):,.0f}</span></div>' for i in items if i])}
<div class="total-row"><span>รวมทั้งสิ้น</span><span>฿{total_cost:,.0f}</span></div>
<div class="row"><span class="label">ชำระโดย:</span><span>{payment_label}</span></div>
<div class="row"><span class="label">สถานะ:</span><span class="status">{status_label}</span></div>
{'<div class="sep"></div><div style="font-size:10px;color:#555;">หมายเหตุ: ' + expert_note + '</div>' if expert_note else ''}
<div class="sep"></div>
<div class="footer">ขอบคุณที่ใช้บริการ TrustLab<br>trustlabthailand.com | @TrustLab</div>
<script>window.onload = () => setTimeout(() => window.print(), 400);</script>
</body>
</html>"""
    else:
        # ── FULL INVOICE (A4) ─────────────────────────────────────────────
        html = f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<title>ใบแจ้งหนี้ {ref_no} - TrustLab</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+Thai:wght@300;400;600;700;800&display=swap');
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ font-family:'IBM Plex Sans Thai',sans-serif; background:#f5f5f5; color:#111827; }}
  .page {{ background:#fff; max-width:794px; margin:0 auto; padding:56px 64px; min-height:1123px; }}
  .header {{ display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:40px; }}
  .brand {{ font-size:26px; font-weight:800; letter-spacing:4px; }}
  .brand-sub {{ font-size:9px; color:#9ca3af; letter-spacing:2px; margin-top:2px; }}
  .invoice-label {{ text-align:right; }}
  .invoice-label h2 {{ font-size:20px; font-weight:800; color:#111; letter-spacing:2px; }}
  .invoice-label .ref {{ font-size:11px; color:#6b7280; margin-top:4px; }}
  .meta-grid {{ display:grid; grid-template-columns:1fr 1fr; gap:24px; margin-bottom:32px; padding:24px; background:#f9fafb; border-radius:12px; border:1px solid #e5e7eb; }}
  .meta-block .meta-title {{ font-size:9px; font-weight:700; color:#9ca3af; letter-spacing:1.5px; text-transform:uppercase; margin-bottom:8px; }}
  .meta-block p {{ font-size:12px; color:#374151; line-height:1.7; }}
  .meta-block p strong {{ color:#111827; font-weight:700; }}
  table {{ width:100%; border-collapse:collapse; margin-bottom:20px; }}
  thead tr {{ background:#111827; color:#fff; }}
  thead th {{ padding:12px 16px; font-size:10px; font-weight:700; letter-spacing:1px; text-transform:uppercase; }}
  thead th:last-child {{ text-align:right; }}
  tbody tr {{ border-bottom:1px solid #f3f4f6; }}
  tbody td {{ padding:12px 16px; font-size:12px; color:#374151; }}
  tbody td:last-child {{ text-align:right; font-weight:700; color:#111827; }}
  .total-block {{ display:flex; justify-content:flex-end; }}
  .total-table {{ width:280px; }}
  .total-table td {{ padding:6px 0; font-size:12px; color:#6b7280; }}
  .total-table td:last-child {{ text-align:right; color:#111827; font-weight:600; }}
  .total-table .grand {{ font-size:16px; font-weight:800; color:#111827; border-top:2px solid #111827; padding-top:10px; }}
  .status-badge {{ display:inline-block; padding:4px 12px; border-radius:999px; font-size:10px; font-weight:700; letter-spacing:1px; background:{'#dcfce7' if payment_status == 'paid' else '#fee2e2'}; color:{status_color}; }}
  .note-block {{ margin-top:28px; padding:16px 20px; background:#fffbeb; border-left:3px solid #f59e0b; border-radius:0 8px 8px 0; font-size:11px; color:#92400e; }}
  .footer-bar {{ margin-top:40px; padding-top:20px; border-top:1px solid #e5e7eb; display:flex; justify-content:space-between; align-items:center; }}
  .footer-bar .company {{ font-size:10px; color:#9ca3af; }}
  @media print {{
    @page {{ margin:0; size:A4; }}
    body {{ background:#fff; }}
    .page {{ padding:40px 48px; min-height:unset; box-shadow:none; }}
  }}
</style>
</head>
<body>
<div class="page">
  <div class="header">
    <div>
      <div class="brand">TRUSTLAB</div>
      <div class="brand-sub">LUXURY AUTHENTICATION THAILAND</div>
    </div>
    <div class="invoice-label">
      <h2>{'ใบเสร็จรับเงิน' if payment_status == 'paid' else 'ใบแจ้งหนี้'}</h2>
      <div class="ref">{ref_no}</div>
      <div class="ref" style="margin-top:4px;">{date_str} · {time_str}</div>
    </div>
  </div>

  <div class="meta-grid">
    <div class="meta-block">
      <div class="meta-title">ข้อมูลลูกค้า</div>
      <p><strong>{cname}</strong></p>
      <p>โทร: {cphone}</p>
      <p>ระดับสมาชิก: {cmembership}</p>
    </div>
    <div class="meta-block">
      <div class="meta-title">ข้อมูลสินค้า</div>
      <p><strong>{pbrand}</strong> {pmodel}</p>
      <p>ประเภท: {pcategory} {'· สี: ' + pcolor if pcolor and pcolor != '-' else ''}</p>
      {'<p>Serial: ' + pserial + '</p>' if pserial and pserial != '-' else ''}
      {'<p style="color:#f59e0b;font-weight:700;">⚡ Express Service</p>' if express else ''}
    </div>
  </div>

  <table>
    <thead>
      <tr>
        <th style="text-align:left">รายการบริการ</th>
        <th>จำนวนเงิน</th>
      </tr>
    </thead>
    <tbody>{items_html if items_html else '<tr><td colspan="2" style="text-align:center;color:#9ca3af;padding:20px;">ไม่มีรายการ</td></tr>'}
    </tbody>
  </table>

  <div class="total-block">
    <table class="total-table">
      <tr>
        <td>วิธีชำระ</td>
        <td>{payment_label}</td>
      </tr>
      <tr>
        <td>สถานะ</td>
        <td><span class="status-badge">{status_label}</span></td>
      </tr>
      <tr class="grand">
        <td><strong>รวมทั้งสิ้น</strong></td>
        <td><strong>฿{total_cost:,.0f}</strong></td>
      </tr>
    </table>
  </div>

  {'<div class="note-block"><strong>หมายเหตุจากผู้เชี่ยวชาญ:</strong><br>' + expert_note + '</div>' if expert_note else ''}

  <div class="footer-bar">
    <div class="company">
      TrustLab Thailand · trustlabthailand.com<br>
      โทร 02-XXX-XXXX · อีเมล info@trustlabthailand.com
    </div>
    <div style="font-size:10px;color:#9ca3af;">
      {'คิวที่: ' + str(queue_no) if queue_no else ''}<br>
      เอกสารนี้ออกโดยระบบ TrustLab POS
    </div>
  </div>
</div>
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
