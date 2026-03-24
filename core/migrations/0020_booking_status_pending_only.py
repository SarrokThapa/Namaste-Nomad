from django.db import migrations, models


def migrate_booking_status_forward(apps, schema_editor):
    Booking = apps.get_model('core', 'Booking')
    Booking.objects.filter(status='payment_pending').update(status='pending')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0019_booking_esewa_fields_and_payment_statuses'),
    ]

    operations = [
        migrations.RunPython(
            migrate_booking_status_forward,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name='booking',
            name='status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('confirmed', 'Confirmed'),
                    ('cancelled', 'Cancelled'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
    ]
