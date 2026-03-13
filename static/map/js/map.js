// ═══════════════════════════════════════════════
// Map Rendering
// ═══════════════════════════════════════════════
App.initMap = function() {
  App.map = L.map('map', {
    center: [43, -104],
    zoom: 5,
    preferCanvas: true,
    zoomControl: true,
    maxZoom: 19,
    minZoom: 3
  });

  // Basemap layers
  App._basemaps = {
    topo: L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 19,
      attribution: 'Esri'
    }),
    lightGray: L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 16
    })
  };
  App._basemapRef = L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 16, pane: 'overlayPane'
  });

  // Default to topo
  App._basemaps.topo.addTo(App.map);
  App._activeBasemap = 'topo';

  // Federal Indian Reservations overlay (Census TIGERweb AIANNHA, layer 2)
  App._reservationLayer = L.tileLayer('https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/AIANNHA/MapServer/tile/{z}/{y}/{x}', {
    maxZoom: 19,
    opacity: 0.5,
    attribution: 'US Census TIGERweb'
  });

  // Rankin Map of the Allotted Land of the Crow Reservation 1907 (UVA Library)
  App._rankinLayer = L.tileLayer('https://tiles.arcgis.com/tiles/8k2PygHqghVevhzy/arcgis/rest/services/Rankin_Map_of_the_Allotted_Land_of_the_Crow_Reservation_1907/MapServer/tile/{z}/{y}/{x}', {
    minZoom: 6,
    maxZoom: 18,
    opacity: 0.7,
    attribution: 'UVA Library'
  });

  // Heatmap layer — leaflet.heat 0.2.0 always renders on overlayPane
  // so we style its canvas directly after init
  App.heatLayer = L.heatLayer([], {
    radius: 20,
    blur: 8,
    maxZoom: App.map.getZoom() + 1,
    gradient: {
      0: 'rgba(0,0,0,0)',
      0.2: '#fef0d9',
      0.4: '#fdcc8a',
      0.6: '#fc8d59',
      0.8: '#e34a33',
      1.0: '#b30000'
    }
  }).addTo(App.map);

  // Monkey-patch leaflet.heat _reset to tag canvas with CSS class on every recreate
  var origReset = App.heatLayer._reset;
  App.heatLayer._reset = function() {
    origReset.call(this);
    if (this._canvas) {
      this._canvas.classList.add('heatmap-canvas');
    }
  };
  // Tag canvas if it already exists
  if (App.heatLayer._canvas) {
    App.heatLayer._canvas.classList.add('heatmap-canvas');
  }

  App.pointLayer = L.layerGroup().addTo(App.map);
  App.parcelLayer = L.layerGroup().addTo(App.map);

  // Re-render on zoom change — rebuild heatmap and toggle parcels vs markers
  App.map.on('zoomend', function() {
    var newZoom = App.map.getZoom();
    if (App.lastZoom !== null && App.currentData.length > 0) {
      // Always re-render to rebuild heatmap at new zoom
      if (App.timelineMode && App.timelineYear !== null) {
        App.setTimelineYear(App.timelineYear);
      } else {
        App.renderMap(false);
      }
      // Re-add highlight if present
      App._addHighlight(false);
    }
    App.lastZoom = newZoom;
  });

  App.lastZoom = App.map.getZoom();
};

// Rebuild heatmap radius as fixed geographic distance (~2 miles) in pixels
App.updateHeatRadius = function() {
  if (!App.heatLayer) return;
  var zoom = App.map.getZoom();
  var pixPerDeg = 256 * Math.pow(2, zoom) / 360;
  var radiusPx = Math.max(15, Math.round((2 / 69) * pixPerDeg));
  var blurPx = Math.max(8, Math.round(radiusPx * 0.5));

  // maxZoom = current zoom + 1 disables leaflet.heat internal scaling
  App.heatLayer.setOptions({ radius: radiusPx, blur: blurPx, maxZoom: zoom + 1 });
};

