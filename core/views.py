# core/views.py
from django.shortcuts import render

def home(request):
    """Landing page"""
    return render(request, 'core/home.html')

def about(request):
    """About page"""
    return render(request, 'core/about.html')

def contact(request):
    """Contact page"""
    return render(request, 'core/contact.html')