from io import BytesIO

from django.utils import timezone

from .models import Booking


def invoice_id_for_booking(booking):
    created_at = timezone.localtime(booking.created_at)
    return f"NN-INV-{created_at:%Y%m%d}-{booking.id:06d}"


def invoice_data_for_booking(booking):
    traveler_name = ''
    if booking.traveler:
        traveler_name = booking.traveler.get_full_name().strip() or booking.traveler.email

    vendor_name = ''
    if booking.vendor:
        vendor_name = booking.vendor.get_full_name().strip() or booking.vendor.email

    booking_date = timezone.localtime(booking.created_at).strftime('%Y-%m-%d')
    return {
        'invoice_id': invoice_id_for_booking(booking),
        'booking_id': booking.id,
        'traveler_name': traveler_name or 'N/A',
        'package_name': booking.package.title,
        'vendor_name': vendor_name or 'N/A',
        'number_of_people': booking.number_of_people,
        'travel_date': booking.travel_date.strftime('%Y-%m-%d'),
        'total_amount_paid': booking.total_price,
        'payment_status': booking.get_payment_status_display(),
        'payment_method': booking.get_payment_method_display(),
        'booking_date': booking_date,
    }


def generate_invoice_pdf(booking_id):
    try:
        from reportlab.lib.colors import HexColor
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise RuntimeError('PDF generation requires reportlab. Install it with: pip install reportlab') from exc

    booking = get_booking_for_invoice(booking_id)
    data = invoice_data_for_booking(booking)

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    margin = 50
    y = height - 70

    pdf.setStrokeColor(HexColor('#1f2937'))
    pdf.setLineWidth(1)
    pdf.line(margin, y, width - margin, y)
    y -= 28

    pdf.setFont('Helvetica-Bold', 20)
    pdf.drawString(margin, y, 'Namaste Nomad')
    y -= 24

    pdf.setFont('Helvetica-Bold', 14)
    pdf.drawString(margin, y, 'Booking Invoice')
    y -= 26

    pdf.setFont('Helvetica', 10)
    pdf.drawString(margin, y, f"Invoice ID: {data['invoice_id']}")
    pdf.drawRightString(width - margin, y, f"Booking ID: {data['booking_id']}")
    y -= 18
    pdf.line(margin, y, width - margin, y)
    y -= 26

    pdf.setFont('Helvetica', 11)
    rows = [
        ('Traveler', data['traveler_name']),
        ('Package', data['package_name']),
        ('Vendor', data['vendor_name']),
        ('Travel Date', data['travel_date']),
        ('People', str(data['number_of_people'])),
        ('Payment Method', data['payment_method']),
        ('Payment Status', data['payment_status']),
        ('Booking Date', data['booking_date']),
    ]

    for label, value in rows:
        pdf.setFont('Helvetica-Bold', 11)
        pdf.drawString(margin, y, f'{label}:')
        pdf.setFont('Helvetica', 11)
        pdf.drawString(margin + 120, y, str(value))
        y -= 20

    y -= 6
    pdf.line(margin, y, width - margin, y)
    y -= 26

    pdf.setFont('Helvetica-Bold', 13)
    total_paid = f"Rs {data['total_amount_paid']:.0f}"
    pdf.drawString(margin, y, f'Total Paid: {total_paid}')
    y -= 32

    pdf.setFont('Helvetica-Oblique', 11)
    pdf.drawString(margin, y, 'Thank you for booking with us!')

    pdf.showPage()
    pdf.save()
    buffer.seek(0)
    return buffer.getvalue()


def get_booking_for_invoice(booking_id):
    booking = (
        Booking.objects.select_related('traveler', 'vendor', 'package')
        .filter(id=booking_id)
        .first()
    )
    if booking is None:
        raise Booking.DoesNotExist
    if booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED:
        raise ValueError('Invoice is available only for completed payments.')
    return booking
