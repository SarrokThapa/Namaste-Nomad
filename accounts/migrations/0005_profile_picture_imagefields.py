from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0004_vendorprofile_fields"),
    ]

    operations = [
        migrations.AlterField(
            model_name="vendorprofile",
            name="logo",
            field=models.ImageField(blank=True, null=True, upload_to="vendor_logos/"),
        ),
        migrations.AlterField(
            model_name="adminprofile",
            name="avatar",
            field=models.ImageField(blank=True, null=True, upload_to="admin_avatars/"),
        ),
        migrations.AlterField(
            model_name="travelerprofile",
            name="avatar",
            field=models.ImageField(blank=True, null=True, upload_to="avatars/"),
        ),
    ]
