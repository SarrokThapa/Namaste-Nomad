"""Booking lifecycle and invoice views."""

from ..utils.helpers import *
from .payment_views import *



@login_required(login_url='account_login_choice')
def package_book(request, package_id):
    package = get_object_or_404(Package, id=package_id, is_active=True)

    if getattr(request.user, 'user_type', '') != 'traveler':
        messages.error(request, 'Only traveler accounts can create bookings.')
        return redirect('package_detail', package_id=package.id)

    if not package.is_in_season():
        messages.error(request, 'This package is currently not available for booking.')
        return redirect('package_detail', package_id=package.id)

    with transaction.atomic():
        _expire_stale_pending_bookings(package_id=package.id)
    package.refresh_from_db(fields=['available_slots'])

    if request.method == 'POST':
        form = BookingForm(request.POST, package=package)
        if form.is_valid():
            selected_payment_method = form.cleaned_data['payment_method']
            booking = None
            booking_created = False
            with transaction.atomic():
                _expire_stale_pending_bookings(package_id=package.id)
                locked_package = Package.objects.select_for_update().get(id=package.id)
                number_of_people = form.cleaned_data['number_of_people']
                travel_date = form.cleaned_data['travel_date']
                special_notes = form.cleaned_data.get('special_notes', '')
                original_total = (locked_package.price * number_of_people).quantize(Decimal('0.01'))
                best_discount, _best_amount = _best_available_discount_for_user(
                    request.user,
                    original_total,
                )
                existing_pending_booking = (
                    Booking.objects.select_for_update()
                    .filter(
                        package=locked_package,
                        traveler=request.user,
                        status=Booking.STATUS_PENDING,
                        payment_status__in=[
                            Booking.PAYMENT_STATUS_PENDING,
                            Booking.PAYMENT_STATUS_FAILED,
                        ],
                    )
                    .order_by('-created_at')
                    .first()
                )
                slot_delta = number_of_people
                if existing_pending_booking is not None:
                    slot_delta -= existing_pending_booking.number_of_people

                if slot_delta > locked_package.available_slots:
                    form.add_error(
                        'number_of_people',
                        f'Only {locked_package.available_slots} slot(s) are currently available.',
                    )
                else:
                    booking = existing_pending_booking
                    if booking is None:
                        booking = form.save(commit=False)
                        booking.package = locked_package
                        booking.traveler = request.user
                        booking_created = True
                    else:
                        booking.number_of_people = number_of_people
                        booking.travel_date = travel_date
                        booking.start_date = travel_date
                        booking.end_date = travel_date
                        booking.special_notes = special_notes
                        booking.payment_reference = ''
                        booking.stripe_checkout_session_id = ''
                        booking.esewa_transaction_id = ''
                        booking.paid_amount = None
                        booking.paid_at = None

                    booking.status = Booking.STATUS_PENDING
                    booking.payment_method = selected_payment_method
                    booking.payment_status = Booking.PAYMENT_STATUS_PENDING
                    booking.source = 'direct'
                    booking.discount = best_discount
                    booking.payment_expires_at = _booking_payment_expires_at()
                    booking.save()

                    if slot_delta != 0:
                        locked_package.available_slots -= slot_delta
                        locked_package.save(update_fields=['available_slots'])

            if form.errors:
                package.refresh_from_db(fields=['available_slots'])
            else:
                if booking.payment_method == Booking.PAYMENT_METHOD_STRIPE:
                    success_url = (
                        request.build_absolute_uri(
                            reverse('booking_confirmation', kwargs={'booking_id': booking.id}),
                        )
                        + '?session_id={CHECKOUT_SESSION_ID}'
                    )
                    cancel_url = request.build_absolute_uri(
                        reverse('booking_checkout_cancel', kwargs={'booking_id': booking.id}),
                    )
                    try:
                        session_data = create_checkout_session(
                            booking=booking,
                            success_url=success_url,
                            cancel_url=cancel_url,
                        )
                        checkout_url = session_data.get('url')
                        if not checkout_url:
                            raise StripeError('Stripe did not return a checkout URL.')
                    except StripeError as exc:
                        with transaction.atomic():
                            locked_booking = Booking.objects.select_for_update().get(id=booking.id)
                            _cancel_unpaid_booking(
                                locked_booking,
                                Booking.PAYMENT_STATUS_FAILED,
                            )
                        form.add_error(None, str(exc))
                        package.refresh_from_db(fields=['available_slots'])
                    else:
                        booking.stripe_checkout_session_id = session_data.get('id', '')
                        booking.payment_reference = (
                            session_data.get('payment_intent')
                            or session_data.get('id', '')
                        )
                        booking.save(update_fields=['stripe_checkout_session_id', 'payment_reference'])
                        if booking_created:
                            _notify_booking_created(booking)
                        return redirect(checkout_url)
                elif booking.payment_method == Booking.PAYMENT_METHOD_ESEWA:
                    try:
                        response = _render_esewa_checkout(request, booking)
                    except EsewaError as exc:
                        with transaction.atomic():
                            locked_booking = Booking.objects.select_for_update().get(id=booking.id)
                            _cancel_unpaid_booking(
                                locked_booking,
                                Booking.PAYMENT_STATUS_FAILED,
                            )
                        form.add_error(None, str(exc))
                        package.refresh_from_db(fields=['available_slots'])
                    else:
                        if booking_created:
                            _notify_booking_created(booking)
                        return response
                else:
                    form.add_error('payment_method', 'Unsupported payment method selected.')
    else:
        form = BookingForm(
            package=package,
            initial={
                'number_of_people': 1,
                'travel_date': timezone.localdate(),
                'payment_method': Booking.PAYMENT_METHOD_ESEWA,
            },
        )

    reward_points = total_points_for_user(request.user)
    discount_percent, next_discount_points = discount_for_points(reward_points)
    preview_people = 1
    posted_people = request.POST.get('number_of_people')
    if posted_people:
        try:
            preview_people = max(1, int(posted_people))
        except (TypeError, ValueError):
            preview_people = 1
    preview_original_total = (package.price * preview_people).quantize(Decimal('0.01'))
    available_discount, available_discount_amount = _best_available_discount_for_user(
        request.user,
        preview_original_total,
    )
    preview_final_total = (preview_original_total - available_discount_amount).quantize(Decimal('0.01'))

    return render(request, 'core/booking_form.html', {
        'package': package,
        'form': form,
        'estimated_total': preview_final_total,
        'original_total': preview_original_total,
        'discount_amount': available_discount_amount,
        'available_discount': available_discount,
        'reward_points': reward_points,
        'discount_percent': discount_percent,
        'next_discount_points': next_discount_points,
    })


