/**
 * Operations (運用操作) panel for the GCS Dashboard.
 *
 * - Fetches /api/ops (operation catalog) and renders setting/monitoring/logging/
 *   base-injection operations grouped by category.
 * - Connects to /ws/ops for 1 Hz job-status updates.
 * - Dangerous operations show a confirmation modal before POST /api/ops/{id}/start.
 *
 * 制御系（アーム/離陸/Guided/RTL 等）は既存のカード操作・broadcast パネルが担当。
 */

var opsState = { active: 0, total: 0, jobs: [] };
var opsCatalog = [];

document.addEventListener('DOMContentLoaded', function () {
    initOpsCatalog();
    connectOpsWebSocket();
});

// ==========================================================================
// Catalog
// ==========================================================================
function initOpsCatalog() {
    fetch('/api/ops')
        .then(function (r) { return r.json(); })
        .then(function (data) {
            opsCatalog = data.operations || [];
            renderOpCatalog(opsCatalog);
        })
        .catch(function (err) {
            console.error('[OPS] catalog fetch failed:', err);
            var el = document.getElementById('ops-catalog');
            if (el) el.innerHTML = '<div class="op-desc">操作カタログを取得できません（バックエンド未起動?）。</div>';
        });
}

function renderOpCatalog(ops) {
    var container = document.getElementById('ops-catalog');
    if (!container) return;

    var categories = ['設定系', '監視系', 'ロギング系', '基地局・注入系'];
    var html = '';
    categories.forEach(function (cat) {
        var items = ops.filter(function (o) { return o.category === cat; });
        if (items.length === 0) return;
        html += '<div class="ops-category">' + escapeHtml(cat) + '</div>';
        items.forEach(function (op) {
            html += renderOpCard(op);
        });
    });
    container.innerHTML = html;
}

function renderOpCard(op) {
    var danger = op.dangerous ? ' dangerous' : '';
    var badge = op.dangerous ? ' <span class="op-badge-danger">確認必須</span>' : '';
    var html = '<div class="op-card' + danger + '" id="op-card-' + escapeHtml(op.id) + '">';
    html += '<div class="op-title"><span>' + escapeHtml(op.label) + '</span>' + badge + '</div>';
    if (op.description) html += '<div class="op-desc">' + escapeHtml(op.description) + '</div>';
    html += '<div class="op-params">';
    (op.params || []).forEach(function (p) {
        html += renderParamRow(op.id, p);
    });
    html += '</div>';
    html += '<div class="op-actions">';
    html += '<button class="op-btn' + (op.dangerous ? ' danger' : '') + '" onclick="startOperation(\'' + escapeHtml(op.id) + '\')">実行</button>';
    html += '</div>';
    html += '</div>';
    return html;
}

function renderParamRow(opId, p) {
    var id = 'op-' + opId + '-' + p.name;
    var label = escapeHtml(p.label || p.name);
    var help = p.help ? ' title="' + escapeHtml(p.help) + '"' : '';
    var def = (p.default !== null && p.default !== undefined) ? p.default : '';

    if (p.type === 'bool') {
        var checked = (def === true || def === 'true') ? ' checked' : '';
        return '<div class="op-param-row"><label' + help + '>' + label + '</label>' +
            '<input type="checkbox" id="' + id + '" data-param="' + escapeHtml(p.name) + '"' + checked + '></div>';
    }

    if (p.options && p.options.length) {
        var opts = '';
        p.options.forEach(function (opt) {
            var sel = (opt === def) ? ' selected' : '';
            opts += '<option value="' + escapeHtml(opt) + '"' + sel + '>' + escapeHtml(opt) + '</option>';
        });
        return '<div class="op-param-row"><label' + help + '>' + label + '</label>' +
            '<select id="' + id + '" data-param="' + escapeHtml(p.name) + '">' + opts + '</select></div>';
    }

    var inputType = (p.type === 'int' || p.type === 'float') ? 'number' : 'text';
    var step = (p.type === 'float') ? ' step="any"' : '';
    return '<div class="op-param-row"><label' + help + '>' + label + '</label>' +
        '<input type="' + inputType + '" id="' + id + '" data-param="' + escapeHtml(p.name) + '"' +
        ' value="' + escapeHtml(String(def)) + '" placeholder="' + escapeHtml(p.help || '') + '"' + step + '></div>';
}

function collectParams(opId) {
    var card = document.getElementById('op-card-' + opId);
    var params = {};
    if (!card) return params;
    card.querySelectorAll('[data-param]').forEach(function (el) {
        var name = el.getAttribute('data-param');
        if (el.type === 'checkbox') {
            params[name] = el.checked;
        } else if (el.value === '') {
            // empty = let backend default apply
        } else if (el.type === 'number') {
            params[name] = parseFloat(el.value);
        } else {
            params[name] = el.value;
        }
    });
    return params;
}

