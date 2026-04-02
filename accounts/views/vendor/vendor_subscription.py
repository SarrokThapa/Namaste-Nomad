"""Vendor subscription and feature slot purchase views."""

from ..common import *

@never_cache
@login_required(login_url='account_login_choice')
@csrf_protect

def vendor_subscription_purchase(request, plan_id):
    if not _ensure_vendor(request):
        return redirect('vendor_login')
    if request.method != 'POST':
        return redirect('vendor_settings')

    plan = get_object_or_404(VendorSubscriptionPlan, id=plan_id, is_active=True)
    payment_method = (request.POST.get('payment_method') or Booking.PAYMENT_METHOD_ESEWA).strip().lower()
    if payment_method not in {Booking.PAYMENT_METHOD_ESEWA, Booking.PAYMENT_METHOD_STRIPE}:
        payment_method = Booking.PAYMENT_METHOD_ESEWA

    payment_pid = f'SUB-{request.user.id}-{plan.id}-{uuid.uuid4().hex[:8].upper()}'
    payment_session = {
        'pid': payment_pid,
        'plan_id': plan.id,
        'payment_method': payment_method,
        'amount': format(plan.price, 'f'),
        'created_at': timezone.now().isoformat(),
    }
    request.session[_subscription_payment_session_key(request.user.id)] = payment_session
    request.session.modified = True

    if payment_method == Booking.PAYMENT_METHOD_STRIPE:
        success_url = (
            request.build_absolute_uri(reverse('vendor_subscription_stripe_success'))
            + '?session_id={CHECKOUT_SESSION_ID}'
        )
        cancel_url = request.build_absolute_uri(reverse('vendor_subscription_stripe_cancel'))

        try:
            session_data = create_checkout_session_for_item(
                amount=plan.price,
                name=f'{plan.name} Subscription',
                description=f'{plan.duration_days} days subscription plan',
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=payment_pid,
                metadata={
                    'type': 'subscription',
                    'pid': payment_pid,
                    'plan_id': plan.id,
                    'vendor_id': request.user.id,
                },
                customer_email=request.user.email or None,
            )
            checkout_url = session_data.get('url')
            if not checkout_url:
                raise StripeError('Stripe did not return a checkout URL.')
            payment_session['stripe_session_id'] = session_data.get('id', '')
            request.session[_subscription_payment_session_key(request.user.id)] = payment_session
            request.session.modified = True
            return redirect(checkout_url)
        except StripeError as exc:
            messages.error(request, str(exc))
            return redirect('vendor_settings')

    success_url = request.build_absolute_uri(reverse('vendor_subscription_esewa_success'))
    failure_url = request.build_absolute_uri(reverse('vendor_subscription_esewa_failure'))

    try:
        payload = _subscription_esewa_payload(
            amount=plan.price,
            pid=payment_pid,
            success_url=success_url,
            failure_url=failure_url,
        )
        payment_url = get_esewa_payment_url()
    except EsewaError as exc:
        messages.error(request, str(exc))
        return redirect('vendor_settings')

    return render(
        request,
        'core/esewa_redirect.html',
        {
            'booking': None,
            'esewa_payment_url': payment_url,
            'esewa_payload': payload,
        },
    )


@never_cache
@login_required(login_url='vendor_login')

