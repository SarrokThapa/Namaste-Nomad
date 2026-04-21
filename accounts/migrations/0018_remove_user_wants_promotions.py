from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0017_passwordresetotp'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='user',
            name='wants_promotions',
        ),
    ]
