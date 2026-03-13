// ═══════════════════════════════════════════════
// UI Controls
// ═══════════════════════════════════════════════
App.initControls = function() {
  // Year selectors
  var ys = document.getElementById('sel-year-start');
  var ye = document.getElementById('sel-year-end');
  for (var y = 1854; y <= 2018; y++) {
    ys.add(new Option(y, y));
    ye.add(new Option(y, y));
  }
  ys.value = '1854';
  ye.value = '2018';

  // States
  var ss = document.getElementById('sel-state');
  for (var [st, ct] of Object.entries(App.stateMap)) {
    ss.add(new Option(st + ' (' + ct.toLocaleString() + ')', st));
  }

  // Tribes
  App.renderTribes();
  document.getElementById('tribe-search').addEventListener('input', App.renderTribes);
  document.getElementById('tribe-clear').addEventListener('click', function() {
    App.selectedTribes = [];
    App.renderTribes();
  });

  // Name search
  var nameInput = document.getElementById('name-search');
  var nameBtn = document.getElementById('name-search-btn');
  if (nameBtn && nameInput) {
    nameBtn.addEventListener('click', function() { App.searchByName(nameInput.value); });
    nameInput.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') App.searchByName(nameInput.value);
    });
  }

  // Reservation boundaries checkbox
  document.getElementById('chk-reservations').addEventListener('change', function() {
    if (this.checked) {
      App._reservationLayer.addTo(App.map);
    } else {
      App.map.removeLayer(App._reservationLayer);
    }
  });

  // Rankin 1907 map checkbox
  document.getElementById('chk-rankin').addEventListener('change', function() {
    if (this.checked) {
      App._rankinLayer.addTo(App.map);
    } else {
      App.map.removeLayer(App._rankinLayer);
    }
  });

  // Timeline checkbox
  document.getElementById('chk-timeline').addEventListener('change', function() {
    App.toggleTimeline(this.checked);
  });

  // Original classification mode checkbox
  document.getElementById('chk-original-class').addEventListener('change', function() {
    App.classifyMode = this.checked ? 'original' : 'final';
    if (App.timelineMode && App.timelineYear !== null) {
      App.setTimelineYear(App.timelineYear);
    } else {
      App.renderMap(false);
    }
  });

  // Timeline track interactions
  App.initTimelineTrack();

  // Tab switching
  document.querySelectorAll('.header-tab').forEach(function(tab) {
    tab.addEventListener('click', function() {
      document.querySelectorAll('.header-tab').forEach(function(t) { t.classList.remove('active'); });
      tab.classList.add('active');
      App.switchView(tab.getAttribute('data-view'));
    });
  });

  // Home / reset button
  document.getElementById('btn-home').addEventListener('click', function() {
    App.resetToDefault();
  });
};

App.renderTribes = function() {
  var search = document.getElementById('tribe-search').value.toLowerCase();
  var container = document.getElementById('tribe-list');
  container.innerHTML = '';

  var allEntries = Object.entries(App.tribeMap)
    .filter(function(entry) { return !search || entry[0].toLowerCase().includes(search); })
    .sort(function(a, b) { return b[1] - a[1]; });

  var totalTribes = Object.keys(App.tribeMap).length;
  var countLabel = document.getElementById('tribe-count');
  if (countLabel) {
    countLabel.textContent = search
      ? allEntries.length + ' of ' + totalTribes + ' tribes'
      : totalTribes + ' tribes';
  }

  allEntries.forEach(function(entry) {
    var name = entry[0], count = entry[1];
    var isSelected = App.selectedTribes.indexOf(name) !== -1;
    var div = document.createElement('div');
    div.className = 'tribe-opt' + (isSelected ? ' selected' : '');
    div.innerHTML = '<span>' + name + '</span><span class="ct">' + count.toLocaleString() + '</span>';
    div.onclick = function() {
      var idx = App.selectedTribes.indexOf(name);
      if (idx !== -1) {
        App.selectedTribes.splice(idx, 1);
      } else {
        App.selectedTribes.push(name);
      }
      App.renderTribes();
    };
    container.appendChild(div);
  });

  // Update clear button visibility
  var clearBtn = document.getElementById('tribe-clear');
  clearBtn.style.display = App.selectedTribes.length > 0 ? '' : 'none';
};

App.setTimePreset = function(start, end) {
  document.getElementById('sel-year-start').value = start;
  document.getElementById('sel-year-end').value = end;
};

// View switching (Density / Compare)
App.switchView = function(view) {
  var analysisPanel = document.getElementById('analysis-panel');
  var comparePanel = document.getElementById('compare-panel');
  if (view === 'compare') {
    analysisPanel.style.display = 'none';
    comparePanel.style.display = '';
    App.renderCompare();
  } else {
    analysisPanel.style.display = '';
    comparePanel.style.display = 'none';
  }
};

