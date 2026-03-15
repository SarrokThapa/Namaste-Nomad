from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0008_notification'),
    ]

    operations = [
        migrations.CreateModel(
            name='Badge',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=120, unique=True)),
                ('description', models.TextField()),
                ('icon', models.CharField(max_length=20)),
                ('condition_type', models.CharField(choices=[('first_post', 'First Post'), ('first_wishlist', 'First Wishlist'), ('first_booking_confirmed', 'First Booking Confirmed'), ('post_likes', 'Post Likes'), ('first_review', 'First Review'), ('trek_bookings_confirmed', 'Trek Bookings Confirmed')], max_length=40)),
                ('condition_value', models.PositiveIntegerField(default=1)),
            ],
            options={
                'ordering': ('id',),
            },
        ),
        migrations.CreateModel(
            name='RewardPoint',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('points', models.IntegerField()),
                ('action_type', models.CharField(choices=[('post', 'Community Post'), ('like_received', 'Like Received'), ('review', 'Review'), ('wishlist', 'Wishlist'), ('booking_confirmed', 'Booking Confirmed')], max_length=40)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reward_points', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-created_at',),
            },
        ),
        migrations.CreateModel(
            name='UserBadge',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('earned_at', models.DateTimeField(auto_now_add=True)),
                ('badge', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='earned_by', to='accounts.badge')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='earned_badges', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ('-earned_at',),
            },
        ),
        migrations.AddConstraint(
            model_name='userbadge',
            constraint=models.UniqueConstraint(fields=('user', 'badge'), name='unique_user_badge'),
        ),
    ]

