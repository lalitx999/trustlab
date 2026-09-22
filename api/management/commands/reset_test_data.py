from django.core.management.base import BaseCommand
from django.db import transaction
from api.models import (
    Booking, BookingPhoto, Job, Certificate, CertificateSendLog,
    TopupRequest, CreditEntry, CancellationRequest, WorkflowEvent, StaffNotification,
    Customer, Contact, Partner, StaffUser, Brand, BrandPricing, ServicePackage, MembershipLevel
)


class Command(BaseCommand):
    help = 'Clears all transactional data (Bookings, Jobs, Certificates, Test Customers) while preserving Brands, Pricing, Packages, and Staff accounts.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--yes',
            action='store_true',
            help='Skip confirmation prompt and execute immediately',
        )

    def handle(self, *args, **options):
        if not options['yes']:
            confirm = input("⚠️ คุณแน่ใจหรือไม่ว่าต้องการเคลียร์ประวัติงาน จอง และลูกค้าทดสอบทั้งหมด? (พิมพ์ 'yes' เพื่อยืนยัน): ")
            if confirm.strip().lower() != 'yes':
                self.stdout.write(self.style.WARNING("ยกเลิกการทำงาน ข้อมูลไม่มีการเปลี่ยนแปลง"))
                return

        self.stdout.write(self.style.NOTICE("กำลังเริ่มเคลียร์ข้อมูลประวัติงานและธุรกรรม..."))

        with transaction.atomic():
            CertificateSendLog.objects.all().delete()
            Certificate.objects.all().delete()
            Job.objects.all().delete()
            BookingPhoto.objects.all().delete()
            CancellationRequest.objects.all().delete()
            WorkflowEvent.objects.all().delete()
            StaffNotification.objects.all().delete()
            CreditEntry.objects.all().delete()
            TopupRequest.objects.all().delete()
            Booking.objects.all().delete()
            Contact.objects.all().delete()
            Partner.objects.all().delete()

            # Delete customer-role user accounts and customers
            customer_users = StaffUser.objects.filter(role='customer')
            deleted_cust_users = customer_users.count()
            customer_users.delete()
            Customer.objects.all().delete()

        self.stdout.write(self.style.SUCCESS("=" * 50))
        self.stdout.write(self.style.SUCCESS("✅ เคลียร์ข้อมูลธุรกรรมสำเร็จเรียบร้อยแล้ว!"))
        self.stdout.write(self.style.SUCCESS("=" * 50))
        self.stdout.write(f"- Bookings: {Booking.objects.count()}")
        self.stdout.write(f"- Jobs: {Job.objects.count()}")
        self.stdout.write(f"- Certificates: {Certificate.objects.count()}")
        self.stdout.write(f"- Customers: {Customer.objects.count()}")
        self.stdout.write(self.style.NOTICE(f"\n Master Data ยังคงอยู่ครบถ้วน:"))
        self.stdout.write(f"✓ Brands: {Brand.objects.count()} แบรนด์")
        self.stdout.write(f"✓ BrandPricing: {BrandPricing.objects.count()} รายการ")
        self.stdout.write(f"✓ ServicePackages: {ServicePackage.objects.count()} แพ็กเกจ")
        self.stdout.write(f"✓ MembershipLevels: {MembershipLevel.objects.count()} ระดับ")
        self.stdout.write(f"✓ StaffUsers: {StaffUser.objects.count()} บัญชีพนักงาน")
