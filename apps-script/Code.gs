/**
 * STAY DRIVEN — YouTube token helper (Apps Script)
 *
 * Kaj: GitHub e video toiri hoye gele GitHub ei script ke jiggesh kore
 * "YouTube e upload korar chabi (token) dao". Script ta Stay Driven channel er
 * nijer Google account e chole, tai upload ta channel er nijer kora hishebe jay
 * (RelPulse e jevabe YouTube upload hoy, same niyom).
 *
 * Setup: guide er Step 5 dekhun. Ekbar "setup" function Run korun, tarpor
 * Deploy > New deployment > Web app.
 */

function doGet(e) {
  var secret = PropertiesService.getScriptProperties().getProperty('SECRET');
  var key = e && e.parameter ? e.parameter.key : '';
  if (!secret || key !== secret) {
    return json_({ ok: false, error: 'wrong key' });
  }
  return json_({ ok: true, token: ScriptApp.getOAuthToken(), channel: channelName_() });
}

/** EKBAR Run korun. Log e je SECRET ashbe seta GitHub secret SD_TOKEN_SECRET e boshaben. */
function setup() {
  var props = PropertiesService.getScriptProperties();
  var s = props.getProperty('SECRET');
  if (!s) {
    s = Utilities.getUuid().replace(/-/g, '') + Utilities.getUuid().replace(/-/g, '');
    props.setProperty('SECRET', s);
  }
  Logger.log('SD_TOKEN_SECRET = ' + s);
  Logger.log('YouTube channel = ' + channelName_());
}

/** Kono karone SECRET bodlate chaile eta Run korun, tarpor GitHub e notun ta boshan. */
function newSecret() {
  PropertiesService.getScriptProperties().deleteProperty('SECRET');
  setup();
}

function channelName_() {
  try {
    var r = UrlFetchApp.fetch('https://www.googleapis.com/youtube/v3/channels?part=snippet&mine=true', {
      headers: { Authorization: 'Bearer ' + ScriptApp.getOAuthToken() },
      muteHttpExceptions: true
    });
    var d = JSON.parse(r.getContentText());
    return d.items && d.items.length ? d.items[0].snippet.title : 'NO CHANNEL FOUND';
  } catch (err) {
    return 'error: ' + err;
  }
}

function json_(o) {
  return ContentService.createTextOutput(JSON.stringify(o)).setMimeType(ContentService.MimeType.JSON);
}
