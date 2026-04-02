from datetime import timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Badge, Notification, RewardPoint, TravelerProfile, User, UserBadge, VendorProfile
from .models import Booking, ContactMessage, Discount, Package, PackageImage, Post, Review, SupportConversation, SupportMessage
from .payments import StripeError
from .views import _complete_paid_booking


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


class TaggedVendorDisplayTests(TestCase):
    def setUp(self):
        self.traveler = User.objects.create_user(
            username='traveler_tag_feed',
            password='traveler-pass-123',
            email='traveler-tag-feed@example.com',
            user_type='traveler',
        )
        self.vendor = User.objects.create_user(
            username='vendor-tag-feed@example.com',
            password='vendor-pass-123',
            email='vendor-tag-feed@example.com',
            user_type='vendor',
        )
        VendorProfile.objects.create(
            user=self.vendor,
            business_name='Himalayan Horizon Treks',
            owner_name='Vendor Owner',
        )
        self.post = Post.objects.create(
            user=self.traveler,
            caption='Just returned from an incredible trip.',
        )
        self.post.tagged_vendors.add(self.vendor)

    def test_tagged_vendor_uses_company_name_not_email(self):
        response = self.client.get(reverse('community_feed'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Himalayan Horizon Treks')
        self.assertNotContains(response, 'vendor-tag-feed@example.com')


class PackageMapApiTests(TestCase):
    def setUp(self):
        self.vendor = User.objects.create_user(
            username='map_vendor',
            password='vendor-pass-123',
            email='map-vendor@example.com',
            user_type='vendor',
        )
        self.package = Package.objects.create(
            vendor=self.vendor,
            title='Langtang Valley Trek',
            location_name='Langtang',
            latitude=28.211,
            longitude=85.558,
            description='A scenic Himalayan route.',
            price='1200.00',
            available_slots=6,
            available_from=timezone.localdate() - timedelta(days=3),
            available_until=timezone.localdate() + timedelta(days=20),
            is_active=True,
        )

    def test_packages_map_api_includes_details_endpoint_url(self):
        response = self.client.get(reverse('packages_map_api'))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(len(payload), 1)
        package_data = payload[0]
        self.assertEqual(package_data['id'], self.package.id)
        self.assertEqual(
            package_data['details_url'],
            reverse('package_details_api', args=[self.package.id]),
        )

    def test_package_details_api_returns_uploaded_images(self):
        with TemporaryDirectory() as media_root:
            with self.settings(MEDIA_ROOT=media_root):
                package = Package.objects.create(
                    vendor=self.vendor,
                    title='Annapurna Circuit Trek',
                    location_name='Annapurna',
                    latitude=28.598,
                    longitude=83.931,
                    description='Classic multi-day trekking package.',
                    price='1500.00',
                    available_slots=8,
                    available_from=timezone.localdate() - timedelta(days=2),
                    available_until=timezone.localdate() + timedelta(days=25),
                    is_active=True,
                )
                PackageImage.objects.create(
                    package=package,
                    image=SimpleUploadedFile(
                        'annapurna-one.jpg',
                        b'fake-image-data-1',
                        content_type='image/jpeg',
                    ),
                    order=1,
                )
                PackageImage.objects.create(
                    package=package,
                    image=SimpleUploadedFile(
                        'annapurna-two.jpg',
                        b'fake-image-data-2',
                        content_type='image/jpeg',
                    ),
                    order=2,
                )

                response = self.client.get(reverse('package_details_api', args=[package.id]))

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['name'], 'Annapurna Circuit Trek')
        self.assertEqual(payload['description'], 'Classic multi-day trekking package.')
        self.assertEqual(len(payload['images']), 2)

    def test_package_details_api_hides_inactive_package(self):
        self.package.is_active = False
        self.package.save(update_fields=['is_active'])

        response = self.client.get(reverse('package_details_api', args=[self.package.id]))

        self.assertEqual(response.status_code, 404)


class ContactPageTests(TestCase):
    @patch('core.views.package_views.send_mail')
    def test_contact_submit_saves_message_and_sends_admin_email(self, mock_send_mail):
        response = self.client.post(
            reverse('contact'),
            data={
                'full_name': 'Contact Tester',
                'email': 'contact.tester@example.com',
                'subject': 'Need itinerary help',
                'message': 'Can you help plan a 7-day Annapurna trip?',
            },
            follow=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Message sent successfully')
        self.assertEqual(ContactMessage.objects.count(), 1)
        saved_message = ContactMessage.objects.first()
        self.assertEqual(saved_message.subject, 'Need itinerary help')
        self.assertEqual(saved_message.email, 'contact.tester@example.com')
        mock_send_mail.assert_called_once()

    @patch('core.views.package_views.send_mail')
    def test_contact_submit_skips_email_when_no_recipient_configured(self, mock_send_mail):
        with self.settings(CONTACT_RECEIVER_EMAIL='', CONTACT_RECEIVER_EMAILS=[], EMAIL_HOST_USER=''):
            response = self.client.post(
                reverse('contact'),
                data={
                    'full_name': 'No Recipient Tester',
                    'email': 'norecipient@example.com',
                    'subject': 'General inquiry',
                    'message': 'Testing fallback behavior.',
                },
                follow=True,
            )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Message sent successfully')
        self.assertEqual(ContactMessage.objects.count(), 1)
        mock_send_mail.assert_not_called()


class BookingStripeFlowTests(TestCase):
    def setUp(self):
        self.vendor = User.objects.create_user(
            username='vendor_user',
            password='vendor-pass-123',
            email='vendor@example.com',
            user_type='vendor',
        )
        self.admin = User.objects.create_user(
            username='admin_user',
            password='admin-pass-123',
            email='admin@example.com',
            user_type='admin',
            is_staff=True,
        )
        self.traveler = User.objects.create_user(
            username='traveler_user',
            password='traveler-pass-123',
            email='traveler@example.com',
            user_type='traveler',
        )
        self.other_traveler = User.objects.create_user(
            username='other_traveler',
            password='traveler-pass-123',
            email='other-traveler@example.com',
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
            status=Booking.STATUS_PENDING,
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

    def _create_paid_booking(self):
        booking = self._create_pending_esewa_booking()
        booking.status = Booking.STATUS_CONFIRMED
        booking.payment_status = Booking.PAYMENT_STATUS_COMPLETED
        booking.payment_method = Booking.PAYMENT_METHOD_ESEWA
        booking.paid_amount = booking.total_price
        booking.paid_at = timezone.now()
        booking.payment_expires_at = None
        booking.save(
            update_fields=[
                'status',
                'payment_status',
                'payment_method',
                'paid_amount',
                'paid_at',
                'payment_expires_at',
            ]
        )
        return booking

    def _create_pending_esewa_booking(self):
        booking = Booking.objects.create(
            package=self.package,
            traveler=self.traveler,
            number_of_people=2,
            travel_date=self.travel_date,
            special_notes='Need pickup from airport.',
            status=Booking.STATUS_PENDING,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
            payment_status=Booking.PAYMENT_STATUS_PENDING,
            payment_expires_at=timezone.now() + timedelta(minutes=30),
            total_price='0',
        )
        self.package.available_slots = 3
        self.package.save(update_fields=['available_slots'])
        return booking

    @patch('core.views.booking_views.create_checkout_session')
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

        self.assertEqual(booking.status, Booking.STATUS_PENDING)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_PENDING)
        self.assertEqual(booking.payment_method, Booking.PAYMENT_METHOD_STRIPE)
        self.assertEqual(booking.stripe_checkout_session_id, 'cs_test_123')
        self.assertEqual(self.package.available_slots, 3)

    @patch('core.views.booking_views.create_checkout_session', side_effect=StripeError('Stripe unavailable.'))
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
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_FAILED)
        self.assertEqual(self.package.available_slots, 5)

    @patch('core.views.booking_views.retrieve_checkout_session')
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
        self.assertEqual(booking.status, Booking.STATUS_CONFIRMED)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_COMPLETED)
        self.assertEqual(booking.payment_reference, 'pi_test_123')
        self.assertIsNotNone(booking.paid_at)

    @patch('core.views.booking_views.expire_checkout_session')
    def test_booking_checkout_cancel_releases_slots(self, mock_expire_checkout_session):
        booking = self._create_pending_booking()
        self.client.force_login(self.traveler)

        response = self.client.get(reverse('booking_checkout_cancel', args=[booking.id]))

        booking.refresh_from_db()
        self.package.refresh_from_db()

        self.assertRedirects(response, reverse('package_book', args=[self.package.id]))
        self.assertEqual(booking.status, Booking.STATUS_CANCELLED)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_FAILED)
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
        self.assertEqual(booking.status, Booking.STATUS_PENDING)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_PENDING)

    def test_package_book_renders_esewa_checkout_form(self):
        self.client.force_login(self.traveler)

        response = self.client.post(
            reverse('package_book', args=[self.package.id]),
            data={
                'number_of_people': 2,
                'travel_date': self.travel_date.isoformat(),
                'special_notes': 'Vegetarian meals',
                'payment_method': Booking.PAYMENT_METHOD_ESEWA,
            },
        )

        booking = Booking.objects.get()
        self.package.refresh_from_db()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'rc-epay.esewa.com.np/api/epay/main/v2/form')
        self.assertContains(response, 'name="transaction_uuid"', html=False)
        self.assertContains(response, f'value="{booking.id}"', html=False)
        self.assertEqual(booking.status, Booking.STATUS_PENDING)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_PENDING)
        self.assertEqual(booking.payment_method, Booking.PAYMENT_METHOD_ESEWA)
        self.assertEqual(self.package.available_slots, 3)

    def test_package_book_reuses_existing_pending_booking_for_esewa(self):
        pending_booking = self._create_pending_esewa_booking()
        self.client.force_login(self.traveler)

        response = self.client.post(
            reverse('package_book', args=[self.package.id]),
            data={
                'number_of_people': 2,
                'travel_date': self.travel_date.isoformat(),
                'special_notes': 'Need pickup from airport.',
                'payment_method': Booking.PAYMENT_METHOD_ESEWA,
            },
        )

        self.package.refresh_from_db()
        booking = Booking.objects.get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(booking.id, pending_booking.id)
        self.assertContains(response, f'value=\"{pending_booking.id}\"', html=False)
        self.assertEqual(booking.status, Booking.STATUS_PENDING)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_PENDING)
        self.assertEqual(self.package.available_slots, 3)

    def test_traveler_bookings_shows_continue_payment_for_unpaid_esewa(self):
        booking = self._create_pending_esewa_booking()
        self.client.force_login(self.traveler)

        response = self.client.get(reverse('traveler_bookings'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Payment Pending')
        self.assertContains(response, reverse('booking_confirmation', args=[booking.id]))
        self.assertContains(response, 'Continue Payment')

    def test_traveler_bookings_shows_continue_payment_for_unpaid_stripe(self):
        booking = self._create_pending_booking()
        self.client.force_login(self.traveler)

        response = self.client.get(reverse('traveler_bookings'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('booking_confirmation', args=[booking.id]))
        self.assertContains(response, 'Continue Payment')

    def test_booking_confirmation_shows_both_payment_options_for_unpaid_booking(self):
        booking = self._create_pending_booking()
        self.client.force_login(self.traveler)

        response = self.client.get(reverse('booking_confirmation', args=[booking.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('booking_stripe_checkout', args=[booking.id]))
        self.assertContains(response, reverse('booking_esewa_checkout', args=[booking.id]))
        self.assertContains(response, 'Pay via Stripe')
        self.assertContains(response, 'Pay via eSewa')

    @patch('core.views.payment_views.create_checkout_session')
    def test_booking_stripe_checkout_redirects_to_gateway(self, mock_create_checkout_session):
        booking = self._create_pending_booking()
        booking.payment_status = Booking.PAYMENT_STATUS_FAILED
        booking.save(update_fields=['payment_status'])
        mock_create_checkout_session.return_value = {
            'id': 'cs_test_retry_456',
            'url': 'https://checkout.stripe.com/c/pay/cs_test_retry_456',
            'payment_intent': 'pi_test_retry_456',
        }
        self.client.force_login(self.traveler)

        response = self.client.get(reverse('booking_stripe_checkout', args=[booking.id]))

        booking.refresh_from_db()
        self.assertRedirects(
            response,
            'https://checkout.stripe.com/c/pay/cs_test_retry_456',
            fetch_redirect_response=False,
        )
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(booking.status, Booking.STATUS_PENDING)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_PENDING)
        self.assertEqual(booking.stripe_checkout_session_id, 'cs_test_retry_456')
        self.assertEqual(booking.payment_reference, 'pi_test_retry_456')

    @patch('core.views.payment_views.create_checkout_session')
    def test_booking_stripe_checkout_refreshes_expired_payment_window(self, mock_create_checkout_session):
        booking = self._create_pending_booking()
        booking.payment_expires_at = timezone.now() - timedelta(minutes=5)
        booking.save(update_fields=['payment_expires_at'])

        def _fake_create_session(*, booking, success_url, cancel_url):
            self.assertGreater(booking.payment_expires_at, timezone.now())
            return {
                'id': 'cs_test_retry_expired',
                'url': 'https://checkout.stripe.com/c/pay/cs_test_retry_expired',
                'payment_intent': 'pi_test_retry_expired',
            }

        mock_create_checkout_session.side_effect = _fake_create_session
        self.client.force_login(self.traveler)

        response = self.client.get(reverse('booking_stripe_checkout', args=[booking.id]))

        booking.refresh_from_db()
        self.assertRedirects(
            response,
            'https://checkout.stripe.com/c/pay/cs_test_retry_expired',
            fetch_redirect_response=False,
        )
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_PENDING)
        self.assertGreater(booking.payment_expires_at, timezone.now())

    @patch('core.views.payment_views.create_checkout_session')
    def test_booking_stripe_checkout_switches_method_from_esewa(self, mock_create_checkout_session):
        booking = self._create_pending_esewa_booking()
        mock_create_checkout_session.return_value = {
            'id': 'cs_test_switch_789',
            'url': 'https://checkout.stripe.com/c/pay/cs_test_switch_789',
            'payment_intent': 'pi_test_switch_789',
        }
        self.client.force_login(self.traveler)

        response = self.client.get(reverse('booking_stripe_checkout', args=[booking.id]))

        booking.refresh_from_db()
        self.assertRedirects(
            response,
            'https://checkout.stripe.com/c/pay/cs_test_switch_789',
            fetch_redirect_response=False,
        )
        self.assertEqual(booking.payment_method, Booking.PAYMENT_METHOD_STRIPE)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_PENDING)
        self.assertEqual(booking.esewa_transaction_id, '')

    def test_booking_esewa_checkout_switches_method_from_stripe(self):
        booking = self._create_pending_booking()
        self.client.force_login(self.traveler)

        response = self.client.get(reverse('booking_esewa_checkout', args=[booking.id]))

        booking.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(booking.payment_method, Booking.PAYMENT_METHOD_ESEWA)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_PENDING)
        self.assertEqual(booking.stripe_checkout_session_id, '')

    def test_package_book_reuses_failed_booking_for_retry(self):
        failed_booking = self._create_pending_esewa_booking()
        failed_booking.payment_status = Booking.PAYMENT_STATUS_FAILED
        failed_booking.save(update_fields=['payment_status'])
        self.client.force_login(self.traveler)

        response = self.client.post(
            reverse('package_book', args=[self.package.id]),
            data={
                'number_of_people': 2,
                'travel_date': self.travel_date.isoformat(),
                'special_notes': 'Need pickup from airport.',
                'payment_method': Booking.PAYMENT_METHOD_ESEWA,
            },
        )

        booking = Booking.objects.get()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Booking.objects.count(), 1)
        self.assertEqual(booking.id, failed_booking.id)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_PENDING)

    @patch('core.views.payment_views.esewa_process_success_callback')
    def test_esewa_success_marks_booking_completed_after_verification(self, mock_callback):
        booking = self._create_pending_esewa_booking()
        mock_callback.return_value = (
            {'transaction_code': 'ESEWA_TXN_123', 'status': 'COMPLETE', 'total_amount': 30000.0, 'transaction_uuid': str(booking.id)},
            {'status': 'COMPLETE', 'ref_id': '0007G36'},
        )
        self.client.force_login(self.traveler)

        import base64, json
        fake_data = base64.b64encode(json.dumps({'status': 'COMPLETE'}).encode()).decode()
        response = self.client.get(
            reverse('booking_esewa_success', args=[booking.id]),
            data={'data': fake_data},
        )

        booking.refresh_from_db()

        self.assertRedirects(response, reverse('booking_confirmation', args=[booking.id]))
        self.assertEqual(booking.status, Booking.STATUS_CONFIRMED)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_COMPLETED)
        self.assertEqual(booking.payment_reference, '0007G36')
        self.assertEqual(booking.esewa_transaction_id, 'ESEWA_TXN_123')
        self.assertEqual(str(booking.paid_amount), '30000.00')

    @patch('core.views.payment_views.esewa_process_success_callback')
    def test_esewa_success_marks_booking_failed_when_amount_mismatch(self, mock_callback):
        from core.services.esewa_service import EsewaError
        mock_callback.side_effect = EsewaError('Amount mismatch: expected 30000.00, got 10.00.')
        booking = self._create_pending_esewa_booking()
        self.client.force_login(self.traveler)

        import base64, json
        fake_data = base64.b64encode(json.dumps({'status': 'COMPLETE'}).encode()).decode()
        response = self.client.get(
            reverse('booking_esewa_success', args=[booking.id]),
            data={'data': fake_data},
        )

        booking.refresh_from_db()

        self.assertRedirects(response, reverse('booking_confirmation', args=[booking.id]))
        self.assertEqual(booking.status, Booking.STATUS_PENDING)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_FAILED)

    def test_esewa_failure_marks_failed_and_allows_retry(self):
        booking = self._create_pending_esewa_booking()
        self.client.force_login(self.traveler)

        response = self.client.get(reverse('booking_esewa_failure', args=[booking.id]))

        booking.refresh_from_db()
        self.package.refresh_from_db()

        self.assertRedirects(response, reverse('booking_confirmation', args=[booking.id]))
        self.assertEqual(booking.status, Booking.STATUS_PENDING)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_FAILED)
        self.assertEqual(self.package.available_slots, 3)

        retry_response = self.client.get(reverse('booking_esewa_checkout', args=[booking.id]))
        booking.refresh_from_db()
        self.assertEqual(retry_response.status_code, 200)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_PENDING)

    def test_invoice_download_available_for_paid_booking(self):
        booking = self._create_paid_booking()
        self.client.force_login(self.traveler)

        response = self.client.get(reverse('booking_invoice_download', args=[booking.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
    def test_invoice_view_shows_customer_only_fields(self):
        booking = self._create_paid_booking()
        self.client.force_login(self.traveler)

        response = self.client.get(reverse('booking_invoice', args=[booking.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Booking Invoice')
        self.assertContains(response, booking.package.title)
        self.assertContains(response, 'Payment Method')
        self.assertNotContains(response, 'Platform Fee')
        self.assertNotContains(response, 'Vendor Share')

    def test_other_traveler_cannot_access_invoice(self):
        booking = self._create_paid_booking()
        self.client.force_login(self.other_traveler)

        response = self.client.get(reverse('booking_invoice_download', args=[booking.id]))

        self.assertEqual(response.status_code, 404)

    def test_admin_can_access_any_invoice(self):
        booking = self._create_paid_booking()
        self.client.force_login(self.admin)

        response = self.client.get(reverse('booking_invoice_download', args=[booking.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')


class AchievementDiscountFlowTests(TestCase):
    def setUp(self):
        self.vendor = User.objects.create_user(
            username='discount_vendor',
            password='vendor-pass-123',
            email='discount-vendor@example.com',
            user_type='vendor',
        )
        self.traveler = User.objects.create_user(
            username='discount_traveler',
            password='traveler-pass-123',
            email='discount-traveler@example.com',
            user_type='traveler',
        )
        self.package = Package.objects.create(
            vendor=self.vendor,
            title='Discount Test Trek',
            location='Pokhara',
            description='Discount flow test package.',
            price='10000.00',
            available_slots=12,
            available_from=timezone.localdate() - timedelta(days=1),
            available_until=timezone.localdate() + timedelta(days=20),
            is_active=True,
        )
        self.travel_date = timezone.localdate() + timedelta(days=5)

    def test_checkout_auto_applies_best_valid_discount(self):
        Discount.objects.create(
            user=self.traveler,
            percentage=5,
            max_discount_cap=1000,
            expires_at=timezone.now() + timedelta(days=7),
            source=Discount.SOURCE_ACHIEVEMENT,
        )
        Discount.objects.create(
            user=self.traveler,
            fixed_amount=1500,
            expires_at=timezone.now() + timedelta(days=7),
            source=Discount.SOURCE_ACHIEVEMENT,
        )

        self.client.force_login(self.traveler)
        response = self.client.post(
            reverse('package_book', args=[self.package.id]),
            data={
                'number_of_people': 2,
                'travel_date': self.travel_date.isoformat(),
                'special_notes': 'Discount apply test',
                'payment_method': Booking.PAYMENT_METHOD_ESEWA,
            },
        )

        self.assertEqual(response.status_code, 200)
        booking = Booking.objects.filter(traveler=self.traveler, package=self.package).latest('id')
        self.assertEqual(booking.original_total_price, Decimal('20000.00'))
        self.assertEqual(booking.discount_amount, Decimal('1500.00'))
        self.assertEqual(booking.total_price, Decimal('18500.00'))

    def test_successful_payment_marks_discount_used(self):
        discount = Discount.objects.create(
            user=self.traveler,
            percentage=10,
            max_discount_cap=2000,
            expires_at=timezone.now() + timedelta(days=7),
            source=Discount.SOURCE_ACHIEVEMENT,
        )
        booking = Booking.objects.create(
            package=self.package,
            traveler=self.traveler,
            number_of_people=1,
            travel_date=self.travel_date,
            special_notes='mark-used test',
            status=Booking.STATUS_PENDING,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
            payment_status=Booking.PAYMENT_STATUS_PENDING,
            discount=discount,
            total_price='0',
        )

        _complete_paid_booking(booking, paid_amount=booking.total_price)

        discount.refresh_from_db()
        booking.refresh_from_db()
        self.assertTrue(discount.is_used)
        self.assertIsNotNone(discount.used_at)
        self.assertEqual(booking.payment_status, Booking.PAYMENT_STATUS_COMPLETED)


class PostBookingAutoMessageTests(TestCase):
    def setUp(self):
        self.vendor = User.objects.create_user(
            username='autochat_vendor',
            password='vendor-pass-123',
            email='autochat-vendor@example.com',
            user_type='vendor',
            phone='9800000001',
        )
        self.traveler = User.objects.create_user(
            username='autochat_traveler',
            password='traveler-pass-123',
            email='autochat-traveler@example.com',
            user_type='traveler',
        )
        self.package = Package.objects.create(
            vendor=self.vendor,
            title='Auto Chat Package',
            location='Pokhara',
            description='Package for auto-message tests.',
            price='15000.00',
            available_slots=8,
            available_from=timezone.localdate() - timedelta(days=1),
            available_until=timezone.localdate() + timedelta(days=20),
            is_active=True,
        )

    def test_complete_paid_booking_creates_vendor_system_message(self):
        booking = Booking.objects.create(
            package=self.package,
            traveler=self.traveler,
            vendor=self.vendor,
            number_of_people=2,
            travel_date=timezone.localdate() + timedelta(days=7),
            special_notes='auto-message test',
            status=Booking.STATUS_PENDING,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
            payment_status=Booking.PAYMENT_STATUS_PENDING,
            total_price='0',
        )

        _complete_paid_booking(booking, paid_amount=booking.total_price)

        conversation = SupportConversation.objects.filter(user=self.traveler).first()
        self.assertIsNotNone(conversation)
        support_message = SupportMessage.objects.filter(related_booking=booking).first()
        self.assertIsNotNone(support_message)
        self.assertTrue(support_message.is_system_generated)
        self.assertTrue(support_message.is_admin_reply)
        self.assertEqual(support_message.sender_id, self.vendor.id)
        self.assertIn('Thank you for booking with us!', support_message.message)
        self.assertIn('Auto Chat Package', support_message.message)

    def test_complete_paid_booking_creates_required_notifications(self):
        booking = Booking.objects.create(
            package=self.package,
            traveler=self.traveler,
            vendor=self.vendor,
            number_of_people=1,
            travel_date=timezone.localdate() + timedelta(days=5),
            special_notes='notification test',
            status=Booking.STATUS_PENDING,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
            payment_status=Booking.PAYMENT_STATUS_PENDING,
            total_price='0',
        )

        _complete_paid_booking(booking, paid_amount=booking.total_price)

        self.assertTrue(
            Notification.objects.filter(
                user=self.traveler,
                message='You received a message from vendor',
                type=Notification.TYPE_BOOKING,
                related_object_id=booking.id,
            ).exists()
        )
        self.assertTrue(
            Notification.objects.filter(
                user=self.vendor,
                message='Booking confirmed successfully',
                type=Notification.TYPE_BOOKING,
                related_object_id=booking.id,
            ).exists()
        )


class HomePromotionsPersonalizationTests(TestCase):
    def setUp(self):
        self.vendor = User.objects.create_user(
            username='promo_home_vendor',
            password='vendor-pass-123',
            email='promo-home-vendor@example.com',
            user_type='vendor',
        )
        self.package = Package.objects.create(
            vendor=self.vendor,
            title='Promo Home Trek',
            category=Package.CATEGORY_TREK,
            location='Annapurna',
            location_name='Annapurna',
            price='12000.00',
            available_slots=6,
            available_from=timezone.localdate() - timedelta(days=1),
            available_until=timezone.localdate() + timedelta(days=10),
            is_active=True,
        )

    def test_home_shows_promotions_for_opted_in_traveler(self):
        from .models import SpecialOffer, TravelTip, Wishlist

        traveler = User.objects.create_user(
            username='promo_home_traveler',
            password='traveler-pass-123',
            email='promo-home-traveler@example.com',
            user_type='traveler',
            wants_promotions=True,
        )
        Wishlist.objects.create(traveler=traveler, package=self.package)
        TravelTip.objects.create(
            title='Pack Better for High Altitude',
            summary='Layering and hydration essentials.',
            content='Bring layers, keep water intake steady, and pace your ascent.',
            is_active=True,
        )
        SpecialOffer.objects.create(
            title='Spring Trek Discount',
            summary='Save on selected departures.',
            content='Book this month and receive a special package discount.',
            is_active=True,
        )

        self.client.force_login(traveler)
        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Recommended for You')
        self.assertContains(response, 'Special Offers')
        self.assertContains(response, 'Travel Tips')

    def test_home_shows_opt_in_hint_for_non_opted_traveler(self):
        traveler = User.objects.create_user(
            username='no_promo_home_traveler',
            password='traveler-pass-123',
            email='no-promo-home-traveler@example.com',
            user_type='traveler',
            wants_promotions=False,
        )
        self.client.force_login(traveler)

        response = self.client.get(reverse('home'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'travel tips and special offers')


class PublicTravelerProfileTests(TestCase):
    def setUp(self):
        self.traveler = User.objects.create_user(
            username='public_traveler',
            password='traveler-pass-123',
            email='public-traveler@example.com',
            phone='9800001111',
            user_type='traveler',
        )
        TravelerProfile.objects.create(
            user=self.traveler,
            bio='Mountain wanderer and sunrise chaser.',
        )
        self.vendor = User.objects.create_user(
            username='public_profile_vendor',
            password='vendor-pass-123',
            email='public-profile-vendor@example.com',
            user_type='vendor',
        )
        self.package = Package.objects.create(
            vendor=self.vendor,
            title='Public Profile Trek',
            location='Langtang',
            price='8000.00',
            available_slots=10,
            available_from=timezone.localdate() - timedelta(days=3),
            available_until=timezone.localdate() + timedelta(days=20),
            is_active=True,
        )
        Booking.objects.create(
            package=self.package,
            traveler=self.traveler,
            vendor=self.vendor,
            number_of_people=1,
            travel_date=timezone.localdate() + timedelta(days=4),
            status=Booking.STATUS_CONFIRMED,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
            payment_status=Booking.PAYMENT_STATUS_COMPLETED,
            total_price='0',
        )
        self.post = Post.objects.create(
            user=self.traveler,
            caption='A perfect day on the trail.',
        )
        Review.objects.create(
            package=self.package,
            traveler=self.traveler,
            rating=5,
            comment='Amazing route and great guide support.',
        )
        badge = Badge.objects.create(
            name='Public Explorer Badge',
            description='Awarded for profile visibility tests.',
            icon='trophy',
            condition_type=Badge.CONDITION_FIRST_POST,
            condition_value=1,
        )
        UserBadge.objects.create(user=self.traveler, badge=badge)
        RewardPoint.objects.create(
            user=self.traveler,
            points=25,
            action_type=RewardPoint.ACTION_POST,
        )

    def test_public_profile_shows_social_sections_without_sensitive_data(self):
        response = self.client.get(reverse('public_traveler_profile', args=[self.traveler.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '@public_traveler')
        self.assertContains(response, 'Mountain wanderer and sunrise chaser.')
        self.assertContains(response, 'Total Trips Completed')
        self.assertContains(response, 'Total Posts')
        self.assertContains(response, 'Total Achievements')
        self.assertContains(response, 'Community Posts')
        self.assertContains(response, 'Reviews by This Traveler')
        self.assertNotContains(response, 'public-traveler@example.com')
        self.assertNotContains(response, '9800001111')

    def test_reviews_and_posts_link_to_public_profile(self):
        profile_url = reverse('public_traveler_profile', args=[self.traveler.id])

        reviews_response = self.client.get(reverse('review_list'))
        self.assertEqual(reviews_response.status_code, 200)
        self.assertContains(reviews_response, profile_url)

        community_response = self.client.get(reverse('community_feed'))
        self.assertEqual(community_response.status_code, 200)
        self.assertContains(community_response, profile_url)

        package_response = self.client.get(reverse('package_detail', args=[self.package.id]))
        self.assertEqual(package_response.status_code, 200)
        self.assertContains(package_response, profile_url)
