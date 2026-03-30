(function () {
    var hero = document.querySelector('.hero');
    if (!hero) {
        return;
    }

    var slides = [
        '/static/images/hero/slide01.jpg?v=20260330c',
        '/static/images/hero/slide02.jpg?v=20260330c',
        '/static/images/hero/slide03.jpg?v=20260330c',
        '/static/images/hero/slide04.jpg?v=20260330c',
        '/static/images/hero/slide05.jpg?v=20260330c',
        '/static/images/hero/slide06.jpg?v=20260330c',
        '/static/images/hero/slide07.jpg?v=20260330c',
        '/static/images/hero/slide08.jpg?v=20260330c',
        '/static/images/hero/slide09.jpg?v=20260330c',
        '/static/images/hero/slide10.jpg?v=20260330c',
        '/static/images/hero/slide11.jpg?v=20260330c',
        '/static/images/hero/slide12.jpg?v=20260330c',
        '/static/images/hero/slide13.jpg?v=20260330c',
        '/static/images/hero/slide14.jpg?v=20260330c',
        '/static/images/hero/slide15.jpg?v=20260330c',
        '/static/images/hero/slide16.jpg?v=20260330c',
        '/static/images/hero/slide17.jpg?v=20260330c'
    ];

    if (slides.length === 0) {
        return;
    }

    var index = 0;
    var fadeMs = 700;
    var displayMs = 3000;

    hero.style.setProperty('--hero-slide-image', 'url("' + slides[index] + '")');
    hero.style.setProperty('--hero-slide-opacity', '1');

    window.setInterval(function () {
        index = (index + 1) % slides.length;
        hero.style.setProperty('--hero-slide-opacity', '0');

        window.setTimeout(function () {
            hero.style.setProperty('--hero-slide-image', 'url("' + slides[index] + '")');
            hero.style.setProperty('--hero-slide-opacity', '1');
        }, fadeMs);
    }, displayMs);
})();
