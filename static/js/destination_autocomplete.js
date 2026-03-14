(() => {
    const inputs = document.querySelectorAll('[data-destination-input]');
    if (!inputs.length) {
        return;
    }

    const cache = new Map();

    const fetchDestinations = async (endpoint) => {
        if (cache.has(endpoint)) {
            return cache.get(endpoint);
        }
        const response = await fetch(endpoint, {
            headers: { 'X-Requested-With': 'XMLHttpRequest' },
        });
        if (!response.ok) {
            return [];
        }
        const data = await response.json();
        const list = Array.isArray(data) ? data : [];
        cache.set(endpoint, list);
        return list;
    };

    const normalize = (value) => (value || '').toString().toLowerCase();

    inputs.forEach((input) => {
        const container = input.closest('.search-field, .destination-input-shell, .explore-search-input-group') || input.parentElement;
        const list = container ? container.querySelector('[data-destination-list]') : null;
        const endpoint = input.dataset.destinationEndpoint || '/api/destinations/';

        if (!list) {
            return;
        }

        let destinations = [];

        const render = (items) => {
            list.innerHTML = '';
            if (!items.length) {
                const empty = document.createElement('div');
                empty.className = 'destination-empty';
                empty.textContent = 'No destinations found.';
                list.appendChild(empty);
                return;
            }

            items.forEach((item) => {
                const option = document.createElement('div');
                option.className = 'destination-suggestion';
                option.innerHTML = `<span>${item}</span><small>Destination</small>`;
                option.addEventListener('click', () => {
                    input.value = item;
                    closeList();
                });
                list.appendChild(option);
            });
        };

        const openList = () => {
            list.classList.add('is-open');
        };

        const closeList = () => {
            list.classList.remove('is-open');
        };

        const updateList = () => {
            const term = normalize(input.value);
            const filtered = term
                ? destinations.filter((item) => normalize(item).includes(term))
                : destinations;
            render(filtered);
            if (filtered.length) {
                openList();
            } else {
                closeList();
            }
        };

        fetchDestinations(endpoint)
            .then((data) => {
                destinations = data;
                updateList();
            })
            .catch(() => {
                destinations = [];
            });

        input.addEventListener('focus', () => {
            updateList();
        });

        input.addEventListener('input', () => {
            updateList();
        });

        document.addEventListener('click', (event) => {
            if (!container.contains(event.target)) {
                closeList();
            }
        });
    });
})();