// Reset all filters and return to default view
App.resetToDefault = function() {
  // Clear URL parameters
  window.history.replaceState({}, '', window.location.pathname);

  // Reset filters
  App.selectedTribes = [];
  document.getElementById('sel-category').value = 'all';
  document.getElementById('sel-year-start').value = '1854';
  document.getElementById('sel-year-end').value = '2018';
  document.getElementById('sel-state').value = '';
  document.getElementById('name-search').value = '';
  document.getElementById('name-results').innerHTML = '';
  document.getElementById('tribe-search').value = '';

  // Reset map display checkboxes
  document.getElementById('chk-heatmap').checked = true;
  document.getElementById('chk-points').checked = true;
  document.getElementById('chk-forced-highlight').checked = true;
  document.getElementById('chk-reservations').checked = false;
  document.getElementById('chk-rankin').checked = false;
  document.getElementById('chk-timeline').checked = false;
  document.getElementById('chk-original-class').checked = false;

  // Remove overlay layers
  if (App._reservationLayer && App.map.hasLayer(App._reservationLayer)) {
    App.map.removeLayer(App._reservationLayer);
  }
  if (App._rankinLayer && App.map.hasLayer(App._rankinLayer)) {
    App.map.removeLayer(App._rankinLayer);
  }

  // Turn off timeline
  if (App.timelineMode) {
    App.toggleTimeline(false);
  }

  // Clear map data
  App.currentData = [];
  App.pointLayer.clearLayers();
  App.parcelLayer.clearLayers();
  App.heatLayer.setLatLngs([]);
  App.map.setView([43, -104], 5);

  // Reset map overlay
  document.getElementById('map-stat').innerHTML = 'Select filters and click <strong>Run Analysis</strong> to load patent data.';
  document.getElementById('status').textContent = '\u2014';

  // Reset right panel stats
  ['s-total', 's-tribes', 's-states', 's-span'].forEach(function(id) {
    var el = document.getElementById(id);
    if (el) el.textContent = '\u2014';
  });

  // Clear chart canvases
  ['chart-temporal', 'chart-compare', 'chart-forced-rate', 'chart-velocity'].forEach(function(id) {
    var canvas = document.getElementById(id);
    if (canvas) {
      var ctx = canvas.getContext('2d');
      ctx.clearRect(0, 0, canvas.width, canvas.height);
    }
  });

  // Reset insight text
  document.getElementById('insight-temporal').textContent = 'Run an analysis to see temporal patterns.';
  document.getElementById('insight-compare').textContent = '\u2014';
  document.getElementById('insight-forced-rate').textContent = '\u2014';
  document.getElementById('insight-velocity').textContent = '\u2014';
  document.getElementById('county-bars').innerHTML = '';

  // Switch to Analysis tab
  document.querySelectorAll('.header-tab').forEach(function(t) { t.classList.remove('active'); });
  document.querySelector('[data-view="heatmap"]').classList.add('active');
  App.switchView('heatmap');

  App.renderTribes();
};

// Render compare table from loaded data
App.renderCompare = function() {
  var container = document.getElementById('compare-content');
  if (App.currentData.length === 0) {
    container.innerHTML = '<div class="insight">Run an analysis first to compare tribes.</div>';
    return;
  }

  // Group current data by tribe
  var tribes = {};
  App.currentData.forEach(function(f) {
    var p = f.properties;
    var tribe = p.preferred_name || 'Unknown';
    if (!tribes[tribe]) tribes[tribe] = { trust: 0, fee: 0, forced: 0, years: [] };
    var type = App.classifyPatent(p.authority, p.forced_fee);
    if (p.forced_fee === 'True') tribes[tribe].forced++;
    if (type === 'fee') tribes[tribe].fee++;
    else if (type === 'trust') tribes[tribe].trust++;
    if (p.signature_date) {
      var y = new Date(p.signature_date).getFullYear();
      if (y >= 1850 && y <= 1975) tribes[tribe].years.push(y);
    }
  });

  // Sort by total patents descending (fee already includes forced)
  var sorted = Object.entries(tribes).sort(function(a, b) {
    var totalA = a[1].trust + a[1].fee;
    var totalB = b[1].trust + b[1].fee;
    return totalB - totalA;
  });

  var html = '<table class="compare-table">';
  html += '<thead><tr><th>Tribe</th><th>Total</th><th>Trust</th><th>Fee</th><th>Forced</th><th>Fee %</th><th>Span</th></tr></thead>';
  html += '<tbody>';

  sorted.forEach(function(entry) {
    var name = entry[0], d = entry[1];
    var total = d.trust + d.fee;
    var feePct = total > 0 ? (d.fee / total * 100).toFixed(1) : '0.0';
    d.years.sort(function(a, b) { return a - b; });
    var span = d.years.length > 0 ? d.years[0] + '–' + d.years[d.years.length - 1] : '—';

    var feeClass = '';
    if (parseFloat(feePct) >= 50) feeClass = ' class="warn"';
    else if (parseFloat(feePct) >= 25) feeClass = ' class="highlight"';

    html += '<tr>';
    html += '<td class="compare-tribe">' + name + '</td>';
    html += '<td>' + total.toLocaleString() + '</td>';
    html += '<td style="color:var(--trust-color)">' + d.trust.toLocaleString() + '</td>';
    html += '<td style="color:var(--fee-color)">' + d.fee.toLocaleString() + '</td>';
    html += '<td style="color:var(--forced-color)">' + d.forced.toLocaleString() + '</td>';
    html += '<td' + feeClass + '>' + feePct + '%</td>';
    html += '<td>' + span + '</td>';
    html += '</tr>';
  });

  html += '</tbody></table>';
  container.innerHTML = html;
};

