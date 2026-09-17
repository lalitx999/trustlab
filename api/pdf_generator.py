import os
import datetime
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
import qrcode
from django.conf import settings
from django.utils import timezone

# We will use Helvetica and Helvetica-Bold for professional look
FONT_REGULAR = "Helvetica"
FONT_BOLD = "Helvetica-Bold"

def draw_safe_image(c, bp, x, y, w, h):
    """Safely draws a booking photo image or renders a clean placeholder box if missing."""
    if bp and bp.photo and os.path.exists(bp.photo.path):
        try:
            c.drawImage(bp.photo.path, x, y, width=w, height=h, preserveAspectRatio=True)
            # Add subtle image border
            c.saveState()
            c.setStrokeColorRGB(0.88, 0.88, 0.88)
            c.setLineWidth(0.5)
            c.rect(x, y, w, h, fill=False, stroke=True)
            c.restoreState()
            return True
        except Exception:
            pass
            
    # Clean luxury placeholder
    c.saveState()
    c.setFillColorRGB(0.97, 0.97, 0.97)
    c.rect(x, y, w, h, fill=True, stroke=False)
    c.setFillColorRGB(0.65, 0.65, 0.65)
    c.setFont(FONT_REGULAR, 7)
    c.drawCentredString(x + w/2.0, y + h/2.0 - 2, "NO IMAGE")
    c.restoreState()
    return False


