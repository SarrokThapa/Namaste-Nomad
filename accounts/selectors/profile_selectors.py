from accounts.models import AdminProfile, TravelerProfile, VendorFeatureSubscription, VendorProfile


def get_vendor_profile(user):
    # get vendor profile if it exists
    try:
        return user.vendor_profile
    except VendorProfile.DoesNotExist:
        return None


def get_admin_profile(user):
    # fetch admin profile for dashboard pages
    try:
        return user.admin_profile
    except AdminProfile.DoesNotExist:
        return None


def get_traveler_profile(user):
    # fetch traveler profile used across auth/profile flows
    try:
        return user.traveler_profile
    except TravelerProfile.DoesNotExist:
        return None


def get_active_subscription(vendor):
    # get currently active feature subscription for a vendor
    return VendorFeatureSubscription.active_for_vendor(vendor)
