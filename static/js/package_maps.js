(() => {
    if (typeof L === 'undefined') {
        return;
    }

    const mapElements = document.querySelectorAll('[data-package-map]');
    if (!mapElements.length) {
        return;
    }

    const trekIcon = L.divIcon({
        className: 'map-marker-icon',
        html: '<span class="map-pin map-pin--trek"></span>',
        iconSize: [18, 18],
        iconAnchor: [9, 9],
        popupAnchor: [0, -8],
    });

    const tourIcon = L.divIcon({
        className: 'map-marker-icon',
        html: '<span class="map-pin map-pin--tour"></span>',
        iconSize: [18, 18],
        iconAnchor: [9, 9],
        popupAnchor: [0, -8],
    });

    const getIcon = (category) => {
        const value = (category || '').toString().toLowerCase();
        return value === 'tour' || value === 'tour_packages' || value === 'touring' ? tourIcon : trekIcon;
    };

    const toNumber = (value) => {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
    };

    const formatPrice = (value) => {
        const numberValue = Number(value);
        if (!Number.isFinite(numberValue)) {
            return 'Price on request';
        }
        return `Rs ${numberValue.toLocaleString()}`;
    };

    const buildPopup = (pkg) => {
        const name = pkg.name || 'Package';
        const location = pkg.location_name || '';
        const priceLabel = formatPrice(pkg.price);
        const imageBlock = pkg.image
            ? `<div class="map-popup__image" style="background-image: url('${pkg.image}')"></div>`
            : '';
        const locationLine = location ? `<div class="map-popup__meta">${location}</div>` : '';

        return `
            <div class="map-popup">
                ${imageBlock}
                <div class="map-popup__body">
                    <div class="map-popup__title">${name}</div>
                    ${locationLine}
                    <div class="map-popup__price">${priceLabel}</div>
                    <a class="map-popup__link" href="${pkg.url || '#'}">View Package</a>
                </div>
            </div>
        `;
    };

    mapElements.forEach((element) => {
        const latValue = toNumber(element.dataset.lat);
        const lngValue = toNumber(element.dataset.lng);
        const centerLat = toNumber(element.dataset.centerLat) ?? latValue ?? 28.3949;
        const centerLng = toNumber(element.dataset.centerLng) ?? lngValue ?? 84.1240;
        const zoom = Number(element.dataset.zoom) || (latValue && lngValue ? 10 : 6);

        const map = L.map(element).setView([centerLat, centerLng], zoom);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            attribution: '&copy; OpenStreetMap contributors',
        }).addTo(map);

        const fitBounds = element.dataset.fitBounds === '1';

        if (latValue !== null && lngValue !== null) {
            const marker = L.marker([latValue, lngValue], {
                icon: getIcon(element.dataset.category),
            }).addTo(map);
            const label = element.dataset.name || 'Package Location';
            marker.bindPopup(`<div class="map-popup__single">${label}</div>`).openPopup();
            return;
        }

        const apiUrl = element.dataset.apiUrl;
        if (!apiUrl) {
            return;
        }

        fetch(apiUrl)
            .then((response) => response.json())
            .then((packages) => {
                if (!Array.isArray(packages)) {
                    return;
                }
                const bounds = [];
                packages.forEach((pkg) => {
                    const lat = toNumber(pkg.lat);
                    const lng = toNumber(pkg.lng);
                    if (lat === null || lng === null) {
                        return;
                    }
                    const marker = L.marker([lat, lng], { icon: getIcon(pkg.category) }).addTo(map);
                    marker.bindPopup(buildPopup(pkg));
                    bounds.push([lat, lng]);
                });
                if (fitBounds && bounds.length) {
                    map.fitBounds(bounds, { padding: [40, 40] });
                }
            })
            .catch((error) => {
                console.error('Failed to load map packages', error);
            });
    });
})();
