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

    document.querySelectorAll('[data-carousel]').forEach(function (carousel) {
        initCarousel(carousel);
    });
})();
