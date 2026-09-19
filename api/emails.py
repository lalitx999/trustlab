"""
Email notification module for TRUST LAB THAILAND.
Uses Hostinger SMTP (or configured Django Email Backend) to send HTML emails:
1. Payment Confirmation Email (ชำระเงินเรียบร้อย)
2. Inspection Result Email (แจ้งผลการตรวจ - Authentic / Fake / Inconclusive)
3. Certificate Delivery Email (ส่งใบรับรองสินค้าพร้อมลิงก์ PDF & เว็บ)
"""
import os
import threading
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags

PUBLIC_SITE_URL = getattr(settings, 'PUBLIC_SITE_URL', 'https://www.trustlabthailand.com')
DEFAULT_FROM = getattr(settings, 'DEFAULT_FROM_EMAIL', 'TRUST LAB THAILAND <noreply@trustlabthailand.com>')


def send_async_email(subject, recipient_list, html_content):
    """Sends HTML email asynchronously in a separate background thread."""
    if not recipient_list or not any(recipient_list):
        return

    valid_recipients = [r.strip() for r in recipient_list if r and '@' in str(r)]
    if not valid_recipients:
        return

    def _send():
        try:
            text_content = strip_tags(html_content)
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email=DEFAULT_FROM,
                to=valid_recipients
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=True)
            print(f"📧 Email sent successfully to {valid_recipients}: {subject}")
        except Exception as e:
            print(f"⚠️ Failed to send email to {valid_recipients}: {e}")

    thread = threading.Thread(target=_send)
    thread.daemon = True
    thread.start()


def get_base_html_template(title, header_subtitle, body_html):
    """Wraps body content in standard TRUST LAB premium gold/black email layout."""
    return f"""<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  body {{ margin:0; padding:0; background-color:#f3f4f6; font-family:'Helvetica Neue', Helvetica, Arial, sans-serif; -webkit-font-smoothing:antialiased; }}
  table {{ border-collapse:collapse; }}
  .container {{ max-width:600px; margin:0 auto; background-color:#ffffff; border-radius:12px; overflow:hidden; box-shadow:0 4px 15px rgba(0,0,0,0.06); }}
  .header {{ background-color:#111827; padding:32px 24px; text-align:center; }}
  .brand {{ color:#D4AF37; font-size:22px; font-weight:800; letter-spacing:3px; margin:0; text-transform:uppercase; }}
  .slogan {{ color:#9CA3AF; font-size:9px; font-weight:700; letter-spacing:2px; margin-top:4px; text-transform:uppercase; }}
  .subhead {{ color:#E5E7EB; font-size:14px; margin-top:12px; font-weight:500; }}
  .content {{ padding:32px 28px; color:#1F2937; line-height:1.6; font-size:14px; }}
  .card {{ background-color:#F9FAFB; border:1px solid #E5E7EB; border-radius:10px; padding:20px; margin:20px 0; }}
  .label {{ color:#6B7280; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.5px; margin-bottom:2px; }}
  .value {{ color:#111827; font-size:14px; font-weight:700; }}
  .btn {{ display:inline-block; background-color:#111827; color:#ffffff !important; font-size:13px; font-weight:700; text-decoration:none; padding:14px 28px; border-radius:8px; text-transform:uppercase; letter-spacing:1px; margin-top:16px; text-align:center; }}
  .footer {{ background-color:#F9FAFB; border-top:1px solid #E5E7EB; padding:24px; text-align:center; color:#9CA3AF; font-size:11px; line-height:1.5; }}
  .badge-authentic {{ display:inline-block; background-color:#ECFDF5; color:#047857; border:1px solid #A7F3D0; font-size:12px; font-weight:800; padding:6px 14px; border-radius:20px; text-transform:uppercase; }}
  .badge-fake {{ display:inline-block; background-color:#FEF2F2; color:#B91C1C; border:1px solid #FECACA; font-size:12px; font-weight:800; padding:6px 14px; border-radius:20px; text-transform:uppercase; }}
  .badge-inconclusive {{ display:inline-block; background-color:#FFFBEB; color:#B45309; border:1px solid #FDE68A; font-size:12px; font-weight:800; padding:6px 14px; border-radius:20px; text-transform:uppercase; }}
</style>
</head>
<body>
<div style="background-color:#f3f4f6; padding:24px 12px;">
  <div class="container">
    <div class="header">
      <h1 class="brand">TRUST LAB THAILAND</h1>
      <div class="slogan">VERIFY · INSPECT · ASSURE</div>
      <div class="subhead">{header_subtitle}</div>
    </div>
    
    <div class="content">
      {body_html}
    </div>
    
    <div class="footer">
      <strong style="color:#4B5563;">TRUST LAB THAILAND</strong><br>
      สถาบันตรวจวิเคราะห์และออกใบรับรองความแท้สินค้าแบรนด์เนมมาตรฐานสากล<br>
      Siam Square One ชั้น 1 กรุงเทพมหานคร · เว็บไซต์: <a href="{PUBLIC_SITE_URL}" style="color:#111827;text-decoration:underline;">www.trustlabthailand.com</a>
    </div>
  </div>
</div>
</body>
</html>"""


