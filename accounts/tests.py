from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import User, VendorProfile


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