def vendor_subscription_esewa_success(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    session_key = _subscription_payment_session_key(request.user.id)
    payment_session = request.session.get(session_key)
    if not payment_session:
        messages.error(request, 'Subscription payment session not found. Please try again.')
        return redirect('vendor_settings')
    if payment_session.get('payment_method') != Booking.PAYMENT_METHOD_ESEWA:
        messages.error(request, 'Invalid payment callback for this subscription session.')
        return redirect('vendor_settings')

    # eSewa V2: success redirect carries base64-encoded JSON in ?data=
    encoded_data = (request.GET.get('data') or '').strip()
    if not encoded_data:
        messages.error(request, 'Subscription payment verification failed: Missing eSewa response data.')
        return redirect('vendor_settings')

    try:
        expected_amount = Decimal(str(payment_session.get('amount') or '0')).quantize(Decimal('0.01'))
    except InvalidOperation:
        messages.error(request, 'Subscription payment verification failed: Invalid amount.')
        return redirect('vendor_settings')

    expected_pid = payment_session.get('pid', '')

    try:
        response_data, verification = esewa_process_success_callback(
            encoded_data,
            expected_total_amount=expected_amount,
            expected_transaction_uuid=expected_pid,
        )
    except EsewaError as exc:
        _record_subscription_transaction(
            vendor=request.user,
            subscription=None,
            amount=expected_amount,
            payment_status=Booking.PAYMENT_STATUS_FAILED,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
        )
        messages.error(request, f'Subscription payment verification failed: {exc}')
        return redirect('vendor_settings')

    plan = get_object_or_404(VendorSubscriptionPlan, id=payment_session.get('plan_id'))
    subscription = _activate_subscription_after_verified_payment(
        vendor=request.user,
        plan=plan,
        amount=expected_amount,
        payment_method=Booking.PAYMENT_METHOD_ESEWA,
    )

    request.session.pop(session_key, None)
    messages.success(request, f'{subscription.plan_name} subscription activated until {subscription.end_date:%b %d, %Y}.')
    return redirect('vendor_settings')


@never_cache
@login_required(login_url='vendor_login')

def vendor_subscription_esewa_failure(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    session_key = _subscription_payment_session_key(request.user.id)
    payment_session = request.session.get(session_key)
    if payment_session:
        if payment_session.get('payment_method') != Booking.PAYMENT_METHOD_ESEWA:
            messages.error(request, 'Invalid payment callback for this subscription session.')
            return redirect('vendor_settings')
        try:
            failed_amount = Decimal(str(payment_session.get('amount') or '0')).quantize(Decimal('0.01'))
        except InvalidOperation:
            failed_amount = Decimal('0.00')
        _record_subscription_transaction(
            vendor=request.user,
            subscription=None,
            amount=failed_amount,
            payment_status=Booking.PAYMENT_STATUS_FAILED,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
        )
        request.session.pop(session_key, None)

    messages.error(request, 'Subscription payment failed. Please try again.')
    return redirect('vendor_settings')


@never_cache
@login_required(login_url='vendor_login')

def vendor_subscription_stripe_success(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    session_key = _subscription_payment_session_key(request.user.id)
    payment_session = request.session.get(session_key)
    if not payment_session:
        messages.error(request, 'Subscription payment session not found. Please try again.')
        return redirect('vendor_settings')
    if payment_session.get('payment_method') != Booking.PAYMENT_METHOD_STRIPE:
        messages.error(request, 'Invalid payment callback for this subscription session.')
        return redirect('vendor_settings')

    stripe_session_id = (request.GET.get('session_id') or '').strip()
    if not stripe_session_id:
        messages.error(request, 'Missing Stripe checkout session id.')
        return redirect('vendor_settings')

    try:
        expected_amount = Decimal(str(payment_session.get('amount') or '0')).quantize(Decimal('0.01'))
    except InvalidOperation:
        messages.error(request, 'Subscription payment verification failed: Invalid amount.')
        return redirect('vendor_settings')

    try:
        session_data = retrieve_checkout_session(stripe_session_id)
    except StripeError as exc:
        messages.warning(request, f'Stripe verification is pending: {exc}')
        return redirect('vendor_settings')

    metadata = session_data.get('metadata') or {}
    expected_pid = payment_session.get('pid')
    is_paid = (
        session_data.get('status') == 'complete'
        and session_data.get('payment_status') == 'paid'
        and str(session_data.get('client_reference_id') or '') == str(expected_pid)
        and str(metadata.get('pid') or '') == str(expected_pid)
    )

    if not is_paid:
        _record_subscription_transaction(
            vendor=request.user,
            subscription=None,
            amount=expected_amount,
            payment_status=Booking.PAYMENT_STATUS_FAILED,
            payment_method=Booking.PAYMENT_METHOD_STRIPE,
        )
        messages.error(request, 'Stripe payment was not marked as paid. Please retry.')
        return redirect('vendor_settings')

    plan = get_object_or_404(VendorSubscriptionPlan, id=payment_session.get('plan_id'))
    subscription = _activate_subscription_after_verified_payment(
        vendor=request.user,
        plan=plan,
        amount=expected_amount,
        payment_method=Booking.PAYMENT_METHOD_STRIPE,
    )

    request.session.pop(session_key, None)
    messages.success(request, f'{subscription.plan_name} subscription activated until {subscription.end_date:%b %d, %Y}.')
    return redirect('vendor_settings')


@never_cache
@login_required(login_url='vendor_login')

def vendor_subscription_stripe_cancel(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    session_key = _subscription_payment_session_key(request.user.id)
    payment_session = request.session.get(session_key)
    if payment_session and payment_session.get('payment_method') == Booking.PAYMENT_METHOD_STRIPE:
        try:
            failed_amount = Decimal(str(payment_session.get('amount') or '0')).quantize(Decimal('0.01'))
        except InvalidOperation:
            failed_amount = Decimal('0.00')
        _record_subscription_transaction(
            vendor=request.user,
            subscription=None,
            amount=failed_amount,
            payment_status=Booking.PAYMENT_STATUS_FAILED,
            payment_method=Booking.PAYMENT_METHOD_STRIPE,
        )
        request.session.pop(session_key, None)

    messages.warning(request, 'Stripe checkout was canceled. You can try again anytime.')
    return redirect('vendor_settings')


@never_cache
@login_required(login_url='vendor_login')
@csrf_protect

def vendor_feature_slot_purchase(request, slot_id):
    if not _ensure_vendor(request):
        return redirect('vendor_login')
    if request.method != 'POST':
        return redirect('vendor_settings')

    slot = get_object_or_404(FeatureSlot, id=slot_id, is_active=True)
    quantity_raw = (request.POST.get('quantity') or '1').strip()
    try:
        quantity = int(quantity_raw)
    except (TypeError, ValueError):
        messages.error(request, 'Invalid slot quantity.')
        return redirect('vendor_settings')

    if quantity < 1:
        messages.error(request, 'Quantity must be at least 1.')
        return redirect('vendor_settings')
    if quantity > slot.max_slots:
        messages.error(request, f'You can purchase up to {slot.max_slots} slot(s) per order for this slot type.')
        return redirect('vendor_settings')

    payment_method = (request.POST.get('payment_method') or Booking.PAYMENT_METHOD_ESEWA).strip().lower()
    if payment_method not in {Booking.PAYMENT_METHOD_ESEWA, Booking.PAYMENT_METHOD_STRIPE}:
        payment_method = Booking.PAYMENT_METHOD_ESEWA

    amount = (slot.price_per_slot * quantity).quantize(Decimal('0.01'))
    payment_pid = f'FSL-{request.user.id}-{slot.id}-{uuid.uuid4().hex[:8].upper()}'
    payment_session = {
        'pid': payment_pid,
        'slot_id': slot.id,
        'payment_method': payment_method,
        'quantity': quantity,
        'amount': format(amount, 'f'),
        'created_at': timezone.now().isoformat(),
    }
    request.session[_feature_slot_payment_session_key(request.user.id)] = payment_session
    request.session.modified = True

    if payment_method == Booking.PAYMENT_METHOD_STRIPE:
        success_url = (
            request.build_absolute_uri(reverse('vendor_feature_slot_stripe_success'))
            + '?session_id={CHECKOUT_SESSION_ID}'
        )
        cancel_url = request.build_absolute_uri(reverse('vendor_feature_slot_stripe_cancel'))

        try:
            session_data = create_checkout_session_for_item(
                amount=amount,
                name=f'{slot.name} Feature Slot',
                description=f'{quantity} feature slot purchase',
                success_url=success_url,
                cancel_url=cancel_url,
                client_reference_id=payment_pid,
                metadata={
                    'type': 'feature_slot',
                    'pid': payment_pid,
                    'slot_id': slot.id,
                    'vendor_id': request.user.id,
                    'quantity': quantity,
                },
                customer_email=request.user.email or None,
            )
            checkout_url = session_data.get('url')
            if not checkout_url:
                raise StripeError('Stripe did not return a checkout URL.')
            payment_session['stripe_session_id'] = session_data.get('id', '')
            request.session[_feature_slot_payment_session_key(request.user.id)] = payment_session
            request.session.modified = True
            return redirect(checkout_url)
        except StripeError as exc:
            messages.error(request, str(exc))
            return redirect('vendor_settings')

    success_url = request.build_absolute_uri(reverse('vendor_feature_slot_esewa_success'))
    failure_url = request.build_absolute_uri(reverse('vendor_feature_slot_esewa_failure'))
    try:
        payload = _subscription_esewa_payload(
            amount=amount,
            pid=payment_pid,
            success_url=success_url,
            failure_url=failure_url,
        )
    except EsewaError as exc:
        messages.error(request, str(exc))
        return redirect('vendor_settings')

    return render(
        request,
        'core/esewa_redirect.html',
        {
            'booking': None,
            'esewa_payment_url': get_esewa_payment_url(),
            'esewa_payload': payload,
        },
    )


@never_cache
@login_required(login_url='vendor_login')

def vendor_feature_slot_esewa_success(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    session_key = _feature_slot_payment_session_key(request.user.id)
    payment_session = request.session.get(session_key)
    if not payment_session:
        messages.error(request, 'Feature slot payment session not found. Please try again.')
        return redirect('vendor_settings')
    if payment_session.get('payment_method') != Booking.PAYMENT_METHOD_ESEWA:
        messages.error(request, 'Invalid payment callback for this feature slot session.')
        return redirect('vendor_settings')

    # eSewa V2: success redirect carries base64-encoded JSON in ?data=
    encoded_data = (request.GET.get('data') or '').strip()
    if not encoded_data:
        messages.error(request, 'Feature slot payment verification failed: Missing eSewa response data.')
        return redirect('vendor_settings')

    try:
        expected_amount = Decimal(str(payment_session.get('amount') or '0')).quantize(Decimal('0.01'))
    except InvalidOperation:
        messages.error(request, 'Feature slot payment verification failed: Invalid amount.')
        return redirect('vendor_settings')

    expected_pid = payment_session.get('pid', '')

    try:
        response_data, verification = esewa_process_success_callback(
            encoded_data,
            expected_total_amount=expected_amount,
            expected_transaction_uuid=expected_pid,
        )
    except EsewaError as exc:
        _record_feature_slot_transaction(
            vendor=request.user,
            vendor_feature=None,
            amount=expected_amount,
            payment_status=Booking.PAYMENT_STATUS_FAILED,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
        )
        messages.error(request, f'Feature slot payment verification failed: {exc}')
        return redirect('vendor_settings')

    slot = get_object_or_404(FeatureSlot, id=payment_session.get('slot_id'), is_active=True)
    quantity = int(payment_session.get('quantity') or 1)
    vendor_feature = _activate_feature_slots_after_verified_payment(
        vendor=request.user,
        slot=slot,
        purchased_slots=quantity,
        amount=expected_amount,
        payment_method=Booking.PAYMENT_METHOD_ESEWA,
    )

    request.session.pop(session_key, None)
    messages.success(
        request,
        f'Feature slots activated: {vendor_feature.purchased_slots}. Valid until {vendor_feature.end_date:%b %d, %Y}.',
    )
    return redirect('vendor_settings')


@never_cache
@login_required(login_url='vendor_login')

def vendor_feature_slot_esewa_failure(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    session_key = _feature_slot_payment_session_key(request.user.id)
    payment_session = request.session.get(session_key)
    if payment_session:
        if payment_session.get('payment_method') != Booking.PAYMENT_METHOD_ESEWA:
            messages.error(request, 'Invalid payment callback for this feature slot session.')
            return redirect('vendor_settings')
        try:
            failed_amount = Decimal(str(payment_session.get('amount') or '0')).quantize(Decimal('0.01'))
        except InvalidOperation:
            failed_amount = Decimal('0.00')
        _record_feature_slot_transaction(
            vendor=request.user,
            vendor_feature=None,
            amount=failed_amount,
            payment_status=Booking.PAYMENT_STATUS_FAILED,
            payment_method=Booking.PAYMENT_METHOD_ESEWA,
        )
        request.session.pop(session_key, None)

    messages.error(request, 'Feature slot payment failed. Please try again.')
    return redirect('vendor_settings')


@never_cache
@login_required(login_url='vendor_login')

def vendor_feature_slot_stripe_success(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    session_key = _feature_slot_payment_session_key(request.user.id)
    payment_session = request.session.get(session_key)
    if not payment_session:
        messages.error(request, 'Feature slot payment session not found. Please try again.')
        return redirect('vendor_settings')
    if payment_session.get('payment_method') != Booking.PAYMENT_METHOD_STRIPE:
        messages.error(request, 'Invalid payment callback for this feature slot session.')
        return redirect('vendor_settings')

    stripe_session_id = (request.GET.get('session_id') or '').strip()
    if not stripe_session_id:
        messages.error(request, 'Missing Stripe checkout session id.')
        return redirect('vendor_settings')

    try:
        expected_amount = Decimal(str(payment_session.get('amount') or '0')).quantize(Decimal('0.01'))
    except InvalidOperation:
        messages.error(request, 'Feature slot payment verification failed: Invalid amount.')
        return redirect('vendor_settings')

    try:
        session_data = retrieve_checkout_session(stripe_session_id)
    except StripeError as exc:
        messages.warning(request, f'Stripe verification is pending: {exc}')
        return redirect('vendor_settings')

    metadata = session_data.get('metadata') or {}
    expected_pid = payment_session.get('pid')
    is_paid = (
        session_data.get('status') == 'complete'
        and session_data.get('payment_status') == 'paid'
        and str(session_data.get('client_reference_id') or '') == str(expected_pid)
        and str(metadata.get('pid') or '') == str(expected_pid)
    )

    if not is_paid:
        _record_feature_slot_transaction(
            vendor=request.user,
            vendor_feature=None,
            amount=expected_amount,
            payment_status=Booking.PAYMENT_STATUS_FAILED,
            payment_method=Booking.PAYMENT_METHOD_STRIPE,
        )
        messages.error(request, 'Stripe payment was not marked as paid. Please retry.')
        return redirect('vendor_settings')

    slot = get_object_or_404(FeatureSlot, id=payment_session.get('slot_id'), is_active=True)
    quantity = int(payment_session.get('quantity') or 1)
    vendor_feature = _activate_feature_slots_after_verified_payment(
        vendor=request.user,
        slot=slot,
        purchased_slots=quantity,
        amount=expected_amount,
        payment_method=Booking.PAYMENT_METHOD_STRIPE,
    )

    request.session.pop(session_key, None)
    messages.success(
        request,
        f'Feature slots activated: {vendor_feature.purchased_slots}. Valid until {vendor_feature.end_date:%b %d, %Y}.',
    )
    return redirect('vendor_settings')


@never_cache
@login_required(login_url='vendor_login')

def vendor_feature_slot_stripe_cancel(request):
    if not _ensure_vendor(request):
        return redirect('vendor_login')

    session_key = _feature_slot_payment_session_key(request.user.id)
    payment_session = request.session.get(session_key)
    if payment_session and payment_session.get('payment_method') == Booking.PAYMENT_METHOD_STRIPE:
        try:
            failed_amount = Decimal(str(payment_session.get('amount') or '0')).quantize(Decimal('0.01'))
        except InvalidOperation:
            failed_amount = Decimal('0.00')
        _record_feature_slot_transaction(
            vendor=request.user,
            vendor_feature=None,
            amount=failed_amount,
            payment_status=Booking.PAYMENT_STATUS_FAILED,
            payment_method=Booking.PAYMENT_METHOD_STRIPE,
        )
        request.session.pop(session_key, None)

    messages.warning(request, 'Stripe checkout was canceled. You can try again anytime.')
    return redirect('vendor_settings')

