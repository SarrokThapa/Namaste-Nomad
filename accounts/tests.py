from datetime import datetime, timedelta

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import FeatureSlot, Notification, TravelerProfile, User, VendorFeature, VendorProfile
from core.models import Booking, Package, SpecialOffer


class VendorApprovalFlowTests(TestCase):
    def test_vendor_registration_requires_document(self):
        response = self.client.post(
            reverse('vendor_register'),
            data={
                'business_name': 'Himalayan Trails',
                'owner_name': 'Ram Bahadur',
                'email': 'vendor-required-doc@example.com',
                'phone': '+9779800000001',
                'password': 'strong-pass-123',
                'confirm_password': 'strong-pass-123',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Verification document is required for vendor registration.')
        self.assertFalse(User.objects.filter(email='vendor-required-doc@example.com').exists())

    def test_vendor_registration_saves_document_and_pending_status(self):
        document = SimpleUploadedFile(
            'verification.pdf',
            b'fake verification payload',
            content_type='application/pdf',
        )

        response = self.client.post(
            reverse('vendor_register'),
            data={
                'business_name': 'Altitude Adventures',
                'owner_name': 'Sita Gurung',
                'email': 'vendor-with-doc@example.com',
                'phone': '+9779800000002',
                'password': 'strong-pass-123',
                'confirm_password': 'strong-pass-123',
                'document': document,
            },
        )

        user = User.objects.get(email='vendor-with-doc@example.com')
        profile = user.vendor_profile

        self.assertRedirects(response, reverse('verify_otp'))
        self.assertEqual(user.user_type, 'vendor')
        self.assertFalse(profile.is_approved)
        self.assertTrue(bool(profile.document))

    def test_vendor_registration_rejects_invalid_document_type(self):
        document = SimpleUploadedFile(
            'verification.txt',
            b'not supported',
            content_type='text/plain',
        )

        response = self.client.post(
            reverse('vendor_register'),
            data={
                'business_name': 'Bad Doc Vendor',
                'owner_name': 'Owner Bad',
                'email': 'vendor-bad-doc@example.com',
                'phone': '+9779800000099',
                'password': 'strong-pass-123',
                'confirm_password': 'strong-pass-123',
                'document': document,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Please upload a valid PDF, JPG, JPEG, or PNG file.')
        self.assertFalse(User.objects.filter(email='vendor-bad-doc@example.com').exists())

    def test_pending_vendor_cannot_access_package_create(self):
        vendor = User.objects.create_user(
            username='pending-vendor@example.com',
            email='pending-vendor@example.com',
            password='vendor-pass-123',
            user_type='vendor',
        )
        VendorProfile.objects.create(
            user=vendor,
            business_name='Pending Treks',
            owner_name='Owner Pending',
            is_approved=False,
        )
        self.client.force_login(vendor)

        response = self.client.get(reverse('vendor_package_create'), follow=True)

        self.assertTrue(any(reverse('vendor_login') in url for url, _code in response.redirect_chain))
        self.assertTrue(any(reverse('vendor_profile') in url for url, _code in response.redirect_chain))

    def test_pending_vendor_login_redirects_to_profile_with_notice(self):
        vendor = User.objects.create_user(
            username='pending-login@example.com',
            email='pending-login@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_verified=True,
        )
        VendorProfile.objects.create(
            user=vendor,
            business_name='Pending Login Treks',
            owner_name='Owner Pending Login',
            is_approved=False,
        )

        response = self.client.post(
            reverse('vendor_login'),
            data={
                'email': 'pending-login@example.com',
                'password': 'vendor-pass-123',
            },
            follow=True,
        )

        self.assertTrue(any(reverse('vendor_profile') in url for url, _code in response.redirect_chain))

    def test_admin_can_approve_vendor_from_detail_page(self):
        admin = User.objects.create_user(
            username='admin-user@example.com',
            email='admin-user@example.com',
            password='admin-pass-123',
            user_type='admin',
            is_staff=True,
        )
        vendor = User.objects.create_user(
            username='vendor-approve@example.com',
            email='vendor-approve@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_active=False,
        )
        VendorProfile.objects.create(
            user=vendor,
            business_name='Approve Me Pvt Ltd',
            owner_name='Owner Approve',
            is_approved=False,
        )
        self.client.force_login(admin)

        response = self.client.post(
            reverse('admin_vendor_action', args=[vendor.id]),
            data={
                'action': 'approve',
                'next': reverse('admin_vendor_detail', args=[vendor.id]),
            },
        )

        vendor.refresh_from_db()
        vendor.vendor_profile.refresh_from_db()

        self.assertRedirects(response, reverse('admin_vendor_detail', args=[vendor.id]))
        self.assertTrue(vendor.is_active)
        self.assertTrue(vendor.vendor_profile.is_approved)

    def test_rejected_vendor_not_listed_in_pending_approval_requests(self):
        admin = User.objects.create_user(
            username='admin-reject@example.com',
            email='admin-reject@example.com',
            password='admin-pass-123',
            user_type='admin',
            is_staff=True,
        )
        vendor = User.objects.create_user(
            username='reject-vendor@example.com',
            email='reject-vendor@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_active=True,
        )
        VendorProfile.objects.create(
            user=vendor,
            business_name='Reject Me Travels',
            owner_name='Reject Owner',
            is_approved=False,
        )
        self.client.force_login(admin)

        self.client.post(
            reverse('admin_vendor_action', args=[vendor.id]),
            data={
                'action': 'reject',
                'next': reverse('admin_dashboard'),
            },
        )

        response = self.client.get(reverse('admin_dashboard'))
        pending_vendors = response.context['pending_vendors']

        vendor.refresh_from_db()
        vendor.vendor_profile.refresh_from_db()

        self.assertFalse(vendor.is_active)
        self.assertFalse(vendor.vendor_profile.is_approved)
        self.assertFalse(pending_vendors.filter(id=vendor.id).exists())


class VendorAnalyticsChartTests(TestCase):
    def setUp(self):
        self.vendor = User.objects.create_user(
            username='analytics-vendor@example.com',
            email='analytics-vendor@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_active=True,
        )
        self.traveler = User.objects.create_user(
            username='analytics-traveler@example.com',
            email='analytics-traveler@example.com',
            password='traveler-pass-123',
            user_type='traveler',
        )
        VendorProfile.objects.create(
            user=self.vendor,
            business_name='Analytics Treks',
            owner_name='Analytics Owner',
            is_approved=True,
        )
        self.package = Package.objects.create(
            vendor=self.vendor,
            title='Analytics Trek',
            location='Solukhumbu',
            price='12000.00',
            available_slots=20,
            available_from=timezone.localdate() - timedelta(days=2),
            available_until=timezone.localdate() + timedelta(days=60),
            is_active=True,
        )

    def test_vendor_analytics_renders_chart_sections(self):
        Booking.objects.create(
            package=self.package,
            traveler=self.traveler,
            vendor=self.vendor,
            number_of_people=2,
            travel_date=timezone.localdate() + timedelta(days=8),
            status=Booking.STATUS_CONFIRMED,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
            payment_status=Booking.PAYMENT_STATUS_COMPLETED,
            total_price='0',
        )

        self.client.force_login(self.vendor)
        response = self.client.get(reverse('vendor_analytics'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Revenue by Month')
        self.assertContains(response, 'Revenue Trend')
        self.assertContains(response, 'Payment Method Mix')
        self.assertContains(response, 'conic-gradient(')

    def test_vendor_analytics_charts_render_without_bookings(self):
        self.client.force_login(self.vendor)
        response = self.client.get(reverse('vendor_analytics'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Revenue by Month')
        self.assertContains(response, 'Payment Method Mix')


class AdminAnalyticsApiTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='analytics-admin@example.com',
            email='analytics-admin@example.com',
            password='admin-pass-123',
            user_type='admin',
            is_staff=True,
            is_active=True,
        )
        self.vendor = User.objects.create_user(
            username='analytics-vendor-admin@example.com',
            email='analytics-vendor-admin@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_active=True,
        )
        VendorProfile.objects.create(
            user=self.vendor,
            business_name='Atlas Peak Treks',
            owner_name='Admin Analytics Vendor',
            is_approved=True,
        )
        self.traveler = User.objects.create_user(
            username='analytics-traveler-admin@example.com',
            email='analytics-traveler-admin@example.com',
            password='traveler-pass-123',
            user_type='traveler',
        )
        self.package_trek = Package.objects.create(
            vendor=self.vendor,
            title='Everest Ridge Trek',
            category=Package.CATEGORY_TREK,
            location='Khumbu',
            price='10000.00',
            available_slots=12,
            available_from=timezone.localdate() - timedelta(days=10),
            available_until=timezone.localdate() + timedelta(days=40),
            is_active=True,
        )
        self.package_cultural = Package.objects.create(
            vendor=self.vendor,
            title='Kathmandu Cultural Heritage Tour',
            category=Package.CATEGORY_TOUR,
            location='Kathmandu',
            price='8000.00',
            available_slots=15,
            available_from=timezone.localdate() - timedelta(days=10),
            available_until=timezone.localdate() + timedelta(days=40),
            is_active=True,
        )

    def _set_created_at(self, instance, target_datetime):
        model = type(instance)
        model.objects.filter(id=instance.id).update(created_at=target_datetime)

    def _aware(self, year, month, day):
        return timezone.make_aware(datetime(year, month, day, 10, 0, 0))

    def _create_booking(self, package, year, month, day):
        booking = Booking.objects.create(
            package=package,
            traveler=self.traveler,
            vendor=self.vendor,
            number_of_people=1,
            travel_date=timezone.localdate() + timedelta(days=7),
            status=Booking.STATUS_CONFIRMED,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
            payment_status=Booking.PAYMENT_STATUS_COMPLETED,
            total_price='0',
        )
        self._set_created_at(booking, self._aware(year, month, day))
        return booking

    def test_admin_analytics_api_requires_admin_login(self):
        response = self.client.get(reverse('admin_analytics_api'))
        self.assertEqual(response.status_code, 302)
        self.assertIn(reverse('admin_login'), response.url)

    def test_admin_analytics_api_returns_chart_payload_for_year(self):
        self._create_booking(self.package_trek, 2026, 3, 10)
        self._create_booking(self.package_cultural, 2026, 2, 10)
        old_booking = self._create_booking(self.package_trek, 2025, 4, 10)
        self.assertIsNotNone(old_booking.id)

        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_analytics_api'), {'year': 2026})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['year'], 2026)
        self.assertEqual(len(payload['months']), 12)
        self.assertEqual(payload['bookings']['values'][1], 1)  # Feb
        self.assertEqual(payload['bookings']['values'][2], 1)  # Mar
        self.assertGreater(payload['revenue']['values'][2], 0)
        self.assertEqual(payload['categories']['labels'], ['Treks', 'Tours', 'Cultural'])
        self.assertEqual(payload['categories']['values'], [1, 0, 1])
        self.assertTrue(any(vendor['name'] == 'Atlas Peak Treks' for vendor in payload['top_vendors']))

    def test_admin_analytics_api_applies_year_filter(self):
        self._create_booking(self.package_trek, 2026, 3, 11)
        self._create_booking(self.package_trek, 2025, 4, 11)

        self.client.force_login(self.admin)
        response = self.client.get(reverse('admin_analytics_api'), {'year': 2025})

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['year'], 2025)
        self.assertEqual(payload['bookings']['values'][3], 1)  # Apr
        self.assertEqual(payload['bookings']['values'][2], 0)  # Mar


class PromotionsPreferenceTests(TestCase):
    def test_traveler_registration_saves_promotions_preference(self):
        response = self.client.post(
            reverse('traveler_register'),
            data={
                'first_name': 'Promo',
                'last_name': 'Traveler',
                'email': 'promo-traveler@example.com',
                'phone': '+9779800001234',
                'password': 'strong-pass-123',
                'confirm_password': 'strong-pass-123',
                'wants_promotions': 'on',
            },
        )

        self.assertRedirects(response, reverse('verify_otp'))
        user = User.objects.get(email='promo-traveler@example.com')
        self.assertTrue(user.wants_promotions)

    def test_vendor_registration_saves_promotions_preference(self):
        document = SimpleUploadedFile(
            'verification.pdf',
            b'fake verification payload',
            content_type='application/pdf',
        )
        response = self.client.post(
            reverse('vendor_register'),
            data={
                'business_name': 'Offer Trails',
                'owner_name': 'Offer Owner',
                'email': 'promo-vendor@example.com',
                'phone': '+9779800005678',
                'password': 'strong-pass-123',
                'confirm_password': 'strong-pass-123',
                'document': document,
                'wants_promotions': 'on',
            },
        )

        self.assertRedirects(response, reverse('verify_otp'))
        user = User.objects.get(email='promo-vendor@example.com')
        self.assertTrue(user.wants_promotions)

    def test_traveler_profile_updates_promotions_preference(self):
        user = User.objects.create_user(
            username='profile-traveler',
            email='profile-traveler@example.com',
            password='traveler-pass-123',
            user_type='traveler',
            wants_promotions=False,
        )
        TravelerProfile.objects.create(user=user)
        self.client.force_login(user)

        response = self.client.post(
            reverse('traveler_profile'),
            data={
                'full_name': 'Profile Traveler',
                'email': 'profile-traveler@example.com',
                'phone': '+9779800012345',
                'gender': 'male',
                'nationality': 'Nepali',
                'bio': 'Test bio',
                'wants_promotions': 'on',
            },
        )

        self.assertRedirects(response, reverse('traveler_profile'))
        user.refresh_from_db()
        self.assertTrue(user.wants_promotions)

    def test_vendor_profile_enabling_promotions_adds_active_offer_notification(self):
        vendor = User.objects.create_user(
            username='profile-vendor@example.com',
            email='profile-vendor@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            wants_promotions=False,
            is_active=True,
        )
        VendorProfile.objects.create(
            user=vendor,
            business_name='Offer Vendor',
            owner_name='Vendor Owner',
            is_approved=True,
        )
        SpecialOffer.objects.create(
            title='Weekend Escape Deal',
            summary='Limited-time package discount.',
            content='Save more when you book this weekend.',
            is_active=True,
        )
        self.client.force_login(vendor)

        response = self.client.post(
            reverse('vendor_profile'),
            data={
                'business_name': 'Offer Vendor',
                'owner_name': 'Vendor Owner',
                'email': 'profile-vendor@example.com',
                'phone': '+9779800099999',
                'tagline': '',
                'website': '',
                'license_number': '',
                'business_address': '',
                'description': '',
                'bank_name': '',
                'account_number': '',
                'routing_number': '',
                'paypal_email': '',
                'wants_promotions': 'on',
            },
        )

        self.assertRedirects(response, reverse('vendor_profile'))
        vendor.refresh_from_db()
        self.assertTrue(vendor.wants_promotions)
        self.assertTrue(
            Notification.objects.filter(
                user=vendor,
                type=Notification.TYPE_PROMOTION,
                message__contains='Special offer available',
            ).exists()
        )

    def test_vendor_package_limited_offer_notifies_only_opted_in_travelers(self):
        vendor = User.objects.create_user(
            username='limited-offer-vendor@example.com',
            email='limited-offer-vendor@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_active=True,
        )
        VendorProfile.objects.create(
            user=vendor,
            business_name='Limited Offer Treks',
            owner_name='Offer Owner',
            is_approved=True,
        )
        opted_in_traveler = User.objects.create_user(
            username='opted-in-traveler@example.com',
            email='opted-in-traveler@example.com',
            password='traveler-pass-123',
            user_type='traveler',
            wants_promotions=True,
            is_active=True,
        )
        opted_out_traveler = User.objects.create_user(
            username='opted-out-traveler@example.com',
            email='opted-out-traveler@example.com',
            password='traveler-pass-123',
            user_type='traveler',
            wants_promotions=False,
            is_active=True,
        )

        self.client.force_login(vendor)
        response = self.client.post(
            reverse('vendor_package_create'),
            data={
                'title': 'Limited Spring Trek',
                'category': Package.CATEGORY_TREK,
                'location_name': 'Manang',
                'latitude': '28.669',
                'longitude': '84.021',
                'price': '14999.00',
                'duration_days': '8',
                'available_slots': '12',
                'available_from': timezone.localdate().isoformat(),
                'available_until': (timezone.localdate() + timedelta(days=30)).isoformat(),
                'difficulty': 'moderate',
                'group_size': '10',
                'best_season': 'Spring',
                'image_url': '',
                'description': 'Limited offer package.',
                'itinerary': 'Day 1\nDay 2',
                'inclusions': 'Guide',
                'exclusions': 'Flights',
                'has_guide': 'on',
                'includes_meals': 'on',
                'includes_accommodation': 'on',
                'includes_transport': 'on',
                'includes_permits': 'on',
                'is_active': 'on',
                'is_featured': '',
                'limited_time_offer': 'on',
            },
        )

        self.assertRedirects(response, reverse('vendor_packages'))
        package = Package.objects.get(title='Limited Spring Trek')
        self.assertTrue(
            Notification.objects.filter(
                user=opted_in_traveler,
                type=Notification.TYPE_PROMOTION,
                related_object_id=package.id,
                message__contains='Limited-time package offer',
            ).exists()
        )
        self.assertFalse(
            Notification.objects.filter(
                user=opted_out_traveler,
                type=Notification.TYPE_PROMOTION,
                related_object_id=package.id,
                message__contains='Limited-time package offer',
            ).exists()
        )


class FeatureSlotEnforcementTests(TestCase):
    def setUp(self):
        self.vendor = User.objects.create_user(
            username='slot-vendor@example.com',
            email='slot-vendor@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_active=True,
        )
        VendorProfile.objects.create(
            user=self.vendor,
            business_name='Slot Vendor',
            owner_name='Slot Owner',
            is_approved=True,
        )
        self.package_one = Package.objects.create(
            vendor=self.vendor,
            title='Slot Package One',
            category=Package.CATEGORY_TREK,
            location_name='Pokhara',
            latitude=28.2,
            longitude=84.0,
            price='9000.00',
            available_slots=10,
            available_from=timezone.localdate(),
            available_until=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )
        self.package_two = Package.objects.create(
            vendor=self.vendor,
            title='Slot Package Two',
            category=Package.CATEGORY_TREK,
            location_name='Kathmandu',
            latitude=27.7,
            longitude=85.3,
            price='11000.00',
            available_slots=10,
            available_from=timezone.localdate(),
            available_until=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )

    def test_vendor_cannot_feature_package_without_purchased_slots(self):
        self.client.force_login(self.vendor)

        response = self.client.post(
            reverse('vendor_feature_toggle', args=[self.package_one.id]),
            data={'next': reverse('vendor_packages')},
            follow=True,
        )

        self.package_one.refresh_from_db()
        self.assertFalse(self.package_one.is_featured)
        self.assertContains(response, 'Upgrade subscription to feature more packages')

    def test_vendor_cannot_exceed_purchased_feature_slots(self):
        slot = FeatureSlot.objects.create(
            name='Homepage Featured Slot',
            max_slots=10,
            price_per_slot='1000.00',
            is_active=True,
        )
        VendorFeature.objects.create(
            vendor=self.vendor,
            slot=slot,
            purchased_slots=1,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=10),
            is_active=True,
        )
        self.client.force_login(self.vendor)

        first = self.client.post(
            reverse('vendor_feature_toggle', args=[self.package_one.id]),
            data={'next': reverse('vendor_packages')},
            follow=True,
        )
        second = self.client.post(
            reverse('vendor_feature_toggle', args=[self.package_two.id]),
            data={'next': reverse('vendor_packages')},
            follow=True,
        )

        self.package_one.refresh_from_db()
        self.package_two.refresh_from_db()
        self.assertTrue(self.package_one.is_featured)
        self.assertFalse(self.package_two.is_featured)
        self.assertContains(first, 'featured')
        self.assertContains(second, 'Upgrade subscription to feature more packages')
