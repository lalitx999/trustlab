import qrcode
from io import BytesIO

def crc16(data: str) -> str:
    """Calculates the CRC16-CCITT checksum (polynomial 0x1021, initial 0xFFFF) for EMVCo specifications."""
    crc = 0xFFFF
    for char in data.encode('ascii'):
        crc ^= (char << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return f"{crc:04X}"


def generate_promptpay_payload(phone_or_taxid: str, amount: float = None) -> str:
    """
    Generates a standard PromptPay QR payload according to EMVCo standard.
    phone_or_taxid can be:
    - Mobile phone number (e.g. 0812345678)
    - Tax ID / National ID (13 digits)
    """
    # Clean input: remove dashes and spaces
    target = "".join(filter(str.isdigit, phone_or_taxid))
    
    # Format target according to phone vs tax id
    if len(target) == 13:
        # Tax ID or National ID
        merchant_info = f"0010A0000006770101110213{target}"
    elif len(target) in (9, 10):
        # Mobile Phone
        # Strip leading 0 if any, then pad to 9 digits, prefix with 0066 (Thailand country code)
        if target.startswith('0'):
            target = target[1:]
        phone_formatted = f"0066{target.zfill(9)}"
        merchant_info = f"0010A0000006770101110113{phone_formatted}"
    else:
        # Fallback raw merchant info
        merchant_info = f"0010A00000067701011103{len(target):02d}{target}"

    # Build parts
    parts = []
    parts.append("000201")  # Version
    parts.append("010211" if amount is None else "010212")  # QR Type (11 = Static, 12 = Dynamic with amount)
    parts.append(f"29{len(merchant_info):02d}{merchant_info}")
    parts.append("5303764")  # Currency (764 = THB)
    
    if amount is not None:
        amount_str = f"{amount:.2f}"
        parts.append(f"54{len(amount_str):02d}{amount_str}")
        
    parts.append("5802TH")  # Country Code
    
    # Calculate CRC checksum
    partial_payload = "".join(parts) + "6304"
    checksum = crc16(partial_payload)
    
    return partial_payload + checksum


def generate_qr_code_image(payload: str) -> BytesIO:
    """Generates a PNG image bytes buffer from the PromptPay payload."""
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=4,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    
    img = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    buffer.seek(0)
    return buffer
