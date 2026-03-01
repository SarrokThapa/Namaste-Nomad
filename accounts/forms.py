from django import forms

from core.models import Package
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
            'difficulty',
            'group_size',
            'best_season',
            'image_url',
            'description',
            'itinerary',
            'inclusions',
            'exclusions',
            'is_active',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Everest Base Camp Trek'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'location': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Khumbu, Nepal'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '1899'}),
            'duration_days': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '14'}),
            'difficulty': forms.Select(attrs={'class': 'form-control'}),
            'group_size': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '10'}),
            'best_season': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Mar-May, Sep-Nov'}),
            'image_url': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'https://...'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'itinerary': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Day 1: Kathmandu\nDay 2: Lukla...'}),
            'inclusions': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Guide\nPermits\nAccommodation'}),
            'exclusions': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'International flights\nInsurance'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }
        labels = {
            'category': 'Category',
            'duration_days': 'Duration (days)',
            'group_size': 'Group Size',
            'image_url': 'Cover Image URL',
            'is_active': 'Publish package',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['category'].required = True
        self.fields['category'].choices = [('', 'Select category')] + list(Package.CATEGORY_CHOICES)


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
