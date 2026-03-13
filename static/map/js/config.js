// ═══════════════════════════════════════════════
// Config & Shared State
// ═══════════════════════════════════════════════
window.App = {
  BASE: 'https://services2.arcgis.com/8k2PygHqghVevhzy/arcgis/rest/services/tribal_land_patents_aliquot_20240304/FeatureServer/0/query',
  FETCH_LIMIT: 25000,

  CATEGORIES: {
    fee: "(authority IN ('Indian Fee Patent','Indian Homestead Fee Patent','Indian Fee Patent (Heir)','Indian Trust to Fee','Indian Fee Patent-Misc.','Indian Fee Patent (Non-IRA)','Indian Fee Patent-Term or Non','Indian Fee Patent (IRA)') OR forced_fee = 'True')",
    // fee_authority: fee by authority only — for year-by-year chart where signature_date
    // reflects actual fee issuance, not trust patent date of forced conversions
    fee_authority: "authority IN ('Indian Fee Patent','Indian Homestead Fee Patent','Indian Fee Patent (Heir)','Indian Trust to Fee','Indian Fee Patent-Misc.','Indian Fee Patent (Non-IRA)','Indian Fee Patent-Term or Non','Indian Fee Patent (IRA)')",
    trust: "authority IN ('Indian Trust Patent','Indian Reissue Trust','Indian Homestead Trust','Indian Trust Patent (Wind R)','Indian Allotment - General','Indian Allotment-Wyandotte','Indian Allotment in Nat. Forest','Indian Partition') AND forced_fee = 'False'",
    forced: "forced_fee = 'True'",
    all: '1=1'
  },

  // Mutable state
  map: null,
  heatLayer: null,
  pointLayer: null,
  parcelLayer: null,
  currentData: [],
  tribeMap: {},
  stateMap: {},
  selectedTribes: [],
  analysisCache: {},
  lastZoom: null,

  // Timeline state
  timelineMode: false,
  timelineIndex: [],
  timelineYear: null,
  timelineInterval: null,

  // Classification mode: 'final' (default) or 'original' (show as originally issued)
  classifyMode: 'final',

  // Aliases for cross-linking from Federal Register app
  TRIBE_ALIASES: {
    'Pine Ridge (Oglala Sioux)': 'Oglala Lakota',
    'Flathead (Salish-Kootenai)': 'Flathead',
    'Coeur d\'Alene': 'Coeur D\'alene',
    'Fort Berthold': 'Mandan, Hidatsa, Arikara',
    'Cheyenne-Arapaho': 'Cheyenne Arapaho',
    'Sisseton-Wahpeton': 'Sisseton\u2013Wahpeton Oyate',
    'Yankton Sioux': 'Yaknton Sioux Tribe',
    'Devil\'s Lake Sioux': 'Devil\'s Lake Sioux',
    'Fort Peck Assiniboine and Sioux': 'Assiniboine And Sioux',
    'Fort Belknap': 'Assiniboine And Gros Ventre',
    'Shoshone-Bannock': 'Shoshone And Bannock',
    'Otoe-Missouria': 'Otoe And Missouria',
    'Sac and Fox': 'Sac And Fox',
    'Prairie Potawatomi': 'Prairie Band Of Potawatami Nation',
    'Citizen Band Potawatomi': 'Citizen Potawatomi',
    'Turtle Mountain Chippewa': 'Turtle Mountain Band Of Chippewa Indians'
  }
};

// Find a tribe by exact match, alias, or case-insensitive partial match
App.findTribe = function(name) {
  if (App.tribeMap[name]) return name;
  if (App.TRIBE_ALIASES[name] && App.tribeMap[App.TRIBE_ALIASES[name]]) {
    return App.TRIBE_ALIASES[name];
  }
  var lower = name.toLowerCase();
  var keys = Object.keys(App.tribeMap);
  for (var i = 0; i < keys.length; i++) {
    if (keys[i].toLowerCase() === lower) return keys[i];
  }
  for (var i = 0; i < keys.length; i++) {
    if (keys[i].toLowerCase().indexOf(lower) !== -1) return keys[i];
  }
  return null;
};
