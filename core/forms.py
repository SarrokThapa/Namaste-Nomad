from django import forms

from .models import Review


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
