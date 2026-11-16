(function () {
  // Mobile nav
  var t = document.getElementById('navToggle'), n = document.getElementById('nav');
  if (t && n) t.addEventListener('click', function () {
    var open = n.classList.toggle('open');
    t.setAttribute('aria-expanded', open ? 'true' : 'false');
  });

  function json(id) {
    var e = document.getElementById(id);
    return e ? JSON.parse(e.textContent) : null;
  }

  // Charts from embedded JSON
  var bars = json('data-bars');
  if (bars) MI.columns('chart-bars', bars.data, { unit: bars.unit, dec: bars.dec, label: bars.label });

  var lines = json('data-lines');
  if (lines && lines.series.length) MI.lines('chart-lines', lines.years, lines.series,
    { unit: lines.unit, dec: lines.dec, forecastFrom: lines.forecastFrom, label: lines.label });

  var rev = json('data-rev');
  if (rev) MI.columns('chart-rev', rev.data, { unit: 'US$ m', dec: 0, label: 'Revenue' });

  var mar = json('data-margin');
  if (mar) MI.lines('chart-margin', mar.years, [{ name: 'EBITDA margin', values: mar.values }],
    { unit: '%', dec: 1, zero: false, axisDec: 1, label: 'EBITDA margin' });

  // Charts embedded in articles (```chart blocks)
  MI.renderAll(document);

  // Clickable table rows
  document.querySelectorAll('tr.click[data-href]').forEach(function (tr) {
    tr.addEventListener('click', function (e) {
      if (e.target.closest('a')) return;
      window.location = tr.getAttribute('data-href');
    });
  });

  // Auto-submit filters
  document.querySelectorAll('form[data-auto] select').forEach(function (s) {
    s.addEventListener('change', function () { s.form.submit(); });
  });

  // Print buttons
  document.querySelectorAll('[data-print]').forEach(function (b) {
    b.addEventListener('click', function () { window.print(); });
  });
})();
