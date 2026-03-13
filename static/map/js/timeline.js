// ═══════════════════════════════════════════════
// Cumulative Timeline Mode
// ═══════════════════════════════════════════════

// Build a sorted index of features with precomputed .year
App.buildTimelineIndex = function() {
  App.timelineIndex = [];
  App.currentData.forEach(function(f) {
    var ts = f.properties.signature_date;
    if (!ts) return;
    var year = new Date(ts).getFullYear();
    if (year < 1850 || year > 2018) return;
    f._tlYear = year;
    App.timelineIndex.push(f);
  });
  App.timelineIndex.sort(function(a, b) { return a._tlYear - b._tlYear; });
};

// Toggle timeline mode on/off
App.toggleTimeline = function(enabled) {
  App.timelineMode = enabled;
  var bar = document.getElementById('timeline-bar');
  var overlay = document.getElementById('map-year-overlay');
  var metrics = document.getElementById('tl-metrics-overlay');
  var appEl = document.querySelector('.app');

  if (enabled) {
    if (App.timelineIndex.length === 0) {
      App.buildTimelineIndex();
    }
    if (App.timelineIndex.length === 0) return; // no data

    bar.style.display = '';
    metrics.style.display = '';
    appEl.classList.add('timeline-active');
    App.drawTimelineChart();

    var startYear = App.timelineIndex[0]._tlYear - 10;
    App.setTimelineYear(startYear);
    overlay.style.display = '';
  } else {
    App.pauseTimeline();
    bar.style.display = 'none';
    overlay.style.display = 'none';
    metrics.style.display = 'none';
    appEl.classList.remove('timeline-active');
    App.timelineYear = null;

    // Restore full dataset rendering
    App.renderMap(false);
  }
};

// Draw stacked area chart on the timeline track canvas
App.drawTimelineChart = function() {
  var canvas = document.getElementById('tl-chart');
  var ctx = canvas.getContext('2d');
  var dpr = window.devicePixelRatio || 1;
  var rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = 40 * dpr;
  canvas.style.height = '40px';
  ctx.scale(dpr, dpr);
  var W = rect.width, H = 40;

  // Bin features by year and type
  var bins = {}; // year -> { trust, fee, forced }
  var minYear = Infinity, maxYear = -Infinity;

  App.timelineIndex.forEach(function(f) {
    var y = f._tlYear;
    if (y < minYear) minYear = y;
    if (y > maxYear) maxYear = y;
    if (!bins[y]) bins[y] = { trust: 0, fee: 0, forced: 0 };
    var type = App.classifyPatent(f.properties.authority, f.properties.forced_fee);
    var isForced = f.properties.forced_fee === 'True';
    if (isForced) bins[y].forced++;
    if (type === 'fee') bins[y].fee++;
    else if (type === 'trust') bins[y].trust++;
  });

  if (minYear > maxYear) return;

  // Start 10 years before first patent so timeline shows the "blank slate"
  var displayMin = minYear - 10;

  // Build year array
  var years = [];
  for (var y = displayMin; y <= maxYear; y++) years.push(y);

  // Find max stacked value (fee already includes forced)
  var maxVal = 1;
  years.forEach(function(y) {
    var b = bins[y] || { trust: 0, fee: 0, forced: 0 };
    var total = b.trust + b.fee;
    if (total > maxVal) maxVal = total;
  });

  ctx.clearRect(0, 0, W, H);
  var chartH = H - 12; // reserve 12px at bottom for year labels
  var barW = W / years.length;

  // Draw trust (blue, back) then fee (amber, front) stacked
  years.forEach(function(year, i) {
    var b = bins[year] || { trust: 0, fee: 0, forced: 0 };
    var x = i * barW;

    var trustH = (b.trust / maxVal) * (chartH - 2);
    var feeH = (b.fee / maxVal) * (chartH - 2);

    // Trust (deep blue) on bottom
    ctx.fillStyle = 'rgba(11, 83, 148, 0.6)';
    ctx.fillRect(x, chartH - 1 - trustH - feeH, Math.max(barW - 0.5, 1), trustH);

    // Fee (orange) stacked on top of trust
    ctx.fillStyle = 'rgba(224, 120, 0, 0.8)';
    ctx.fillRect(x, chartH - 1 - feeH, Math.max(barW - 0.5, 1), feeH);
  });

  // Year labels along x-axis
  ctx.fillStyle = '#9a9490';
  ctx.font = '9px "IBM Plex Mono"';
  ctx.textAlign = 'center';
  var span = maxYear - minYear;
  var step = span > 80 ? 20 : span > 40 ? 10 : 5;
  var firstTick = Math.ceil(minYear / step) * step;
  for (var tick = firstTick; tick <= maxYear; tick += step) {
    var tx = ((tick - minYear) / span) * W;
    ctx.fillText(tick, tx, H - 1);
  }

  // Store layout info for hit-testing and slider
  App._tlYears = years;
  App._tlMinYear = displayMin;
  App._tlMaxYear = maxYear;

  // Sync range slider bounds
  var slider = document.getElementById('tl-slider');
  slider.min = displayMin;
  slider.max = maxYear;
  slider.value = App.timelineYear || minYear;
};

