from django import forms

from core.models import Package
from .models import VendorSubscription
from .models import VendorProfile


class PackageForm(forms.ModelForm):
    class Meta:
        model = Package
        fields = [
            'title',
            'category',
            'location',
            'price',
            'duration_days',
            'available_slots',
            'available_from',
            'available_until',
            'difficulty',
            'group_size',
            'best_season',
            'image_url',
            'description',
            'itinerary',
            'inclusions',
            'exclusions',
            'is_active',
            'is_featured',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Everest Base Camp Trek'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Khumbu, Nepal'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '1899'}),
            'duration_days': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '14'}),
            'available_slots': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '12'}),
            'available_from': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'available_until': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'difficulty': forms.Select(attrs={'class': 'form-control'}),
            'group_size': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '10'}),
            'best_season': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Mar-May, Sep-Nov'}),
            'image_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'itinerary': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Day 1: Kathmandu\nDay 2: Lukla...'}),
            'inclusions': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Guide\nPermits\nAccommodation'}),
            'exclusions': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'International flights\nInsurance'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'is_featured': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }
        labels = {
            'category': 'Category',
            'duration_days': 'Duration (days)',
            'available_slots': 'Available Slots',
            'available_from': 'Available From',
            'available_until': 'Available Until',
            'group_size': 'Group Size',
            'image_url': 'Cover Image URL',
            'is_active': 'Publish package',
            'is_featured': 'Feature this package',
        }

    def __init__(self, *args, **kwargs):
        self.vendor = kwargs.pop('vendor', None)
        super().__init__(*args, **kwargs)
        self.fields['category'].required = True
        self.fields['category'].choices = [('', 'Select category')] + list(Package.CATEGORY_CHOICES)
        self.fields['available_from'].required = True
        self.fields['available_until'].required = True
        self.subscription = None
        if self.vendor is None:
            self.fields.pop('is_featured', None)
        else:
            self.subscription = VendorSubscription.active_for_vendor(self.vendor)
            if not self.subscription and 'is_featured' in self.fields:
                if getattr(self.instance, 'is_featured', False):
                    self.instance.is_featured = False
                self.fields['is_featured'].disabled = True

    def clean(self):
        cleaned_data = super().clean()
        available_from = cleaned_data.get('available_from')
        available_until = cleaned_data.get('available_until')
        is_featured = cleaned_data.get('is_featured')

        if available_from and available_until and available_from > available_until:
            self.add_error('available_until', 'Available until must be after the available from date.')

        if is_featured:
            subscription = VendorSubscription.active_for_vendor(self.vendor)
            if subscription is None:
                self.add_error('is_featured', 'An active subscription is required to feature packages.')
            elif subscription.max_featured_packages is not None:
                featured_count = Package.objects.filter(
                    vendor=self.vendor,
                    is_featured=True,
                ).exclude(pk=getattr(self.instance, 'pk', None)).count()
                if featured_count >= subscription.max_featured_packages:
                    self.add_error(
                        'is_featured',
                        f'Your plan allows up to {subscription.max_featured_packages} featured package(s).',
                    )

        return cleaned_data


class VendorProfileForm(forms.ModelForm):
    class Meta:
        model = VendorProfile
        fields = [
            'business_name',
            'owner_name',
            'tagline',
            'website',
            'license_number',
            'business_address',
            'description',
            'bank_name',
            'account_number',
            'routing_number',
            'paypal_email',
            'logo',
            'cover_image',
        ]
        widgets = {
            'business_name': forms.TextInput(attrs={'class': 'form-control'}),
            'owner_name': forms.TextInput(attrs={'class': 'form-control'}),
            'tagline': forms.TextInput(attrs={'class': 'form-control'}),
            'website': forms.URLInput(attrs={'class': 'form-control'}),
            'license_number': forms.TextInput(attrs={'class': 'form-control'}),
            'business_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'bank_name': forms.TextInput(attrs={'class': 'form-control'}),
            'account_number': forms.TextInput(attrs={'class': 'form-control'}),
            'routing_number': forms.TextInput(attrs={'class': 'form-control'}),
            'paypal_email': forms.EmailInput(attrs={'class': 'form-control'}),
        }