def generate_certificate_pdf(certificate) -> BytesIO:
    """
    Generates a beautifully formatted, premium A4 PDF certificate matching the mockup.
    Includes custom layout, dynamic image boxes, vector icons, and verification QR code.
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4  # 595.27 x 841.89 points
    
    # 1. Outer Border & Base Styling
    c.saveState()
    # Light gold/gray subtle outer borders
    c.setStrokeColorRGB(0.85, 0.85, 0.85)
    c.setLineWidth(0.5)
    c.rect(20, 20, width - 40, height - 40, fill=False, stroke=True)
    c.restoreState()

    # 1.5 Background Watermark Pattern (Certificate ID grid)
    c.saveState()
    c.setFillColorRGB(0.975, 0.975, 0.975)  # Extremely light soft gray
    c.setFont(FONT_BOLD, 7)
    c.rotate(25)
    watermark_text = certificate.cert_code or "TRUST LAB"
    for y in range(-300, 1000, 32):
        for x in range(-300, 1000, 110):
            c.drawString(x, y, watermark_text)
    c.restoreState()

    # Giant Status Watermark for Non-Authentic states (Revoked or Expired)
    if certificate.cert_status == 'revoked':
        c.saveState()
        c.setFillColorRGB(0.99, 0.93, 0.93)  # Soft light red
        c.setFont(FONT_BOLD, 42)
        c.translate(width / 2.0, height / 2.0)
        c.rotate(35)
        c.drawCentredString(0, 0, "REVOKED / CANCELLED")
        c.restoreState()
    elif certificate.cert_status == 'expired' or (certificate.expires_at and timezone.now() >= certificate.expires_at):
        c.saveState()
        c.setFillColorRGB(0.99, 0.96, 0.91)  # Soft light orange/yellow
        c.setFont(FONT_BOLD, 42)
        c.translate(width / 2.0, height / 2.0)
        c.rotate(35)
        c.drawCentredString(0, 0, "EXPIRED")
        c.restoreState()
    
    # 2. Header Logo and Slogan
    c.saveState()
    c.setFont(FONT_BOLD, 18)
    c.setFillColorRGB(0.08, 0.08, 0.08)
    logo_path = os.path.join(settings.BASE_DIR, 'assets', 'logo-trust-lab.png')
    if os.path.exists(logo_path):
        c.drawImage(logo_path, width / 2 - 32, height - 74, width=64, height=54, preserveAspectRatio=True, anchor='c', mask='auto')
    
    c.setFont(FONT_REGULAR, 6)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(width / 2.0, height - 82, "VERIFY   ·   INSPECT   ·   ASSURE")
    
    c.setStrokeColorRGB(0.9, 0.9, 0.9)
    c.setLineWidth(0.5)
    c.line(40, height - 92, width - 40, height - 92)
    c.restoreState()
    
    # 3. Main Title
    c.saveState()
    c.setFont(FONT_BOLD, 22)
    c.setFillColorRGB(0.08, 0.08, 0.08)
    c.drawCentredString(width / 2.0, height - 122, "CERTIFICATE")
    
    c.setFont(FONT_BOLD, 14)
    c.setFillColorRGB(0.08, 0.08, 0.08)
    c.drawCentredString(width / 2.0, height - 138, "OF AUTHENTICITY")
    
    c.setFont(FONT_BOLD, 5.5)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawCentredString(width / 2.0, height - 148, "PROFESSIONAL LUXURY AUTHENTICATION LABORATORY")
    c.restoreState()
    
    # Retrieve Selected Photos
    selected_ids = certificate.selected_photos or []
    bps = []
    if certificate.job.booking:
        bps = list(certificate.job.booking.photos.all())
        
    if not selected_ids:
        # Fallback to first 3 staff-sourced photos
        fallback = [bp for bp in bps if bp.photo_type == 'staff'][:3]
        selected_ids = [bp.id for bp in fallback]
        
    selected_bps = []
    bps_map = {bp.id: bp for bp in bps}
    for pid in selected_ids:
        if pid in bps_map:
            selected_bps.append(bps_map[pid])
            
    main_bp = selected_bps[0] if len(selected_bps) > 0 else None
    sub_bp1 = selected_bps[1] if len(selected_bps) > 1 else None
    sub_bp2 = selected_bps[2] if len(selected_bps) > 2 else None
    
    # 4. Left Column: Result & Product Images
    job = certificate.job
    is_authentic = (getattr(job, 'result', '') == 'authentic')
    
    c.saveState()
    if is_authentic:
        c.setFillColorRGB(0.06, 0.46, 0.25)  # Green color
        c.circle(50, height - 175, 8, fill=True, stroke=False)
        c.setStrokeColorRGB(1.0, 1.0, 1.0)
        c.setLineWidth(1.5)
        p = c.beginPath()
        p.moveTo(47, height - 176)
        p.lineTo(49.5, height - 179.5)
        p.lineTo(54, height - 172.5)
        c.drawPath(p, fill=False, stroke=True)
        
        c.setFont(FONT_BOLD, 12.5)
        c.drawString(64, height - 179, "AUTHENTIC")
    else:
        c.setFillColorRGB(0.85, 0.15, 0.15)  # Red color
        c.circle(50, height - 175, 8, fill=True, stroke=False)
        c.setStrokeColorRGB(1.0, 1.0, 1.0)
        c.setLineWidth(1.5)
        c.line(46, height - 179, 54, height - 171)
        c.line(46, height - 171, 54, height - 179)
        
        c.setFont(FONT_BOLD, 12.5)
        c.drawString(64, height - 179, "UNAUTHENTIC / FAIL")
    c.restoreState()
    
    # Large Product Main Image Box
    draw_safe_image(c, main_bp, 40, height - 370, 240, 180)
    
    # Stamp fail overlay across image if unauthentic
    if not is_authentic:
        c.saveState()
        c.setFillColorRGB(0.85, 0.15, 0.15)
        c.setFillAlpha(0.2)
        c.setFont(FONT_BOLD, 28)
        c.translate(160, height - 280)
        c.rotate(-25)
        c.drawCentredString(0, 0, "UNAUTHENTIC")
        c.restoreState()
    
    # Two Thumbnail Sub Images Box
    draw_safe_image(c, sub_bp1, 40, height - 465, 115, 85)
    draw_safe_image(c, sub_bp2, 165, height - 465, 115, 85)
    
    # 5. Right Column: Specifications and QR Code
    cat_friendly = {
        'Bag': 'Luxury Handbag',
        'Watch': 'Luxury Timepiece',
        'Clothes': 'Luxury Garment',
        'Shoes': 'Luxury Footwear',
        'Accessories': 'Luxury Accessories'
    }.get(job.category, job.category or "Luxury Handbag")
    
    # Format issue date
    issue_date = timezone.localtime(certificate.created_at).strftime("%d %b %Y").upper()
    serial_val = getattr(job, 'serial_number', '') or getattr(certificate, 'serial_number', '') or '-'
    
    # Draw Specifications Table
    start_y = height - 175
    line_h = 24
    fields = [
        ("CERTIFICATE ID", certificate.cert_code or f"TL-{certificate.id}"),
        ("BRAND", job.brand.upper()),
        ("MODEL", job.model.upper()),
        ("SERIAL NUMBER", str(serial_val).upper()),
        ("CATEGORY", cat_friendly.upper()),
        ("INSPECTION DATE", issue_date)
    ]
    
    c.saveState()
    for idx, (lbl, val) in enumerate(fields):
        y = start_y - (idx * line_h)
        
        # Label style
        c.setFont(FONT_BOLD, 6)
        c.setFillColorRGB(0.55, 0.55, 0.55)
        c.drawString(305, y, lbl)
        
        # Value style
        c.setFont(FONT_BOLD, 8.5)
        c.setFillColorRGB(0.08, 0.08, 0.08)
        c.drawString(305, y - 9, val)
        
        # Bottom divider line
        c.setStrokeColorRGB(0.92, 0.92, 0.92)
        c.setLineWidth(0.5)
        c.line(305, y - 12, width - 40, y - 12)
    c.restoreState()
    
    # "VERIFY ONLINE" Block
    verify_y = height - 465
    verify_h = 135
    verify_w = width - 40 - 305  # 250 points
    
    c.saveState()
    # Draw subtle background box
    c.setFillColorRGB(0.97, 0.97, 0.97)
    c.rect(305, verify_y, verify_w, verify_h, fill=True, stroke=False)
    
    # Generate Verification QR Code in memory
    qr = qrcode.QRCode(version=1, box_size=5, border=1)
    verify_url = f"{settings.PUBLIC_SITE_URL}/verify?id={certificate.cert_code or certificate.id}"
    qr.add_data(verify_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    
    qr_buffer = BytesIO()
    qr_img.save(qr_buffer, format="PNG")
    qr_buffer.seek(0)
    
    # Draw QR code image inside box
    qr_reader = ImageReader(qr_buffer)
    c.drawImage(qr_reader, 315, verify_y + 12, width=82, height=82)
    
    # Text side labels inside block
    c.setFont(FONT_BOLD, 8.5)
    c.setFillColorRGB(0.08, 0.08, 0.08)
    c.drawString(410, verify_y + 88, "VERIFY ONLINE")
    
    c.setFont(FONT_REGULAR, 5.5)
    c.setFillColorRGB(0.45, 0.45, 0.45)
    c.drawString(410, verify_y + 78, "SCAN QR CODE TO VERIFY")
    
    c.drawString(410, verify_y + 55, "OR VISIT")
    c.setFont(FONT_BOLD, 7)
    c.setFillColorRGB(0.08, 0.08, 0.08)
    c.drawString(410, verify_y + 46, "trustlabthailand.com/verify")
    
    # Certificate ID pill (solid black background with white text)
    c.setFillColorRGB(0.08, 0.08, 0.08)
    c.rect(410, verify_y + 18, 125, 18, fill=True, stroke=False)
    
    c.setFont(FONT_BOLD, 7.5)
    c.setFillColorRGB(1.0, 1.0, 1.0)
    c.drawCentredString(410 + 62.5, verify_y + 24, certificate.cert_code or f"TL-{certificate.id}")
    c.restoreState()
    
    # 6. Validity Cards Section
    cards_y = height - 565
    c.saveState()
    
    # Determine validity duration based on job service_package (15 days vs 90 days / 3 months)
    pkg = getattr(job, 'service_package', '') or ''
    val_days = getattr(certificate, 'validity_days', 90) or 90
    if val_days == 90 or (not certificate.validity_days and '15' not in pkg):
        val_title = "VALID FOR 3 MONTHS"
        val_sub = "This certificate is valid for 3 months from the inspection date."
    else:
        val_title = f"VALID FOR {val_days} DAYS"
        val_sub = f"This certificate is valid for {val_days} days from the inspection date."

    expire_dt = timezone.localtime(certificate.expires_at).date() if certificate.expires_at else timezone.localtime(certificate.created_at).date() + datetime.timedelta(days=val_days)
    expiry_date_str = expire_dt.strftime("%d %b %Y").upper()

    # Left Card: Validity Duration
    c.setFillColorRGB(0.98, 0.98, 0.98)
    c.rect(40, cards_y, 240, 68, fill=True, stroke=False)
    c.setStrokeColorRGB(0.9, 0.9, 0.9)
    c.setLineWidth(0.5)
    c.rect(40, cards_y, 240, 68, fill=False, stroke=True)
    
    c.setFont(FONT_BOLD, 8.5)
    c.setFillColorRGB(0.08, 0.08, 0.08)
    c.drawString(55, cards_y + 44, val_title)
    c.setFont(FONT_REGULAR, 6.5)
    c.setFillColorRGB(0.45, 0.45, 0.45)
    c.drawString(55, cards_y + 26, val_sub)
    
    # Right Card: Valid Until Date
    c.setFillColorRGB(0.98, 0.98, 0.98)
    c.rect(315, cards_y, 240, 68, fill=True, stroke=False)
    c.setStrokeColorRGB(0.9, 0.9, 0.9)
    c.setLineWidth(0.5)
    c.rect(315, cards_y, 240, 68, fill=False, stroke=True)
    
    c.setFont(FONT_BOLD, 6.5)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(330, cards_y + 48, "VALID UNTIL")
    c.setFont(FONT_BOLD, 13.5)
    c.setFillColorRGB(0.08, 0.08, 0.08)
    c.drawString(330, cards_y + 30, expiry_date_str)
    c.setFont(FONT_REGULAR, 5.5)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(330, cards_y + 17, "(ONLINE VERIFICATION)")
    c.restoreState()
    
    # 7. Important Notice & Footer Notes
    notice_y = cards_y - 20
    c.saveState()
    c.setFont(FONT_BOLD, 6.5)
    c.setFillColorRGB(0.15, 0.15, 0.15)
    c.drawString(40, notice_y, "IMPORTANT NOTICE")
    
    c.setFont(FONT_REGULAR, 5.5)
    c.setFillColorRGB(0.45, 0.45, 0.45)
    bullets = [
        "This result is based on visual and laboratory inspection using current data and available reference standards.",
        "Results do not guarantee identification of all modifications, repairs, or replaced parts.",
        "This certificate confirms the authenticity of the item examined by TRUST LAB THAILAND based on the standard inspection process.",
        "This certificate does not represent a guarantee of the item or any affiliated brand."
    ]
    for idx, bullet in enumerate(bullets):
        c.drawString(40, notice_y - 10 - (idx * 9), f"•  {bullet}")
        
    # Footer Links (Clickable URL hotspots)
    c.setFont(FONT_REGULAR, 6)
    c.setFillColorRGB(0.2, 0.2, 0.2)
    
    c.drawString(40, 36, "www.trustlabthailand.com")
    c.linkURL("https://trustlabthailand.com", (40, 30, 170, 46), relative=0)
    
    c.drawString(200, 36, "IG : trustlab.thailand")
    c.linkURL("https://instagram.com/trustlab.thailand", (200, 30, 310, 46), relative=0)
    
    c.drawString(340, 36, "Line: @trustlab")
    c.linkURL("https://line.me/R/ti/p/@trustlab", (340, 30, 430, 46), relative=0)
    
    # Draw small bottom right QR code
    c.setFont(FONT_REGULAR, 5.5)
    c.drawRightString(width - 80, 42, "SCAN TO VERIFY")
    c.drawImage(qr_reader, width - 70, 32, width=30, height=30)
    
    
    # 9. Watermark overlay if revoked
    if certificate.cert_status == 'revoked':
        c.saveState()
        c.setFillColorRGB(0.85, 0.15, 0.15)
        c.setFillAlpha(0.18)
        c.setFont("Helvetica-Bold", 54)
        c.translate(width / 2.0, height / 2.0)
        c.rotate(35)
        c.drawCentredString(0, 30, "REVOKED / CANCELLED")
        c.drawCentredString(0, -30, "ใบรับรองนี้ถูกยกเลิกแล้ว")
        c.restoreState()
        
    c.showPage()
    c.save()
    
    buffer.seek(0)
    return buffer


def generate_daily_report_pdf(stats, date_str) -> BytesIO:
    """
    Generates a beautifully structured daily summary report PDF using ReportLab A4.
    """
    buffer = BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    # Border
    c.saveState()
    c.setStrokeColorRGB(0.85, 0.85, 0.85)
    c.setLineWidth(0.5)
    c.rect(25, 25, width - 50, height - 50, fill=False, stroke=True)
    c.restoreState()
    
    # Header
    c.saveState()
    c.setFont(FONT_BOLD, 18)
    c.setFillColorRGB(0.08, 0.08, 0.08)
    c.drawCentredString(width / 2.0, height - 70, "TRUST LAB THAILAND")
    
    c.setFont(FONT_REGULAR, 8)
    c.setFillColorRGB(0.4, 0.4, 0.4)
    c.drawCentredString(width / 2.0, height - 85, "DAILY REVENUE & PERFORMANCE REPORT")
    c.restoreState()
    
    # Date
    c.saveState()
    c.setFont(FONT_BOLD, 10)
    c.setFillColorRGB(0.1, 0.1, 0.1)
    c.drawString(45, height - 120, f"DATE: {date_str}")
    
    # Draw line separator
    c.setStrokeColorRGB(0.8, 0.8, 0.8)
    c.setLineWidth(1)
    c.line(45, height - 130, width - 45, height - 130)
    c.restoreState()
    
    # Section 1: Performance Statistics
    c.saveState()
    c.setFont(FONT_BOLD, 12)
    c.setFillColorRGB(0.08, 0.08, 0.08)
    c.drawString(45, height - 160, "1. WORKLOAD & INSPECTION METRICS")
    c.restoreState()
    
    metrics = [
        ("Total Jobs Received", stats.get("total_jobs", 0), "Items"),
        ("Completed Inspections", stats.get("completed_jobs", 0), "Items"),
        ("Authentic Results", stats.get("authentic_jobs", 0), "Items"),
        ("Counterfeit Results", stats.get("fake_jobs", 0), "Items"),
        ("Inconclusive Results", stats.get("inconclusive_jobs", 0), "Items"),
    ]
    
    y = height - 190
    c.saveState()
    c.setFont(FONT_REGULAR, 10)
    for desc, val, unit in metrics:
        c.setFillColorRGB(0.2, 0.2, 0.2)
        c.drawString(50, y, desc)
        c.drawRightString(width - 55, y, f"{val} {unit}")
        # Draw light dotted line
        c.setStrokeColorRGB(0.9, 0.9, 0.9)
        c.setLineWidth(0.5)
        c.line(50, y - 8, width - 50, y - 8)
        y -= 25
    c.restoreState()
    
    # Section 2: Revenue breakdown
    y -= 15
    c.saveState()
    c.setFont(FONT_BOLD, 12)
    c.setFillColorRGB(0.08, 0.08, 0.08)
    c.drawString(45, y, "2. REVENUE BREAKDOWN BY PAYMENT METHOD")
    c.restoreState()
    
    y -= 30
    payments = [
        ("Cash", stats.get("revenue_cash", 0.00)),
        ("Bank Transfer", stats.get("revenue_transfer", 0.00)),
        ("Credit Card", stats.get("revenue_card", 0.00)),
        ("PromptPay QR", stats.get("revenue_promptpay", 0.00)),
        ("Member Credit", stats.get("revenue_member", 0.00)),
        ("Refunds Paid Out", -stats.get("refunds", 0.00)),
    ]
    
    c.saveState()
    c.setFont(FONT_REGULAR, 10)
    for method, amt in payments:
        c.setFillColorRGB(0.2, 0.2, 0.2)
        c.drawString(50, y, method)
        c.drawRightString(width - 55, y, f"THB {amt:,.2f}")
        c.setStrokeColorRGB(0.9, 0.9, 0.9)
        c.setLineWidth(0.5)
        c.line(50, y - 8, width - 50, y - 8)
        y -= 25
    
    # Draw solid total revenue line
    total_rev = stats.get("total_revenue", 0.00)
    c.setFont(FONT_BOLD, 11)
    c.setFillColorRGB(0.0, 0.0, 0.0)
    c.drawString(50, y, "Net Service Payments")
    c.drawRightString(width - 55, y, f"THB {total_rev:,.2f}")
    c.setStrokeColorRGB(0.1, 0.1, 0.1)
    c.setLineWidth(1)
    c.line(45, y - 8, width - 45, y - 8)
    y -= 40
    c.restoreState()
    
    # Section 3: Summary and Authorization
    c.saveState()
    c.setFont(FONT_REGULAR, 8)
    c.setFillColorRGB(0.5, 0.5, 0.5)
    c.drawString(45, y, "This daily report summary was auto-compiled from SQL database transactions.")
    c.drawRightString(width - 45, y, f"Generated At: {datetime.datetime.now().strftime('%d/%m/%Y %H:%M')}")
    
    # Footer signatures
    y -= 80
    c.setStrokeColorRGB(0.7, 0.7, 0.7)
    c.setLineWidth(0.5)
    c.line(45, y, 195, y)
    c.line(width - 195, y, width - 45, y)
    
    c.setFont(FONT_REGULAR, 9)
    c.setFillColorRGB(0.3, 0.3, 0.3)
    c.drawCentredString(120, y - 15, "Reported By (Staff)")
    c.drawCentredString(width - 120, y - 15, "Verified By (Manager)")
    c.restoreState()
    
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer
