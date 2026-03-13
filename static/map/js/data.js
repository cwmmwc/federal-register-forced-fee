// ═══════════════════════════════════════════════
// Data Fetching
// ═══════════════════════════════════════════════
App.query = async function(params) {
  var url = new URL(App.BASE);
  var defaults = { f: 'json', outSR: 4326 };
  for (var [k, v] of Object.entries({ ...defaults, ...params })) {
    url.searchParams.set(k, typeof v === 'object' ? JSON.stringify(v) : String(v));
  }
  var r = await fetch(url);
  return r.json();
};

App.loadMetadata = async function() {
  App.setLoad(20, 'Loading tribe data\u2026');
  var tribeRes = await App.query({
    where: '1=1',
    outStatistics: [{statisticType:'count',onStatisticField:'OBJECTID',outStatisticFieldName:'cnt'}],
    groupByFieldsForStatistics: 'preferred_name',
    orderByFields: 'cnt DESC'
  });
  tribeRes.features.forEach(function(f) {
    if (f.attributes.preferred_name) App.tribeMap[f.attributes.preferred_name] = f.attributes.cnt;
  });

  App.setLoad(50, 'Loading state data\u2026');
  var stateRes = await App.query({
    where: '1=1',
    outStatistics: [{statisticType:'count',onStatisticField:'OBJECTID',outStatisticFieldName:'cnt'}],
    groupByFieldsForStatistics: 'state',
    orderByFields: 'cnt DESC'
  });
  stateRes.features.forEach(function(f) {
    if (f.attributes.state) App.stateMap[f.attributes.state] = f.attributes.cnt;
  });

  App.setLoad(100, 'Ready');
};

App.runAnalysis = async function() {
  var category = document.getElementById('sel-category').value;
  var yearStart = parseInt(document.getElementById('sel-year-start').value);
  var yearEnd = parseInt(document.getElementById('sel-year-end').value);
  var state = document.getElementById('sel-state').value;

  document.getElementById('status').textContent = 'Querying\u2026';
  document.getElementById('map-stat').innerHTML = 'Loading patent data\u2026';

  // Build where clause
  var clauses = [App.CATEGORIES[category]];
  if (yearStart > 1854 || yearEnd < 2018) {
    clauses.push("signature_date >= timestamp '" + yearStart + "-01-01' AND signature_date < timestamp '" + (yearEnd + 1) + "-01-01'");
  }
  if (state) clauses.push("state = '" + state + "'");
  if (App.selectedTribes.length === 1) {
    clauses.push("preferred_name = '" + App.selectedTribes[0].replace(/'/g, "''") + "'");
  } else if (App.selectedTribes.length > 1) {
    clauses.push("preferred_name IN (" + App.selectedTribes.map(function(t) { return "'" + t.replace(/'/g, "''") + "'"; }).join(',') + ")");
  }

  var where = clauses.join(' AND ');

  // Get total count
  var countRes = await App.query({ where: where, returnCountOnly: true });
  var total = countRes.count || 0;

  // For large queries (> 25k), use centroids only — much smaller payload
  var useCentroidsOnly = total > App.FETCH_LIMIT;
  // Larger batches for centroids (no geometry), smaller for full polygons
  var batchSize = useCentroidsOnly ? 5000 : 2000;

  // Fetch all features — no cap
  var allFeatures = [];
  var offset = 0;

  while (offset < total) {
    var queryParams = {
      where: where,
      outFields: 'OBJECTID,accession_number,preferred_name,full_name,signature_date,authority,state,county,forced_fee,cancelled_doc,aliquot_parts,section_number,township_number,range_number',
      resultRecordCount: batchSize,
      resultOffset: offset
    };
    if (useCentroidsOnly) {
      queryParams.returnGeometry = false;
      queryParams.returnCentroid = true;
      queryParams.f = 'json';
    } else {
      queryParams.returnGeometry = true;
      queryParams.returnCentroid = true;
      queryParams.f = 'geojson';
    }
    var res = await App.query(queryParams);

    if (useCentroidsOnly) {
      if (!res.features || res.features.length === 0) break;
      res.features.forEach(function(f) {
        if (f.centroid) {
          allFeatures.push({
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [f.centroid.x, f.centroid.y] },
            properties: f.attributes
          });
        }
      });
      offset += res.features.length;
    } else {
      if (!res.features || res.features.length === 0) break;
      allFeatures = allFeatures.concat(res.features);
      offset += res.features.length;
    }

    var pct = Math.round((offset / total) * 100);
    document.getElementById('status').textContent = 'Loading\u2026 ' + pct + '% (' + allFeatures.length.toLocaleString() + ' of ' + total.toLocaleString() + ')';
  }

  App.currentData = allFeatures;
  var statusText = App.currentData.length.toLocaleString() + ' patents loaded';
  if (useCentroidsOnly) statusText += ' (centroids \u2014 select a tribe for parcels)';
  document.getElementById('status').textContent = statusText;

  // Render map and basic analysis immediately — don't wait for stat queries
  App.renderMap();
  App.analyzePatterns();
  App.renderCompare();

  // Build timeline index for cumulative mode
  App.buildTimelineIndex();
  if (App.timelineMode && App.timelineIndex.length > 0) {
    App.drawTimelineChart();
    App.setTimelineYear(App.timelineIndex[0]._tlYear - 10);
  }

  // Fire stat queries in parallel (independent of loaded data)
  // These update the comparison chart and forced fee rate chart when they arrive
  Promise.all([
    App.loadComparisonData(yearStart, yearEnd, state).then(function() {
      App.drawCompareChart();
    }).catch(function(e) { console.warn('Comparison data failed:', e); }),

    App.loadForcedFeeByTribe(yearStart, yearEnd, state).then(function() {
      App.drawForcedRateChart();
    }).catch(function(e) { console.warn('Forced fee stats failed:', e); })
  ]);
};

App.loadComparisonData = async function(yearStart, yearEnd, state) {
  // Load year-by-year counts for both trust and fee
  var timeClauses = [];
  if (yearStart > 1854 || yearEnd < 2018) {
    timeClauses.push("signature_date >= timestamp '" + yearStart + "-01-01' AND signature_date < timestamp '" + (yearEnd + 1) + "-01-01'");
  }
  if (state) timeClauses.push("state = '" + state + "'");
  if (App.selectedTribes.length === 1) {
    timeClauses.push("preferred_name = '" + App.selectedTribes[0].replace(/'/g, "''") + "'");
  } else if (App.selectedTribes.length > 1) {
    timeClauses.push("preferred_name IN (" + App.selectedTribes.map(function(t) { return "'" + t.replace(/'/g, "''") + "'"; }).join(',') + ")");
  }

  var extraWhere = timeClauses.length ? ' AND ' + timeClauses.join(' AND ') : '';

  // Fee patents per year (authority-only, so dates reflect actual fee issuance)
  var feeYears = await App.query({
    where: App.CATEGORIES.fee_authority + extraWhere,
    outStatistics: [{statisticType:'count',onStatisticField:'OBJECTID',outStatisticFieldName:'cnt'}],
    groupByFieldsForStatistics: 'signature_date',
    orderByFields: 'signature_date ASC'
  });

  // Trust patents per year
  var trustYears = await App.query({
    where: App.CATEGORIES.trust + extraWhere,
    outStatistics: [{statisticType:'count',onStatisticField:'OBJECTID',outStatisticFieldName:'cnt'}],
    groupByFieldsForStatistics: 'signature_date',
    orderByFields: 'signature_date ASC'
  });

  // Forced fee per year
  var forcedYears = await App.query({
    where: App.CATEGORIES.forced + extraWhere,
    outStatistics: [{statisticType:'count',onStatisticField:'OBJECTID',outStatisticFieldName:'cnt'}],
    groupByFieldsForStatistics: 'signature_date',
    orderByFields: 'signature_date ASC'
  });

  // Aggregate into year bins
  App.analysisCache.feeByYear = App.binByYear(feeYears.features || []);
  App.analysisCache.trustByYear = App.binByYear(trustYears.features || []);
  App.analysisCache.forcedByYear = App.binByYear(forcedYears.features || []);
};

App.binByYear = function(features) {
  var bins = {};
  features.forEach(function(f) {
    var ts = f.attributes.signature_date;
    if (!ts) return;
    var year = new Date(ts).getFullYear();
    if (year >= 1850 && year <= 2018) {
      bins[year] = (bins[year] || 0) + f.attributes.cnt;
    }
  });
  return bins;
};

// Query fee and forced fee counts per tribe — uses stat queries so no record limit
App.loadForcedFeeByTribe = async function(yearStart, yearEnd, state) {
  var timeClauses = [];
  if (yearStart > 1854 || yearEnd < 2018) {
    timeClauses.push("signature_date >= timestamp '" + yearStart + "-01-01' AND signature_date < timestamp '" + (yearEnd + 1) + "-01-01'");
  }
  if (state) timeClauses.push("state = '" + state + "'");
  if (App.selectedTribes.length === 1) {
    timeClauses.push("preferred_name = '" + App.selectedTribes[0].replace(/'/g, "''") + "'");
  } else if (App.selectedTribes.length > 1) {
    timeClauses.push("preferred_name IN (" + App.selectedTribes.map(function(t) { return "'" + t.replace(/'/g, "''") + "'"; }).join(',') + ")");
  }
  var extraWhere = timeClauses.length ? ' AND ' + timeClauses.join(' AND ') : '';

  // Fee patents per tribe (all fee patents including forced)
  var feeRes = await App.query({
    where: App.CATEGORIES.fee + extraWhere,
    outStatistics: [{statisticType:'count',onStatisticField:'OBJECTID',outStatisticFieldName:'cnt'}],
    groupByFieldsForStatistics: 'preferred_name',
    orderByFields: 'cnt DESC'
  });

  // Forced fee patents per tribe
  var forcedRes = await App.query({
    where: App.CATEGORIES.forced + extraWhere,
    outStatistics: [{statisticType:'count',onStatisticField:'OBJECTID',outStatisticFieldName:'cnt'}],
    groupByFieldsForStatistics: 'preferred_name',
    orderByFields: 'cnt DESC'
  });

  // Secretarial transfers (Trust to Fee) per tribe — administrative conversions
  var secRes = await App.query({
    where: "authority = 'Indian Trust to Fee'" + extraWhere,
    outStatistics: [{statisticType:'count',onStatisticField:'OBJECTID',outStatisticFieldName:'cnt'}],
    groupByFieldsForStatistics: 'preferred_name',
    orderByFields: 'cnt DESC'
  });

  // Build lookup: tribe → { fee, forced, secretarial }
  var byTribe = {};
  (feeRes.features || []).forEach(function(f) {
    var name = f.attributes.preferred_name;
    if (!name) return;
    if (!byTribe[name]) byTribe[name] = { fee: 0, forced: 0, secretarial: 0 };
    byTribe[name].fee = f.attributes.cnt;
  });
  (forcedRes.features || []).forEach(function(f) {
    var name = f.attributes.preferred_name;
    if (!name) return;
    if (!byTribe[name]) byTribe[name] = { fee: 0, forced: 0, secretarial: 0 };
    byTribe[name].forced = f.attributes.cnt;
  });
  (secRes.features || []).forEach(function(f) {
    var name = f.attributes.preferred_name;
    if (!name) return;
    if (!byTribe[name]) byTribe[name] = { fee: 0, forced: 0, secretarial: 0 };
    byTribe[name].secretarial = f.attributes.cnt;
  });

  App.analysisCache.forcedFeeByTribe = byTribe;
};
