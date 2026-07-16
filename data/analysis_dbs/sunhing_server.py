"""
Sun Hing KPI Data Server — Dashboard + Data Editor

Usage:
  python3 data/analysis_dbs/sunhing_server.py

Serves:
  /                   → Dashboard (sunhing_dashboard.html)
  /editor             → Data editor panel
  /api/kpi-data       → GET: KPI data as JSON
  /api/kpi-update     → POST: update single KPI value
  /api/add-row        → POST: add a new period row
"""

import json, sqlite3, os, http.server, urllib.parse, pathlib

DB_PATH = pathlib.Path(__file__).parent / "sunhing_kpi.db"
DASHBOARD_PATH = pathlib.Path(__file__).parent / "sunhing_dashboard.html"
PORT = 8999

# ── DB helpers ──────────────────────────────────────────────────────────

def get_conn():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn

def fetch_kpi_data():
    conn = get_conn()
    rows = conn.execute("""
        SELECT f.id, f.period, d.kpi_id, d.kpi_name, d.roe_factor,
               f.actual, f.target, f.unit, d.kpi_type
        FROM fact_kpi_monthly f
        JOIN dim_kpi d ON f.kpi_id = d.kpi_id
        ORDER BY f.period, d.roe_factor, d.kpi_name
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def fetch_periods():
    conn = get_conn()
    rows = conn.execute("SELECT DISTINCT period FROM fact_kpi_monthly ORDER BY period").fetchall()
    conn.close()
    return [r["period"] for r in rows]

def fetch_employees(factory=None, month=None, department=None):
    conn = get_conn()
    sql = "SELECT * FROM raw_employee WHERE 1=1"
    params = []
    if factory:
        sql += " AND factory = ?"
        params.append(factory)
    if month:
        sql += " AND severance_month = ?"
        params.append(month)
    if department:
        sql += " AND department = ?"
        params.append(department)
    sql += " ORDER BY employee_code LIMIT 2000"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def fetch_employee_summary():
    conn = get_conn()
    summary = {}
    summary["total"] = conn.execute("SELECT COUNT(*) FROM raw_employee").fetchone()[0]
    summary["severed"] = conn.execute("SELECT COUNT(*) FROM raw_employee WHERE is_severed=1").fetchone()[0]
    summary["retained"] = conn.execute("SELECT COUNT(*) FROM raw_employee WHERE is_severed=0").fetchone()[0]
    summary["disputes"] = conn.execute("SELECT COUNT(*) FROM raw_employee WHERE has_dispute=1").fetchone()[0]
    summary["converted"] = conn.execute("SELECT COUNT(*) FROM raw_employee WHERE converted_to_partner=1").fetchone()[0]
    summary["avg_compensation"] = round(conn.execute("SELECT AVG(compensation_wan) FROM raw_employee WHERE is_severed=1").fetchone()[0], 2)
    summary["avg_tenure"] = round(conn.execute("SELECT AVG(tenure_years) FROM raw_employee").fetchone()[0], 1)
    # by factory
    summary["by_factory"] = {}
    for f in ["东莞", "河源"]:
        summary["by_factory"][f] = {
            "total": conn.execute("SELECT COUNT(*) FROM raw_employee WHERE factory=?", (f,)).fetchone()[0],
            "severed": conn.execute("SELECT COUNT(*) FROM raw_employee WHERE factory=? AND is_severed=1", (f,)).fetchone()[0],
        }
    # by month
    by_month = conn.execute("SELECT severance_month, COUNT(*) as cnt FROM raw_employee WHERE is_severed=1 GROUP BY severance_month ORDER BY severance_month").fetchall()
    summary["by_month"] = {r["severance_month"]: r["cnt"] for r in by_month}
    conn.close()
    return summary

def fetch_liability_summary():
    conn = get_conn()
    summary = {}
    summary["total_items"] = conn.execute("SELECT COUNT(*) FROM raw_liability").fetchone()[0]
    summary["total_amount"] = round(conn.execute("SELECT SUM(total_amount_wan) FROM raw_liability").fetchone()[0], 0)
    summary["resolved"] = round(conn.execute("SELECT SUM(resolved_wan) FROM raw_liability").fetchone()[0], 0)
    summary["remaining"] = round(conn.execute("SELECT SUM(remaining_wan) FROM raw_liability").fetchone()[0], 0)
    summary["resolution_rate"] = round(summary["resolved"] / summary["total_amount"] * 100, 1)
    # by category
    by_cat = conn.execute("""
        SELECT category, COUNT(*), ROUND(SUM(total_amount_wan),0), ROUND(SUM(resolved_wan),0), ROUND(SUM(remaining_wan),0)
        FROM raw_liability GROUP BY category ORDER BY category
    """).fetchall()
    summary["by_category"] = {r[0]: {"count": r[1], "total": r[2], "resolved": r[3], "remaining": r[4]} for r in by_cat}
    # by status
    by_status = conn.execute("""
        SELECT status, COUNT(*), ROUND(SUM(remaining_wan),0)
        FROM raw_liability GROUP BY status ORDER BY status
    """).fetchall()
    summary["by_status"] = {r[0]: {"count": r[1], "remaining": r[2]} for r in by_status}
    # high priority items
    summary["high_priority_remaining"] = round(conn.execute("SELECT SUM(remaining_wan) FROM raw_liability WHERE priority='高'").fetchone()[0], 0)
    conn.close()
    return summary

def fetch_liability_items(category=None, status=None):
    conn = get_conn()
    sql = "SELECT * FROM raw_liability WHERE 1=1"
    params = []
    if category:
        sql += " AND category = ?"
        params.append(category)
    if status:
        sql += " AND status = ?"
        params.append(status)
    sql += " ORDER BY priority DESC, remaining_wan DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def update_kpi_value(row_id: int, new_actual: float):
    conn = get_conn()
    conn.execute("UPDATE fact_kpi_monthly SET actual = ? WHERE id = ?", (new_actual, row_id))
    conn.commit()
    conn.close()

def add_period_row(period: str, kpi_id: str, actual: float, target: float, unit: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO fact_kpi_monthly (company_id, kpi_id, period, actual, target, unit) VALUES (1,?,?,?,?,?)",
        (kpi_id, period, actual, target, unit)
    )
    conn.commit()
    conn.close()

def fetch_entities(entity_type=None):
    conn = get_conn()
    sql = "SELECT * FROM raw_entity WHERE 1=1"
    params = []
    if entity_type:
        sql += " AND entity_type = ?"
        params.append(entity_type)
    sql += " ORDER BY registration_month, id"
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]

# ── HTML pages ──────────────────────────────────────────────────────────

EMPLOYEE_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Sun Hing — Employee List</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; padding: 20px; font-family: -apple-system, 'Noto Sans SC', sans-serif; background: #f0f2f5; }
  h1 { font-size: 18px; margin-bottom: 4px; }
  .subtitle { color: #666; font-size: 13px; margin-bottom: 16px; }
  .summary { display: flex; gap: 14px; margin-bottom: 16px; flex-wrap: wrap; }
  .summary-card { background: #fff; padding: 12px 18px; border-radius: 8px; border-left: 4px solid #1f77b4; box-shadow: 0 1px 3px rgba(0,0,0,.06); min-width: 120px; }
  .summary-card .label { font-size: 11px; color: #7f8c8d; }
  .summary-card .value { font-size: 20px; font-weight: 700; }
  .summary-card.warn { border-left-color: #e74c3c; }
  .summary-card.ok { border-left-color: #2ca02c; }
  .filters { display: flex; gap: 8px; align-items: center; margin-bottom: 12px; flex-wrap: wrap; }
  .filters select, .filters input { padding: 5px 10px; border: 1px solid #d0d5dd; border-radius: 4px; font-size: 13px; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.06); font-size: 12px; }
  th { background: #f8f9fa; padding: 8px 6px; text-align: left; border-bottom: 2px solid #e0e0e0; white-space: nowrap; font-weight: 600; }
  td { padding: 6px; border-bottom: 1px solid #f0f0f0; white-space: nowrap; }
  tr:hover td { background: #f8faff; }
  .badge { display: inline-block; padding: 1px 6px; border-radius: 8px; font-size: 11px; }
  .badge.severed { background: #fde8e8; color: #e74c3c; }
  .badge.retained { background: #e8f4f8; color: #1f77b4; }
  .badge.dispute { background: #fff3cd; color: #856404; }
  .badge.converted { background: #d4edda; color: #155724; }
  .badge.skill-primary { background: #e3f2fd; color: #1565c0; }
  .badge.skill-middle { background: #fff3e0; color: #e65100; }
  .badge.skill-senior { background: #f3e5f5; color: #7b1fa2; }
  .badge.skill-master { background: #fce4ec; color: #c62828; }
  .pagination { margin-top: 10px; font-size: 13px; color: #999; }
</style>
</head>
<body>

<h1>👥 Employee Detail — 协商减员</h1>
<div class="subtitle">856 employees (810 severed, 46 retained)</div>

<div class="summary" id="summaryBox"></div>

<div class="filters">
  <select id="filterFactory" onchange="loadEmployees()">
    <option value="">All Factories</option>
    <option value="东莞">东莞</option>
    <option value="河源">河源</option>
  </select>
  <select id="filterMonth" onchange="loadEmployees()">
    <option value="">All Months</option>
  </select>
  <select id="filterStatus" onchange="loadEmployees()">
    <option value="">All Status</option>
    <option value="severed">Severed</option>
    <option value="retained">Retained</option>
    <option value="dispute">Has Dispute</option>
    <option value="converted">Converted to Partner</option>
  </select>
  <span id="rowCount" style="font-size:12px;color:#999;margin-left:8px;"></span>
</div>

<div id="tableWrap"></div>

<script>
function loadSummary() {
  fetch('/api/employee-summary')
    .then(function(r) { return r.json(); })
    .then(function(s) {
      var html = ''
        + '<div class="summary-card"><div class="label">Total Employees</div><div class="value">' + s.total + '</div></div>'
        + '<div class="summary-card ok"><div class="label">Severed</div><div class="value">' + s.severed + '</div></div>'
        + '<div class="summary-card"><div class="label">Retained</div><div class="value">' + s.retained + '</div></div>'
        + '<div class="summary-card warn"><div class="label">Disputes</div><div class="value">' + s.disputes + '</div></div>'
        + '<div class="summary-card ok"><div class="label">Converted to Partner</div><div class="value">' + s.converted + '</div></div>'
        + '<div class="summary-card"><div class="label">Avg Compensation</div><div class="value">' + s.avg_compensation + '万</div></div>'
        + '<div class="summary-card"><div class="label">Avg Tenure</div><div class="value">' + s.avg_tenure + 'yr</div></div>';
      // by factory
      Object.keys(s.by_factory).forEach(function(f) {
        html += '<div class="summary-card"><div class="label">' + f + '</div><div class="value">' + s.by_factory[f].severed + '/' + s.by_factory[f].total + '</div></div>';
      });
      document.getElementById('summaryBox').innerHTML = html;

      // populate months filter
      var monthSel = document.getElementById('filterMonth');
      monthSel.innerHTML = '<option value="">All Months</option>';
      Object.keys(s.by_month).sort().forEach(function(m) {
        monthSel.innerHTML += '<option value="' + m + '">' + m + ' (' + s.by_month[m] + ')</option>';
      });
    });
}

function loadEmployees() {
  var factory = document.getElementById('filterFactory').value;
  var month = document.getElementById('filterMonth').value;
  var status = document.getElementById('filterStatus').value;
  var url = '/api/employees?factory=' + encodeURIComponent(factory) + '&month=' + encodeURIComponent(month);
  fetch(url)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var filtered = data;
      if (status === 'severed') filtered = data.filter(function(e) { return e.is_severed; });
      else if (status === 'retained') filtered = data.filter(function(e) { return !e.is_severed; });
      else if (status === 'dispute') filtered = data.filter(function(e) { return e.has_dispute; });
      else if (status === 'converted') filtered = data.filter(function(e) { return e.converted_to_partner; });

      var html = '<table><tr><th>Code</th><th>Name</th><th>Factory</th><th>Dept</th><th>Role</th><th>Skill</th><th>Tenure</th><th>Status</th><th>Severed</th><th>Month</th><th>Comp(万)</th><th>Dispute</th><th>Partner</th><th>Satisfaction</th></tr>';
      filtered.forEach(function(e) {
        var skillClass = '';
        if (e.skill_level === '初级工') skillClass = 'skill-primary';
        else if (e.skill_level === '中级工') skillClass = 'skill-middle';
        else if (e.skill_level === '高级工') skillClass = 'skill-senior';
        else if (e.skill_level === '技师' || e.skill_level === '高级技师') skillClass = 'skill-master';
        html += '<tr>'
          + '<td>' + e.employee_code + '</td>'
          + '<td><strong>' + e.name_cn + '</strong></td>'
          + '<td>' + e.factory + '</td>'
          + '<td>' + e.department + '</td>'
          + '<td>' + e.position_category + '</td>'
          + '<td><span class="badge ' + skillClass + '">' + e.skill_level + '</span></td>'
          + '<td><span class="badge ' + (e.is_severed ? 'severed' : 'retained') + '">' + (e.is_severed ? 'Severed' : 'Retained') + '</span></td>'
          + '<td>' + (e.is_severed ? '✅' : '❌') + '</td>'
          + '<td>' + (e.severance_month || '-') + '</td>'
          + '<td>' + (e.compensation_wan || '-') + '</td>'
          + '<td>' + (e.has_dispute ? '<span class="badge dispute">⚠️</span>' : '✅') + '</td>'
          + '<td>' + (e.converted_to_partner ? '<span class="badge converted">✅</span>' : '❌') + '</td>'
          + '<td>' + (e.satisfaction_score || '-') + '</td>'
          + '</tr>';
      });
      html += '</table>';
      document.getElementById('tableWrap').innerHTML = html;
      document.getElementById('rowCount').textContent = filtered.length + ' rows';
    });
}

loadSummary();
loadEmployees();
</script>
</body>
</html>"""

EDITOR_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Sun Hing KPI Data Editor</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; padding: 20px; font-family: -apple-system, 'Noto Sans SC', sans-serif; background: #f0f2f5; }
  h1 { font-size: 18px; margin-bottom: 4px; }
  .subtitle { color: #666; font-size: 13px; margin-bottom: 16px; }
  .toolbar { display: flex; gap: 10px; align-items: center; margin-bottom: 14px; flex-wrap: wrap; }
  .toolbar button, .toolbar select, .toolbar input { padding: 6px 12px; border-radius: 6px; border: 1px solid #d0d5dd; background: #fff; font-size: 13px; cursor: pointer; }
  .toolbar button { background: #1f77b4; color: #fff; border-color: #1f77b4; }
  .toolbar button:hover { background: #155a8a; }
  .toolbar .cancel { background: #e74c3c; border-color: #e74c3c; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; }
  .badge.roe { background: #e8f4f8; color: #1f77b4; }
  .badge.risk { background: #fde8e8; color: #e74c3c; }
  .badge.support { background: #f0f0f0; color: #666; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.06); font-size: 13px; }
  th { background: #f8f9fa; padding: 10px 8px; text-align: left; border-bottom: 2px solid #e0e0e0; white-space: nowrap; font-weight: 600; }
  td { padding: 8px; border-bottom: 1px solid #f0f0f0; }
  td input[type=number] { width: 70px; padding: 4px 6px; border: 1px solid #d0d5dd; border-radius: 4px; font-size: 13px; text-align: right; }
  td input[type=number].changed { background: #fff3cd; border-color: #ffc107; }
  tr:hover td { background: #f8faff; }
  .status-ok { color: #2ca02c; font-weight: 600; }
  .status-warn { color: #e74c3c; font-weight: 600; }
  .actions button { padding: 3px 8px; border-radius: 4px; border: 1px solid #d0d5dd; background: #fff; cursor: pointer; font-size: 12px; }
  .actions button.save { background: #2ca02c; color: #fff; border-color: #2ca02c; }
  .toast { position: fixed; bottom: 20px; right: 20px; background: #2ca02c; color: #fff; padding: 10px 18px; border-radius: 8px; font-size: 13px; opacity: 0; transition: opacity .3s; }
  .toast.show { opacity: 1; }
  .toast.error { background: #e74c3c; }
  .add-row-section { background: #fff; padding: 14px; border-radius: 8px; margin-top: 16px; border: 1px dashed #d0d5dd; }
  .add-row-section h3 { margin: 0 0 10px; font-size: 14px; }
  .add-row-section .row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .add-row-section select, .add-row-section input { padding: 5px 10px; border: 1px solid #d0d5dd; border-radius: 4px; font-size: 13px; }
  .filter-bar { display: flex; gap: 8px; align-items: center; margin-bottom: 10px; }
  .filter-bar select { padding: 4px 8px; border: 1px solid #d0d5dd; border-radius: 4px; font-size: 12px; }
</style>
</head>
<body>

<h1>✏️ KPI Data Editor</h1>
<div class="subtitle">Sun Hing Vision Group — 集团组织变革 KPI v2.0</div>

<div class="toolbar">
  <button onclick="saveAll()">💾 Save All Changes</button>
  <button onclick="refreshData()">🔄 Refresh</button>
  <button onclick="openDashboard()">📊 View Dashboard</button>
  <button onclick="openEmployees()">👥 Employees</button>
  <span id="saveStatus" style="font-size:12px;color:#999;"></span>
</div>

<div class="filter-bar">
  <label style="font-size:12px;">Filter factor:</label>
  <select id="factorFilter" onchange="filterTable()">
    <option value="all">All</option>
    <option value="净利润率">净利润率</option>
    <option value="资产周转率">资产周转率</option>
    <option value="权益乘数">权益乘数</option>
    <option value="支撑层">支撑层</option>
    <option value="风险监控">风险监控</option>
  </select>
  <label style="font-size:12px;">Period:</label>
  <select id="periodFilter" onchange="filterTable()">
    <option value="all">All</option>
  </select>
</div>

<div id="tableContainer"></div>

<div class="add-row-section">
  <h3>➕ Add New Period Data</h3>
  <div class="row">
    <select id="newPeriod"></select>
    <select id="newKpi" style="width:200px;">
      <option value="01_协商减员完成率">01_协商减员完成率</option>
      <option value="02_历史人力成本追缴化解率">02_历史人力成本追缴化解率</option>
      <option value="03_赔偿金额预算控制率">03_赔偿金额预算控制率</option>
    </select>
    <input type="number" id="newActual" placeholder="actual" step="0.1">
    <button onclick="addRow()">Add</button>
  </div>
</div>

<div id="toast" class="toast"></div>

<script>
var allData = [];
var changes = {};

function refreshData() {
  fetch('/api/kpi-data')
    .then(function(r) { return r.json(); })
    .then(function(data) {
      allData = data;
      populateFilters();
      filterTable();
    });
}

function populateFilters() {
  var periodSet = {};
  allData.forEach(function(r) { periodSet[r.period] = true; });
  var periods = Object.keys(periodSet).sort();
  var sel = document.getElementById('periodFilter');
  sel.innerHTML = '<option value="all">All</option>';
  periods.forEach(function(p) {
    sel.innerHTML += '<option value="' + p + '">' + p + '</option>';
  });
  // also populate add-row period selector
  var addSel = document.getElementById('newPeriod');
  addSel.innerHTML = '';
  var nextMonth = new Date(periods[periods.length - 1] + '-01');
  nextMonth.setMonth(nextMonth.getMonth() + 1);
  var ym = nextMonth.toISOString().slice(0, 7);
  for (var i = 0; i < 6; i++) {
    var d = new Date(ym + '-01');
    d.setMonth(d.getMonth() + i);
    var val = d.toISOString().slice(0, 7);
    addSel.innerHTML += '<option value="' + val + '">' + val + '</option>';
  }
}

function filterTable() {
  var factor = document.getElementById('factorFilter').value;
  var period = document.getElementById('periodFilter').value;
  var filtered = allData.filter(function(r) {
    if (factor !== 'all' && r.roe_factor !== factor) return false;
    if (period !== 'all' && r.period !== period) return false;
    return true;
  });
  renderTable(filtered);
}

function renderTable(data) {
  var html = '<table><tr><th>Period</th><th>KPI</th><th>Factor</th><th>Type</th><th>Target</th><th>Actual</th><th>Status</th><th>Actions</th></tr>';
  data.forEach(function(r) {
    var isChanged = changes[r.id] !== undefined;
    var val = isChanged ? changes[r.id] : r.actual;
    var status = '';
    var statusClass = '';
    if (r.kpi_type === '风险') {
      status = val <= r.target ? '🟢 OK' : '🔴 Alert';
      statusClass = val <= r.target ? 'status-ok' : 'status-warn';
    } else {
      status = val >= r.target ? '🟢 Met' : '🔴 Below';
      statusClass = val >= r.target ? 'status-ok' : 'status-warn';
    }
    var badgeClass = r.roe_factor === '风险监控' ? 'risk' : (r.roe_factor === '支撑层' ? 'support' : 'roe');
    html += '<tr>'
      + '<td>' + r.period + '</td>'
      + '<td>' + r.kpi_name + '</td>'
      + '<td><span class="badge ' + badgeClass + '">' + r.roe_factor + '</span></td>'
      + '<td><span class="badge ' + badgeClass + '">' + r.kpi_type + '</span></td>'
      + '<td>' + r.target + '</td>'
      + '<td><input type="number" step="0.01" value="' + val + '" class="' + (isChanged ? 'changed' : '') + '" onchange="trackChange(' + r.id + ', this.value)"></td>'
      + '<td class="' + statusClass + '">' + status + '</td>'
      + '<td class="actions"><button class="save" onclick="saveOne(' + r.id + ')">Save</button></td>'
      + '</tr>';
  });
  html += '</table><p style="font-size:12px;color:#999;">' + data.length + ' rows shown</p>';
  document.getElementById('tableContainer').innerHTML = html;
}

function trackChange(id, val) {
  var old = allData.find(function(r) { return r.id == id; });
  if (old && parseFloat(val) === parseFloat(old.actual)) {
    delete changes[id];
  } else {
    changes[id] = parseFloat(val);
  }
  filterTable();
}

function saveOne(id) {
  var val = changes[id] !== undefined ? changes[id] : null;
  if (val === null) return;
  fetch('/api/kpi-update', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({id: id, actual: val}) })
    .then(function(r) { return r.json(); })
    .then(function(resp) {
      if (resp.ok) {
        var row = allData.find(function(r) { return r.id == id; });
        if (row) row.actual = val;
        delete changes[id];
        showToast('Saved: ' + (row ? row.kpi_name : '') + ' = ' + val);
        filterTable();
      } else {
        showToast('Error: ' + resp.error, true);
      }
    });
}

function saveAll() {
  var ids = Object.keys(changes);
  if (ids.length === 0) { showToast('No changes to save'); return; }
  var promises = ids.map(function(id) {
    return fetch('/api/kpi-update', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({id: parseInt(id), actual: changes[id]}) })
      .then(function(r) { return r.json(); });
  });
  Promise.all(promises).then(function(results) {
    var ok = results.filter(function(r) { return r.ok; }).length;
    ids.forEach(function(id) {
      var row = allData.find(function(r) { return r.id == id; });
      if (row) row.actual = changes[id];
      delete changes[id];
    });
    showToast('Saved ' + ok + '/' + ids.length + ' changes');
    filterTable();
  });
}

function addRow() {
  var period = document.getElementById('newPeriod').value;
  var kpi_id = document.getElementById('newKpi').value;
  var actual = parseFloat(document.getElementById('newActual').value);
  if (!actual && actual !== 0) { showToast('Enter a value', true); return; }
  fetch('/api/add-row', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({period: period, kpi_id: kpi_id, actual: actual}) })
    .then(function(r) { return r.json(); })
    .then(function(resp) {
      if (resp.ok) {
        showToast('Row added: ' + period + ' ' + kpi_id + ' = ' + actual);
        document.getElementById('newActual').value = '';
        refreshData();
      } else {
        showToast('Error: ' + resp.error, true);
      }
    });
}

function openDashboard() {
  window.open('/', '_blank');
}
function openEmployees() {
  window.open('/employees', '_blank');
}

function showToast(msg, isError) {
  var el = document.getElementById('toast');
  el.textContent = msg;
  el.className = 'toast show' + (isError ? ' error' : '');
  setTimeout(function() { el.className = 'toast'; }, 3000);
}

refreshData();
</script>
</body>
</html>"""

# ── HTTP Handler ────────────────────────────────────────────────────────

# ── Nav bar ────────────────────────────────────────────────────────────

LIABILITY_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>Sun Hing — 历史人力成本追缴化解</title>
<style>
  * { box-sizing: border-box; }
  body { margin: 0; padding: 20px; font-family: -apple-system, 'Noto Sans SC', sans-serif; background: #f0f2f5; }
  h1 { font-size: 18px; margin-bottom: 4px; }
  .subtitle { color: #666; font-size: 13px; margin-bottom: 16px; }
  .summary { display: flex; gap: 14px; margin-bottom: 16px; flex-wrap: wrap; }
  .summary-card { background: #fff; padding: 12px 18px; border-radius: 8px; border-left: 4px solid #1f77b4; box-shadow: 0 1px 3px rgba(0,0,0,.06); min-width: 120px; }
  .summary-card .label { font-size: 11px; color: #7f8c8d; }
  .summary-card .value { font-size: 20px; font-weight: 700; }
  .summary-card.warn { border-left-color: #e74c3c; }
  .summary-card.ok { border-left-color: #2ca02c; }
  .filters { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
  .filters select { padding: 5px 10px; border: 1px solid #d0d5dd; border-radius: 4px; font-size: 13px; }
  table { width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.06); font-size: 13px; }
  th { background: #f8f9fa; padding: 8px 6px; text-align: left; border-bottom: 2px solid #e0e0e0; white-space: nowrap; font-weight: 600; }
  td { padding: 6px; border-bottom: 1px solid #f0f0f0; }
  tr:hover td { background: #f8faff; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 8px; font-size: 11px; }
  .badge.resolved { background: #d4edda; color: #155724; }
  .badge.partial { background: #fff3cd; color: #856404; }
  .badge.pending { background: #fde8e8; color: #e74c3c; }
  .bar { height: 20px; border-radius: 4px; background: #eee; position: relative; overflow: hidden; }
  .bar-fill { height: 100%; background: #2ca02c; border-radius: 4px; transition: width .5s; }
  .bar-fill.warn { background: #ff7f0e; }
  .bar-fill.danger { background: #e74c3c; }
  .kpi-big { text-align: center; padding: 24px; background: #fff; border-radius: 10px; box-shadow: 0 1px 3px rgba(0,0,0,.06); margin-bottom: 16px; }
  .kpi-big .num { font-size: 42px; font-weight: 700; }
  .kpi-big .label { color: #666; font-size: 13px; margin-top: 4px; }
</style>
</head>
<body>

<h1>💰 KPI #02 — 历史人力成本追缴化解率</h1>
<div class="subtitle">Total historical liability: 6,864万HKD | Target: ≥80% resolution in 12 months</div>

<div id="kpiBig" class="kpi-big">
  <div class="num" id="kpiRate">--</div>
  <div class="label">Resolution Rate</div>
  <div class="bar" style="width:80%;margin:12px auto;">
    <div id="kpiBar" class="bar-fill" style="width:0%"></div>
  </div>
</div>

<div class="summary" id="summaryBox"></div>

<div class="filters">
  <select id="filterCategory" onchange="loadItems()">
    <option value="">All Categories</option>
  </select>
  <select id="filterStatus" onchange="loadItems()">
    <option value="">All Status</option>
    <option value="已化解">已化解 (Resolved)</option>
    <option value="部分化解">部分化解 (Partial)</option>
    <option value="未启动">未启动 (Not Started)</option>
  </select>
  <span id="rowCount" style="font-size:12px;color:#999;"></span>
</div>

<div id="tableWrap"></div>

<script>
function loadSummary() {
  fetch('/api/liability-summary')
    .then(function(r) { return r.json(); })
    .then(function(s) {
      var rateEl = document.getElementById('kpiRate');
      var barEl = document.getElementById('kpiBar');
      rateEl.textContent = s.resolution_rate + '%';
      barEl.style.width = s.resolution_rate + '%';
      barEl.className = 'bar-fill' + (s.resolution_rate >= 80 ? '' : (s.resolution_rate >= 50 ? ' warn' : ' danger'));

      var html = ''
        + '<div class="summary-card"><div class="label">Total Items</div><div class="value">' + s.total_items + '</div></div>'
        + '<div class="summary-card"><div class="label">Total Amount</div><div class="value">' + s.total_amount + '万</div></div>'
        + '<div class="summary-card ok"><div class="label">Resolved</div><div class="value">' + s.resolved + '万</div></div>'
        + '<div class="summary-card warn"><div class="label">Remaining</div><div class="value">' + s.remaining + '万</div></div>'
        + '<div class="summary-card"><div class="label">High Priority</div><div class="value">' + s.high_priority_remaining + '万</div></div>';
      document.getElementById('summaryBox').innerHTML = html;

      // populate category filter
      var catSel = document.getElementById('filterCategory');
      catSel.innerHTML = '<option value="">All Categories</option>';
      Object.keys(s.by_category).forEach(function(c) {
        catSel.innerHTML += '<option value="' + c + '">' + c + ' (' + s.by_category[c].remaining + '万)</option>';
      });
    });
}

function loadItems() {
  var category = document.getElementById('filterCategory').value;
  var status = document.getElementById('filterStatus').value;
  var url = '/api/liability-data?category=' + encodeURIComponent(category) + '&status=' + encodeURIComponent(status);
  fetch(url)
    .then(function(r) { return r.json(); })
    .then(function(data) {
      var html = '<table><tr><th>Code</th><th>Category</th><th>Description</th><th>Authority</th><th>Total(万)</th><th>Resolved(万)</th><th>Remaining(万)</th><th>Progress</th><th>Status</th><th>Method</th><th>Priority</th></tr>';
      data.forEach(function(d) {
        var pct = d.total_amount_wan > 0 ? Math.round(d.resolved_wan / d.total_amount_wan * 100) : 0;
        var statusClass = d.status === '已化解' ? 'resolved' : (d.status === '未启动' ? 'pending' : 'partial');
        var barClass = pct >= 90 ? '' : (pct >= 50 ? 'warn' : 'danger');
        html += '<tr>'
          + '<td>' + d.item_code + '</td>'
          + '<td>' + d.category + '</td>'
          + '<td>' + d.description + '</td>'
          + '<td>' + d.authority + '</td>'
          + '<td>' + d.total_amount_wan + '</td>'
          + '<td>' + d.resolved_wan + '</td>'
          + '<td><strong>' + d.remaining_wan + '</strong></td>'
          + '<td style="width:120px;"><div class="bar"><div class="bar-fill ' + barClass + '" style="width:' + pct + '%"></div></div><span style="font-size:11px;color:#999;">' + pct + '%</span></td>'
          + '<td><span class="badge ' + statusClass + '">' + d.status + '</span></td>'
          + '<td style="font-size:11px;">' + (d.resolution_method || '-') + '</td>'
          + '<td>' + d.priority + '</td>'
          + '</tr>';
      });
      html += '</table>';
      document.getElementById('tableWrap').innerHTML = html;
      document.getElementById('rowCount').textContent = data.length + ' items';
    });
}

loadSummary();
loadItems();
</script>
</body>
</html>"""

NAV_BAR = """<div style="background:#1a1a2e;padding:10px 20px;display:flex;align-items:center;gap:12px;flex-wrap:wrap;position:sticky;top:0;z-index:1000;">
  <span style="color:#fff;font-weight:600;font-size:14px;">Sun Hing KPI</span>
  <a href="/" style="color:#fff;text-decoration:none;padding:4px 10px;border-radius:4px;font-size:12px;{ACTIVE_DASH}">Dashboard</a>
  <span style="color:#555;font-size:11px;">|</span>
  <span style="color:#888;font-size:11px;">Factors:</span>
  <a href="/profit" style="color:#fff;text-decoration:none;padding:4px 10px;border-radius:4px;font-size:12px;{ACTIVE_PROFIT}">📈 Profit</a>
  <a href="/turnover" style="color:#fff;text-decoration:none;padding:4px 10px;border-radius:4px;font-size:12px;{ACTIVE_TURN}">🔄 Turnover</a>
  <a href="/leverage" style="color:#fff;text-decoration:none;padding:4px 10px;border-radius:4px;font-size:12px;{ACTIVE_LEV}">🏗️ Leverage</a>
  <a href="/support" style="color:#fff;text-decoration:none;padding:4px 10px;border-radius:4px;font-size:12px;{ACTIVE_SUPP}">🛡️ Support</a>
  <a href="/risk" style="color:#fff;text-decoration:none;padding:4px 10px;border-radius:4px;font-size:12px;{ACTIVE_RISK}">⚠️ Risk</a>
   <span style="color:#555;font-size:11px;">|</span>
   <a href="/editor" style="color:#fff;text-decoration:none;padding:4px 10px;border-radius:4px;font-size:12px;{ACTIVE_EDIT}">Editor</a>
   <a href="/employees" style="color:#fff;text-decoration:none;padding:4px 10px;border-radius:4px;font-size:12px;{ACTIVE_EMP}">Employees</a>
   <a href="/liability" style="color:#fff;text-decoration:none;padding:4px 10px;border-radius:4px;font-size:12px;{ACTIVE_LIAB}">Liability</a>
   <a href="/gantt" style="color:#fff;text-decoration:none;padding:4px 10px;border-radius:4px;font-size:12px;{ACTIVE_GANTT}">📅 Gantt</a>
   <a href="/erd" style="color:#fff;text-decoration:none;padding:4px 10px;border-radius:4px;font-size:12px;{ACTIVE_ERD}">🗄️ ERD</a>
  <span style="flex:1"></span>
  <span style="color:#888;font-size:10px;">Sun Hing Vision Group</span>
</div>"""

def inject_nav(html, active="dash"):
    active_styles = {
        "dash": "background:rgba(255,255,255,.15);font-weight:700",
        "kpi2": "background:rgba(255,255,255,.15);font-weight:700",
        "kpi3": "background:rgba(255,255,255,.15);font-weight:700",
        "profit": "background:rgba(255,255,255,.15);font-weight:700",
        "turn": "background:rgba(255,255,255,.15);font-weight:700",
        "lev": "background:rgba(255,255,255,.15);font-weight:700",
        "supp": "background:rgba(255,255,255,.15);font-weight:700",
        "risk": "background:rgba(255,255,255,.15);font-weight:700",
        "erd": "background:rgba(255,255,255,.15);font-weight:700",
        "gantt": "background:rgba(255,255,255,.15);font-weight:700",
        "edit": "background:rgba(255,255,255,.15);font-weight:700",
        "emp": "background:rgba(255,255,255,.15);font-weight:700",
        "liab": "background:rgba(255,255,255,.15);font-weight:700",
    }
    nav = NAV_BAR.replace("{ACTIVE_DASH}", active_styles.get("dash", "") if active == "dash" else "color:#999")
    nav = nav.replace("{ACTIVE_PROFIT}", active_styles.get("profit", "") if active == "profit" else "color:#999")
    nav = nav.replace("{ACTIVE_TURN}", active_styles.get("turn", "") if active == "turn" else "color:#999")
    nav = nav.replace("{ACTIVE_LEV}", active_styles.get("lev", "") if active == "lev" else "color:#999")
    nav = nav.replace("{ACTIVE_SUPP}", active_styles.get("supp", "") if active == "supp" else "color:#999")
    nav = nav.replace("{ACTIVE_RISK}", active_styles.get("risk", "") if active == "risk" else "color:#999")
    nav = nav.replace("{ACTIVE_ERD}", active_styles.get("erd", "") if active == "erd" else "color:#999")
    nav = nav.replace("{ACTIVE_GANTT}", active_styles.get("gantt", "") if active == "gantt" else "color:#999")
    nav = nav.replace("{ACTIVE_EDIT}", active_styles.get("edit", "") if active == "edit" else "color:#999")
    nav = nav.replace("{ACTIVE_EMP}", active_styles.get("emp", "") if active == "emp" else "color:#999")
    nav = nav.replace("{ACTIVE_LIAB}", active_styles.get("liab", "") if active == "liab" else "color:#999")
    # single replace: add body style + nav in one shot
    html = html.replace("<body>", f'<body style="padding-top:0;">{nav}')
    html = html.replace("body { margin: 0; padding: 24px;", "body { margin: 0; padding: 20px 24px 24px;")
    return html


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == "/":
            if DASHBOARD_PATH.exists():
                html = DASHBOARD_PATH.read_text(encoding="utf-8")
                html = inject_nav(html, "dash")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            else:
                self.send_error(404, "Dashboard not found")
            return

        KPI02_PATH = pathlib.Path(__file__).parent / "sunhing_dashboard_kpi02.html"
        if path == "/kpi02":
            if KPI02_PATH.exists():
                html = KPI02_PATH.read_text(encoding="utf-8")
                html = inject_nav(html, "kpi2")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            else:
                self.send_error(404, "KPI #02 Dashboard not found")
            return

        KPI03_PATH = pathlib.Path(__file__).parent / "sunhing_dashboard_kpi03.html"
        if path == "/kpi03":
            if KPI03_PATH.exists():
                html = KPI03_PATH.read_text(encoding="utf-8")
                html = inject_nav(html, "kpi3")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            else:
                self.send_error(404, "KPI #03 Dashboard not found")
            return

        # Factor-grouped KPI dashboards
        FACTOR_PAGES = {
            "profit": "sunhing_dashboard_profit.html",
            "turnover": "sunhing_dashboard_turnover.html",
            "leverage": "sunhing_dashboard_leverage.html",
            "support": "sunhing_dashboard_support.html",
            "risk": "sunhing_dashboard_risk.html",
            "erd": "sunhing_erd.html",
        }
        for route_key, filename in FACTOR_PAGES.items():
            if path == f"/{route_key}":
                fpath = pathlib.Path(__file__).parent / filename
                if fpath.exists():
                    html = fpath.read_text(encoding="utf-8")
                    html = inject_nav(html, route_key)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.end_headers()
                    self.wfile.write(html.encode("utf-8"))
                else:
                    self.send_error(404, f"{filename} not found")
                return

        if path == "/editor":
            html = inject_nav(EDITOR_HTML, "edit")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        if path == "/api/kpi-data":
            data = fetch_kpi_data()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
            return

        if path == "/api/employees":
            qs = urllib.parse.parse_qs(parsed.query)
            factory = qs.get("factory", [None])[0]
            month = qs.get("month", [None])[0]
            dept = qs.get("department", [None])[0]
            data = fetch_employees(factory, month, dept)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
            return

        if path == "/api/employee-summary":
            data = fetch_employee_summary()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
            return

        if path == "/api/liability-summary":
            data = fetch_liability_summary()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
            return

        if path == "/api/liability-data":
            qs = urllib.parse.parse_qs(parsed.query)
            category = qs.get("category", [None])[0]
            status = qs.get("status", [None])[0]
            data = fetch_liability_items(category, status)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
            return

        if path == "/api/sample-data":
            qs = urllib.parse.parse_qs(parsed.query)
            table = qs.get("table", [None])[0]
            # Allowed tables for sample data
            ALLOWED = {
                "company", "dim_kpi", "dim_pmo_phase", "fact_kpi_monthly", "fact_roe_summary",
                "raw_hr", "raw_employee", "raw_finance", "raw_production",
                "raw_legal", "raw_digital_platform", "raw_crm", "raw_entity",
                "raw_pmo", "raw_sentiment", "raw_liability",
            }
            if table not in ALLOWED:
                self.send_error(400, "Invalid table name")
                return
            conn = get_conn()
            try:
                # Get columns
                cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
                # Get up to 5 sample rows
                rows = conn.execute(f"SELECT * FROM {table} LIMIT 5").fetchall()
                data = {
                    "columns": cols,
                    "rows": [list(r) for r in rows],
                    "total_rows": conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0],
                }
            except Exception as e:
                self.send_error(500, str(e))
                return
            finally:
                conn.close()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
            return

        if path == "/employees":
            html = inject_nav(EMPLOYEE_HTML, "emp")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        if path == "/liability":
            html = inject_nav(LIABILITY_HTML, "liab")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return

        GANTT_PATH = pathlib.Path(__file__).parent / "sunhing_gantt.html"
        if path == "/gantt":
            if GANTT_PATH.exists():
                html = GANTT_PATH.read_text(encoding="utf-8")
                html = inject_nav(html, "gantt")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(html.encode("utf-8"))
            else:
                self.send_error(404, "Gantt chart not found")
            return

        if path == "/api/gantt-data":
            conn = get_conn()
            try:
                milestones = []
                for row in conn.execute("SELECT milestone_id, phase_id, milestone_description, planned_date, actual_date, status, completed_on_time FROM raw_pmo ORDER BY phase_id, milestone_id").fetchall():
                    milestones.append({
                        "milestone_id": row["milestone_id"],
                        "phase_id": row["phase_id"],
                        "milestone_description": row["milestone_description"],
                        "planned_date": row["planned_date"],
                        "actual_date": row["actual_date"],
                        "status": row["status"],
                        "completed_on_time": row["completed_on_time"],
                    })
                phases = []
                for row in conn.execute("SELECT phase_id, phase_name, phase_name_cn, start_month, end_month, phase_owner, milestone_count, budget_allocated_wan FROM dim_pmo_phase ORDER BY phase_id").fetchall():
                    phases.append({
                        "phase_id": row["phase_id"],
                        "phase_name": row["phase_name"],
                        "phase_name_cn": row["phase_name_cn"],
                        "start_month": row["start_month"],
                        "end_month": row["end_month"],
                        "phase_owner": row["phase_owner"],
                        "milestone_count": row["milestone_count"],
                        "budget_allocated_wan": row["budget_allocated_wan"],
                    })
                data = {"milestones": milestones, "phases": phases}
            except Exception as e:
                self.send_error(500, str(e))
                return
            finally:
                conn.close()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data, ensure_ascii=False).encode())
            return

        # fallback: try static files in current dir
        return super().do_GET()

    def do_POST(self):
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len else {}

        if self.path == "/api/kpi-update":
            row_id = body.get("id")
            actual = body.get("actual")
            try:
                update_kpi_value(int(row_id), float(actual))
                resp = {"ok": True}
            except Exception as e:
                resp = {"ok": False, "error": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode())
            return

        if self.path == "/api/add-row":
            period = body.get("period")
            kpi_id = body.get("kpi_id")
            actual = body.get("actual")
            try:
                # find target and unit from existing data
                conn = get_conn()
                row = conn.execute("SELECT target, unit FROM dim_kpi WHERE kpi_id = ?", (kpi_id,)).fetchone()
                conn.close()
                if row:
                    add_period_row(period, kpi_id, float(actual), row["target"], row["unit"])
                    resp = {"ok": True}
                else:
                    resp = {"ok": False, "error": f"KPI not found: {kpi_id}"}
            except Exception as e:
                resp = {"ok": False, "error": str(e)}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(resp).encode())
            return

        self.send_error(404)

    def log_message(self, format, *args):
        # cleaner logs
        print(f"  [{self.command}] {args[0]} {args[1]}" if len(args) >= 2 else f"  {format % args}")


if __name__ == "__main__":
    os.chdir(str(pathlib.Path(__file__).parent))
    print(f"🚀 Sun Hing KPI Server running at:")
    print(f"   Dashboard:   http://localhost:{PORT}/")
    print(f"   Profit:      http://localhost:{PORT}/profit")
    print(f"   Turnover:    http://localhost:{PORT}/turnover")
    print(f"   Leverage:    http://localhost:{PORT}/leverage")
    print(f"   Support:     http://localhost:{PORT}/support")
    print(f"   Risk:        http://localhost:{PORT}/risk")
    print(f"   KPI #02:     http://localhost:{PORT}/kpi02")
    print(f"   KPI #03:     http://localhost:{PORT}/kpi03")
    print(f"   Editor:      http://localhost:{PORT}/editor")
    print(f"   Employees:   http://localhost:{PORT}/employees")
    print(f"   Liability:   http://localhost:{PORT}/liability")
    print(f"   Gantt:       http://localhost:{PORT}/gantt")
    srv = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        srv.server_close()