App.renderMap = function(fitBounds) {
  App.pointLayer.clearLayers();
  App.parcelLayer.clearLayers();
  var heatPoints = [];
  var showHeat = document.getElementById('chk-heatmap').checked;
  var showPoints = document.getElementById('chk-points').checked;
  var highlightForced = document.getElementById('chk-forced-highlight').checked;
  var zoom = App.map.getZoom();
  var showParcels = zoom >= 9;

  var feeCount = 0, trustCount = 0, forcedCount = 0;

  var useOriginal = App.timelineMode && App.classifyMode === 'original';
  var classifyFn = useOriginal ? App.classifyPatentOriginal : App.classifyPatent;

  // Build section-level forced fee counts for popup context
  var sectionCounts = {};
  App.currentData.forEach(function(f) {
    var p = f.properties;
    if (p.forced_fee !== 'True') return;
    var twp = p.township_number, rng = p.range_number, sec = p.section_number;
    if (!twp || !rng || !sec) return;
    var key = 'T' + twp + 'R' + rng + ' \u00a7' + sec;
    if (!sectionCounts[key]) sectionCounts[key] = { forced: 0, allottees: new Set() };
    sectionCounts[key].forced++;
    if (p.full_name) sectionCounts[key].allottees.add(p.full_name);
  });
  App.analysisCache.sectionCounts = sectionCounts;

  // Two-pass rendering: non-forced first, then forced on top (so red is always visible)
  var deferredForced = [];

  App.currentData.forEach(function(f) {
    var p = f.properties;
    var type = useOriginal ? classifyFn(p.authority) : classifyFn(p.authority, p.forced_fee);
    var isForced = p.forced_fee === 'True';

    if (isForced) forcedCount++;
    if (type === 'fee') feeCount++;
    else if (type === 'trust') trustCount++;

    // Compute centroid for heatmap and circle markers
    var lat, lng;
    if (f.geometry.type === 'Point') {
      lng = f.geometry.coordinates[0];
      lat = f.geometry.coordinates[1];
    } else if (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon') {
      var coords = f.geometry.type === 'Polygon' ? f.geometry.coordinates[0] : f.geometry.coordinates[0][0];
      lng = coords.reduce(function(s, c) { return s + c[0]; }, 0) / coords.length;
      lat = coords.reduce(function(s, c) { return s + c[1]; }, 0) / coords.length;
    }
    if (!lat || !lng) return;

    // Heatmap: only fee patents (forced is a subset of fee)
    if (showHeat && type === 'fee') {
      heatPoints.push([lat, lng, isForced ? 1.0 : 0.5]);
    }

    // Defer forced fee parcels to render on top
    if (isForced && highlightForced) {
      deferredForced.push({ f: f, p: p, type: type, lat: lat, lng: lng });
      return;
    }

    // Parcel polygons at zoom >= 9
    if (showPoints && showParcels && (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon')) {
      var fillColor, borderColor, fillOpacity, dashArray = null, weight = 1;
      if (type === 'fee') {
        fillColor = '#e07800'; borderColor = '#9a5200'; fillOpacity = 0.95;
      } else if (type === 'trust') {
        fillColor = '#1565c0'; borderColor = '#0d47a1'; fillOpacity = 0.95;
      } else {
        fillColor = '#9a9490'; borderColor = '#6a6460'; fillOpacity = 0.6;
      }

      var parcel = L.geoJSON(f.geometry, {
        style: {
          fillColor: fillColor, color: borderColor, weight: weight,
          fillOpacity: fillOpacity, opacity: 0.7, dashArray: dashArray
        }
      });
      parcel.bindPopup(function() { return App.makePopup(p); });
      App.parcelLayer.addLayer(parcel);
    }

    // Circle markers at zoom < 9 (or as fallback for Point geometry)
    if (showPoints && (!showParcels || f.geometry.type === 'Point')) {
      var color, radius, opacity, markerBorder = 'rgba(0,0,0,0.15)', markerWeight = 0.5;
      if (useOriginal && isForced && type === 'trust') {
        color = '#0b5394'; radius = 3.5; opacity = 0.65;
        markerBorder = '#e07800'; markerWeight = 1.5;
      } else if (type === 'fee') {
        color = '#e07800'; radius = 3.5; opacity = 0.7;
      } else if (type === 'trust') {
        color = '#0b5394'; radius = 3; opacity = 0.6;
      } else {
        color = '#9a9490'; radius = 2; opacity = 0.3;
      }

      var marker = L.circleMarker([lat, lng], {
        radius: radius, fillColor: color, fillOpacity: opacity,
        color: markerBorder, weight: markerWeight
      });
      marker.bindPopup(function() { return App.makePopup(p); });
      App.pointLayer.addLayer(marker);
    }
  });

  // Second pass: render forced fee parcels on top so red is always visible
  deferredForced.forEach(function(d) {
    if (showPoints && showParcels && (d.f.geometry.type === 'Polygon' || d.f.geometry.type === 'MultiPolygon')) {
      var parcel = L.geoJSON(d.f.geometry, {
        style: {
          fillColor: '#c62828', color: '#ffd600', weight: 2,
          fillOpacity: 0.95, opacity: 1
        }
      });
      parcel.bindPopup(function() { return App.makePopup(d.p); });
      App.parcelLayer.addLayer(parcel);
    }

    if (showPoints && (!showParcels || d.f.geometry.type === 'Point')) {
      var marker = L.circleMarker([d.lat, d.lng], {
        radius: 4, fillColor: '#c62828', fillOpacity: 0.9,
        color: '#ffd600', weight: 1.5
      });
      marker.bindPopup(function() { return App.makePopup(d.p); });
      App.pointLayer.addLayer(marker);
    }
  });

  if (heatPoints.length > 0) {
    var dynamicMax = Math.max(1.0, heatPoints.length / 200);
    App.heatLayer.setOptions({ max: dynamicMax });
  }
  // Hide heatmap at parcel zoom levels — it muddies the parcel colors
  App.heatLayer.setLatLngs(showHeat && !showParcels ? heatPoints : []);
  App.updateHeatRadius();

  // Legend counts
  document.getElementById('leg-trust').textContent = trustCount.toLocaleString();
  document.getElementById('leg-fee').textContent = feeCount.toLocaleString();
  document.getElementById('leg-forced').textContent = forcedCount.toLocaleString();

  // Fit bounds only on initial load, not on zoom-triggered re-renders
  // Skip if we're about to zoom to a specific accession
  if (fitBounds !== false && !App._skipFitBounds) {
    var allLats = [], allLngs = [];
    App.currentData.forEach(function(f) {
      var lat, lng;
      if (f.geometry.type === 'Point') {
        lng = f.geometry.coordinates[0];
        lat = f.geometry.coordinates[1];
      } else if (f.geometry.type === 'Polygon' || f.geometry.type === 'MultiPolygon') {
        var coords = f.geometry.type === 'Polygon' ? f.geometry.coordinates[0] : f.geometry.coordinates[0][0];
        lng = coords.reduce(function(s, c) { return s + c[0]; }, 0) / coords.length;
        lat = coords.reduce(function(s, c) { return s + c[1]; }, 0) / coords.length;
      }
      if (lat && lng) { allLats.push(lat); allLngs.push(lng); }
    });

    if (allLats.length > 0) {
      App.map.fitBounds([
        [Math.min.apply(null, allLats), Math.min.apply(null, allLngs)],
        [Math.max.apply(null, allLats), Math.max.apply(null, allLngs)]
      ], { padding: [30, 30] });
    }
  }

  var modeLabel = showParcels ? 'parcels' : 'markers';
  document.getElementById('map-stat').innerHTML = '<strong>' + App.currentData.length.toLocaleString() + '</strong> patents displayed (' + modeLabel + ')';
};

// Zoom to a specific patent by accession number (for deep-linking)
App.zoomToAccession = async function(accession) {
  App._skipFitBounds = false;

  var res = await App.query({
    where: "accession_number = '" + accession.replace(/'/g, "''") + "'",
    outFields: 'OBJECTID,accession_number,preferred_name,full_name,signature_date,authority,state,county,forced_fee,cancelled_doc,aliquot_parts,section_number,township_number,range_number',
    returnGeometry: true,
    f: 'geojson'
  });

  if (!res.features || res.features.length === 0) {
    document.getElementById('status').textContent += ' | Patent ' + accession + ' not found in map data.';
    return;
  }

  var feature = res.features[0];
  var p = feature.properties;

  var lat, lng;
  if (feature.geometry.type === 'Point') {
    lng = feature.geometry.coordinates[0];
    lat = feature.geometry.coordinates[1];
  } else if (feature.geometry.type === 'Polygon' || feature.geometry.type === 'MultiPolygon') {
    var coords = feature.geometry.type === 'Polygon' ? feature.geometry.coordinates[0] : feature.geometry.coordinates[0][0];
    lng = coords.reduce(function(s, c) { return s + c[0]; }, 0) / coords.length;
    lat = coords.reduce(function(s, c) { return s + c[1]; }, 0) / coords.length;
  }

  if (lat && lng) {
    // Save highlight so it can be re-added after zoomend re-renders
    App._highlight = {
      geometry: feature.geometry,
      props: p
    };

    App.map.setView([lat, lng], 14);

    // Add highlight after map settles
    App.map.once('moveend', function() {
      App._addHighlight(true);
    });
  }
};

// Add the saved highlight parcel to the map
App._addHighlight = function(openPopup) {
  if (!App._highlight) return;
  if (App._highlightLayer) {
    App.map.removeLayer(App._highlightLayer);
  }
  App._highlightLayer = L.geoJSON(App._highlight.geometry, {
    style: {
      fillColor: '#ffff00',
      color: '#d00',
      weight: 4,
      fillOpacity: 0.6,
      opacity: 1
    }
  });
  App._highlightLayer.bindPopup(App.makePopup(App._highlight.props));
  App._highlightLayer.addTo(App.map);
  if (openPopup) App._highlightLayer.openPopup();
};

App.makePopup = function(p) {
  var date = p.signature_date ? new Date(p.signature_date).toLocaleDateString('en-US', {year:'numeric',month:'short',day:'numeric'}) : '\u2014';
  var type = App.classifyPatent(p.authority, p.forced_fee);
  var isForced = p.forced_fee === 'True';
  var tagClass = isForced ? 'forced' : (type === 'fee' ? 'fee' : 'trust');
  var tagText = isForced ? 'Forced Fee' : (type === 'fee' ? 'Fee Patent' : 'Trust Patent');

  // Show conversion path for forced-fee patents
  var conversionNote = '';
  var sectionContext = '';
  if (isForced) {
    var originalType = App.classifyPatentOriginal(p.authority);
    if (originalType === 'trust') {
      conversionNote = '<div class="popup-conversion">Issued as Trust \u2192 Converted to Fee (forced)</div>';
    }
    // Add section-level context so user understands this parcel in aggregate
    var twp = p.township_number, rng = p.range_number, sec = p.section_number;
    if (twp && rng && sec) {
      var secKey = 'T' + twp + 'R' + rng + ' \u00a7' + sec;
      var sc = App.analysisCache.sectionCounts;
      if (sc && sc[secKey]) {
        var allotteeCount = sc[secKey].allottees ? sc[secKey].allottees.size : sc[secKey].forced;
        if (allotteeCount > 1) {
          sectionContext = '<div style="margin-top:4px;padding:3px 6px;background:rgba(198,40,40,0.08);border-left:3px solid #c62828;font-size:10px;color:var(--text-dim);">' +
            '1 of <strong>' + allotteeCount + '</strong> forced fee allottees in this section' +
            '</div>';
        }
      }
    }
  }

  return '<div>' +
    '<div class="popup-name">' + (p.full_name || 'Unknown') + '</div>' +
    '<span class="popup-tag ' + tagClass + '">' + tagText + '</span>' +
    conversionNote +
    '<div class="popup-row"><span class="k">Tribe</span><span class="v">' + (p.preferred_name || '\u2014') + '</span></div>' +
    '<div class="popup-row"><span class="k">Date</span><span class="v">' + date + '</span></div>' +
    '<div class="popup-row"><span class="k">Authority</span><span class="v">' + (p.authority || '\u2014') + '</span></div>' +
    '<div class="popup-row"><span class="k">State/County</span><span class="v">' + (p.state || '') + (p.county ? ', ' + p.county : '') + '</span></div>' +
    '<div class="popup-row"><span class="k">Location</span><span class="v">T' + (p.township_number || '?') + ' R' + (p.range_number || '?') + ' \u00a7' + (p.section_number || '?') + ' ' + (p.aliquot_parts || '') + '</span></div>' +
    '<div class="popup-row"><span class="k">Accession</span><span class="v">' + (p.accession_number || '\u2014') + '</span></div>' +
    (p.cancelled_doc === 'True' ? '<div style="color:var(--text-faint);font-style:italic;margin-top:4px;">Cancelled</div>' : '') +
    sectionContext +
    '</div>';
};

App.switchBasemap = function(key) {
  if (key === App._activeBasemap) return;
  // Remove current basemap
  App.map.removeLayer(App._basemaps[App._activeBasemap]);
  // Remove reference layer if it was added (light gray uses it)
  if (App.map.hasLayer(App._basemapRef)) App.map.removeLayer(App._basemapRef);
  // Add new basemap
  App._basemaps[key].addTo(App.map);
  App._basemaps[key].bringToBack();
  // Light gray needs a reference overlay for labels
  if (key === 'lightGray') App._basemapRef.addTo(App.map);
  App._activeBasemap = key;
  // Update button states
  document.querySelectorAll('.basemap-btn').forEach(function(b) { b.classList.remove('active'); });
  var btn = document.getElementById('btn-basemap-' + key);
  if (btn) btn.classList.add('active');
};

