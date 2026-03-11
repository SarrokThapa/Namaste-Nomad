from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from accounts.models import TravelerProfile, VendorProfile, VendorSubscription, VendorSubscriptionPlan
from core.models import Package, Review


class Command(BaseCommand):
    help = "Seed dummy trekking packages for the homepage demo."

    def handle(self, *args, **options):
        today = timezone.localdate()
        static_prefix = (settings.STATIC_URL or "/static/").rstrip("/")

        def static_url(path):
            return f"{static_prefix}/{path.lstrip('/')}"

        def ensure_user(username, user_type, email, first_name, last_name):
            user_model = get_user_model()
            user = user_model.objects.filter(username=username).first()
            if user is None:
                user = user_model.objects.create_user(
                    username=username,
                    email=email,
                    user_type=user_type,
                    first_name=first_name,
                    last_name=last_name,
                    password="demo12345",
                )
                return user

            updates = []
            for field, value in (
                ("email", email),
                ("user_type", user_type),
                ("first_name", first_name),
                ("last_name", last_name),
            ):
                if getattr(user, field) != value:
                    setattr(user, field, value)
                    updates.append(field)
            if updates:
                user.save(update_fields=updates)
            return user

        def ensure_vendor_profile(user, business_name, owner_name, tagline):
            profile = VendorProfile.objects.filter(user=user).first()
            if profile is None:
                return VendorProfile.objects.create(
                    user=user,
                    business_name=business_name,
                    owner_name=owner_name,
                    tagline=tagline,
                )
            updates = []
            if profile.business_name != business_name:
                profile.business_name = business_name
                updates.append("business_name")
            if profile.owner_name != owner_name:
                profile.owner_name = owner_name
                updates.append("owner_name")
            if profile.tagline != tagline:
                profile.tagline = tagline
                updates.append("tagline")
            if updates:
                profile.save(update_fields=updates)
            return profile

        def ensure_traveler_profile(user):
            profile = TravelerProfile.objects.filter(user=user).first()
            if profile is None:
                return TravelerProfile.objects.create(user=user)
            return profile

        def ensure_plan():
            plan, created = VendorSubscriptionPlan.objects.get_or_create(
                name="Premium Featured",
                defaults={
                    "price": Decimal("15000.00"),
                    "duration_days": 90,
                    "max_featured_packages": None,
                    "is_active": True,
                },
            )
            updates = []
            if plan.price != Decimal("15000.00"):
                plan.price = Decimal("15000.00")
                updates.append("price")
            if plan.duration_days != 90:
                plan.duration_days = 90
                updates.append("duration_days")
            if plan.max_featured_packages is not None:
                plan.max_featured_packages = None
                updates.append("max_featured_packages")
            if not plan.is_active:
                plan.is_active = True
                updates.append("is_active")
            if updates:
                plan.save(update_fields=updates)
            return plan

        def ensure_subscription(vendor, plan):
            active = VendorSubscription.active_for_vendor(vendor)
            if active:
                return active
            start_date = today
            end_date = today + timedelta(days=plan.duration_days)
            return VendorSubscription.objects.create(
                vendor=vendor,
                plan=plan,
                plan_name=plan.name,
                price=plan.price,
                duration_days=plan.duration_days,
                max_featured_packages=plan.max_featured_packages,
                start_date=start_date,
                end_date=end_date,
                status=VendorSubscription.STATUS_ACTIVE,
            )

        vendor_specs = {
            "summit_sherpa": {
                "email": "summit@namastenomad.demo",
                "first_name": "Summit",
                "last_name": "Sherpa",
                "business_name": "Summit Sherpa Expeditions",
                "owner_name": "Dorje Sherpa",
                "tagline": "High-altitude trekking with local experts.",
            },
            "himalayan_trails": {
                "email": "trails@namastenomad.demo",
                "first_name": "Himalayan",
                "last_name": "Trails",
                "business_name": "Himalayan Trails Co.",
                "owner_name": "Maya Gurung",
                "tagline": "Curated Himalayan routes with cozy lodges.",
            },
        }

        packages = [
            {
                "title": "Everest Base Camp Trek",
                "description": "A classic 14-day journey to the base of the world’s tallest peak with Sherpa culture and alpine vistas.",
                "price": Decimal("135000.00"),
                "duration_days": 14,
                "location": "Everest Region",
                "image_url": static_url("images/featured/everest-base-camp.jpg"),
                "vendor_key": "summit_sherpa",
                "rating": 5,
                "review_comment": "Unforgettable views and a great guide team.",
                "views_count": 1420,
                "is_featured": True,
                "difficulty": "challenging",
                "group_size": 12,
                "best_season": "Spring, Autumn",
            },
            {
                "title": "Annapurna Base Camp Trek",
                "description": "A balanced trek through rhododendron forests to the Annapurna sanctuary with dramatic mountain amphitheaters.",
                "price": Decimal("98000.00"),
                "duration_days": 12,
                "location": "Annapurna Region",
                "image_url": static_url("images/featured/annapurna-circuit.jpg"),
                "vendor_key": "himalayan_trails",
                "rating": 5,
                "review_comment": "Perfect itinerary and cozy tea houses.",
                "views_count": 1180,
                "is_featured": True,
                "difficulty": "moderate",
                "group_size": 10,
                "best_season": "Spring, Autumn",
            },
            {
                "title": "Langtang Valley Trek",
                "description": "A shorter adventure close to Kathmandu featuring Tamang heritage villages, yak pastures, and glacier views.",
                "price": Decimal("78000.00"),
                "duration_days": 10,
                "location": "Langtang Region",
                "image_url": static_url("images/featured/tilicho-lake.jpg"),
                "vendor_key": "summit_sherpa",
                "rating": 4,
                "review_comment": "Beautiful scenery and a relaxed pace.",
                "views_count": 860,
                "is_featured": False,
                "difficulty": "moderate",
                "group_size": 14,
                "best_season": "Spring, Autumn",
            },
            {
                "title": "Mardi Himal Trek",
                "description": "A scenic ridge trek above Pokhara with panoramic views of Machapuchare and the Annapurna range.",
                "price": Decimal("69000.00"),
                "duration_days": 9,
                "location": "Annapurna Region",
                "image_url": static_url("images/featured/swayambhu-valley.jpg"),
                "vendor_key": "himalayan_trails",
                "rating": 4,
                "review_comment": "Quiet trails and stunning sunrise viewpoints.",
                "views_count": 740,
                "is_featured": False,
                "difficulty": "moderate",
                "group_size": 10,
                "best_season": "Spring, Autumn",
            },
            {
                "title": "Manaslu Circuit Trek",
                "description": "A remote circuit trek with high mountain passes, Tibetan culture, and off-the-beaten-path trails.",
                "price": Decimal("150000.00"),
                "duration_days": 16,
                "location": "Manaslu Region",
                "image_url": static_url("images/featured/manaslu-circuit.jpg"),
                "vendor_key": "summit_sherpa",
                "rating": 5,
                "review_comment": "Remote and breathtaking, worth every step.",
                "views_count": 990,
                "is_featured": False,
                "difficulty": "challenging",
                "group_size": 10,
                "best_season": "Spring, Autumn",
            },
        ]

        with transaction.atomic():
            plan = ensure_plan()

            vendors = {}
            for username, spec in vendor_specs.items():
                user = ensure_user(
                    username=username,
                    user_type="vendor",
                    email=spec["email"],
                    first_name=spec["first_name"],
                    last_name=spec["last_name"],
                )
                ensure_vendor_profile(
                    user,
                    business_name=spec["business_name"],
                    owner_name=spec["owner_name"],
                    tagline=spec["tagline"],
                )
                vendors[username] = user

            traveler = ensure_user(
                username="demo_traveler",
                user_type="traveler",
                email="traveler@namastenomad.demo",
                first_name="Demo",
                last_name="Traveler",
            )
            ensure_traveler_profile(traveler)

            start_date = today - timedelta(days=10)
            end_date = today + timedelta(days=120)

            created_count = 0
            updated_count = 0

            for pkg in packages:
                vendor = vendors[pkg["vendor_key"]]
                if pkg["is_featured"]:
                    ensure_subscription(vendor, plan)

                defaults = {
                    "vendor": vendor,
                    "category": Package.CATEGORY_TREK,
                    "location": pkg["location"],
                    "description": pkg["description"],
                    "duration_days": pkg["duration_days"],
                    "difficulty": pkg["difficulty"],
                    "group_size": pkg["group_size"],
                    "available_from": start_date,
                    "available_until": end_date,
                    "best_season": pkg["best_season"],
                    "image_url": pkg["image_url"],
                    "price": pkg["price"],
                    "is_active": True,
                    "is_featured": pkg["is_featured"],
                    "views_count": pkg["views_count"],
                }

                package = Package.objects.filter(title=pkg["title"]).first()
                if package is None:
                    package = Package.objects.create(title=pkg["title"], **defaults)
                    created_count += 1
                else:
                    updates = []
                    for field, value in defaults.items():
                        if getattr(package, field) != value:
                            setattr(package, field, value)
                            updates.append(field)
                    if updates:
                        package.save(update_fields=updates)
                        updated_count += 1
                existing_review = Review.objects.filter(package=package, traveler=traveler).first()
                if existing_review is None:
                    Review.objects.create(
                        package=package,
                        traveler=traveler,
                        rating=pkg["rating"],
                        comment=pkg["review_comment"],
                    )
                else:
                    review_updates = []
                    if existing_review.rating != pkg["rating"]:
                        existing_review.rating = pkg["rating"]
                        review_updates.append("rating")
                    if existing_review.comment != pkg["review_comment"]:
                        existing_review.comment = pkg["review_comment"]
                        review_updates.append("comment")
                    if review_updates:
                        existing_review.save(update_fields=review_updates)

        self.stdout.write(
            self.style.SUCCESS(
                f"Dummy packages seeded. Created: {created_count}, Updated: {updated_count}."
            )
        )