// ==========================================================================
// Start / Stop / Clear
// ==========================================================================
function startOperation(opId) {
    var op = null;
    opsCatalog.forEach(function (o) { if (o.id === opId) op = o; });
    if (!op) return;

    var params = collectParams(opId);

    function doStart() {
        fetch('/api/ops/' + encodeURIComponent(opId) + '/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ params: params })
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.job_id) {
                if (typeof showToast === 'function') showToast(op.label + ' を開始しました (' + data.job_id + ')', 'info');
            } else if (data.detail) {
                if (typeof showAlertModal === 'function') showAlertModal({ title: '開始失敗', message: data.detail, variant: 'warn' });
            }
        })
        .catch(function (err) {
            console.error('[OPS] start failed:', err);
            if (typeof showToast === 'function') showToast('開始エラー: ' + (err.message || err), 'error');
        });
    }

    if (op.dangerous) {
        if (typeof showConfirmModal !== 'function') { if (window.confirm(op.label + ' を実行しますか？')) doStart(); return; }
        showConfirmModal({
            title: op.label,
            message: '⚠️ 危険操作です。\n' + (op.description || '') + '\n\n本当に実行しますか？',
            confirmText: '実行する',
            variant: 'danger',
            onConfirm: doStart
        });
    } else {
        doStart();
    }
}

function stopJob(jobId) {
    fetch('/api/ops/jobs/' + encodeURIComponent(jobId) + '/stop', { method: 'POST' })
        .then(function (r) { return r.json(); })
        .then(function () {
            if (typeof showToast === 'function') showToast('停止要求を送信しました (' + jobId + ')', 'info');
        })
        .catch(function (err) { console.error('[OPS] stop failed:', err); });
}

function clearJob(jobId) {
    fetch('/api/ops/jobs/' + encodeURIComponent(jobId), { method: 'DELETE' })
        .then(function (r) { return r.json(); })
        .then(function () { renderJobs(opsState.jobs); })
        .catch(function (err) { console.error('[OPS] clear failed:', err); });
}

function showJobLog(jobId) {
    fetch('/api/ops/jobs/' + encodeURIComponent(jobId))
        .then(function (r) { return r.json(); })
        .then(function (job) {
            var box = document.getElementById('job-log-' + jobId);
            if (!box) return;
            var logs = (job.logs || []).map(function (l) { return '[' + l.t + '] ' + l.msg; });
            box.textContent = logs.join('\n') || '(ログなし)';
            box.style.display = 'block';
        })
        .catch(function (err) { console.error('[OPS] log fetch failed:', err); });
}

// ==========================================================================
// Job rendering
// ==========================================================================
function renderJobs(jobs) {
    var container = document.getElementById('ops-jobs');
    if (!container) return;

    if (!jobs || jobs.length === 0) {
        container.innerHTML = '<div class="op-desc">実行中のジョブはありません。</div>';
        return;
    }

    var html = '';
    jobs.forEach(function (j) {
        var pct = (j.progress !== null && j.progress !== undefined) ? Math.round(j.progress) : null;
        var barWidth = pct !== null ? pct + '%' : '100%';
        var barClass = (pct === null) ? 'job-progress-bar indeterminate' : 'job-progress-bar';
        var progressHtml = '';
        if (pct !== null || j.status === 'RUNNING') {
            progressHtml = '<div class="job-progress"><div class="' + barClass + '" style="width:' + barWidth + '"></div></div>';
        }

        var running = j.status === 'RUNNING';
        var terminal = (j.status === 'PASS' || j.status === 'FAIL' || j.status === 'STOPPED');

        html += '<div class="job-item">';
        html += '<div class="job-head">';
        html += '<span class="job-op">' + escapeHtml(opLabel(j.op_id)) + '</span>';
        html += '<span class="job-status ' + escapeHtml(j.status) + '">' + escapeHtml(j.status) + '</span>';
        html += '<span class="job-id">' + escapeHtml(j.id) + '</span>';
        html += '</div>';
        if (j.message) html += '<div class="job-message">' + escapeHtml(j.message) + '</div>';
        if (j.error) html += '<div class="job-error">' + escapeHtml(j.error) + '</div>';
        html += progressHtml;
        html += '<div class="job-actions">';
        if (running) html += '<button class="op-btn danger" onclick="stopJob(\'' + escapeHtml(j.id) + '\')">停止</button>';
        html += '<button class="op-btn" onclick="showJobLog(\'' + escapeHtml(j.id) + '\')">ログ</button>';
        if (terminal) html += '<button class="op-btn" onclick="clearJob(\'' + escapeHtml(j.id) + '\')">クリア</button>';
        html += '</div>';
        html += '<pre class="job-log" id="job-log-' + escapeHtml(j.id) + '" style="display:none;"></pre>';
        html += '</div>';
    });
    container.innerHTML = html;
}

function opLabel(opId) {
    var label = opId;
    opsCatalog.forEach(function (o) { if (o.id === opId) label = o.label; });
    return label;
}

// ==========================================================================
// WebSocket /ws/ops
// ==========================================================================
var opsWs = null;
var opsWsRetry = 0;

function connectOpsWebSocket() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var port = location.port || '8000';
    opsWs = new WebSocket(proto + '//' + location.hostname + ':' + port + '/ws/ops');

    opsWs.onopen = function () { opsWsRetry = 0; };
    opsWs.onmessage = function (event) {
        try {
            var payload = JSON.parse(event.data);
            if (payload.type === 'ops') {
                opsState = payload;
                renderJobs(payload.jobs || []);
            }
        } catch (e) {
            console.error('[OPS] parse error:', e);
        }
    };
    opsWs.onclose = function () {
        if (opsWsRetry < 10) {
            opsWsRetry++;
            setTimeout(connectOpsWebSocket, Math.min(5000 * Math.pow(2, opsWsRetry), 60000));
        }
    };
    opsWs.onerror = function () {};
}
