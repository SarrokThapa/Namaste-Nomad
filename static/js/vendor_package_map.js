(() => {
    const mapElement = document.getElementById('packageLocationMap');
    if (!mapElement || typeof L === 'undefined') {
        return;
    }

    const latInput = document.getElementById('id_latitude');
    const lngInput = document.getElementById('id_longitude');

    const fallbackLat = Number(mapElement.dataset.mapDefaultLat || 28.3949);
    const fallbackLng = Number(mapElement.dataset.mapDefaultLng || 84.124);

    const parseCoord = (input, fallback) => {
        if (!input) {
            return fallback;
        }
        const value = Number(input.value);
        return Number.isFinite(value) ? value : fallback;
    };

    const hasCoords = () => {
        return (
            latInput
            && lngInput
            && latInput.value.trim() !== ''
            && lngInput.value.trim() !== ''
            && Number.isFinite(Number(latInput.value))
            && Number.isFinite(Number(lngInput.value))
        );
    };

    const initialLat = parseCoord(latInput, fallbackLat);
    const initialLng = parseCoord(lngInput, fallbackLng);
    const initialZoom = hasCoords() ? 10 : 6;

    const map = L.map(mapElement).setView([initialLat, initialLng], initialZoom);
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '&copy; OpenStreetMap contributors',
    }).addTo(map);

    let marker = null;

    const updateInputs = (lat, lng) => {
        if (latInput) {
            latInput.value = lat.toFixed(6);
        }
        if (lngInput) {
            lngInput.value = lng.toFixed(6);
        }
    };

    const placeMarker = (lat, lng, shouldCenter = false) => {
        if (!marker) {
            marker = L.marker([lat, lng], { draggable: true }).addTo(map);
            marker.on('dragend', () => {
                const position = marker.getLatLng();
                updateInputs(position.lat, position.lng);
            });
        } else {
            marker.setLatLng([lat, lng]);
        }
        if (shouldCenter) {
            map.setView([lat, lng], 11);
        }
    };

    if (hasCoords()) {
        placeMarker(initialLat, initialLng);
    }

    map.on('click', (event) => {
        const { lat, lng } = event.latlng;
        placeMarker(lat, lng, true);
        updateInputs(lat, lng);
    });

    const handleManualChange = () => {
        if (!hasCoords()) {
            return;
        }
        const lat = Number(latInput.value);
        const lng = Number(lngInput.value);
        if (!Number.isFinite(lat) || !Number.isFinite(lng)) {
            return;
        }
        placeMarker(lat, lng, true);
    };

    if (latInput) {
        latInput.addEventListener('change', handleManualChange);
    }
    if (lngInput) {
        lngInput.addEventListener('change', handleManualChange);
    }
})();
