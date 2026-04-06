from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0016_delete_vendorfeature_delete_vendorsubscription_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='PasswordResetOTP',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(db_index=True)),
                ('otp_hash', models.CharField(max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('attempts', models.PositiveSmallIntegerField(default=0)),
                ('is_used', models.BooleanField(default=False)),
                ('verified', models.BooleanField(default=False)),
                ('blocked_until', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'ordering': ('-created_at',),
            },
        ),
    ]
