from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User
from .models import Booking, Package
from .payments import StripeError


class PublicNavigationAccessTests(TestCase):
    def setUp(self):
        self.traveler = User.objects.create_user(
            username='traveler_nav',
            password='traveler-pass-123',
            email='traveler-nav@example.com',
            user_type='traveler',
        )
        self.vendor = User.objects.create_user(
            username='vendor_nav',
            password='vendor-pass-123',
            email='vendor-nav@example.com',
            user_type='vendor',
        )
        self.admin = User.objects.create_user(
            username='admin_nav',
            password='admin-pass-123',
            email='admin-nav@example.com',
            user_type='admin',
            is_staff=True,
        )

    def _assert_public_pages_accessible(self):
        public_urls = (
            reverse('home'),
            reverse('home_page'),
            reverse('package_list'),
            reverse('explore_map'),
            reverse('community_feed'),
        )
        for url in public_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, msg=f'Expected 200 for {url}')

    def test_traveler_can_access_public_pages_while_logged_in(self):
        self.client.force_login(self.traveler)
        self._assert_public_pages_accessible()

    def test_vendor_can_access_public_pages_while_logged_in(self):
        self.client.force_login(self.vendor)
        self._assert_public_pages_accessible()

    def test_admin_can_access_public_pages_while_logged_in(self):
        self.client.force_login(self.admin)
        self._assert_public_pages_accessible()


