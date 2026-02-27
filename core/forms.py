from django import forms

from .models import Comment, Post, Review


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
    class Meta:
        model = Post
        fields = ['image', 'caption']
        widgets = {
            'caption': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Write a caption for your travel moment...',
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