def send_payment_confirmation_email(booking):
    """1. Sends Payment Confirmation Email upon successful payment."""
    if not booking or not booking.customer_email:
        return

    cname = booking.customer_name or 'ลูกค้าผู้มีอุปการคุณ'
    booking_no = getattr(booking, 'booking_id', f"BK-{booking.pk}")
    brand = booking.brand_name or '-'
    model = booking.model or '-'
    total = f"{booking.price_snapshot.get('total', 0):,.2f}" if booking.price_snapshot else '0.00'
    pay_method = {'cash': 'เงินสด', 'transfer': 'โอนเงิน', 'credit_card': 'บัตรเครดิต', 'promptpay': 'PromptPay QR', 'wallet': 'เครดิตสะสม (Wallet)'}.get(booking.payment_method, booking.payment_method)
    receipt_url = f"{PUBLIC_SITE_URL}/authenzs/administator/walk-in?id={booking.pk}"

    body_html = f"""
      <p style="margin-top:0;">เรียน คุณ <strong>{cname}</strong>,</p>
      <p>สถาบัน TRUST LAB THAILAND ได้รับยอดชำระเงินสำหรับบริการตรวจสินค้าเรียบร้อยแล้ว รายละเอียดรายการชำระเงินดังนี้:</p>
      
      <div class="card">
        <table width="100%" cellpadding="6" cellspacing="0">
          <tr>
            <td width="40%"><div class="label">รหัสการจอง (Booking ID)</div><div class="value">{booking_no}</div></td>
            <td width="60%"><div class="label">ยอดชำระทั้งสิ้น</div><div class="value" style="color:#047857;font-size:16px;">฿{total} บาท</div></td>
          </tr>
          <tr>
            <td style="padding-top:12px;"><div class="label">สินค้า</div><div class="value">{brand} {model}</div></td>
            <td style="padding-top:12px;"><div class="label">ช่องชำระเงิน</div><div class="value">{pay_method}</div></td>
          </tr>
        </table>
      </div>

      <p style="font-size:13px;color:#4B5563;">สินค้าของท่านเข้าสู่กระบวนการตรวจโดยผู้เชี่ยวชาญเรียบร้อยแล้ว ท่านสามารถติดตามสถานะการตรวจได้ตลอดเวลาผ่านทางระบบออนไลน์</p>
      
      <div style="text-align:center;margin-top:24px;">
        <a href="{PUBLIC_SITE_URL}" class="btn" target="_blank">เข้าสู่ระบบติดตามงานตรวจ</a>
      </div>
    """

    subject = f"[TRUST LAB] ยืนยันการชำระเงินเรียบร้อยแล้ว - รหัส {booking_no}"
    html = get_base_html_template("ยืนยันการชำระเงิน - TRUST LAB", "ยืนยันการรับชำระเงิน (PAYMENT CONFIRMED)", body_html)
    send_async_email(subject, [booking.customer_email], html)


def send_inspection_result_email(job):
    """2. Sends Inspection Result Email when inspection is completed."""
    if not job or not job.customer or not job.customer.email:
        return

    cname = job.customer.full_name or 'ลูกค้าผู้มีอุปการคุณ'
    job_no = getattr(job, 'job_id', f"JOB-{job.pk}")
    brand = job.brand or '-'
    model = job.model or '-'
    result = job.result or 'authentic'

    badge_html = '<span class="badge-authentic">✓ ตรวจผ่าน - ของแท้ (AUTHENTIC)</span>'
    if result == 'fake':
        badge_html = '<span class="badge-fake">✕ ไม่ผ่านเกณฑ์ - ผลปลอม (UNAUTHENTIC)</span>'
    elif result == 'inconclusive':
        badge_html = '<span class="badge-inconclusive">? ไม่ชัดเจน (INCONCLUSIVE)</span>'

    cert_code = job.tag_code or (getattr(job, 'certificate', None) and job.certificate.cert_code) or '-'
    verify_url = f"{PUBLIC_SITE_URL}/verify?id={cert_code}" if cert_code != '-' else PUBLIC_SITE_URL

    body_html = f"""
      <p style="margin-top:0;">เรียน คุณ <strong>{cname}</strong>,</p>
      <p>ผู้เชี่ยวชาญสถาบัน TRUST LAB THAILAND ได้ทำการตรวจวิเคราะห์สินค้าของท่านเสร็จสิ้นสมบูรณ์แล้ว รายละเอียดผลการตรวจสอบมีดังนี้:</p>
      
      <div class="card" style="text-align:center;padding:24px;">
        <div class="label" style="margin-bottom:8px;">ผลการตรวจวิเคราะห์ (INSPECTION RESULT)</div>
        <div style="margin-bottom:16px;">{badge_html}</div>
        
        <table width="100%" cellpadding="6" cellspacing="0" style="text-align:left;margin-top:12px;border-top:1px solid #E5E7EB;padding-top:12px;">
          <tr>
            <td width="50%"><div class="label">รหัสงานตรวจ (Job ID)</div><div class="value">{job_no}</div></td>
            <td width="50%"><div class="label">สินค้า</div><div class="value">{brand} {model}</div></td>
          </tr>
          <tr>
            <td style="padding-top:10px;"><div class="label">หมายเลขใบรับรอง</div><div class="value">{cert_code}</div></td>
            <td style="padding-top:10px;"><div class="label">ผู้ตรวจวิเคราะห์</div><div class="value">{job.expert_source or 'Specialist Team'}</div></td>
          </tr>
        </table>
      </div>

      <p style="font-size:13px;color:#4B5563;">ท่านสามารถกดปุ่มด้านล่างเพื่อตรวจสอบรายละเอียดใบรับรอง และรายงานจุดตรวจทางออนไลน์ได้ทันที</p>
      
      <div style="text-align:center;margin-top:24px;">
        <a href="{verify_url}" class="btn" target="_blank">ตรวจสอบผลการตรวจออนไลน์</a>
      </div>
    """

    subject = f"[TRUST LAB] แจ้งผลการตรวจสอบสินค้า {job_no} ({brand} {model})"
    html = get_base_html_template("แจ้งผลการตรวจสอบ - TRUST LAB", "แจ้งผลการตรวจสินค้า (INSPECTION COMPLETE)", body_html)
    send_async_email(subject, [job.customer.email], html)