class CommunityPostComposerVisibilityTests(TestCase):
    def setUp(self):
        self.traveler = User.objects.create_user(
            username='traveler_composer',
            password='traveler-pass-123',
            email='traveler-composer@example.com',
            user_type='traveler',
        )

    def test_public_explore_hides_post_composer_for_guest(self):
        response = self.client.get(reverse('community_feed'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Create a Post')
        self.assertNotContains(response, 'Upload Photos / Videos')
        self.assertNotContains(response, 'Tag Vendors')

    def test_public_explore_hides_post_composer_for_logged_in_user(self):
        self.client.force_login(self.traveler)
        response = self.client.get(reverse('community_feed'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Create a Post')
        self.assertNotContains(response, 'Upload Photos / Videos')
        self.assertNotContains(response, 'Tag Vendors')

    def test_dashboard_community_shows_post_composer_for_logged_in_traveler(self):
        self.client.force_login(self.traveler)
        response = self.client.get(reverse('community_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Create a Post')
        self.assertContains(response, 'Upload Photos / Videos')
        self.assertContains(response, 'Tag Vendors')


class BookingStripeFlowTests(TestCase):
    def setUp(self):
        self.vendor = User.objects.create_user(
            username='vendor_user',
            password='vendor-pass-123',
            email='vendor@example.com',
            user_type='vendor',
        )
        self.traveler = User.objects.create_user(
            username='traveler_user',
            password='traveler-pass-123',
            email='traveler@example.com',
            user_type='traveler',
        )
        self.package = Package.objects.create(
            vendor=self.vendor,
            title='Everest Base Camp Trek',
            location='Khumbu',
            price='15000.00',
            available_slots=5,
            available_from=timezone.localdate() - timedelta(days=1),
            available_until=timezone.localdate() + timedelta(days=30),
            is_active=True,
        )
        self.travel_date = timezone.localdate() + timedelta(days=10)

    def _create_pending_booking(self):
        booking = Booking.objects.create(
            package=self.package,
            traveler=self.traveler,
            number_of_people=2,
            travel_date=self.travel_date,
            special_notes='Window seat if available.',
            status=Booking.STATUS_PAYMENT_PENDING,
            payment_method=Booking.PAYMENT_METHOD_STRIPE,
            payment_status=Booking.PAYMENT_STATUS_PENDING,
            stripe_checkout_session_id='cs_test_123',
            payment_reference='cs_test_123',
            payment_expires_at=timezone.now() + timedelta(minutes=30),
            total_price='0',
        )
        self.package.available_slots = 3
        self.package.save(update_fields=['available_slots'])
        return booking

    @patch('core.views.create_checkout_session')
    def test_package_book_redirects_to_stripe_checkout(self, mock_create_checkout_session):
        mock_create_checkout_session.return_value = {
            'id': 'cs_test_123',
            'url': 'https://checkout.stripe.com/c/pay/cs_test_123',
        }
        self.client.force_login(self.traveler)

        response = self.client.post(
            reverse('package_book', args=[self.package.id]),
            data={
                'number_of_people': 2,
                'travel_date': self.travel_date.isoformat(),
                'special_notes': 'Vegetarian meals',
                'payment_method': Booking.PAYMENT_METHOD_STRIPE,
            },
        )

        self.assertRedirects(
            response,
            'https://checkout.stripe.com/c/pay/cs_test_123',
            fetch_redirect_response=False,
        )
        booking = Booking.objects.get()
        self.package.refresh_from_db()

        self.assertEqual(booking.status, Booking.STATUS_PAYMENT_PENDING)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_PENDING)
        self.assertEqual(booking.payment_method, Booking.PAYMENT_METHOD_STRIPE)
        self.assertEqual(booking.stripe_checkout_session_id, 'cs_test_123')
        self.assertEqual(self.package.available_slots, 3)

    @patch('core.views.create_checkout_session', side_effect=StripeError('Stripe unavailable.'))
    def test_package_book_restores_slots_when_checkout_creation_fails(self, _mock_create_checkout_session):
        self.client.force_login(self.traveler)

        response = self.client.post(
            reverse('package_book', args=[self.package.id]),
            data={
                'number_of_people': 2,
                'travel_date': self.travel_date.isoformat(),
                'special_notes': 'Vegetarian meals',
                'payment_method': Booking.PAYMENT_METHOD_STRIPE,
            },
        )

        booking = Booking.objects.get()
        self.package.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Stripe unavailable.')
        self.assertEqual(booking.status, Booking.STATUS_CANCELLED)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_CANCELLED)
        self.assertEqual(self.package.available_slots, 5)

    @patch('core.views.retrieve_checkout_session')
    def test_booking_confirmation_marks_booking_paid_after_verification(self, mock_retrieve_checkout_session):
        booking = self._create_pending_booking()
        mock_retrieve_checkout_session.return_value = {
            'id': 'cs_test_123',
            'status': 'complete',
            'payment_status': 'paid',
            'client_reference_id': str(booking.id),
            'payment_intent': 'pi_test_123',
        }
        self.client.force_login(self.traveler)

        response = self.client.get(
            reverse('booking_confirmation', args=[booking.id]),
            data={'session_id': 'cs_test_123'},
        )

        booking.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(booking.status, Booking.STATUS_PENDING)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_PAID)
        self.assertEqual(booking.payment_reference, 'pi_test_123')
        self.assertIsNotNone(booking.paid_at)

    @patch('core.views.expire_checkout_session')
    def test_booking_checkout_cancel_releases_slots(self, mock_expire_checkout_session):
        booking = self._create_pending_booking()
        self.client.force_login(self.traveler)

        response = self.client.get(reverse('booking_checkout_cancel', args=[booking.id]))

        booking.refresh_from_db()
        self.package.refresh_from_db()

        self.assertRedirects(response, reverse('package_book', args=[self.package.id]))
        self.assertEqual(booking.status, Booking.STATUS_CANCELLED)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_CANCELLED)
        self.assertEqual(self.package.available_slots, 5)
        mock_expire_checkout_session.assert_called_once_with('cs_test_123')

    def test_vendor_cannot_confirm_unpaid_booking(self):
        booking = self._create_pending_booking()
        self.client.force_login(self.vendor)

        response = self.client.post(
            reverse('vendor_booking_status_update', args=[booking.id]),
            data={'status': 'confirmed'},
        )

        booking.refresh_from_db()

        self.assertRedirects(response, reverse('vendor_bookings'))
        self.assertEqual(booking.status, Booking.STATUS_PAYMENT_PENDING)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_PENDING)
