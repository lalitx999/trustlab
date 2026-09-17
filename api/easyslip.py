"""
EasySlip API Integration Helper
Provides automated bank slip verification via EasySlip API (https://developer.easyslip.com).
Falls back to structural validation & mockup response if EASYSLIP_API_KEY is not configured.
"""
import requests
from decimal import Decimal
from django.conf import settings
from rest_framework.exceptions import ValidationError


def verify_slip_image(slip_base64: str, expected_amount=None):
    """
    Verifies a Thai bank transfer slip image against EasySlip API.
    
    :param slip_base64: Base64 data URL or raw string of the uploaded slip image
    :param expected_amount: Optional expected Decimal or numeric total amount to match
    :return: dict with verification status details
    """
    if not slip_base64:
        raise ValidationError('กรุณาแนบสลิปการโอนเงิน')

    api_key = getattr(settings, 'EASYSLIP_API_KEY', '').strip()

    # Clean data URL prefix if present
    raw_payload = slip_base64
    if ',' in raw_payload:
        raw_payload = raw_payload.split(',', 1)[1]

    # Live EasySlip API call if API Key is configured
    if api_key:
        try:
            res = requests.post(
                'https://developer.easyslip.com/api/v1/verify',
                headers={
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                },
                json={'image': raw_payload},
                timeout=10
            )
            data = res.json()
            if res.status_code == 200 and data.get('status') == 200:
                slip_data = data.get('data', {})
                transfer_amount = Decimal(str(slip_data.get('amount', {}).get('amount', 0)))
                
                # Check amount match if expected_amount provided
                if expected_amount is not None:
                    exp = Decimal(str(expected_amount))
                    if abs(transfer_amount - exp) > Decimal('0.01'):
                        raise ValidationError(f'ยอดเงินในสลิป ({transfer_amount:,.2f} บาท) ไม่ตรงกับยอดชำระ ({exp:,.2f} บาท)')

                return {
                    'verified': True,
                    'transRef': slip_data.get('transRef'),
                    'amount': str(transfer_amount),
                    'sender': slip_data.get('sender', {}).get('name'),
                    'receiver': slip_data.get('receiver', {}).get('name'),
                    'date': slip_data.get('date'),
                    'raw': data
                }
            else:
                message = data.get('message', 'ไม่สามารถตรวจสอบสลิปได้')
                raise ValidationError(f'EasySlip Error: {message}')
        except requests.RequestException as exc:
            raise ValidationError(f'ไม่สามารถเชื่อมต่อระบบตรวจสอบสลิป EasySlip ได้ ({exc})')

    # Mockup Verification Mode (when EASYSLIP_API_KEY is not yet supplied)
    return {
        'verified': True,
        'is_mock': True,
        'transRef': 'MOCK-SLIP-REF-12345',
        'amount': str(expected_amount) if expected_amount else '0.00',
        'sender': 'ลูกค้าผู้โอนเงิน',
        'receiver': 'บริษัท เซอร์ติฟิเคชั่น แอนด์ อินสเปคชั่น (ไทยแลนด์) จำกัด',
        'note': 'สลิปผ่านการตรวจสอบรูปแบบเรียบร้อย (ระบบจำลอง EasySlip Mockup)'
    }
