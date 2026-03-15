(() => {
    const getCookie = (name) => {
        const cookieValue = document.cookie
            .split('; ')
            .find((row) => row.startsWith(`${name}=`));
        return cookieValue ? cookieValue.split('=')[1] : '';
    };

    const csrfToken = getCookie('csrftoken');

    const updateCount = (count) => {
        document.querySelectorAll('[data-wishlist-count]').forEach((badge) => {
            const value = Number(count || 0);
            badge.textContent = value > 99 ? '99+' : `${value}`;
            badge.hidden = value <= 0;
        });
    };

    const setButtonState = (button, isActive) => {
        button.classList.toggle('is-active', isActive);
        button.setAttribute('aria-pressed', isActive ? 'true' : 'false');
        button.setAttribute(
            'aria-label',
            isActive ? 'Remove from wishlist' : 'Save package to wishlist'
        );
        if (isActive) {
            button.classList.add('is-animate');
            window.setTimeout(() => button.classList.remove('is-animate'), 250);
        }
    };

    const removeWishlistCard = (button) => {
        const card = button.closest('[data-wishlist-card]');
        if (!card) return;
        card.classList.add('wishlist-card--removing');
        window.setTimeout(() => {
            card.remove();
            const grid = document.querySelector('[data-wishlist-grid]');
            if (!grid) return;
            if (grid.querySelectorAll('[data-wishlist-card]').length === 0) {
                const empty = document.createElement('div');
                empty.className = 'wishlist-empty';
                empty.textContent = 'You have no saved packages yet.';
                grid.replaceWith(empty);
            }
        }, 200);
    };

    const handleToggle = async (button) => {
        if (button.classList.contains('is-busy')) return;

        const canWishlist = button.dataset.canWishlist === 'true';
        if (!canWishlist) {
            const isAuthenticated = button.dataset.authenticated === 'true';
            const loginUrl = button.dataset.loginUrl;
            if (!isAuthenticated && loginUrl) {
                window.location.href = loginUrl;
                return;
            }
            const message = button.dataset.deniedMessage || 'Wishlist is available for traveler accounts only.';
            window.alert(message);
            return;
        }

        const packageId = button.dataset.packageId;
        const url = button.dataset.wishlistUrl;
        if (!packageId || !url) return;

        button.classList.add('is-busy');
        try {
            const formData = new FormData();
            formData.set('package_id', packageId);

            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: formData,
            });

            if (!response.ok) {
                button.classList.remove('is-busy');
                return;
            }

            const payload = await response.json();
            if (typeof payload.is_wishlisted === 'boolean') {
                const selector = `[data-wishlist-toggle][data-package-id="${packageId}"]`;
                document.querySelectorAll(selector).forEach((btn) => {
                    setButtonState(btn, payload.is_wishlisted);
                });
            }
            if (typeof payload.count === 'number') {
                updateCount(payload.count);
            }
            if (payload.status === 'removed') {
                removeWishlistCard(button);
            }
        } catch (error) {
            console.error(error);
        } finally {
            button.classList.remove('is-busy');
        }
    };

    document.addEventListener('click', (event) => {
        const button = event.target.closest('[data-wishlist-toggle]');
        if (!button) return;
        event.preventDefault();
        handleToggle(button);
    });
})();
