from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_booking_number_of_people_booking_special_notes_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='booking',
            name='status',
            field=models.CharField(
                choices=[
                    ('payment_pending', 'Payment Pending'),
                    ('pending', 'Pending'),
                    ('confirmed', 'Confirmed'),
                    ('cancelled', 'Cancelled'),
                ],
                default='payment_pending',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='paid_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='payment_expires_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='booking',
            name='payment_method',
            field=models.CharField(
                choices=[
                    ('stripe', 'Stripe'),
                    ('esewa', 'eSewa'),
                    ('khalti', 'Khalti'),
                ],
                default='stripe',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='payment_reference',
            field=models.CharField(blank=True, max_length=255),
        ),
        migrations.AddField(
            model_name='booking',
            name='payment_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('paid', 'Paid'),
                    ('cancelled', 'Cancelled'),
                    ('expired', 'Expired'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='booking',
            name='stripe_checkout_session_id',
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
