/* =============================================================
   toast.js — Toast notifications + confirmation modals
   Namaste Nomad
   ============================================================= */

(function (global) {
    'use strict';

    /* ------------------------------------------------------------------
       Icons (inline SVG strings)
       ------------------------------------------------------------------ */
    var ICONS = {
        success: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M20 6L9 17l-5-5"/></svg>',
        error:   '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M18 6L6 18M6 6l12 12"/></svg>',
        warning: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/></svg>',
        info:    '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>',
    };

    var TITLES = { success: 'Success', error: 'Error', warning: 'Warning', info: 'Info' };
    var DEFAULT_DURATION = 4000;

    /* ------------------------------------------------------------------
       Ensure container exists
       ------------------------------------------------------------------ */
    function getContainer() {
        var el = document.getElementById('toast-container');
        if (!el) {
            el = document.createElement('div');
            el.id = 'toast-container';
            el.className = 'toast-container';
            document.body.appendChild(el);
        }
        return el;
    }

    /* ------------------------------------------------------------------
       Show a toast
       ------------------------------------------------------------------ */
    function show(type, message, options) {
        options = options || {};
        var duration = options.duration != null ? options.duration : DEFAULT_DURATION;
        var title = options.title || TITLES[type] || 'Notice';

        var container = getContainer();

        var toast = document.createElement('div');
        toast.className = 'toast toast-' + type;
        toast.innerHTML = [
            '<div class="toast-icon">' + (ICONS[type] || '') + '</div>',
            '<div class="toast-body">',
            '  <div class="toast-title">' + escHtml(title) + '</div>',
            '  <div class="toast-message">' + escHtml(message) + '</div>',
            '</div>',
            '<button class="toast-close" aria-label="Close">&times;</button>',
            '<div class="toast-progress" style="width:100%"></div>',
        ].join('');

        container.appendChild(toast);

        // Animate in
        requestAnimationFrame(function () {
            requestAnimationFrame(function () { toast.classList.add('toast-show'); });
        });

        // Progress bar countdown
        var progress = toast.querySelector('.toast-progress');
        if (duration > 0 && progress) {
            progress.style.transition = 'transform ' + duration + 'ms linear';
            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    progress.style.transform = 'scaleX(0)';
                    progress.style.transformOrigin = 'left';
                });
            });
        }

        // Close button
        toast.querySelector('.toast-close').addEventListener('click', function () {
            dismiss(toast);
        });

        // Auto-dismiss
        var timer;
        if (duration > 0) {
            timer = setTimeout(function () { dismiss(toast); }, duration);
        }

        // Pause on hover
        toast.addEventListener('mouseenter', function () { clearTimeout(timer); });
        toast.addEventListener('mouseleave', function () {
            if (duration > 0) timer = setTimeout(function () { dismiss(toast); }, 1000);
        });

        return toast;
    }

    function dismiss(toast) {
        toast.classList.remove('toast-show');
        toast.classList.add('toast-hide');
        toast.addEventListener('transitionend', function () { toast.remove(); }, { once: true });
    }

    function escHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /* ------------------------------------------------------------------
       Public API
       ------------------------------------------------------------------ */
    var Toast = {
        success: function (msg, opts) { return show('success', msg, opts); },
        error:   function (msg, opts) { return show('error',   msg, opts); },
        warning: function (msg, opts) { return show('warning', msg, opts); },
        info:    function (msg, opts) { return show('info',    msg, opts); },
        show:    show,
        dismiss: dismiss,
    };

    /* ------------------------------------------------------------------
       Confirmation modal
       ------------------------------------------------------------------ */
    Toast.confirm = function (options) {
        options = options || {};
        var title   = options.title   || 'Are you sure?';
        var message = options.message || 'This action cannot be undone.';
        var confirmLabel = options.confirmLabel || "Yes, I'm sure";
        var cancelLabel  = options.cancelLabel  || 'Cancel';

        return new Promise(function (resolve) {
            var overlay = document.createElement('div');
            overlay.className = 'confirm-overlay';
            overlay.innerHTML = [
                '<div class="confirm-modal" role="dialog" aria-modal="true">',
                '  <div class="confirm-icon">',
                '    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">',
                '      <path d="M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/>',
                '    </svg>',
                '  </div>',
                '  <div class="confirm-title">' + escHtml(title) + '</div>',
                '  <div class="confirm-message">' + escHtml(message) + '</div>',
                '  <div class="confirm-actions">',
                '    <button class="confirm-btn-cancel">' + escHtml(cancelLabel) + '</button>',
                '    <button class="confirm-btn-confirm">' + escHtml(confirmLabel) + '</button>',
                '  </div>',
                '</div>',
            ].join('');

            document.body.appendChild(overlay);
            requestAnimationFrame(function () {
                requestAnimationFrame(function () { overlay.classList.add('confirm-show'); });
            });

            function close(result) {
                overlay.classList.remove('confirm-show');
                overlay.addEventListener('transitionend', function () { overlay.remove(); }, { once: true });
                resolve(result);
            }

            overlay.querySelector('.confirm-btn-cancel').addEventListener('click', function () { close(false); });
            overlay.querySelector('.confirm-btn-confirm').addEventListener('click', function () { close(true); });
            overlay.addEventListener('click', function (e) {
                if (e.target === overlay) close(false);
            });
            document.addEventListener('keydown', function handler(e) {
                if (e.key === 'Escape') { close(false); document.removeEventListener('keydown', handler); }
            });
        });
    };

    /* ------------------------------------------------------------------
       Auto-render Django flash messages embedded in the page
       Looks for <div id="django-messages" data-messages="[...]">
       ------------------------------------------------------------------ */
    function renderDjangoMessages() {
        var el = document.getElementById('django-messages-data');
        if (!el) return;
        var msgs;
        try { msgs = JSON.parse(el.textContent); } catch (e) { return; }
        msgs.forEach(function (m, i) {
            setTimeout(function () {
                var type = m.level_tag === 'error' ? 'error'
                         : m.level_tag === 'success' ? 'success'
                         : m.level_tag === 'warning' ? 'warning'
                         : 'info';
                Toast[type](m.message);
            }, i * 180);
        });
        el.remove();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', renderDjangoMessages);
    } else {
        renderDjangoMessages();
    }

    global.Toast = Toast;
})(window);
