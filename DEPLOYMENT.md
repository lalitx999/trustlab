# Backend release

Repository นี้เป็น Django backend สำหรับ frontend บน Vercel ใช้ Python 3.14 และ PostgreSQL

ตั้ง .env จาก .env.example แล้ว build image ตรวจ backup, migrate --plan, migrate, collectstatic, check --deploy และ restart app ตามลำดับ ห้ามเปลี่ยน DB credentials หรือ volume ของระบบเดิมโดยไม่มีแผนย้ายข้อมูล

Migration 0015–0018 เพิ่ม workflow, quote snapshots, ledger, cancellations และแพ็กเกจใหม่ ไม่มีการแก้ข้อมูลราคา/อายุใบเซอร์เก่าอัตโนมัติ นโยบายรับชำระเริ่มจาก approved=False ต้องให้ Admin ยืนยัน VAT/ค่าส่งและราคาก่อนเปิดรับงาน

CORS_ALLOWED_ORIGINS ต้องมี frontend Vercel/custom domains ที่อนุญาตจริง; PUBLIC_SITE_URL ใช้สร้างลิงก์ Verify; PROMPTPAY_RECEIVER_ID ต้องเป็นบัญชีรับเงินจริงที่ตรวจแล้ว

Reverse proxy ต้องเปิด /api/, /admin/, /static/ และรูปสินค้า /media/ ตาม config จริง แต่ห้ามเผยแพร่ /media/slips/ หรือ directory listing เอกสาร Label ต้องมี THAI_FONT_PATH (Docker image ติดตั้ง Garuda)

Tests: python manage.py test api.tests_workflows --settings=backend_config.test_settings

Tests นี้ใช้ SQLite แยก ต้องทดสอบ concurrency และ migration กับ PostgreSQL staging ก่อน release จริง ไม่เปิด gateway mock หรือ Corporate Postpaid ในชุดนี้
