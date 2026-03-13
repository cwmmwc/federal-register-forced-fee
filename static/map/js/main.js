// ═══════════════════════════════════════════════
// Init & Boot
// ═══════════════════════════════════════════════
App.init = async function() {
  App.initMap();
  await App.loadMetadata();
  App.initControls();
  document.getElementById('loading').classList.add('done');

  // Read URL parameters for deep-linking
  var params = new URLSearchParams(window.location.search);
  var tribe = params.get('tribe');
  var accession = params.get('accession');

  if (tribe) {
    var match = App.findTribe(tribe);
    if (match) {
      App.selectedTribes = [match];
      App.renderTribes();
      // If we have an accession, skip fitting bounds to tribe — zoom straight to parcel
      if (accession) {
        App._skipFitBounds = true;
      }
      await App.runAnalysis();
      if (accession) {
        await App.zoomToAccession(accession);
      }
    }
  }
};

// Expose globals for onclick handlers in HTML
window.runAnalysis = function() { return App.runAnalysis(); };
window.setTimePreset = function(start, end) { return App.setTimePreset(start, end); };
window.switchBasemap = function(key) { return App.switchBasemap(key); };

// Boot
App.init().catch(function(err) {
  console.error(err);
  document.getElementById('load-msg').textContent = 'Error: ' + err.message;
});
