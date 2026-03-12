from django import forms
from django.utils import timezone

from .models import Booking, Comment, Post, Review


class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


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
    media_files = forms.FileField(
        required=True,
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
        media_files = self.files.getlist('media_files')
        if not media_files:
            raise forms.ValidationError('Please upload at least one photo or video.')

        for media_file in media_files:
            content_type = (getattr(media_file, 'content_type', '') or '').lower()
            if not (content_type.startswith('image/') or content_type.startswith('video/')):
                raise forms.ValidationError('Only image or video files are allowed.')

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
            'payment_method': forms.HiddenInput(),
        }

    def __init__(self, *args, **kwargs):
        self.package = kwargs.pop('package', None)
        super().__init__(*args, **kwargs)
        self.fields['special_notes'].required = False
        self.fields['payment_method'].initial = Booking.PAYMENT_METHOD_STRIPE

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
            or Booking.PAYMENT_METHOD_STRIPE
        ).strip().lower()
        if payment_method != Booking.PAYMENT_METHOD_STRIPE:
            raise forms.ValidationError('Stripe is the only payment method available right now.')
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
