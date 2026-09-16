"""Printable return labels with a Thai font configured on the backend host."""
import io
import os
from xml.sax.saxutils import escape
from django.conf import settings
from rest_framework.exceptions import ValidationError
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image
from reportlab.lib.units import mm


def thai_font():
    path = getattr(settings, 'THAI_FONT_PATH', '')
    if not path or not os.path.isfile(path):
        raise ValidationError('กรุณาตั้ง THAI_FONT_PATH ก่อนพิมพ์ใบปะหน้าภาษาไทย')
    if 'TrustLabThai' not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont('TrustLabThai', path))
    return 'TrustLabThai'


def return_label(job):
    booking = job.booking
    if not booking or booking.delivery_method != 'shipping' or not booking.return_address_detail:
        raise ValidationError('รายการนี้ไม่มีที่อยู่จัดส่งคืน')
    if job.status not in ('completed', 'cancelled') or job.service_package == 'photo_review':
        raise ValidationError('รายการยังไม่พร้อมจัดส่ง')
    output = io.BytesIO()
    doc = SimpleDocTemplate(output, pagesize=(100*mm, 150*mm), leftMargin=8*mm, rightMargin=8*mm, topMargin=8*mm, bottomMargin=8*mm)
    style = ParagraphStyle('Thai', fontName=thai_font(), fontSize=12, leading=19, wordWrap='CJK')
    logo = os.path.join(settings.BASE_DIR, 'assets', 'logo-trust-lab.png')
    lines = [Image(logo, width=45*mm, height=15*mm, kind='proportional'), Spacer(1, 6*mm)]
    address = [f'ส่งคืน / RETURN — JOB {job.pk}', booking.return_address_name, booking.return_phone,
               booking.return_address_detail, f'{booking.return_subdistrict} {booking.return_district}',
               f'{booking.return_province} {booking.return_postal_code}', f'Tracking: {job.tracking_number or "-"}']
    for value in address:
        lines.append(Paragraph(escape(value), style))
        lines.append(Spacer(1, 2*mm))
    doc.build(lines)
    return output.getvalue()