// ═══════════════════════════════════════════════
// Name Search
// ═══════════════════════════════════════════════
App.searchByName = async function(name) {
  var container = document.getElementById('name-results');
  name = name.trim();
  if (!name) { container.innerHTML = ''; return; }

  container.innerHTML = '<div class="name-results-status">Searching\u2026</div>';

  // Query the feature service for matching names (case-insensitive LIKE)
  var safeName = name.replace(/'/g, "''").replace(/%/g, '');
  var where = "UPPER(full_name) LIKE '%" + safeName.toUpperCase() + "%'";

  var res = await App.query({
    where: where,
    outFields: 'OBJECTID,accession_number,preferred_name,full_name,signature_date,authority,state,county,forced_fee,section_number,township_number,range_number,aliquot_parts',
    returnGeometry: false,
    returnCentroid: true,
    resultRecordCount: 50,
    orderByFields: 'full_name ASC'
  });

  var features = res.features || [];
  if (features.length === 0) {
    container.innerHTML = '<div class="name-results-status">No patents found for "' + name + '"</div>';
    return;
  }

  // Collect unique tribes from results for context loading
  var resultTribes = {};
  features.forEach(function(f) {
    var t = f.attributes.preferred_name;
    if (t) resultTribes[t] = true;
  });
  App._searchResultTribes = Object.keys(resultTribes);
  App._searchResultAccessions = features.map(function(f) { return f.attributes.accession_number; }).filter(Boolean);

  var tribeLabel = App._searchResultTribes.length === 1
    ? App._searchResultTribes[0]
    : App._searchResultTribes.length + ' tribes';

  var contextChecked = App._nameSearchContext ? ' checked' : '';
  var html = '<div class="name-results-status">' + features.length + (features.length === 50 ? '+' : '') + ' results</div>';
  html += '<label class="ctrl-checkbox name-context-toggle"><input type="checkbox" id="chk-name-context"' + contextChecked + ' /> Show all ' + tribeLabel + ' patents</label>';

  features.forEach(function(f) {
    var a = f.attributes;
    var date = a.signature_date ? new Date(a.signature_date).getFullYear() : '\u2014';
    var type = App.classifyPatent(a.authority, a.forced_fee);
    var isForced = a.forced_fee === 'True';
    var tagClass = isForced ? 'forced' : (type === 'fee' ? 'fee' : 'trust');
    var tagText = isForced ? 'Forced' : (type === 'fee' ? 'Fee' : 'Trust');
    var loc = 'T' + (a.township_number || '?') + ' R' + (a.range_number || '?') + ' \u00a7' + (a.section_number || '?');

    html += '<div class="name-result" data-accession="' + (a.accession_number || '') + '">';
    html += '<div class="name-result-name">' + (a.full_name || 'Unknown') + ' <span class="name-result-tag ' + tagClass + '">' + tagText + '</span></div>';
    html += '<div class="name-result-detail">' + (a.preferred_name || '') + ' \u00b7 ' + date + ' \u00b7 ' + loc + ' \u00b7 ' + (a.state || '') + (a.county ? ', ' + a.county : '') + '</div>';
    html += '</div>';
  });

  container.innerHTML = html;

  // Click handler for results
  container.querySelectorAll('.name-result').forEach(function(el) {
    el.addEventListener('click', function() {
      var accession = this.getAttribute('data-accession');
      if (accession) App.zoomToAccession(accession);
    });
  });

  // Context toggle handler
  var contextChk = document.getElementById('chk-name-context');
  if (contextChk) {
    contextChk.addEventListener('change', function() {
      App._nameSearchContext = this.checked;
      if (this.checked) {
        App.loadNameSearchContext();
      } else {
        // Remove context layer, keep just the highlight
        if (App._contextLayer) {
          App.map.removeLayer(App._contextLayer);
          App._contextLayer = null;
        }
      }
    });
    // If toggle was already on (re-search), load context immediately
    if (App._nameSearchContext) {
      App.loadNameSearchContext();
    }
  }
};

// Load all patents for the tribe(s) found in name search results
App.loadNameSearchContext = async function() {
  if (!App._searchResultTribes || App._searchResultTribes.length === 0) return;

  document.getElementById('status').textContent = 'Loading context\u2026';

  // Select the tribe(s) and run a full analysis
  App.selectedTribes = App._searchResultTribes.slice();
  App.renderTribes();

  // Skip fit bounds — we want to stay near the searched patent
  App._skipFitBounds = true;
  await App.runAnalysis();
  App._skipFitBounds = false;

  // Re-add the highlight on top so the searched patent stays visible
  App._addHighlight(false);

  document.getElementById('status').textContent = App.currentData.length.toLocaleString() + ' patents loaded (context)';
};
