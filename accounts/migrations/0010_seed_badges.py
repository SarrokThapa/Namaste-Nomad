from django.db import migrations


def seed_badges(apps, schema_editor):
    Badge = apps.get_model('accounts', 'Badge')
    badges = [
        {
            'name': 'First Explorer',
            'description': 'Shared your first community post.',
            'icon': 'FE',
            'condition_type': 'first_post',
            'condition_value': 1,
        },
        {
            'name': 'Travel Planner',
            'description': 'Saved your first package to wishlist.',
            'icon': 'TP',
            'condition_type': 'first_wishlist',
            'condition_value': 1,
        },
        {
            'name': 'Adventurer',
            'description': 'Completed your first confirmed booking.',
            'icon': 'ADV',
            'condition_type': 'first_booking_confirmed',
            'condition_value': 1,
        },
        {
            'name': 'Social Traveler',
            'description': 'Received 5 likes on your community posts.',
            'icon': 'ST',
            'condition_type': 'post_likes',
            'condition_value': 5,
        },
        {
            'name': 'Reviewer',
            'description': 'Wrote your first review.',
            'icon': 'REV',
            'condition_type': 'first_review',
            'condition_value': 1,
        },
        {
            'name': 'Trek Lover',
            'description': 'Booked 3 confirmed trekking packages.',
            'icon': 'TL',
            'condition_type': 'trek_bookings_confirmed',
            'condition_value': 3,
        },
    ]
    for entry in badges:
        Badge.objects.update_or_create(
            name=entry['name'],
            defaults=entry,
        )


def unseed_badges(apps, schema_editor):
    Badge = apps.get_model('accounts', 'Badge')
    Badge.objects.filter(
        name__in=[
            'First Explorer',
            'Travel Planner',
            'Adventurer',
            'Social Traveler',
            'Reviewer',
            'Trek Lover',
        ]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0009_badges_reward_points'),
    ]

    operations = [
        migrations.RunPython(seed_badges, unseed_badges),
    ]

