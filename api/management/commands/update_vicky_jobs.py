from decimal import Decimal
from django.core.management.base import BaseCommand
from api.models import Job

class Command(BaseCommand):
    help = 'Updates Jobs 25 to 30 for Vicky Chou to promo price 1,000 THB'

    def handle(self, *args, **options):
        target_ids = [25, 26, 27, 28, 29, 30]
        jobs = Job.objects.filter(id__in=target_ids).order_by('id')
        
        count = 0
        for job in jobs:
            price_val = 1000.00
            vat_val = round(price_val - (price_val / 1.07), 2)
            subtotal_val = round(price_val - vat_val, 2)
            
            job.price = Decimal('1000.00')
            job.vat_amount = Decimal(f"{vat_val:.2f}")

            # Job price snapshot
            snap = job.price_snapshot or {}
            snap['total'] = "1000.00"
            snap['service_amount'] = "1000.00"
            snap['subtotal'] = f"{subtotal_val:.2f}"
            snap['vat_amount'] = f"{vat_val:.2f}"
            snap['price_reason'] = "ส่วนลดโปรโมชั่นหน้าร้าน 1,000 บาท"
            snap['service_amount_before_discount'] = "1000.00"
            job.price_snapshot = snap
            job.save()

            # Booking price snapshot
            if job.booking:
                bsnap = job.booking.price_snapshot or {}
                bsnap['total'] = "1000.00"
                bsnap['service_amount'] = "1000.00"
                bsnap['subtotal'] = f"{subtotal_val:.2f}"
                bsnap['vat_amount'] = f"{vat_val:.2f}"
                bsnap['price_reason'] = "ส่วนลดโปรโมชั่นหน้าร้าน 1,000 บาท"
                bsnap['service_amount_before_discount'] = "1000.00"
                job.booking.price_snapshot = bsnap
                job.booking.save(update_fields=['price_snapshot'])
            
            count += 1
            self.stdout.write(self.style.SUCCESS(f"Updated Job #{job.id} ({job.brand} {job.model}) -> 1,000 THB"))

        self.stdout.write(self.style.SUCCESS(f"\nSuccessfully updated {count} jobs to 1,000 THB."))
