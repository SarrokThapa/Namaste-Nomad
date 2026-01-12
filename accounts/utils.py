
import random
from django.core.mail import send_mail
from django.conf import settings
from .models import OTP

def generate_otp():
    """Generate a 6-digit OTP"""
    return str(random.randint(100000, 999999))

def send_otp_email(user, otp_code):
    """Send OTP via email"""
    subject = 'Your OTP Code'
    message = f'Your OTP code is: {otp_code}\n\nThis code will expire in 10 minutes.'
    from_email = settings.DEFAULT_FROM_EMAIL
    recipient_list = [user.email]
    
    try:
        send_mail(subject, message, from_email, recipient_list)
        return True
    except Exception as e:
        print(f"Error sending email: {e}")
        return False

def create_otp(user):
    """Create and send OTP to user"""
    # Invalidate old OTPs
    OTP.objects.filter(user=user, is_used=False).update(is_used=True)
    
    # Generate new OTP
    otp_code = generate_otp()
    otp = OTP.objects.create(user=user, otp_code=otp_code)
    
    # Send OTP via email
    send_otp_email(user, otp_code)
    
    return otp

def verify_otp(user, otp_code):
    """Verify OTP code"""
    try:
        otp = OTP.objects.get(user=user, otp_code=otp_code, is_used=False)
        if otp.is_valid():
            otp.is_used = True
            otp.save()
            return True
        return False
    except OTP.DoesNotExist:
        return False