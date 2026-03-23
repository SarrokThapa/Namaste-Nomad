from django.core.validators import MinValueValidator
from django.db import migrations, models


def migrate_payment_status_values_forward(apps, schema_editor):
    Booking = apps.get_model('core', 'Booking')
    Booking.objects.filter(payment_status='paid').update(payment_status='completed')
    Booking.objects.filter(payment_status__in=['cancelled', 'expired']).update(payment_status='failed')


def migrate_payment_status_values_backward(apps, schema_editor):
    Booking = apps.get_model('core', 'Booking')
    Booking.objects.filter(payment_status='completed').update(payment_status='paid')
    Booking.objects.filter(payment_status='failed').update(payment_status='cancelled')


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0018_wishlist'),
    ]

    operations = [
        migrations.AddField(
            model_name='booking',
            name='esewa_transaction_id',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='booking',
            name='paid_amount',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                max_digits=10,
                null=True,
                validators=[MinValueValidator(0)],
            ),
        ),
        migrations.RunPython(
            migrate_payment_status_values_forward,
            migrate_payment_status_values_backward,
        ),
        migrations.AlterField(
            model_name='booking',
            name='payment_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('completed', 'Completed'),
                    ('failed', 'Failed'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
    ]
