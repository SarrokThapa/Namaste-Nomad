"""Tests for the accounts app: auth, OTP, vendor approval, feature plans, achievements."""

# NOTE: file > 300 lines — split deferred. Same reasoning as core/tests.py:
# splitting Django test modules changes test discovery paths.

from datetime import datetime, timedelta
from decimal import Decimal

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import AdminProfile, FeaturedPackage, FeaturePlan, Notification, TravelerProfile, User, VendorFeatureSubscription, VendorProfile
from core.models import Booking, Package, Review, Transaction


class VendorApprovalFlowTests(TestCase):
    def _valid_vendor_package_payload(self, **overrides):
        payload = {
            'title': 'Coordinate Validation Trek',
            'category': Package.CATEGORY_TREK,
            'location_name': 'Mustang',
            'latitude': '28.2096',
            'longitude': '83.9856',
            'price': '12000',
            'available_slots': '10',
            'available_from': str(timezone.localdate() + timedelta(days=1)),
            'available_until': str(timezone.localdate() + timedelta(days=7)),
            'is_active': 'on',
        }
        payload.update(overrides)
        return payload

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

    def test_verify_otp_creates_vendor_without_promotions_field(self):
        document = SimpleUploadedFile(
            'verification.pdf',
            b'fake verification payload',
            content_type='application/pdf',
        )

        response = self.client.post(
            reverse('vendor_register'),
            data={
                'business_name': 'OTP Treks',
                'owner_name': 'Gita Rai',
                'email': 'vendor-otp@example.com',
                'phone': '+9779800000003',
                'password': 'strong-pass-123',
                'confirm_password': 'strong-pass-123',
                'document': document,
            },
        )

        self.assertRedirects(response, reverse('verify_otp'))

        session = self.client.session
        otp_code = session['_reg_otp_code']

        with self.settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            verify_response = self.client.post(
                reverse('verify_otp'),
                data={'otp_code': otp_code},
            )

        user = User.objects.get(email='vendor-otp@example.com')

        self.assertEqual(verify_response.status_code, 302)
        self.assertEqual(user.user_type, 'vendor')
        self.assertTrue(user.is_verified)

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

    def test_vendor_profile_post_does_not_change_email(self):
        vendor = User.objects.create_user(
            username='profile-vendor@example.com',
            email='profile-vendor@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_verified=True,
        )
        VendorProfile.objects.create(
            user=vendor,
            business_name='Profile Treks',
            owner_name='Profile Owner',
            is_approved=True,
        )
        self.client.force_login(vendor)

        response = self.client.post(
            reverse('vendor_profile'),
            data={
                'business_name': 'Profile Treks Updated',
                'owner_name': 'Profile Owner',
                'tagline': 'Updated tagline',
                'license_number': '',
                'business_address': '',
                'description': '',
                'phone': '9800000000',
                'email': 'changed-email@example.com',
            },
            follow=True,
        )

        vendor.refresh_from_db()
        vendor.vendor_profile.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Profile updated successfully.')
        self.assertEqual(vendor.email, 'profile-vendor@example.com')
        self.assertEqual(vendor.username, 'profile-vendor@example.com')
        self.assertEqual(vendor.phone, '9800000000')
        self.assertEqual(vendor.vendor_profile.business_name, 'Profile Treks Updated')

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

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Your account has not been Approved yet')

    def test_suspended_vendor_login_shows_suspended_message(self):
        vendor = User.objects.create_user(
            username='suspended-login@example.com',
            email='suspended-login@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_verified=True,
            is_active=False,
        )
        VendorProfile.objects.create(
            user=vendor,
            business_name='Suspended Login Treks',
            owner_name='Owner Suspended Login',
            is_approved=True,
        )

        response = self.client.post(
            reverse('vendor_login'),
            data={
                'email': 'suspended-login@example.com',
                'password': 'vendor-pass-123',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Your account has been suspend')

    def test_vendor_booking_status_filter_uses_completed_mapping(self):
        vendor = User.objects.create_user(
            username='booking-filter-vendor@example.com',
            email='booking-filter-vendor@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_verified=True,
        )
        VendorProfile.objects.create(
            user=vendor,
            business_name='Filter Treks',
            owner_name='Owner Filter',
            is_approved=True,
        )
        traveler = User.objects.create_user(
            username='booking-filter-traveler@example.com',
            email='booking-filter-traveler@example.com',
            password='traveler-pass-123',
            user_type='traveler',
            is_verified=True,
        )
        pending_package = Package.objects.create(vendor=vendor, title='Pending Filter Package', available_slots=5, price=1000)
        confirmed_package = Package.objects.create(vendor=vendor, title='Completed Filter Package', available_slots=5, price=1000)
        Booking.objects.create(
            package=pending_package,
            traveler=traveler,
            vendor=vendor,
            number_of_people=2,
            travel_date='2026-04-20',
            status=Booking.STATUS_PENDING,
            payment_status=Booking.PAYMENT_STATUS_PENDING,
        )
        Booking.objects.create(
            package=confirmed_package,
            traveler=traveler,
            vendor=vendor,
            number_of_people=2,
            travel_date='2026-04-21',
            status=Booking.STATUS_CONFIRMED,
            payment_status=Booking.PAYMENT_STATUS_COMPLETED,
        )
        self.client.force_login(vendor)

        response = self.client.get(reverse('vendor_bookings'), data={'status': 'completed'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Completed Filter Package')
        self.assertNotContains(response, 'Pending Filter Package')

    def test_vendor_package_create_rejects_latitude_out_of_range(self):
        vendor = User.objects.create_user(
            username='lat-vendor@example.com',
            email='lat-vendor@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_verified=True,
        )
        VendorProfile.objects.create(
            user=vendor,
            business_name='Lat Guard Treks',
            owner_name='Owner Lat Guard',
            is_approved=True,
        )
        self.client.force_login(vendor)

        response = self.client.post(
            reverse('vendor_package_create'),
            data=self._valid_vendor_package_payload(latitude='95'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Latitude must be between -90 and 90.')
        self.assertFalse(Package.objects.filter(vendor=vendor, title='Coordinate Validation Trek').exists())

    def test_vendor_package_create_rejects_longitude_out_of_range(self):
        vendor = User.objects.create_user(
            username='lng-vendor@example.com',
            email='lng-vendor@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_verified=True,
        )
        VendorProfile.objects.create(
            user=vendor,
            business_name='Lng Guard Treks',
            owner_name='Owner Lng Guard',
            is_approved=True,
        )
        self.client.force_login(vendor)

        response = self.client.post(
            reverse('vendor_package_create'),
            data=self._valid_vendor_package_payload(longitude='195'),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Longitude must be between -180 and 180.')
        self.assertFalse(Package.objects.filter(vendor=vendor, title='Coordinate Validation Trek').exists())

    def test_vendor_package_create_rejects_available_from_after_available_until(self):
        vendor = User.objects.create_user(
            username='date-vendor@example.com',
            email='date-vendor@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_verified=True,
        )
        VendorProfile.objects.create(
            user=vendor,
            business_name='Date Guard Treks',
            owner_name='Owner Date Guard',
            is_approved=True,
        )
        self.client.force_login(vendor)

        response = self.client.post(
            reverse('vendor_package_create'),
            data=self._valid_vendor_package_payload(
                available_from=str(timezone.localdate() + timedelta(days=8)),
                available_until=str(timezone.localdate() + timedelta(days=2)),
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Available from date cannot be later than available until date.')
        self.assertFalse(Package.objects.filter(vendor=vendor, title='Coordinate Validation Trek').exists())

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

    def test_admin_can_suspend_traveler_and_view_name_email_in_customers_list(self):
        admin = User.objects.create_user(
            username='admin-suspend-traveler@example.com',
            email='admin-suspend-traveler@example.com',
            password='admin-pass-123',
            user_type='admin',
            is_staff=True,
            is_active=True,
        )
        traveler = User.objects.create_user(
            username='traveler-suspend@example.com',
            email='traveler-suspend@example.com',
            password='traveler-pass-123',
            user_type='traveler',
            first_name='Hari',
            last_name='Sharma',
            is_active=True,
        )
        self.client.force_login(admin)

        response = self.client.post(
            reverse('admin_traveler_action', args=[traveler.id]),
            data={
                'action': 'suspend',
                'next': f"{reverse('admin_dashboard')}#users",
            },
        )

        traveler.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], f"{reverse('admin_dashboard')}#users")
        self.assertFalse(traveler.is_active)

        dashboard_response = self.client.get(reverse('admin_dashboard'))
        self.assertContains(dashboard_response, 'Hari Sharma')
        self.assertContains(dashboard_response, 'traveler-suspend@example.com')
        self.assertContains(dashboard_response, 'Activate')

    def test_admin_can_activate_traveler_from_customers_list(self):
        admin = User.objects.create_user(
            username='admin-activate-traveler@example.com',
            email='admin-activate-traveler@example.com',
            password='admin-pass-123',
            user_type='admin',
            is_staff=True,
            is_active=True,
        )
        traveler = User.objects.create_user(
            username='traveler-activate@example.com',
            email='traveler-activate@example.com',
            password='traveler-pass-123',
            user_type='traveler',
            is_active=False,
        )
        self.client.force_login(admin)

        response = self.client.post(
            reverse('admin_traveler_action', args=[traveler.id]),
            data={
                'action': 'activate',
                'next': f"{reverse('admin_dashboard')}#users",
            },
        )

        traveler.refresh_from_db()
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], f"{reverse('admin_dashboard')}#users")
        self.assertTrue(traveler.is_active)

    def test_admin_dashboard_reviews_section_lists_all_traveler_reviews(self):
        admin = User.objects.create_user(
            username='admin-reviews@example.com',
            email='admin-reviews@example.com',
            password='admin-pass-123',
            user_type='admin',
            is_staff=True,
            is_active=True,
        )
        vendor = User.objects.create_user(
            username='vendor-reviews@example.com',
            email='vendor-reviews@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_active=True,
        )
        traveler = User.objects.create_user(
            username='traveler-reviews@example.com',
            email='traveler-reviews@example.com',
            password='traveler-pass-123',
            user_type='traveler',
            first_name='Sita',
            last_name='Rai',
        )
        package = Package.objects.create(
            vendor=vendor,
            title='Annapurna Base Camp Trek',
            location='Annapurna',
            price='15000.00',
            available_slots=10,
            available_from=timezone.localdate() - timedelta(days=2),
            available_until=timezone.localdate() + timedelta(days=60),
            is_active=True,
        )
        Review.objects.create(
            package=package,
            traveler=traveler,
            rating=5,
            comment='Amazing guide and very well organized trek.',
        )
        self.client.force_login(admin)

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'All Traveler Reviews')
        self.assertContains(response, 'Sita Rai')
        self.assertContains(response, 'traveler-reviews@example.com')
        self.assertContains(response, 'Annapurna Base Camp Trek')
        self.assertContains(response, '5/5')


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


class FeaturePlanEnforcementTests(TestCase):
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

    def test_vendor_cannot_feature_package_without_subscription(self):
        self.client.force_login(self.vendor)

        response = self.client.post(
            reverse('vendor_feature_toggle', args=[self.package_one.id]),
            data={'next': reverse('vendor_packages')},
            follow=True,
        )

        self.assertFalse(self.package_one.is_featured)
        self.assertContains(response, 'active feature plan')

    def test_vendor_cannot_exceed_subscription_slots(self):
        plan = FeaturePlan.objects.create(
            name='Basic',
            slots_count=1,
            price='5000.00',
            duration_days=30,
            is_active=True,
        )
        subscription = VendorFeatureSubscription.objects.create(
            vendor=self.vendor,
            plan=plan,
            plan_name=plan.name,
            slots_total=1,
            price=plan.price,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=29),
            payment_status=VendorFeatureSubscription.PAYMENT_STATUS_PAID,
            payment_method=VendorFeatureSubscription.PAYMENT_METHOD_ESEWA,
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

        self.assertTrue(self.package_one.is_featured)
        self.assertFalse(self.package_two.is_featured)
        self.assertContains(first, 'featured')
        self.assertContains(second, 'slots are in use')

    def test_expired_subscription_creates_vendor_notification_once(self):
        plan = FeaturePlan.objects.create(
            name='Starter',
            slots_count=1,
            price='2500.00',
            duration_days=7,
            is_active=True,
        )
        subscription = VendorFeatureSubscription.objects.create(
            vendor=self.vendor,
            plan=plan,
            plan_name=plan.name,
            slots_total=plan.slots_count,
            price=plan.price,
            start_date=timezone.localdate() - timedelta(days=10),
            end_date=timezone.localdate() - timedelta(days=1),
            payment_status=VendorFeatureSubscription.PAYMENT_STATUS_PAID,
            payment_method=VendorFeatureSubscription.PAYMENT_METHOD_ESEWA,
            is_active=True,
        )

        expired_ids = VendorFeatureSubscription.expire_overdue(vendor=self.vendor)
        self.assertIn(subscription.id, expired_ids)

        subscription.refresh_from_db()
        self.assertFalse(subscription.is_active)

        notifications = Notification.objects.filter(
            user=self.vendor,
            type=Notification.TYPE_SUBSCRIPTION,
            related_object_id=subscription.id,
        )
        self.assertEqual(notifications.count(), 1)
        self.assertIn('has expired', notifications.first().message)

        # Re-running should not duplicate since subscription is already inactive.
        VendorFeatureSubscription.expire_overdue(vendor=self.vendor)
        self.assertEqual(
            Notification.objects.filter(
                user=self.vendor,
                type=Notification.TYPE_SUBSCRIPTION,
                related_object_id=subscription.id,
            ).count(),
            1,
        )


class TransactionCommissionSplitTests(TestCase):
    def setUp(self):
        self.vendor = User.objects.create_user(
            username='commission-vendor@example.com',
            email='commission-vendor@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_verified=True,
        )
        VendorProfile.objects.create(
            user=self.vendor,
            business_name='Commission Vendor',
            owner_name='Commission Owner',
            is_approved=True,
        )
        self.traveler = User.objects.create_user(
            username='commission-traveler@example.com',
            email='commission-traveler@example.com',
            password='traveler-pass-123',
            user_type='traveler',
            is_verified=True,
        )
        TravelerProfile.objects.create(user=self.traveler)
        self.package = Package.objects.create(
            vendor=self.vendor,
            title='Commission Check Package',
            available_slots=10,
            price='8000.00',
            is_active=True,
        )

    def test_booking_transaction_keeps_configured_commission_split(self):
        from core.services.site_settings import calculate_commission_split

        booking = Booking.objects.create(
            package=self.package,
            traveler=self.traveler,
            vendor=self.vendor,
            number_of_people=1,
            travel_date=timezone.localdate() + timedelta(days=7),
            status=Booking.STATUS_CONFIRMED,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
            payment_status=Booking.PAYMENT_STATUS_COMPLETED,
            total_price='0',
        )
        transaction = Transaction.objects.create(
            transaction_type=Transaction.TYPE_BOOKING,
            booking=booking,
            traveler=self.traveler,
            vendor=self.vendor,
            total_amount=booking.total_price,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
            payment_status=Booking.PAYMENT_STATUS_COMPLETED,
        )

        expected_vendor, expected_platform = calculate_commission_split(transaction.total_amount)

        self.assertEqual(transaction.vendor_earnings, expected_vendor)
        self.assertEqual(transaction.platform_fee, expected_platform)

    def test_feature_subscription_transaction_routes_full_amount_to_admin(self):
        plan = FeaturePlan.objects.create(
            name='Commission Plan',
            slots_count=3,
            price='2500.00',
            duration_days=30,
            is_active=True,
        )
        subscription = VendorFeatureSubscription.objects.create(
            vendor=self.vendor,
            plan=plan,
            plan_name=plan.name,
            slots_total=plan.slots_count,
            price=plan.price,
            start_date=timezone.localdate(),
            end_date=timezone.localdate() + timedelta(days=29),
            payment_status=VendorFeatureSubscription.PAYMENT_STATUS_PAID,
            payment_method=VendorFeatureSubscription.PAYMENT_METHOD_ESEWA,
            is_active=True,
        )
        transaction = Transaction.objects.create(
            transaction_type=Transaction.TYPE_FEATURE_SUBSCRIPTION,
            feature_subscription=subscription,
            vendor=self.vendor,
            total_amount=plan.price,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
            payment_status=Booking.PAYMENT_STATUS_COMPLETED,
        )

        self.assertEqual(transaction.vendor_earnings, Decimal('0.00'))
        self.assertEqual(transaction.platform_fee, transaction.total_amount)


class TransactionFiltersTests(TestCase):
    def setUp(self):
        self.vendor = User.objects.create_user(
            username='tx-vendor@example.com',
            email='tx-vendor@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_verified=True,
        )
        VendorProfile.objects.create(
            user=self.vendor,
            business_name='Transaction Vendor',
            owner_name='Tx Owner',
            is_approved=True,
        )
        self.traveler = User.objects.create_user(
            username='tx-traveler@example.com',
            email='tx-traveler@example.com',
            password='traveler-pass-123',
            user_type='traveler',
            is_verified=True,
        )
        TravelerProfile.objects.create(user=self.traveler)
        self.package = Package.objects.create(
            vendor=self.vendor,
            title='Transaction Filter Package',
            available_slots=10,
            price='4500.00',
            is_active=True,
        )

    def _create_transaction(self, payment_status):
        booking_status = (
            Booking.STATUS_CONFIRMED
            if payment_status == Booking.PAYMENT_STATUS_COMPLETED
            else Booking.STATUS_PENDING
        )
        booking = Booking.objects.create(
            package=self.package,
            traveler=self.traveler,
            vendor=self.vendor,
            number_of_people=1,
            travel_date=timezone.localdate() + timedelta(days=5),
            status=booking_status,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
            payment_status=payment_status,
            total_price='0',
        )
        return Transaction.objects.create(
            booking=booking,
            traveler=self.traveler,
            vendor=self.vendor,
            total_amount='4500.00',
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
            payment_status=payment_status,
        )

    def test_traveler_transactions_show_completed_only_and_hide_status_filter(self):
        completed_tx = self._create_transaction(Booking.PAYMENT_STATUS_COMPLETED)
        self._create_transaction(Booking.PAYMENT_STATUS_PENDING)

        self.client.force_login(self.traveler)
        response = self.client.get(reverse('traveler_transactions'), data={'status': 'pending'})

        self.assertEqual(response.status_code, 200)
        transactions = list(response.context['transactions'])
        self.assertEqual([tx.id for tx in transactions], [completed_tx.id])
        self.assertEqual(response.context['filters']['status'], '')
        self.assertNotContains(response, 'name="status"')

    def test_traveler_transactions_invalid_date_filter_shows_error(self):
        self._create_transaction(Booking.PAYMENT_STATUS_COMPLETED)

        self.client.force_login(self.traveler)
        response = self.client.get(
            reverse('traveler_transactions'),
            data={
                'date_from': (timezone.localdate() + timedelta(days=2)).isoformat(),
                'date_to': (timezone.localdate() - timedelta(days=2)).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['filters']['date_error'], 'From date cannot be in the future.')
        self.assertContains(response, 'From date cannot be in the future.')

    def test_vendor_transactions_invalid_date_filter_shows_error(self):
        self._create_transaction(Booking.PAYMENT_STATUS_COMPLETED)

        self.client.force_login(self.vendor)
        response = self.client.get(
            reverse('vendor_transactions'),
            data={
                'date_from': (timezone.localdate() + timedelta(days=2)).isoformat(),
                'date_to': (timezone.localdate() - timedelta(days=2)).isoformat(),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['filters']['date_error'], 'From date cannot be in the future.')
        self.assertContains(response, 'From date cannot be in the future.')


class RoleRouteAccessControlTests(TestCase):
    def setUp(self):
        self.traveler = User.objects.create_user(
            username='role-traveler@example.com',
            email='role-traveler@example.com',
            password='traveler-pass-123',
            user_type='traveler',
            is_verified=True,
        )
        TravelerProfile.objects.create(user=self.traveler)

        self.vendor = User.objects.create_user(
            username='role-vendor@example.com',
            email='role-vendor@example.com',
            password='vendor-pass-123',
            user_type='vendor',
            is_verified=True,
        )
        VendorProfile.objects.create(
            user=self.vendor,
            business_name='Role Vendor',
            owner_name='Role Owner',
            is_approved=True,
        )

        self.admin = User.objects.create_user(
            username='role-admin@example.com',
            email='role-admin@example.com',
            password='admin-pass-123',
            user_type='admin',
            is_staff=True,
            is_superuser=True,
            is_verified=True,
        )
        AdminProfile.objects.create(user=self.admin)

    def test_anonymous_users_are_redirected_to_role_login_pages(self):
        traveler_response = self.client.get(reverse('traveler_home'))
        vendor_response = self.client.get(reverse('vendor_dashboard'))
        admin_response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(traveler_response.status_code, 302)
        self.assertIn(reverse('traveler_login'), traveler_response.url)

        self.assertEqual(vendor_response.status_code, 302)
        self.assertIn(reverse('vendor_login'), vendor_response.url)

        self.assertEqual(admin_response.status_code, 302)
        self.assertEqual(admin_response.url, reverse('admin_login'))

    def test_traveler_cannot_access_vendor_or_admin_pages(self):
        self.client.force_login(self.traveler)

        vendor_response = self.client.get(reverse('vendor_dashboard'))
        admin_response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(vendor_response.status_code, 403)
        self.assertEqual(admin_response.status_code, 403)

    def test_vendor_cannot_access_traveler_or_admin_pages(self):
        self.client.force_login(self.vendor)

        traveler_response = self.client.get(reverse('traveler_home'))
        admin_response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(traveler_response.status_code, 403)
        self.assertEqual(admin_response.status_code, 403)

    def test_admin_cannot_access_vendor_or_traveler_restricted_pages(self):
        self.client.force_login(self.admin)

        traveler_response = self.client.get(reverse('traveler_home'))
        vendor_response = self.client.get(reverse('vendor_dashboard'))

        self.assertEqual(traveler_response.status_code, 403)
        self.assertEqual(vendor_response.status_code, 403)
