(() => {
    const searchForm = document.getElementById('packageSearchForm');
    const filterForm = document.getElementById('packageFilterForm');
    const sortSelect = document.getElementById('packageSort');
    const grid = document.getElementById('packageGrid');
    const countEl = document.querySelector('[data-package-count]');

    if (!grid) {
        return;
    }

    const endpoint = grid.dataset.searchEndpoint;
    if (!endpoint) {
        return;
    }

    const quickButtons = document.querySelectorAll('[data-quick-filter]');
    let activeQuick = null;

    const addFormData = (params, form) => {
        if (!form) return;
        const formData = new FormData(form);
        for (const [key, value] of formData.entries()) {
            if (value === '' || value === null) {
                continue;
            }
            params.append(key, value);
        }
    };

    const updateQuickButtons = () => {
        quickButtons.forEach((btn) => {
            const isActive = activeQuick && btn.dataset.quickFilter === activeQuick;
            btn.classList.toggle('active', isActive);
        });
    };

    const buildParams = () => {
        const params = new URLSearchParams();
        addFormData(params, searchForm);
        addFormData(params, filterForm);
        if (sortSelect && sortSelect.value) {
            params.set('sort', sortSelect.value);
        }
        if (activeQuick) {
            params.set('quick', activeQuick);
        }
        return params;
    };

    const updateResults = () => {
        const params = buildParams();
        const queryString = params.toString();
        const url = queryString ? `${endpoint}?${queryString}` : endpoint;
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then((response) => response.json())
            .then((data) => {
                if (data && typeof data.html === 'string') {
                    grid.innerHTML = data.html;
                }
                if (countEl && typeof data.count === 'number') {
                    countEl.textContent = data.count;
                }
                const newUrl = queryString ? `${window.location.pathname}?${queryString}` : window.location.pathname;
                window.history.replaceState({}, '', newUrl);
            })
            .catch(() => {
                // ignore network errors for now
            });
    };

    let debounceTimer = null;
    const debouncedUpdate = () => {
        window.clearTimeout(debounceTimer);
        debounceTimer = window.setTimeout(updateResults, 300);
    };

    if (searchForm) {
        searchForm.addEventListener('submit', (event) => {
            event.preventDefault();
            updateResults();
        });
        searchForm.addEventListener('input', debouncedUpdate);
        searchForm.addEventListener('change', updateResults);
    }

    if (filterForm) {
        filterForm.addEventListener('change', updateResults);
    }

    if (sortSelect) {
        sortSelect.addEventListener('change', updateResults);
    }

    quickButtons.forEach((btn) => {
        btn.addEventListener('click', () => {
            const value = btn.dataset.quickFilter;
            if (activeQuick === value) {
                activeQuick = null;
            } else {
                activeQuick = value;
            }
            updateQuickButtons();
            updateResults();
        });
        if (btn.classList.contains('active')) {
            activeQuick = btn.dataset.quickFilter;
        }
    });

    const minRange = document.querySelector('[data-price-min-range]');
    const maxRange = document.querySelector('[data-price-max-range]');
    const minInput = document.getElementById('priceMinInput');
    const maxInput = document.getElementById('priceMaxInput');

    const syncPrice = (source) => {
        if (!minRange || !maxRange || !minInput || !maxInput) {
            return;
        }
        let minValue = Number(minInput.value || minRange.value);
        let maxValue = Number(maxInput.value || maxRange.value);
        if (source === 'range') {
            minValue = Number(minRange.value);
            maxValue = Number(maxRange.value);
        }
        if (minValue > maxValue) {
            [minValue, maxValue] = [maxValue, minValue];
        }
        minRange.value = minValue;
        maxRange.value = maxValue;
        minInput.value = minValue;
        maxInput.value = maxValue;
    };

    if (minRange && maxRange && minInput && maxInput) {
        minRange.addEventListener('input', () => {
            syncPrice('range');
            debouncedUpdate();
        });
        maxRange.addEventListener('input', () => {
            syncPrice('range');
            debouncedUpdate();
        });
        minInput.addEventListener('change', () => {
            syncPrice('input');
            updateResults();
        });
        maxInput.addEventListener('change', () => {
            syncPrice('input');
            updateResults();
        });
    }
})();
