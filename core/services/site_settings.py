from decimal import Decimal

from ..models import SiteSetting


def get_site_settings():
    site_settings, _created = SiteSetting.objects.get_or_create(pk=1)
    SiteSetting.objects.exclude(pk=site_settings.pk).delete()
    return site_settings


def get_commission_percent():
    percent = int(get_site_settings().commission_percent or 0)
    return max(0, min(percent, 100))


def get_commission_rates():
    platform_rate = (Decimal(get_commission_percent()) / Decimal('100')).quantize(Decimal('0.0001'))
    vendor_rate = Decimal('1.0000') - platform_rate
    return vendor_rate, platform_rate


def calculate_commission_split(total_amount):
    total = Decimal(str(total_amount or '0')).quantize(Decimal('0.01'))
    vendor_rate, _platform_rate = get_commission_rates()
    vendor_amount = (total * vendor_rate).quantize(Decimal('0.01'))
    platform_fee = total - vendor_amount
    return vendor_amount, platform_fee
