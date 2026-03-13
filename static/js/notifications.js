(() => {
    const shell = document.querySelector('[data-notification]');
    if (!shell) return;

    const toggle = shell.querySelector('[data-notification-toggle]');
    const panel = shell.querySelector('[data-notification-panel]');
    const list = shell.querySelector('[data-notification-list]');
    const badge = shell.querySelector('[data-notification-count]');
    const markAllBtn = shell.querySelector('[data-notification-mark-all]');

    const dataUrl = '/accounts/notifications/data/';
    const readUrl = '/accounts/notifications/read/';

    const getCookie = (name) => {
        const cookieValue = document.cookie
            .split('; ')
            .find((row) => row.startsWith(`${name}=`));
        return cookieValue ? cookieValue.split('=')[1] : '';
    };

    const csrfToken = getCookie('csrftoken');
    let notifications = [];
    let unreadCount = 0;

    const setBadge = (count) => {
        unreadCount = count;
        if (!badge) return;
        badge.textContent = count > 99 ? '99+' : `${count}`;
        badge.hidden = count <= 0;
    };

    const renderList = () => {
        if (!list) return;
        list.innerHTML = '';
        if (!notifications.length) {
            const empty = document.createElement('div');
            empty.className = 'notification-empty';
            empty.textContent = 'No notifications yet.';
            list.appendChild(empty);
            return;
        }

        notifications.forEach((item) => {
            const link = document.createElement('a');
            link.className = `notification-item${item.is_read ? '' : ' unread'}`;
            link.href = item.link || '#';
            link.textContent = item.message;

            const time = document.createElement('small');
            time.textContent = item.created_at;
            link.appendChild(time);

            link.addEventListener('click', async (event) => {
                if (!item.id) return;
                event.preventDefault();
                await markRead(item.id);
                window.location.href = link.href;
            });

            list.appendChild(link);
        });
    };

    const fetchNotifications = async () => {
        try {
            const response = await fetch(dataUrl, { headers: { 'X-Requested-With': 'XMLHttpRequest' } });
            if (!response.ok) return;
            const payload = await response.json();
            notifications = payload.notifications || [];
            setBadge(payload.unread_count || 0);
            renderList();
        } catch (error) {
            console.error(error);
        }
    };

    const markRead = async (notificationId) => {
        try {
            const formData = new FormData();
            formData.set('notification_id', notificationId);
            const response = await fetch(readUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: formData,
            });
            if (!response.ok) return;
            const payload = await response.json();
            setBadge(payload.unread_count || 0);
            notifications = notifications.map((item) => (
                item.id === notificationId ? { ...item, is_read: true } : item
            ));
            renderList();
        } catch (error) {
            console.error(error);
        }
    };

    const markAllRead = async () => {
        try {
            const formData = new FormData();
            formData.set('mark_all', '1');
            const response = await fetch(readUrl, {
                method: 'POST',
                headers: {
                    'X-CSRFToken': csrfToken,
                    'X-Requested-With': 'XMLHttpRequest',
                },
                body: formData,
            });
            if (!response.ok) return;
            const payload = await response.json();
            setBadge(payload.unread_count || 0);
            notifications = notifications.map((item) => ({ ...item, is_read: true }));
            renderList();
        } catch (error) {
            console.error(error);
        }
    };

    const openPanel = () => {
        panel.classList.add('is-open');
        panel.setAttribute('aria-hidden', 'false');
        toggle.setAttribute('aria-expanded', 'true');
        fetchNotifications();
    };

    const closePanel = () => {
        panel.classList.remove('is-open');
        panel.setAttribute('aria-hidden', 'true');
        toggle.setAttribute('aria-expanded', 'false');
    };

    toggle.addEventListener('click', () => {
        if (panel.classList.contains('is-open')) {
            closePanel();
        } else {
            openPanel();
        }
    });

    document.addEventListener('click', (event) => {
        if (!shell.contains(event.target)) {
            closePanel();
        }
    });

    if (markAllBtn) {
        markAllBtn.addEventListener('click', markAllRead);
    }

    fetchNotifications();

    const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
    const socket = new WebSocket(`${protocol}://${window.location.host}/ws/notifications/`);
    socket.addEventListener('message', (event) => {
        try {
            const payload = JSON.parse(event.data);
            if (!payload) return;
            notifications = [payload, ...notifications];
            setBadge(unreadCount + 1);
            renderList();
        } catch (error) {
            console.error(error);
        }
    });
})();
