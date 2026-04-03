/* =============================================================
   animations.js — Shared scroll-reveal + lazy-load for Namaste Nomad
   ============================================================= */

(function () {
    'use strict';

    /* ------------------------------------------------------------------
       Scroll-reveal via IntersectionObserver
       Targets: .reveal, .reveal-left, .reveal-right, .reveal-group
       ------------------------------------------------------------------ */
    function initScrollReveal() {
        const els = document.querySelectorAll('.reveal, .reveal-left, .reveal-right, .reveal-group');
        if (!els.length || !('IntersectionObserver' in window)) {
            // Fallback: make everything visible immediately
            els.forEach(function (el) { el.classList.add('revealed'); });
            return;
        }

        const observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add('revealed');
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.12, rootMargin: '0px 0px -40px 0px' });

        els.forEach(function (el) { observer.observe(el); });
    }

    /* ------------------------------------------------------------------
       Lazy-load images with data-src attribute
       ------------------------------------------------------------------ */
    function initLazyLoad() {
        const imgs = document.querySelectorAll('img[data-src]');
        if (!imgs.length || !('IntersectionObserver' in window)) {
            imgs.forEach(function (img) {
                img.src = img.dataset.src;
                img.classList.add('loaded');
            });
            return;
        }

        const io = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    var img = entry.target;
                    img.src = img.dataset.src;
                    img.classList.add('lazy');
                    img.onload = function () { img.classList.add('loaded'); };
                    io.unobserve(img);
                }
            });
        }, { rootMargin: '200px' });

        imgs.forEach(function (img) { io.observe(img); });
    }

    /* ------------------------------------------------------------------
       Stat counter animation (counts up from 0 to target value)
       Usage: <span class="count-up" data-target="500">0</span>
       ------------------------------------------------------------------ */
    function initCountUp() {
        var els = document.querySelectorAll('.count-up');
        if (!els.length || !('IntersectionObserver' in window)) return;

        var seen = new WeakSet();
        var io = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (!entry.isIntersecting || seen.has(entry.target)) return;
                seen.add(entry.target);
                animateCount(entry.target);
                io.unobserve(entry.target);
            });
        }, { threshold: 0.5 });

        els.forEach(function (el) { io.observe(el); });
    }

    function animateCount(el) {
        var target = parseInt(el.dataset.target, 10) || 0;
        var suffix = el.dataset.suffix || '';
        var duration = 1600;
        var start = performance.now();

        function step(now) {
            var elapsed = now - start;
            var progress = Math.min(elapsed / duration, 1);
            // easeOutExpo
            var ease = progress === 1 ? 1 : 1 - Math.pow(2, -10 * progress);
            el.textContent = Math.floor(ease * target).toLocaleString() + suffix;
            if (progress < 1) requestAnimationFrame(step);
        }
        requestAnimationFrame(step);
    }

    /* ------------------------------------------------------------------
       Active-link highlight (adds .active to nav links matching current URL)
       ------------------------------------------------------------------ */
    function initActiveNav() {
        var path = window.location.pathname;
        document.querySelectorAll('nav a[href]').forEach(function (link) {
            if (link.getAttribute('href') === path) {
                link.classList.add('active');
            }
        });
    }

    /* ------------------------------------------------------------------
       Button ripple effect
       ------------------------------------------------------------------ */
    function initRipple() {
        document.addEventListener('click', function (e) {
            var btn = e.target.closest('.btn-primary, .btn-outline, .btn-danger, .btn-secondary');
            if (!btn) return;
            var circle = document.createElement('span');
            var rect = btn.getBoundingClientRect();
            var size = Math.max(rect.width, rect.height);
            circle.style.cssText = [
                'position:absolute',
                'border-radius:50%',
                'transform:scale(0)',
                'animation:ripple 0.5s linear',
                'background:rgba(255,255,255,0.3)',
                'pointer-events:none',
                'width:' + size + 'px',
                'height:' + size + 'px',
                'left:' + (e.clientX - rect.left - size / 2) + 'px',
                'top:' + (e.clientY - rect.top - size / 2) + 'px',
            ].join(';');
            if (getComputedStyle(btn).position === 'static') {
                btn.style.position = 'relative';
            }
            btn.style.overflow = 'hidden';
            btn.appendChild(circle);
            setTimeout(function () { circle.remove(); }, 600);
        });

        // Inject keyframe once
        if (!document.getElementById('ripple-style')) {
            var s = document.createElement('style');
            s.id = 'ripple-style';
            s.textContent = '@keyframes ripple{to{transform:scale(2.5);opacity:0}}';
            document.head.appendChild(s);
        }
    }

    /* ------------------------------------------------------------------
       Init on DOMContentLoaded
       ------------------------------------------------------------------ */
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

    function init() {
        initScrollReveal();
        initLazyLoad();
        initCountUp();
        initRipple();
    }
})();