@login_required(login_url='account_login_choice')
def booking_confirmation(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package', 'traveler'),
        id=booking_id,
        traveler=request.user,
    )

    if (
        booking.payment_method == Booking.PAYMENT_METHOD_STRIPE
        and booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED
    ):
        session_id = request.GET.get('session_id')
        if session_id:
            try:
                session_data = retrieve_checkout_session(session_id)
            except StripeError as exc:
                messages.warning(request, f'Payment verification is still pending: {exc}')
            else:
                is_paid = (
                    session_data.get('status') == 'complete'
                    and session_data.get('payment_status') == 'paid'
                    and str(session_data.get('client_reference_id')) == str(booking.id)
                )
                if is_paid:
                    with transaction.atomic():
                        locked_booking = get_object_or_404(
                            Booking.objects.select_for_update().select_related('package', 'traveler'),
                            id=booking_id,
                            traveler=request.user,
                        )
                        if (
                            locked_booking.status == Booking.STATUS_PENDING
                            and locked_booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED
                        ):
                            _complete_paid_booking(
                                locked_booking,
                                payment_reference=(
                                    session_data.get('payment_intent')
                                    or session_data.get('id')
                                    or locked_booking.payment_reference
                                ),
                                stripe_checkout_session_id=(
                                    session_data.get('id')
                                    or locked_booking.stripe_checkout_session_id
                                ),
                                paid_amount=_as_money_decimal(locked_booking.total_price),
                            )
                            _notify_booking_paid(locked_booking)
                        booking = locked_booking
                    if booking.payment_status == Booking.PAYMENT_STATUS_COMPLETED:
                        messages.success(
                            request,
                            'Stripe payment received. Your booking is confirmed.',
                        )
                    else:
                        messages.warning(
                            request,
                            'This booking is no longer awaiting payment. Please contact support if you were charged.',
                        )
                else:
                    messages.warning(
                        request,
                        'Your Stripe checkout is not marked as paid yet.',
                    )

    can_continue_payment = (
        booking.status == Booking.STATUS_PENDING
        and booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED
    )
    return render(
        request,
        'core/booking_confirmation.html',
        {
            'booking': booking,
            'can_continue_payment': can_continue_payment,
        },
    )


