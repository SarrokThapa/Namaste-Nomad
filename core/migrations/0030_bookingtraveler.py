import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0029_remove_package_is_featured_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='BookingTraveler',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('traveler_index', models.PositiveSmallIntegerField(default=0)),
                ('full_name', models.CharField(max_length=200)),
                ('age', models.PositiveSmallIntegerField()),
                ('gender', models.CharField(
                    blank=True,
                    choices=[('male', 'Male'), ('female', 'Female'), ('other', 'Other')],
                    max_length=10,
                )),
                ('phone_number', models.CharField(blank=True, max_length=30)),
                ('email', models.EmailField(blank=True, max_length=254)),
                ('nationality', models.CharField(default='Nepali', max_length=80)),
                ('id_type', models.CharField(
                    blank=True,
                    choices=[
                        ('citizenship', 'Citizenship'),
                        ('passport', 'Passport'),
                        ('national_id', 'National ID'),
                        ('driving_license', 'Driving License'),
                    ],
                    max_length=30,
                )),
                ('id_number', models.CharField(max_length=100)),
                ('medical_notes', models.TextField(blank=True)),
                ('emergency_contact_name', models.CharField(blank=True, max_length=200)),
                ('emergency_contact_phone', models.CharField(blank=True, max_length=30)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('booking', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='booking_travelers',
                    to='core.booking',
                )),
            ],
            options={
                'ordering': ('traveler_index',),
            },
        ),
    ]
