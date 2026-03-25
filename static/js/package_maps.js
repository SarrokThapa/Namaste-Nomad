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

    const escapeHtml = (value) => {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    };

    const trimDescription = (value, maxLength = 180) => {
        const text = String(value || '').replace(/\s+/g, ' ').trim();
        if (!text) {
            return '';
        }
        if (text.length <= maxLength) {
            return text;
        }
        return `${text.slice(0, maxLength - 1).trimEnd()}…`;
    };

    const formatPrice = (value) => {
        const numberValue = Number(value);
        if (!Number.isFinite(numberValue)) {
            return 'Price on request';
        }
        return `Rs ${numberValue.toLocaleString()}`;
    };

    const buildGallery = (images, packageName) => {
        if (!images.length) {
            return '<div class="map-popup__gallery-empty">No images uploaded yet.</div>';
        }
        return `
            <div class="map-popup__gallery">
                ${images.slice(0, 6).map((imageUrl, index) => `
                    <img
                        class="map-popup__gallery-image"
                        src="${escapeHtml(imageUrl)}"
                        alt="${escapeHtml(packageName)} image ${index + 1}"
                        loading="lazy"
                    >
                `).join('')}
            </div>
        `;
    };

    const buildPackageCard = (pkg, details) => {
        const name = details.name || pkg.name || 'Package';
        const location = pkg.location_name || '';
        const priceLabel = formatPrice(pkg.price);
        const description = trimDescription(details.description);
        const images = Array.isArray(details.images) ? details.images.filter(Boolean) : [];
        const safeUrl = typeof pkg.url === 'string' && pkg.url.trim() ? pkg.url : '#';
        const locationLine = location ? `<div class="map-popup__meta">${escapeHtml(location)}</div>` : '';
        const descriptionLine = description ? `<p class="map-popup__description">${escapeHtml(description)}</p>` : '';
        const galleryBlock = buildGallery(images, name);

        return `
            <article class="map-popup__package">
                <div class="map-popup__body">
                    <div class="map-popup__title">${escapeHtml(name)}</div>
                    ${locationLine}
                    <div class="map-popup__price">${priceLabel}</div>
                    ${descriptionLine}
                </div>
                ${galleryBlock}
                <a class="map-popup__link" href="${escapeHtml(safeUrl)}">View Details</a>
            </article>
        `;
    };

    const buildLoadingPopup = (count) => {
        return `
            <div class="map-popup map-popup--loading">
                Loading ${count > 1 ? `${count} packages` : 'package details'}...
            </div>
        `;
    };

    const buildErrorPopup = () => {
        return `
            <div class="map-popup map-popup--error">
                Unable to load package details right now.
            </div>
        `;
    };

    const buildMarkerPopup = (packages, detailsList) => {
        const cards = packages.map((pkg, index) => buildPackageCard(pkg, detailsList[index] || {})).join('');
        const heading = packages.length > 1
            ? `<div class="map-popup__group-title">${packages.length} packages at this location</div>`
            : '';
        return `
            <div class="map-popup map-popup--rich">
                ${heading}
                <div class="map-popup__package-list">${cards}</div>
            </div>
        `;
    };

    const groupedPackages = (packages) => {
        const groups = new Map();

        packages.forEach((pkg) => {
            const lat = toNumber(pkg.lat);
            const lng = toNumber(pkg.lng);
            if (lat === null || lng === null) {
                return;
            }

            // Round to group packages that sit at the same or very nearby coordinates.
            const key = `${lat.toFixed(4)}:${lng.toFixed(4)}`;
            if (!groups.has(key)) {
                groups.set(key, {
                    lat,
                    lng,
                    packages: [],
                });
            }
            groups.get(key).packages.push(pkg);
        });

        return Array.from(groups.values());
    };

    const detailsCache = new Map();

    const loadPackageDetails = async (pkg) => {
        const cacheKey = String(pkg.id || '');
        if (detailsCache.has(cacheKey)) {
            return detailsCache.get(cacheKey);
        }

        const fallback = {
            name: pkg.name || 'Package',
            description: '',
            images: pkg.image ? [pkg.image] : [],
        };
        const detailsUrl = pkg.details_url || `/package/${pkg.id}/details/`;
        if (!pkg.id) {
            return fallback;
        }

        try {
            const response = await fetch(detailsUrl, {
                headers: { Accept: 'application/json' },
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            const details = {
                name: payload.name || fallback.name,
                description: payload.description || '',
                images: Array.isArray(payload.images)
                    ? payload.images.filter(Boolean)
                    : fallback.images,
            };
            detailsCache.set(cacheKey, details);
            return details;
        } catch (error) {
            return fallback;
        }
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

                const groups = groupedPackages(packages);
                const bounds = [];
                groups.forEach((group) => {
                    const markerCategory = group.packages.length ? group.packages[0].category : '';
                    const marker = L.marker([group.lat, group.lng], {
                        icon: getIcon(markerCategory),
                    }).addTo(map);

                    marker.bindPopup(
                        buildLoadingPopup(group.packages.length),
                        { maxWidth: 360 }
                    );
                    marker.on('click', async () => {
                        marker.getPopup().setContent(buildLoadingPopup(group.packages.length));
                        const detailsList = await Promise.all(
                            group.packages.map((pkg) => loadPackageDetails(pkg))
                        );
                        if (!detailsList.length) {
                            marker.getPopup().setContent(buildErrorPopup());
                            return;
                        }
                        marker.getPopup().setContent(buildMarkerPopup(group.packages, detailsList));
                    });

                    bounds.push([group.lat, group.lng]);
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
