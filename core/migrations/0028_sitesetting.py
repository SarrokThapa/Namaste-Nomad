from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0027_transaction_vendor_feature_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteSetting',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('commission_percent', models.IntegerField(default=25)),
                ('featured_slots', models.IntegerField(default=8)),
                ('enable_booking', models.BooleanField(default=True)),
                ('enable_community', models.BooleanField(default=True)),
                ('contact_email', models.EmailField(blank=True, max_length=254)),
                ('contact_phone', models.CharField(blank=True, max_length=20)),
                ('instagram_link', models.URLField(blank=True)),
                ('hero_title', models.CharField(blank=True, max_length=255)),
                ('hero_subtitle', models.TextField(blank=True)),
            ],
        ),
    ]
