// ═══════════════════════════════════════════════
// Utilities
// ═══════════════════════════════════════════════
App.haversine = function(lat1, lon1, lat2, lon2) {
  var R = 6371;
  var dLat = (lat2 - lat1) * Math.PI / 180;
  var dLon = (lon2 - lon1) * Math.PI / 180;
  var a = Math.sin(dLat/2) * Math.sin(dLat/2) +
    Math.cos(lat1 * Math.PI/180) * Math.cos(lat2 * Math.PI/180) *
    Math.sin(dLon/2) * Math.sin(dLon/2);
  return R * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
};

App.median = function(arr) {
  var s = arr.slice().sort(function(a, b) { return a - b; });
  var mid = Math.floor(s.length / 2);
  return s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2;
};

App.setLoad = function(pct, msg) {
  document.getElementById('load-fill').style.width = pct + '%';
  document.getElementById('load-msg').textContent = msg;
};

// Returns 'fee', 'trust', or 'other'.
// forced_fee='True' overrides authority — the land left trust regardless of patent type.
App.classifyPatent = function(authority, forced_fee) {
  if (forced_fee === 'True') return 'fee';
  if (!authority) return 'other';
  if (authority.includes('Fee')) return 'fee';
  if (authority.includes('Trust') || authority.includes('Reissue')) return 'trust';
  if (authority.includes('Allotment') || authority.includes('Partition')) return 'trust';
  return 'other';
};

// Classify by original issuance — forced-fee patents show as trust (what they were when issued).
App.classifyPatentOriginal = function(authority) {
  if (!authority) return 'other';
  if (authority.includes('Fee')) return 'fee';
  if (authority.includes('Trust') || authority.includes('Reissue')) return 'trust';
  if (authority.includes('Allotment') || authority.includes('Partition')) return 'trust';
  return 'other';
};
