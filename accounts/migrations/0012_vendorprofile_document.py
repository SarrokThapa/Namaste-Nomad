from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0011_vendorprofile_is_verified'),
    ]

    operations = [
        migrations.AddField(
            model_name='vendorprofile',
            name='document',
            field=models.FileField(blank=True, null=True, upload_to='vendor_documents/'),
        ),
    ]