@login_required(login_url='account_login_choice')
def booking_checkout_cancel(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package'),
        id=booking_id,
        traveler=request.user,
    )

    if booking.payment_status == Booking.PAYMENT_STATUS_COMPLETED:
        return redirect('booking_confirmation', booking_id=booking.id)

    with transaction.atomic():
        locked_booking = get_object_or_404(
            Booking.objects.select_for_update().select_related('package'),
            id=booking_id,
            traveler=request.user,
        )
        if (
            locked_booking.status == Booking.STATUS_PENDING
            and locked_booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED
        ):
            _cancel_unpaid_booking(
                locked_booking,
                Booking.PAYMENT_STATUS_FAILED,
            )

    if (
        booking.payment_method == Booking.PAYMENT_METHOD_STRIPE
        and booking.stripe_checkout_session_id
    ):
        try:
            expire_checkout_session(booking.stripe_checkout_session_id)
        except StripeError:
            pass

    messages.info(
        request,
        'Payment was cancelled. Your reserved slots were released.',
    )
    return redirect('package_book', package_id=booking.package_id)


@login_required(login_url='account_login_choice')
def booking_invoice(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package', 'traveler', 'vendor'),
        id=booking_id,
    )
    if not _can_access_booking_invoice(request.user, booking):
        raise Http404('Invoice not found.')

    if booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED:
        messages.error(request, 'Invoice is available only after successful payment.')
        if booking.traveler_id == request.user.id:
            return redirect('booking_confirmation', booking_id=booking.id)
        return redirect('admin_dashboard')

    return render(
        request,
        'core/invoice_detail.html',
        {
            'booking': booking,
            'invoice': invoice_data_for_booking(booking),
        },
    )


@login_required(login_url='account_login_choice')
def booking_invoice_download(request, booking_id):
    booking = get_object_or_404(
        Booking.objects.select_related('package', 'traveler', 'vendor'),
        id=booking_id,
    )
    if not _can_access_booking_invoice(request.user, booking):
        raise Http404('Invoice not found.')

    if booking.payment_status != Booking.PAYMENT_STATUS_COMPLETED:
        messages.error(request, 'Invoice is available only after successful payment.')
        if booking.traveler_id == request.user.id:
            return redirect('booking_confirmation', booking_id=booking.id)
        return redirect('admin_dashboard')

    try:
        pdf_bytes = generate_invoice_pdf(booking.id)
    except (Booking.DoesNotExist, ValueError, RuntimeError) as exc:
        messages.error(request, str(exc))
        if booking.traveler_id == request.user.id:
            return redirect('booking_confirmation', booking_id=booking.id)
        return redirect('admin_dashboard')
    except Exception:
        messages.error(request, 'Unable to generate invoice for this booking.')
        if booking.traveler_id == request.user.id:
            return redirect('booking_confirmation', booking_id=booking.id)
        return redirect('admin_dashboard')

    filename = f"invoice_{booking.id}.pdf"
    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response
