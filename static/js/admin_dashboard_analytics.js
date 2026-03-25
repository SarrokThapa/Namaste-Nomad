(() => {
    if (typeof Chart === 'undefined') {
        return;
    }

    const root = document.querySelector('[data-admin-analytics-dashboard]');
    if (!root) {
        return;
    }

    const analyticsUrl = root.dataset.analyticsUrl;
    const yearSelect = document.getElementById('adminAnalyticsYear');
    const statusEl = document.getElementById('adminAnalyticsStatus');
    if (!analyticsUrl || !yearSelect) {
        return;
    }

    const MONTH_FULL_NAMES = {
        Jan: 'January',
        Feb: 'February',
        Mar: 'March',
        Apr: 'April',
        May: 'May',
        Jun: 'June',
        Jul: 'July',
        Aug: 'August',
        Sep: 'September',
        Oct: 'October',
        Nov: 'November',
        Dec: 'December',
    };

    const charts = {
        revenue: null,
        bookings: null,
        vendors: null,
        categories: null,
    };

    const formatNumber = (value) => {
        const parsed = Number(value);
        if (!Number.isFinite(parsed)) {
            return '0';
        }
        return parsed.toLocaleString('en-US', {
            maximumFractionDigits: 0,
        });
    };

    const formatCurrency = (value) => `Rs ${formatNumber(value)}`;

    const formatGrowthText = (growth) => {
        if (!growth) {
            return '--';
        }
        if (growth.percent === null || typeof growth.percent === 'undefined') {
            if (growth.previous_month) {
                return `No baseline vs ${growth.previous_month}`;
            }
            return 'No previous month';
        }
        const numeric = Number(growth.percent);
        if (!Number.isFinite(numeric)) {
            return '--';
        }
        const sign = numeric > 0 ? '+' : '';
        return `${sign}${numeric}% from ${growth.previous_month || 'last month'}`;
    };

    const growthClassName = (growth) => {
        if (!growth || growth.percent === null || typeof growth.percent === 'undefined') {
            return 'neutral';
        }
        const numeric = Number(growth.percent);
        if (!Number.isFinite(numeric)) {
            return 'neutral';
        }
        if (numeric > 0) {
            return 'positive';
        }
        if (numeric < 0) {
            return 'negative';
        }
        return 'neutral';
    };

    const setStatus = (message) => {
        if (statusEl) {
            statusEl.textContent = message;
        }
    };

    const commonAnimation = {
        duration: 650,
        easing: 'easeOutQuart',
    };

    const commonInteraction = {
        mode: 'index',
        intersect: false,
    };

    const getMonthTooltipLabel = (monthAbbr) => MONTH_FULL_NAMES[monthAbbr] || monthAbbr;

    const upsertRevenueChart = (labels, values) => {
        const ctx = document.getElementById('adminRevenueChart');
        if (!ctx) {
            return;
        }

        if (!charts.revenue) {
            charts.revenue = new Chart(ctx, {
                type: 'line',
                data: {
                    labels,
                    datasets: [
                        {
                            label: 'Platform Revenue',
                            data: values,
                            borderColor: '#2563eb',
                            backgroundColor: 'rgba(37, 99, 235, 0.16)',
                            fill: true,
                            tension: 0.35,
                            pointRadius: 3,
                            pointHoverRadius: 7,
                            pointHoverBorderWidth: 2,
                            pointBackgroundColor: '#1d4ed8',
                            pointBorderColor: '#ffffff',
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: commonAnimation,
                    interaction: commonInteraction,
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                callback: (value) => `Rs ${formatNumber(value)}`,
                            },
                            grid: {
                                color: 'rgba(148, 163, 184, 0.2)',
                            },
                        },
                        x: {
                            grid: {
                                display: false,
                            },
                        },
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                title: (items) => `Month: ${getMonthTooltipLabel(items[0].label)}`,
                                label: (item) => `Revenue: ${formatCurrency(item.parsed.y)}`,
                            },
                        },
                    },
                },
            });
            return;
        }

        charts.revenue.data.labels = labels;
        charts.revenue.data.datasets[0].data = values;
        charts.revenue.update();
    };

    const upsertBookingsChart = (labels, values) => {
        const ctx = document.getElementById('adminBookingsChart');
        if (!ctx) {
            return;
        }

        if (!charts.bookings) {
            charts.bookings = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [
                        {
                            label: 'Bookings',
                            data: values,
                            backgroundColor: 'rgba(34, 197, 94, 0.75)',
                            hoverBackgroundColor: 'rgba(22, 163, 74, 0.95)',
                            borderRadius: 8,
                            maxBarThickness: 28,
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: commonAnimation,
                    interaction: commonInteraction,
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: {
                                precision: 0,
                            },
                            grid: {
                                color: 'rgba(148, 163, 184, 0.2)',
                            },
                        },
                        x: {
                            grid: { display: false },
                        },
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                title: (items) => getMonthTooltipLabel(items[0].label),
                                label: (item) => `${item.parsed.y} bookings`,
                            },
                        },
                    },
                },
            });
            return;
        }

        charts.bookings.data.labels = labels;
        charts.bookings.data.datasets[0].data = values;
        charts.bookings.update();
    };

    const upsertVendorsChart = (rows) => {
        const ctx = document.getElementById('adminVendorsChart');
        if (!ctx) {
            return;
        }

        const hasRows = Array.isArray(rows) && rows.length > 0;
        const labels = hasRows ? rows.map((row) => row.name) : ['No vendor data'];
        const values = hasRows ? rows.map((row) => row.earnings) : [0];

        if (!charts.vendors) {
            charts.vendors = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels,
                    datasets: [
                        {
                            label: 'Vendor Earnings',
                            data: values,
                            backgroundColor: hasRows
                                ? 'rgba(14, 116, 144, 0.78)'
                                : 'rgba(148, 163, 184, 0.6)',
                            hoverBackgroundColor: hasRows
                                ? 'rgba(8, 145, 178, 0.9)'
                                : 'rgba(148, 163, 184, 0.7)',
                            borderRadius: 8,
                            maxBarThickness: 26,
                        },
                    ],
                },
                options: {
                    indexAxis: 'y',
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: commonAnimation,
                    scales: {
                        x: {
                            beginAtZero: true,
                            ticks: {
                                callback: (value) => `Rs ${formatNumber(value)}`,
                            },
                            grid: {
                                color: 'rgba(148, 163, 184, 0.2)',
                            },
                        },
                        y: {
                            grid: { display: false },
                        },
                    },
                    plugins: {
                        legend: { display: false },
                        tooltip: {
                            callbacks: {
                                label: (item) => `Earnings: ${formatCurrency(item.parsed.x)}`,
                            },
                        },
                    },
                },
            });
            return;
        }

        charts.vendors.data.labels = labels;
        charts.vendors.data.datasets[0].data = values;
        charts.vendors.data.datasets[0].backgroundColor = hasRows
            ? 'rgba(14, 116, 144, 0.78)'
            : 'rgba(148, 163, 184, 0.6)';
        charts.vendors.data.datasets[0].hoverBackgroundColor = hasRows
            ? 'rgba(8, 145, 178, 0.9)'
            : 'rgba(148, 163, 184, 0.7)';
        charts.vendors.update();
    };

    const upsertCategoryChart = (categoryData) => {
        const ctx = document.getElementById('adminCategoryChart');
        if (!ctx) {
            return;
        }

        const labels = Array.isArray(categoryData?.labels) ? categoryData.labels : ['Treks', 'Tours', 'Cultural'];
        const values = Array.isArray(categoryData?.values) ? categoryData.values : [0, 0, 0];
        const colors = ['#16a34a', '#2563eb', '#f59e0b'];

        if (!charts.categories) {
            charts.categories = new Chart(ctx, {
                type: 'pie',
                data: {
                    labels,
                    datasets: [
                        {
                            data: values,
                            backgroundColor: colors,
                            hoverOffset: 8,
                            borderWidth: 1,
                            borderColor: '#ffffff',
                        },
                    ],
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: commonAnimation,
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: {
                                boxWidth: 12,
                                boxHeight: 12,
                            },
                        },
                        tooltip: {
                            callbacks: {
                                label: (item) => `${item.label}: ${item.parsed}`,
                            },
                        },
                    },
                },
            });
            return;
        }

        charts.categories.data.labels = labels;
        charts.categories.data.datasets[0].data = values;
        charts.categories.update();
    };

    const updateSummaryCards = (summary) => {
        const statFields = {
            platform_earnings: { currency: true },
            vendor_earnings: { currency: true },
            subscription_revenue: { currency: true },
            total_users: { currency: false },
            active_vendors: { currency: false },
            total_bookings: { currency: false },
        };

        Object.keys(statFields).forEach((field) => {
            const el = root.querySelector(`[data-stat-value="${field}"]`);
            if (!el) {
                return;
            }
            const value = summary?.[field] ?? 0;
            el.textContent = statFields[field].currency ? formatCurrency(value) : formatNumber(value);
        });
    };

    const updateGrowthIndicators = (payload) => {
        const growthByKey = {
            revenue: payload?.revenue?.growth,
            vendor_earnings: payload?.vendor_earnings?.growth,
            subscriptions: payload?.subscriptions?.growth,
            users: payload?.users?.growth,
            active_vendors: payload?.active_vendors?.growth,
            bookings: payload?.bookings?.growth,
        };

        root.querySelectorAll('[data-growth-key]').forEach((el) => {
            const key = el.getAttribute('data-growth-key');
            const growth = growthByKey[key];
            el.textContent = formatGrowthText(growth);
            el.classList.remove('positive', 'negative', 'neutral');
            el.classList.add(growthClassName(growth));
        });

        root.querySelectorAll('[data-chart-growth]').forEach((el) => {
            const key = el.getAttribute('data-chart-growth');
            const growth = growthByKey[key];
            el.textContent = formatGrowthText(growth);
            el.classList.remove('positive', 'negative', 'neutral');
            el.classList.add(growthClassName(growth));
        });
    };

    const applyAnalyticsPayload = (payload) => {
        updateSummaryCards(payload.summary || {});
        updateGrowthIndicators(payload);
        upsertRevenueChart(payload.months || [], payload.revenue?.values || []);
        upsertBookingsChart(payload.months || [], payload.bookings?.values || []);
        upsertVendorsChart(payload.top_vendors || []);
        upsertCategoryChart(payload.categories || {});
    };

    const fetchAnalytics = async (year) => {
        const targetYear = Number(year);
        if (!Number.isFinite(targetYear)) {
            return;
        }
        setStatus(`Loading ${targetYear} analytics...`);

        try {
            const response = await fetch(`${analyticsUrl}?year=${targetYear}`, {
                headers: {
                    Accept: 'application/json',
                },
            });
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const payload = await response.json();
            applyAnalyticsPayload(payload);
            setStatus(`Showing analytics for ${payload.year}`);
        } catch (_error) {
            setStatus('Failed to load analytics data.');
        }
    };

    yearSelect.addEventListener('change', () => {
        fetchAnalytics(yearSelect.value);
    });

    fetchAnalytics(yearSelect.value);
})();