// Set the timeline to a specific year and re-render the map
App.setTimelineYear = function(year) {
  if (!App.timelineMode) return;

  year = Math.max(App._tlMinYear || 1850, Math.min(App._tlMaxYear || 1975, year));
  App.timelineYear = year;

  // Filter timelineIndex to features through this year
  var filtered = [];
  for (var i = 0; i < App.timelineIndex.length; i++) {
    if (App.timelineIndex[i]._tlYear <= year) {
      filtered.push(App.timelineIndex[i]);
    } else {
      break; // sorted, so we can stop
    }
  }

  // Temporarily swap currentData, render, restore
  var savedData = App.currentData;
  App.currentData = filtered;
  App.renderMap(false);
  App.currentData = savedData;

  // Update thumb position
  var track = document.getElementById('tl-track');
  var thumb = document.getElementById('tl-thumb');
  var years = App._tlYears || [];
  if (years.length > 1) {
    var pct = (year - years[0]) / (years[years.length - 1] - years[0]);
    thumb.style.left = (pct * track.offsetWidth) + 'px';
  }

  // Update year label and slider
  document.getElementById('tl-year-label').textContent = year;
  document.getElementById('tl-slider').value = year;

  // Update overlay
  var overlay = document.getElementById('map-year-overlay');
  overlay.textContent = year;
  overlay.style.display = '';

  // Update stats (fee already includes forced via classifyPatent)
  var trustCount = 0, feeCount = 0, forcedCount = 0;
  filtered.forEach(function(f) {
    var type = App.classifyPatent(f.properties.authority, f.properties.forced_fee);
    if (f.properties.forced_fee === 'True') forcedCount++;
    if (type === 'fee') feeCount++;
    else if (type === 'trust') trustCount++;
  });

  var total = trustCount + feeCount;
  var feePct = total > 0 ? (feeCount / total * 100).toFixed(1) : '0.0';
  var voluntaryFee = feeCount - forcedCount;

  document.getElementById('tl-stats').textContent =
    'Through ' + year + ': ' +
    trustCount.toLocaleString() + ' trust, ' +
    feeCount.toLocaleString() + ' fee (' +
    forcedCount.toLocaleString() + ' forced) — ' +
    feePct + '% fee';

  // Update ratio bar
  if (total > 0) {
    var trustPct = (trustCount / total * 100);
    var volFeePct = (voluntaryFee / total * 100);
    var forcedPct = (forcedCount / total * 100);
    document.getElementById('tl-ratio-trust').style.width = trustPct + '%';
    document.getElementById('tl-ratio-fee').style.width = volFeePct + '%';
    document.getElementById('tl-ratio-forced').style.width = forcedPct + '%';
    document.getElementById('tl-ratio-label').textContent =
      trustPct.toFixed(0) + '% trust / ' + feePct + '% fee';
  }

  // Update metrics overlay
  document.getElementById('tl-metric-total').textContent = total.toLocaleString();
  document.getElementById('tl-metric-trust').textContent = trustCount.toLocaleString();
  document.getElementById('tl-metric-fee').textContent = voluntaryFee.toLocaleString();
  document.getElementById('tl-metric-forced').textContent = forcedCount.toLocaleString();
  document.getElementById('tl-metric-pct').textContent = feePct + '%';
};

// Playback controls
App.playTimeline = function() {
  if (App.timelineInterval) return; // already playing

  var speed = parseInt(document.getElementById('tl-speed').value) || 200;
  var years = App._tlYears || [];
  if (years.length === 0) return;

  var currentYear = App.timelineYear || years[0];
  document.getElementById('tl-play').textContent = '\u23F8'; // pause symbol

  App.timelineInterval = setInterval(function() {
    currentYear++;
    if (currentYear > years[years.length - 1]) {
      App.pauseTimeline();
      return;
    }
    App.setTimelineYear(currentYear);
  }, speed);
};

App.pauseTimeline = function() {
  if (App.timelineInterval) {
    clearInterval(App.timelineInterval);
    App.timelineInterval = null;
  }
  document.getElementById('tl-play').textContent = '\u25B6'; // play symbol
};

// Track click/drag interaction
App.initTimelineTrack = function() {
  var track = document.getElementById('tl-track');
  var dragging = false;

  var yearFromEvent = function(e) {
    var rect = track.getBoundingClientRect();
    var x = Math.max(0, Math.min(e.clientX - rect.left, rect.width));
    var pct = x / rect.width;
    var years = App._tlYears || [];
    if (years.length === 0) return null;
    var year = Math.round(years[0] + pct * (years[years.length - 1] - years[0]));
    return year;
  };

  track.addEventListener('mousedown', function(e) {
    dragging = true;
    App.pauseTimeline();
    var year = yearFromEvent(e);
    if (year !== null) App.setTimelineYear(year);
    e.preventDefault();
  });

  document.addEventListener('mousemove', function(e) {
    if (!dragging) return;
    var year = yearFromEvent(e);
    if (year !== null) App.setTimelineYear(year);
  });

  document.addEventListener('mouseup', function() {
    dragging = false;
  });

  // Play/pause button
  document.getElementById('tl-play').addEventListener('click', function() {
    if (App.timelineInterval) {
      App.pauseTimeline();
    } else {
      App.playTimeline();
    }
  });

  // Range slider — primary manual scrubbing control
  var slider = document.getElementById('tl-slider');
  slider.addEventListener('input', function() {
    App.pauseTimeline();
    App.setTimelineYear(parseInt(this.value));
  });

  // Speed change restarts playback if currently playing
  document.getElementById('tl-speed').addEventListener('change', function() {
    if (App.timelineInterval) {
      App.pauseTimeline();
      App.playTimeline();
    }
  });
};