def send_certificate_email(cert, recipient_email=None):
    """3. Sends Certificate Email with PDF download & online verification links."""
    email_to = recipient_email or (cert.job and cert.job.customer and cert.job.customer.email)
    if not email_to:
        return False

    cname = (cert.job and cert.job.customer and cert.job.customer.email) or 'ลูกค้าผู้มีอุปการคุณ'
    cert_code = cert.cert_code
    brand = cert.job.brand if cert.job else '-'
    model = cert.job.model if cert.job else '-'
    status = cert.cert_status
    
    status_text = 'ของแท้ (AUTHENTIC)' if status == 'authentic' else ('ผลไม่ผ่าน (UNAUTHENTIC)' if status in ('fake', 'unauthentic') else status.upper())
    verify_url = f"{PUBLIC_SITE_URL}/verify?id={cert_code}"
    pdf_url = f"{settings.API_BASE_URL}/certificates/{cert_code}/pdf" if hasattr(settings, 'API_BASE_URL') else f"{PUBLIC_SITE_URL}/api/certificates/{cert_code}/pdf"

    body_html = f"""
      <p style="margin-top:0;">เรียน ท่านลูกค้าผู้มีอุปการคุณ,</p>
      <p>สถาบัน TRUST LAB THAILAND ขอนำส่งเอกสารใบรับรองสินค้าอิเล็กทรอนิกส์ (E-Certificate) สำหรับสินค้า <strong>{brand} {model}</strong> รหัสใบรับรอง: <strong>{cert_code}</strong></p>
      
      <div class="card">
        <table width="100%" cellpadding="6" cellspacing="0">
          <tr>
            <td width="50%"><div class="label">หมายเลขใบรับรอง (Certificate ID)</div><div class="value" style="color:#D4AF37;font-size:16px;">{cert_code}</div></td>
            <td width="50%"><div class="label">สถานะการรับรอง</div><div class="value">{status_text}</div></td>
          </tr>
          <tr>
            <td style="padding-top:12px;"><div class="label">ยี่ห้อ / รุ่น</div><div class="value">{brand} {model}</div></td>
            <td style="padding-top:12px;"><div class="label">ระยะเวลาคุ้มครองออนไลน์</div><div class="value">{cert.validity_days} วัน</div></td>
          </tr>
        </table>
      </div>

      <p style="font-size:13px;color:#4B5563;">ท่านสามารถดูรายละเอียดใบรับรองบนเว็บไซต์ หรือดาวน์โหลดไฟล์ PDF ใบรับรองได้จากปุ่มด้านล่าง:</p>
      
      <div style="text-align:center;margin-top:24px;display:flex;gap:12px;justify-content:center;">
        <a href="{verify_url}" class="btn" target="_blank" style="margin-right:8px;">เปิดดูใบเซอร์ออนไลน์</a>
        <a href="{pdf_url}" class="btn" target="_blank" style="background-color:#047857;">ดาวน์โหลดไฟล์ PDF</a>
      </div>
    """

    subject = f"[TRUST LAB] ใบรับรองสินค้าและผลการตรวจ {cert_code} ({brand} {model})"
    html = get_base_html_template("ใบรับรองสินค้า - TRUST LAB", "เอกสารใบรับรองสินค้า (E-CERTIFICATE ISSUED)", body_html)
    send_async_email(subject, [email_to], html)
    return True
