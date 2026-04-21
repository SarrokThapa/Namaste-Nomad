import mimetypes

import mimetypes

from django.conf import settings
from django import forms
from django.utils import timezone

from .models import Booking, Comment, ContactMessage, Post, Review, SiteSetting


class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultiFileField(forms.Field):
    """Accept multiple uploaded files from a single form input name."""

    default_error_messages = {
        'invalid': 'Only image or video files are allowed.',
    }

    def clean(self, data):
        if not data:
            return []
        if isinstance(data, (list, tuple)):
            return [item for item in data if item]
        return [data]


class ReviewForm(forms.ModelForm):
    class Meta:
        model = Review
        fields = ['package', 'rating', 'comment']

    def __init__(self, *args, **kwargs):
        package_queryset = kwargs.pop('package_queryset', None)
        super().__init__(*args, **kwargs)
        if package_queryset is not None:
            self.fields['package'].queryset = package_queryset
        self.fields['comment'].required = True


class PostForm(forms.ModelForm):
    media_files = MultiFileField(
        required=False,
        widget=MultiFileInput(attrs={
            'multiple': True,
            'accept': 'image/*,video/*',
        }),
    )

    class Meta:
        model = Post
        fields = ['caption']
        widgets = {
            'caption': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Write a caption for your travel moment...',
            }),
        }

    def clean(self):
        cleaned_data = super().clean()
        caption = (cleaned_data.get('caption') or '').strip()
        if not caption:
            raise forms.ValidationError('Please add a caption.')

        media_files = cleaned_data.get('media_files') or self.files.getlist('media_files')
        if not media_files:
            raise forms.ValidationError('Please upload at least one photo or video.')

        for media_file in media_files:
            content_type = (getattr(media_file, 'content_type', '') or '').lower()
            if not content_type:
                guessed_type, _ = mimetypes.guess_type(getattr(media_file, 'name', ''))
                content_type = (guessed_type or '').lower()
            if not (content_type.startswith('image/') or content_type.startswith('video/')):
                raise forms.ValidationError('Only image or video files are allowed.')

        cleaned_data['caption'] = caption
        cleaned_data['media_files'] = media_files
        return cleaned_data


class PostEditForm(forms.ModelForm):
    media_files = forms.FileField(
        required=False,
        widget=MultiFileInput(attrs={
            'multiple': True,
            'accept': 'image/*,video/*',
        }),
    )

    class Meta:
        model = Post
        fields = ['caption']
        widgets = {
            'caption': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Update your caption...',
                'id': 'post-caption',
            }),
        }


class CommentForm(forms.ModelForm):
    class Meta:
        model = Comment
        fields = ['body']
        widgets = {
            'body': forms.Textarea(attrs={
                'rows': 2,
                'placeholder': 'Write a comment...',
            }),
        }


class BookingForm(forms.ModelForm):
    CHECKOUT_METHOD_CHOICES = [
        (Booking.PAYMENT_METHOD_ESEWA, 'eSewa (Nepal)'),
        (Booking.PAYMENT_METHOD_STRIPE, 'Card (Stripe - International)'),
    ]

    class Meta:
        model = Booking
        fields = ['number_of_people', 'travel_date', 'special_notes', 'payment_method']
        widgets = {
            'number_of_people': forms.NumberInput(attrs={'min': 1}),
            'travel_date': forms.DateInput(attrs={'type': 'date'}),
            'special_notes': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Add any special requests (optional).',
            }),
            'payment_method': forms.RadioSelect(),
        }

    def __init__(self, *args, **kwargs):
        self.package = kwargs.pop('package', None)
        super().__init__(*args, **kwargs)
        self.fields['special_notes'].required = False
        self.fields['payment_method'].choices = self.CHECKOUT_METHOD_CHOICES
        default_method = (
            Booking.PAYMENT_METHOD_ESEWA
            if getattr(settings, 'ESEWA_CURRENCY', 'npr').lower() == 'npr'
            else Booking.PAYMENT_METHOD_STRIPE
        )
        self.fields['payment_method'].initial = default_method

    def clean_travel_date(self):
        travel_date = self.cleaned_data['travel_date']
        if travel_date < timezone.localdate():
            raise forms.ValidationError('Please select a valid future travel date.')
        return travel_date

    def clean_number_of_people(self):
        number_of_people = self.cleaned_data['number_of_people']
        if number_of_people < 1:
            raise forms.ValidationError('At least one traveler is required.')
        return number_of_people

    def clean_payment_method(self):
        payment_method = (
            self.cleaned_data.get('payment_method')
            or self.fields['payment_method'].initial
        ).strip().lower()

        allowed_methods = {
            Booking.PAYMENT_METHOD_STRIPE,
            Booking.PAYMENT_METHOD_ESEWA,
        }
        if payment_method not in allowed_methods:
            raise forms.ValidationError('Please choose a valid payment method.')

        if (
            payment_method == Booking.PAYMENT_METHOD_ESEWA
            and getattr(settings, 'ESEWA_CURRENCY', 'npr').lower() != 'npr'
        ):
            raise forms.ValidationError('eSewa is available for NPR payments only.')

        return payment_method

    def clean(self):
        cleaned_data = super().clean()
        number_of_people = cleaned_data.get('number_of_people')

        if self.package and not self.package.is_in_season():
            self.add_error(None, 'This package is currently not available for booking.')

        if self.package and number_of_people:
            if number_of_people > self.package.available_slots:
                self.add_error(
                    'number_of_people',
                    f'Only {self.package.available_slots} slot(s) are currently available.',
                )

        return cleaned_data


class ContactMessageForm(forms.ModelForm):
    class Meta:
        model = ContactMessage
        fields = ['full_name', 'email', 'subject', 'message']
        widgets = {
            'full_name': forms.TextInput(attrs={
                'placeholder': 'Your full name',
                'required': True,
            }),
            'email': forms.EmailInput(attrs={
                'placeholder': 'you@example.com',
                'required': True,
            }),
            'subject': forms.TextInput(attrs={
                'placeholder': 'How can we help?',
                'required': True,
            }),
            'message': forms.Textarea(attrs={
                'rows': 6,
                'placeholder': 'Tell us what you are planning, and we will help you with the best options.',
                'required': True,
            }),
        }


class SiteSettingForm(forms.ModelForm):
    class Meta:
        model = SiteSetting
        fields = [
            'commission_percent',
            'enable_booking',
            'enable_community',
            'hero_title',
            'hero_subtitle',
        ]
        widgets = {
            'commission_percent': forms.NumberInput(attrs={'class': 'form-control', 'min': 0, 'max': 100}),
            'hero_title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Find Your Perfect Nepal Trek'}),
            'hero_subtitle': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
