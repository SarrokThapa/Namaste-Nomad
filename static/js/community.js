(function () {
    function initCarousel(carousel) {
        var track = carousel.querySelector('.carousel-track');
        if (!track) {
            return;
        }

        var slides = Array.prototype.slice.call(track.children);
        var prevButton = carousel.querySelector('.carousel-btn.prev');
        var nextButton = carousel.querySelector('.carousel-btn.next');
        var dots = Array.prototype.slice.call(carousel.querySelectorAll('.carousel-dot'));
        var index = 0;

        function update() {
            track.style.transform = 'translateX(-' + (index * 100) + '%)';
            if (prevButton) {
                prevButton.disabled = index === 0;
            }
            if (nextButton) {
                nextButton.disabled = index >= slides.length - 1;
            }
            dots.forEach(function (dot, dotIndex) {
                if (dotIndex === index) {
                    dot.classList.add('active');
                } else {
                    dot.classList.remove('active');
                }
            });
            slides.forEach(function (slide, slideIndex) {
                var video = slide.querySelector('video');
                if (video && slideIndex !== index) {
                    video.pause();
                }
            });
        }

        if (prevButton) {
            prevButton.addEventListener('click', function () {
                if (index > 0) {
                    index -= 1;
                    update();
                }
            });
        }

        if (nextButton) {
            nextButton.addEventListener('click', function () {
                if (index < slides.length - 1) {
                    index += 1;
                    update();
                }
            });
        }

        dots.forEach(function (dot, dotIndex) {
            dot.addEventListener('click', function () {
                index = dotIndex;
                update();
            });
        });

        update();
    }

    function initPostMenus() {
        var menus = Array.prototype.slice.call(document.querySelectorAll('[data-post-menu]'));
        if (!menus.length) {
            return;
        }

        function closeAll(except) {
            menus.forEach(function (menu) {
                if (menu !== except) {
                    menu.classList.remove('open');
                }
            });
        }

        menus.forEach(function (menu) {
            var trigger = menu.querySelector('.post-menu-trigger');
            var panel = menu.querySelector('.post-menu-panel');
            if (!trigger) {
                return;
            }
            trigger.addEventListener('click', function (event) {
                event.stopPropagation();
                var isOpen = menu.classList.toggle('open');
                if (isOpen) {
                    closeAll(menu);
                }
            });
            if (panel) {
                panel.addEventListener('click', function (event) {
                    event.stopPropagation();
                });
            }
        });

        document.addEventListener('click', function () {
            closeAll();
        });

        document.addEventListener('keydown', function (event) {
            if (event.key === 'Escape') {
                closeAll();
            }
        });
    }

    function initTagPicker(picker) {
        var trigger = picker.querySelector('[data-tag-trigger]');
        var modal = picker.querySelector('[data-tag-modal]');
        var closeButton = picker.querySelector('[data-tag-close]');
        var cancelButton = picker.querySelector('[data-tag-cancel]');
        var applyButton = picker.querySelector('[data-tag-apply]');
        var searchInput = picker.querySelector('[data-tag-search]');
        var previewList = picker.querySelector('.tag-preview-list');
        var options = Array.prototype.slice.call(picker.querySelectorAll('.tag-option'));

        function updatePreview() {
            if (!previewList) {
                return;
            }
            var selected = options.filter(function (option) {
                var checkbox = option.querySelector('input[type="checkbox"]');
                return checkbox && checkbox.checked;
            });
            if (!selected.length) {
                previewList.textContent = 'None';
                return;
            }
            previewList.textContent = selected.map(function (option) {
                return option.querySelector('[data-tag-name]').dataset.tagName;
            }).join(' ');
        }

        function openModal() {
            if (modal) {
                modal.classList.add('open');
            }
        }

        function closeModal() {
            if (modal) {
                modal.classList.remove('open');
            }
        }

        if (trigger) {
            trigger.addEventListener('click', function () {
                openModal();
            });
        }
        if (closeButton) {
            closeButton.addEventListener('click', function () {
                closeModal();
            });
        }
        if (cancelButton) {
            cancelButton.addEventListener('click', function () {
                closeModal();
            });
        }
        if (applyButton) {
            applyButton.addEventListener('click', function () {
                updatePreview();
                closeModal();
            });
        }
        if (modal) {
            modal.addEventListener('click', function (event) {
                if (event.target === modal) {
                    closeModal();
                }
            });
        }
        if (searchInput) {
            searchInput.addEventListener('input', function () {
                var term = searchInput.value.trim().toLowerCase();
                options.forEach(function (option) {
                    var haystack = (option.dataset.filter || '').toLowerCase();
                    if (!term || haystack.indexOf(term) !== -1) {
                        option.style.display = '';
                    } else {
                        option.style.display = 'none';
                    }
                });
            });
        }
        options.forEach(function (option) {
            var checkbox = option.querySelector('input[type="checkbox"]');
            if (checkbox) {
                checkbox.addEventListener('change', updatePreview);
            }
        });

        updatePreview();
        return openModal;
    }

    document.querySelectorAll('[data-carousel]').forEach(function (carousel) {
        initCarousel(carousel);
    });
    initPostMenus();

    var openFirstTagModal = null;
    document.querySelectorAll('[data-tag-picker]').forEach(function (picker) {
        var opener = initTagPicker(picker);
        if (!openFirstTagModal && opener) {
            openFirstTagModal = opener;
        }
    });

    if (window.location.hash === '#tag-vendors' && openFirstTagModal) {
        openFirstTagModal();
    }
})();
