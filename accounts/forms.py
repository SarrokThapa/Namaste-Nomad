from django import forms

from core.models import Package
from .models import VendorProfile


class PackageForm(forms.ModelForm):
    class Meta:
        model = Package
        fields = [
            'title',
            'category',
            'location_name',
            'latitude',
            'longitude',
            'price',
            'duration_days',
            'available_slots',
            'available_from',
            'available_until',
            'difficulty',
            'group_size',
            'best_season',
            'description',
            'itinerary',
            'inclusions',
            'exclusions',
            'has_guide',
            'includes_meals',
            'includes_accommodation',
            'includes_transport',
            'includes_permits',
            'is_active',
        ]
        widgets = {
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Everest Base Camp Trek'}),
            'category': forms.Select(attrs={'class': 'form-control'}),
            'location_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Khumbu Region'}),
            'latitude': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.000001', 'placeholder': '27.9881'}),
            'longitude': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.000001', 'placeholder': '86.9250'}),
            'price': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '1899'}),
            'duration_days': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '14'}),
            'available_slots': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '12'}),
            'available_from': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'available_until': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'difficulty': forms.Select(attrs={'class': 'form-control'}),
            'group_size': forms.NumberInput(attrs={'class': 'form-control', 'placeholder': '10'}),
            'best_season': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Mar-May, Sep-Nov'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
            'itinerary': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Day 1: Kathmandu\nDay 2: Lukla...'}),
            'inclusions': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Guide\nPermits\nAccommodation'}),
            'exclusions': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'International flights\nInsurance'}),
            'has_guide': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'includes_meals': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'includes_accommodation': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'includes_transport': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'includes_permits': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-checkbox'}),
        }
        labels = {
            'category': 'Category',
            'duration_days': 'Duration (days)',
            'available_slots': 'Available Slots',
            'available_from': 'Available From',
            'available_until': 'Available Until',
            'group_size': 'Group Size',
            'has_guide': 'Guide Included',
            'includes_meals': 'Meals Included',
            'includes_accommodation': 'Accommodation Included',
            'includes_transport': 'Transportation Included',
            'includes_permits': 'Permits Included',
            'is_active': 'Publish package',
            'location_name': 'Location Name',
            'latitude': 'Latitude',
            'longitude': 'Longitude',
        }

    def __init__(self, *args, **kwargs):
        self.vendor = kwargs.pop('vendor', None)
        super().__init__(*args, **kwargs)
        self.fields['category'].required = True
        self.fields['category'].choices = [('', 'Select category')] + list(Package.CATEGORY_CHOICES)
        self.fields['location_name'].required = True
        self.fields['latitude'].required = True
        self.fields['longitude'].required = True
        self.fields['available_from'].required = True
        self.fields['available_until'].required = True

    def clean(self):
        cleaned_data = super().clean()
        available_from = cleaned_data.get('available_from')
        available_until = cleaned_data.get('available_until')
        location_name = (cleaned_data.get('location_name') or '').strip()
        latitude = cleaned_data.get('latitude')
        longitude = cleaned_data.get('longitude')

        if not location_name:
            self.add_error('location_name', 'Location name is required.')

        if latitude is None:
            self.add_error('latitude', 'Latitude is required.')
        elif not (-90 <= latitude <= 90):
            self.add_error('latitude', 'Latitude must be between -90 and 90.')

        if longitude is None:
            self.add_error('longitude', 'Longitude is required.')
        elif not (-180 <= longitude <= 180):
            self.add_error('longitude', 'Longitude must be between -180 and 180.')

        if available_from and available_until and available_from > available_until:
            self.add_error('available_until', 'Available from date cannot be later than available until date.')

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        location_name = (self.cleaned_data.get('location_name') or '').strip()
        if location_name:
            instance.location = location_name
        if commit:
            instance.save()
            self.save_m2m()
        return instance


class VendorProfileForm(forms.ModelForm):
    class Meta:
        model = VendorProfile
        fields = [
            'business_name',
            'owner_name',
            'tagline',
            'license_number',
            'business_address',
            'description',
            'logo',
            'cover_image',
        ]
        widgets = {
            'business_name': forms.TextInput(attrs={'class': 'form-control'}),
            'owner_name': forms.TextInput(attrs={'class': 'form-control'}),
            'tagline': forms.TextInput(attrs={'class': 'form-control'}),
            'license_number': forms.TextInput(attrs={'class': 'form-control'}),
            'business_address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }
