from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0012_package_availability_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='package',
            name='is_featured',
            field=models.BooleanField(default=False),
        ),
    ]
