/**
 * Lokamania 10 — Google Sheet sync (Apps Script web app).
 *
 * The website server sends every new or changed application here. This script
 * keeps these tabs up to date:
 *   Dashboard            totals by status, space, days and category (formulas)
 *   Applications         one row per application
 *   one tab per category the same rows, filtered by main category
 * All three kinds of tab are protected: the team can view, filter (Data ->
 * Filter views) and add their own tabs, but cannot type over the mirrored data.
 *
 * Setup: paste this file into Extensions -> Apps Script, set SECRET below to the
 * code you were given, then Deploy -> New deployment -> Web app,
 * Execute as: Me, Who has access: Anyone.
 */

const SECRET = 'PASTE-THE-SECRET-CODE-HERE';

const APPS_TAB = 'Applications';
const DASH_TAB = 'Dashboard';
const CATEGORIES = ['Fashion—Clothing', 'Beauty', 'Fashion Accessories', 'Home & Lifestyle',
                    'Food & Beverages', 'Art & Stationery', 'Other'];
const STATUSES = ['New', 'Under Review', 'Contacted', 'Accepted', 'Waitlisted', 'Rejected',
                  'Payment Pending', 'Confirmed'];
const SPACES = ['The Kiosk (1.5 m × 70 cm)', 'The Booth (80 cm length × 1.5 m width)',
                'The Mega Cube (4 m width × 3 m length)', 'The Flagship (7 m width × 2.5 m length)'];
const DAYS = ['Day 1 only (Nov 26)', 'Day 2 only (Nov 27)', 'Day 3 only (Nov 28)',
              'Days 1 & 2 (Nov 26–27)', 'Days 2 & 3 (Nov 27–28)', 'All 3 days (Nov 26–28)'];

function doGet() {
  return reply_({ ok: true, alive: true });
}

function doPost(e) {
  let body;
  try {
    body = JSON.parse(e.postData.contents);
  } catch (err) {
    return reply_({ ok: false, error: 'bad request' });
  }
  if (!body || body.secret !== SECRET) return reply_({ ok: false, error: 'unauthorized' });

  const lock = LockService.getScriptLock();
  lock.waitLock(30000);
  try {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const headers = body.headers;
    const sheet = ensureAppsTab_(ss, headers);
    let result;
    if (body.action === 'replace_all') result = replaceAll_(sheet, headers, body.rows || []);
    else if (body.action === 'upsert') result = upsert_(sheet, headers, body.rows || []);
    else if (body.action === 'delete') result = removeRows_(sheet, body.references || []);
    else return reply_({ ok: false, error: 'unknown action' });

    rebuildCategoryTabs_(ss, sheet, headers);
    ensureDashboard_(ss, headers);
    ss.getSheetByName(DASH_TAB).getRange('B3').setValue(new Date());
    SpreadsheetApp.flush();
    return reply_(Object.assign({ ok: true }, result));
  } catch (err) {
    return reply_({ ok: false, error: String(err && err.message || err) });
  } finally {
    lock.releaseLock();
  }
}

// ------------------------------------------------------------------ writing
function clean_(row) {
  // Text only, and never let a cell start a formula.
  return row.map(function (v) {
    v = v === null || v === undefined ? '' : String(v);
    return /^[=+\-@]/.test(v) ? "'" + v : v;
  });
}

function replaceAll_(sheet, headers, rows) {
  const width = headers.length;
  const last = sheet.getLastRow();
  if (last > 1) sheet.getRange(2, 1, last - 1, Math.max(width, sheet.getLastColumn())).clearContent();
  if (rows.length) {
    const range = sheet.getRange(2, 1, rows.length, width);
    range.setNumberFormat('@');
    range.setValues(rows.map(clean_));
  }
  return { rows: rows.length };
}

function upsert_(sheet, headers, rows) {
  const width = headers.length;
  const last = sheet.getLastRow();
  const refs = last > 1 ? sheet.getRange(2, 1, last - 1, 1).getValues().map(function (r) { return String(r[0]); }) : [];
  const index = {};
  refs.forEach(function (ref, i) { index[ref] = i + 2; });
  let added = 0, updated = 0, next = last + 1;
  rows.forEach(function (row) {
    const at = index[String(row[0])];
    const target = at || next++;
    const range = sheet.getRange(target, 1, 1, width);
    range.setNumberFormat('@');
    range.setValues([clean_(row)]);
    if (at) updated++; else { added++; index[String(row[0])] = target; }
  });
  return { added: added, updated: updated };
}

function removeRows_(sheet, references) {
  const want = {};
  references.forEach(function (r) { want[String(r)] = true; });
  const last = sheet.getLastRow();
  if (last < 2) return { deleted: 0 };
  const refs = sheet.getRange(2, 1, last - 1, 1).getValues();
  let deleted = 0;
  for (let i = refs.length - 1; i >= 0; i--) {
    if (want[String(refs[i][0])]) { sheet.deleteRow(i + 2); deleted++; }
  }
  return { deleted: deleted };
}

