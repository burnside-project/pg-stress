// PG Stress Test Dashboard - Vanilla JS + Chart.js

const REFRESH_MS = 10_000;
let timeRangeSec = 600; // default 10 minutes
let prevTableRows = {}; // track row counts for delta highlighting

// ─── Chart setup ───────────────────────────────────────────────────────

const chartDefaults = {
    responsive: true,
    maintainAspectRatio: true,
    animation: false,
    plugins: { legend: { labels: { color: '#64748b', font: { size: 11 } } } },
    scales: {
        x: {
            type: 'time',
            time: { tooltipFormat: 'HH:mm:ss' },
            ticks: { color: '#94a3b8', font: { size: 10 }, maxTicksLimit: 8 },
            grid: { color: '#f1f5f9' },
        },
        y: {
            ticks: { color: '#94a3b8', font: { size: 10 } },
            grid: { color: '#f1f5f9' },
            beginAtZero: true,
        },
    },
};

function makeChart(id, datasets) {
    return new Chart(document.getElementById(id), {
        type: 'line',
        data: { datasets },
        options: structuredClone(chartDefaults),
    });
}

const txnChart = makeChart('chart-txn', [
    { label: 'txn/s', borderColor: '#6366f1', backgroundColor: 'rgba(99,102,241,0.1)', data: [], fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
]);

const opsChart = makeChart('chart-ops', [
    { label: 'insert/s', borderColor: '#22c55e', data: [], tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
    { label: 'update/s', borderColor: '#3b82f6', data: [], tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
    { label: 'delete/s', borderColor: '#ef4444', data: [], tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
]);

const connsChart = makeChart('chart-conns', [
    { label: 'active', borderColor: '#22c55e', backgroundColor: 'rgba(34,197,94,0.1)', data: [], fill: true, tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
    { label: 'idle', borderColor: '#6366f1', data: [], tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
    { label: 'idle-in-txn', borderColor: '#eab308', data: [], tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
]);

const cacheChart = makeChart('chart-cache', [
    { label: 'hit ratio', borderColor: '#06b6d4', backgroundColor: 'rgba(6,182,212,0.1)', data: [], fill: true, tension: 0.3, pointRadius: 0, borderWidth: 2 },
]);
// Override y scale for cache ratio.
cacheChart.options.scales.y.min = 0;
cacheChart.options.scales.y.max = 1;

const tablesChart = makeChart('chart-tables', [
    { label: 'search_log', borderColor: '#ef4444', data: [], tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
    { label: 'audit_log', borderColor: '#f97316', data: [], tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
    { label: 'price_history', borderColor: '#eab308', data: [], tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
    { label: 'cart_items', borderColor: '#22c55e', data: [], tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
    { label: 'reviews', borderColor: '#6366f1', data: [], tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
]);

const locksChart = makeChart('chart-locks', [
    { label: 'locks', borderColor: '#ef4444', data: [], tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
    { label: 'waiting', borderColor: '#eab308', data: [], tension: 0.3, pointRadius: 0, borderWidth: 1.5 },
]);

// ─── Time filter buttons ─────────────────────────────────────────────

document.querySelectorAll('.time-filter button').forEach(btn => {
    btn.addEventListener('click', () => {
        document.querySelectorAll('.time-filter button').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        timeRangeSec = parseInt(btn.dataset.range);
        refresh();
    });
});

// ─── Helpers ─────────────────────────────────────────────────────────

function fmt(n) {
    if (n === null || n === undefined || n === '-') return '-';
    if (n >= 1_000_000_000) return (n / 1_000_000_000).toFixed(1) + 'G';
    if (n >= 1_000_000) return (n / 1_000_000).toFixed(1) + 'M';
    if (n >= 1_000) return (n / 1_000).toFixed(1) + 'K';
    return typeof n === 'number' ? (Number.isInteger(n) ? n.toString() : n.toFixed(1)) : n;
}

function fmtBytes(b) {
    if (b >= 1_073_741_824) return (b / 1_073_741_824).toFixed(1) + ' GB';
    if (b >= 1_048_576) return (b / 1_048_576).toFixed(0) + ' MB';
    if (b >= 1_024) return (b / 1_024).toFixed(0) + ' KB';
    return b + ' B';
}

function fmtDuration(sec) {
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = Math.floor(sec % 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
}

function barColor(pct) {
    if (pct > 90) return 'var(--red)';
    if (pct > 70) return 'var(--yellow)';
    return 'var(--green)';
}

// ─── Data fetching ───────────────────────────────────────────────────

async function refresh() {
    try {
        const [statusRes, metricsRes, tablesRes] = await Promise.all([
            fetch('/api/status'),
            fetchMetrics(),
            fetch('/api/tables'),
        ]);

        const status = await statusRes.json();
        const metrics = await metricsRes.json();
        const tables = await tablesRes.json();

        updateHeader(status);
        updateCards(status);
        updateCharts(metrics.samples);
        updateTablesPanel(tables);
        updateLoadgenPanel(status.loadgen);
    } catch (e) {
        console.error('refresh error:', e);
    }
}

async function fetchMetrics() {
    let url = '/api/metrics';
    if (timeRangeSec > 0) {
        const from = new Date(Date.now() - timeRangeSec * 1000).toISOString();
        url += `?from=${from}`;
    }
    return fetch(url);
}

// ─── UI updates ──────────────────────────────────────────────────────

function updateHeader(status) {
    document.getElementById('scenario-name').textContent = status.scenario;
    document.getElementById('elapsed').textContent = fmtDuration(status.elapsed_seconds);
    document.getElementById('samples-count').textContent = `${status.samples_collected} samples`;
}

function updateCards(status) {
    const s = status.latest_sample;
    if (!s) return;

    document.getElementById('card-conns').textContent = s.total_connections;
    document.getElementById('card-conns-sub').textContent = `active: ${s.active_connections} | idle: ${s.idle_connections} | idle-txn: ${s.idle_in_transaction}`;

    document.getElementById('card-txn').textContent = fmt(s.txn_per_sec);
    const totalOps = s.tup_inserted_per_sec + s.tup_updated_per_sec + s.tup_deleted_per_sec;
    document.getElementById('card-ops').textContent = fmt(totalOps);
    document.getElementById('card-ops-sub').textContent = `ins: ${fmt(s.tup_inserted_per_sec)} | upd: ${fmt(s.tup_updated_per_sec)} | del: ${fmt(s.tup_deleted_per_sec)}`;

    document.getElementById('card-cache').textContent = (s.cache_hit_ratio * 100).toFixed(2) + '%';
    document.getElementById('card-cache-sub').textContent = `read: ${fmt(s.blks_read_per_sec)}/s | hit: ${fmt(s.blks_hit_per_sec)}/s`;

    document.getElementById('card-dbsize').textContent = fmtBytes(s.database_size_bytes);

    document.getElementById('card-locks').textContent = s.lock_count;
    document.getElementById('card-locks-sub').textContent = `waiting: ${s.lock_waiting}`;

    document.getElementById('card-deadlocks').textContent = s.deadlocks;
    document.getElementById('card-temp').textContent = s.temp_files;
}

function updateCharts(samples) {
    if (!samples || samples.length === 0) return;

    // Map to chart data.
    const ts = samples.map(s => new Date(s.timestamp));

    function setData(chart, idx, values) {
        chart.data.datasets[idx].data = values.map((v, i) => ({ x: ts[i], y: v }));
    }

    setData(txnChart, 0, samples.map(s => s.txn_per_sec));
    txnChart.update();

    setData(opsChart, 0, samples.map(s => s.tup_inserted_per_sec));
    setData(opsChart, 1, samples.map(s => s.tup_updated_per_sec));
    setData(opsChart, 2, samples.map(s => s.tup_deleted_per_sec));
    opsChart.update();

    setData(connsChart, 0, samples.map(s => s.active_connections));
    setData(connsChart, 1, samples.map(s => s.idle_connections));
    setData(connsChart, 2, samples.map(s => s.idle_in_transaction));
    connsChart.update();

    setData(cacheChart, 0, samples.map(s => s.cache_hit_ratio));
    cacheChart.update();

    const monitoredTables = ['search_log', 'audit_log', 'price_history', 'cart_items', 'reviews'];
    monitoredTables.forEach((table, idx) => {
        tablesChart.data.datasets[idx].data = samples.map((s, i) => ({
            x: ts[i],
            y: s.table_rows?.[table] || 0,
        }));
    });
    tablesChart.update();

    setData(locksChart, 0, samples.map(s => s.lock_count));
    setData(locksChart, 1, samples.map(s => s.lock_waiting));
    locksChart.update();
}

function updateTablesPanel(data) {
    const tbody = document.querySelector('#tables-table tbody');
    tbody.innerHTML = '';

    for (const t of data.tables) {
        const tr = document.createElement('tr');
        const prev = prevTableRows[t.name];
        const delta = (prev != null && t.rows !== prev) ? t.rows - prev : 0;
        const growing = delta > 0;
        const shrinking = delta < 0;

        let barHtml = '-';
        if (t.pct_of_limit !== null) {
            const pct = Math.min(t.pct_of_limit, 100);
            barHtml = `<span class="bar-bg"><span class="bar-fill" style="width:${pct}%;background:${barColor(t.pct_of_limit)}"></span></span> ${t.pct_of_limit.toFixed(1)}%`;
        }

        let deltaHtml = '';
        if (growing) {
            deltaHtml = `<span style="color:#16a34a;font-size:10px;font-weight:600">+${fmt(delta)}</span>`;
        } else if (shrinking) {
            deltaHtml = `<span style="color:#dc2626;font-size:10px;font-weight:600">${fmt(delta)}</span>`;
        }

        if (growing || shrinking) {
            tr.style.transition = 'background 0.5s';
            tr.style.background = growing ? '#f0fdf4' : '#fef2f2';
            setTimeout(() => { tr.style.background = ''; }, 2000);
        }

        tr.innerHTML = `
            <td>${t.name}</td>
            <td class="num">${fmt(t.rows)} ${deltaHtml}</td>
            <td class="num" style="color:${t.dead_tuples > 10000 ? '#dc2626' : '#94a3b8'}">${fmt(t.dead_tuples)}</td>
            <td class="num">${fmtBytes(t.size_bytes)}</td>
            <td>${barHtml}</td>
            <td class="num">${t.limit ? fmt(t.limit) : '-'}</td>
        `;
        tbody.appendChild(tr);
        prevTableRows[t.name] = t.rows;
    }

    // Safety events.
    const eventsDiv = document.getElementById('safety-events');
    if (data.safety_events.length > 0) {
        eventsDiv.innerHTML = '<h4 style="font-size:0.8rem;margin-bottom:0.5rem;color:var(--muted)">Recent Safety Events</h4>';
        data.safety_events.forEach(e => {
            const div = document.createElement('div');
            div.className = 'event';
            const time = new Date(e.timestamp).toLocaleTimeString();
            div.innerHTML = `${time} <span class="action">${e.action}</span> ${e.table}: ${e.detail}`;
            eventsDiv.appendChild(div);
        });
    } else {
        eventsDiv.innerHTML = '';
    }
}

function updateLoadgenPanel(loadgen) {
    const panel = document.getElementById('loadgen-panel');
    const heading = document.getElementById('loadgen-heading');
    if (!loadgen) {
        panel.style.display = 'none';
        if (heading) heading.style.display = 'none';
        return;
    }
    panel.style.display = 'block';
    if (heading) heading.style.display = 'flex';

    const cardsDiv = document.getElementById('loadgen-cards');
    const ops = loadgen.ops || {};
    cardsDiv.innerHTML = Object.entries(ops).map(([k, v]) =>
        `<div class="card"><div class="label">${k}</div><div class="value">${fmt(v)}</div></div>`
    ).join('') +
    `<div class="card"><div class="label">errors</div><div class="value">${fmt(loadgen.errors)}</div></div>` +
    `<div class="card"><div class="label">bursts</div><div class="value">${fmt(loadgen.bursts)}</div></div>` +
    `<div class="card"><div class="label">uptime</div><div class="value">${fmtDuration(loadgen.uptime_s)}</div></div>`;
}

// ─── Reset button ───────────────────────────────────────────────────

document.getElementById('reset-btn').addEventListener('click', async () => {
    if (!confirm('Clear all collected samples and start fresh?')) return;
    await fetch('/api/reset', { method: 'POST' });
    refresh();
});

// ─── Cross-portal link ──────────────────────────────────────────────

const cpLink = document.getElementById('link-control-panel');
if (cpLink) cpLink.href = `${location.protocol}//${location.hostname}:3100`;


// ─── Auto-refresh ────────────────────────────────────────────────────

refresh();
setInterval(refresh, REFRESH_MS);
