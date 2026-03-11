from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import migrations, models
import django.db.models.deletion


def populate_booking_commissions(apps, schema_editor):
    Booking = apps.get_model('core', 'Booking')
    vendor_rate = Decimal('0.75')

    for booking in Booking.objects.select_related('package'):
        total_price = booking.total_price
        if total_price is None:
            continue
        if not isinstance(total_price, Decimal):
            total_price = Decimal(str(total_price))

        vendor_amount = (total_price * vendor_rate).quantize(Decimal('0.01'))
        platform_fee = (total_price - vendor_amount).quantize(Decimal('0.01'))
        updates = {
            'vendor_amount': vendor_amount,
            'platform_fee': platform_fee,
        }
        if booking.vendor_id is None and booking.package_id:
            updates['vendor_id'] = booking.package.vendor_id
        Booking.objects.filter(pk=booking.pk).update(**updates)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0010_booking_payment_fields'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='vendor',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='vendor_bookings',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='vendor_amount',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                max_digits=10,
                validators=[MinValueValidator(0)],
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='platform_fee',
            field=models.DecimalField(
                decimal_places=2,
                default=Decimal('0.00'),
                max_digits=10,
                validators=[MinValueValidator(0)],
            ),
        ),
        migrations.RunPython(populate_booking_commissions, migrations.RunPython.noop),
    ]