// --------------------------------------------------------------------- tabs
function ensureAppsTab_(ss, headers) {
  let sheet = ss.getSheetByName(APPS_TAB);
  if (!sheet) {
    sheet = ss.insertSheet(APPS_TAB);
    // Remove the empty default tab of a new spreadsheet.
    ['Sheet1', 'Feuille 1', 'Hoja 1'].forEach(function (n) {
      const s = ss.getSheetByName(n);
      if (s && s.getLastRow() === 0 && ss.getSheets().length > 1) ss.deleteSheet(s);
    });
  }
  writeHeader_(sheet, headers);
  protect_(sheet, 'Mirrored from the Lokamania 10 website. Edit applications in the admin page.');
  return sheet;
}

function writeHeader_(sheet, headers) {
  const range = sheet.getRange(1, 1, 1, headers.length);
  const current = range.getValues()[0].join('\u0001');
  if (current !== headers.join('\u0001')) {
    range.setValues([headers]);
    range.setFontWeight('bold').setBackground('#111111').setFontColor('#f6ead0');
    sheet.setFrozenRows(1);
    sheet.setFrozenColumns(1);
  }
}

function rebuildCategoryTabs_(ss, appsSheet, headers) {
  const width = headers.length;
  const catCol = headers.indexOf('Main Category');
  const last = appsSheet.getLastRow();
  const data = last > 1 ? appsSheet.getRange(2, 1, last - 1, width).getValues() : [];
  CATEGORIES.forEach(function (cat) {
    let tab = ss.getSheetByName(cat);
    if (!tab) tab = ss.insertSheet(cat);
    writeHeader_(tab, headers);
    protect_(tab, 'Mirrored from the Lokamania 10 website (' + cat + ' only).');
    const rows = data.filter(function (r) { return String(r[catCol]) === cat; });
    const tLast = tab.getLastRow();
    if (tLast > 1) tab.getRange(2, 1, tLast - 1, Math.max(width, tab.getLastColumn())).clearContent();
    if (rows.length) {
      const range = tab.getRange(2, 1, rows.length, width);
      range.setNumberFormat('@');
      range.setValues(rows.map(clean_));
    }
  });
}

function colLetter_(index0) {
  let n = index0 + 1, s = '';
  while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = Math.floor((n - 1) / 26); }
  return s;
}

function ensureDashboard_(ss, headers) {
  let dash = ss.getSheetByName(DASH_TAB);
  if (dash && dash.getRange('A1').getValue() === 'Lokamania 10 — Dashboard') return;
  if (!dash) dash = ss.insertSheet(DASH_TAB, 0);
  dash.clear();
  const col = function (name) { return APPS_TAB + '!' + colLetter_(headers.indexOf(name)) + ':' + colLetter_(headers.indexOf(name)); };
  const rows = [
    ['Lokamania 10 — Dashboard', ''],
    ['Total applications', '=COUNTA(' + APPS_TAB + '!A2:A)'],
    ['Last synced from the website', ''],
    ['', ''],
  ];
  function section(title, list, column) {
    rows.push([title, 'Applications']);
    list.forEach(function (v) { rows.push([v, '=COUNTIF(' + col(column) + ',"' + v.replace(/"/g, '""') + '")']); });
    rows.push(['', '']);
  }
  section('By space', SPACES, 'Space');
  section('By days', DAYS, 'Participation Days');
  section('By category', CATEGORIES, 'Main Category');
  section('By status', STATUSES, 'Application Status');
  dash.getRange(1, 1, rows.length, 2).setValues(rows);
  dash.getRange('A1').setFontSize(16).setFontWeight('bold');
  dash.getRange('B3').setNumberFormat('yyyy-mm-dd hh:mm');
  for (let r = 1; r <= rows.length; r++) {
    if (['By space', 'By days', 'By category', 'By status'].indexOf(rows[r - 1][0]) > -1) {
      dash.getRange(r, 1, 1, 2).setFontWeight('bold').setBackground('#111111').setFontColor('#f6ead0');
    }
  }
  dash.setColumnWidth(1, 320);
  dash.setColumnWidth(2, 140);
  ss.setActiveSheet(dash);
  ss.moveActiveSheet(1);
  protect_(dash, 'Lokamania 10 dashboard (formulas).');
}

function protect_(sheet, note) {
  if (sheet.getProtections(SpreadsheetApp.ProtectionType.SHEET).length) return;
  const p = sheet.protect().setDescription(note);
  p.addEditor(Session.getEffectiveUser());
  p.removeEditors(p.getEditors());
  if (p.canDomainEdit()) p.setDomainEdit(false);
}

function reply_(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
