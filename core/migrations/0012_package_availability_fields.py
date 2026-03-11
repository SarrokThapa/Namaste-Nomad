from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_booking_commission_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='package',
            name='available_from',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='package',
            name='available_until',
            field=models.DateField(blank=True, null=True),
        ),
    ]
