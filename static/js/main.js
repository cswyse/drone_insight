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

  function initCharts() {
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

  }
  initCharts();

  // Charts embedded in articles (```chart blocks)
  MI.renderAll(document);

  // Dashboard: search, sort and paginate the breakdown table (in the browser)
  function initTable() {
    var tbl = document.querySelector('table.sortable');
    if (!tbl) return;
    var card = tbl.closest('.card'), body = tbl.tBodies[0];
    var all = Array.prototype.slice.call(body.rows);
    var per = parseInt(tbl.getAttribute('data-per'), 10) || 25;
    var search = card.querySelector('.tbl-search'), count = card.querySelector('.tbl-count');
    var pager = card.querySelector('.tbl-pager'), none = card.querySelector('.tbl-none');
    var heads = tbl.tHead.rows[0].cells;
    var state = { q: '', col: -1, dir: 1, page: 1 };
    var reset = card.querySelector('.tbl-reset');
    var hasFilters = reset && reset.getAttribute('data-active') === '1';

    function val(tr, i) {
      var v = tr.cells[i].getAttribute('data-v');
      return (v === null || v === '') ? null : v;
    }
    function view() {
      var q = state.q.trim().toLowerCase();
      var rows = q ? all.filter(function (r) { return r.getAttribute('data-q').indexOf(q) > -1; }) : all.slice();
      if (state.col > -1) {
        var num = heads[state.col].getAttribute('data-sort') === 'num', i = state.col, d = state.dir;
        rows.sort(function (a, b) {
          var x = val(a, i), y = val(b, i);
          if (x === null && y === null) return 0;
          if (x === null) return 1;          // blanks always last
          if (y === null) return -1;
          if (num) return (parseFloat(x) - parseFloat(y)) * d;
          return x.localeCompare(y, undefined, { sensitivity: 'base', numeric: true }) * d;
        });
      }
      return rows;
    }
    function render() {
      var rows = view(), pages = Math.max(1, Math.ceil(rows.length / per));
      if (state.page > pages) state.page = pages;
      var start = (state.page - 1) * per, show = rows.slice(start, start + per);
      all.forEach(function (r) { r.hidden = true; });
      show.forEach(function (r) { r.hidden = false; body.appendChild(r); });
      if (none) none.hidden = rows.length > 0;
      tbl.hidden = rows.length === 0;
      if (count) count.textContent = rows.length === all.length
        ? all.length.toLocaleString() + ' total'
        : rows.length.toLocaleString() + ' of ' + all.length.toLocaleString();
      if (pager) {
        pager.hidden = pages < 2;
        pager.querySelector('.where').textContent = 'Page ' + state.page + ' of ' + pages;
        pager.querySelector('.tp-prev').classList.toggle('off', state.page <= 1);
        pager.querySelector('.tp-next').classList.toggle('off', state.page >= pages);
      }
      if (reset) reset.hidden = !(hasFilters || state.q || state.col > -1);
      for (var i = 0; i < heads.length; i++)
        heads[i].setAttribute('aria-sort', i === state.col ? (state.dir > 0 ? 'ascending' : 'descending') : 'none');
    }
    for (var i = 0; i < heads.length; i++) (function (i) {
      var h = heads[i];
      h.tabIndex = 0; h.setAttribute('role', 'columnheader');
      function sort() {
        if (state.col === i) state.dir = -state.dir;
        else { state.col = i; state.dir = h.getAttribute('data-sort') === 'num' ? -1 : 1; }
        state.page = 1; render();
      }
      h.addEventListener('click', sort);
      h.addEventListener('keydown', function (e) { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); sort(); } });
    })(i);
    if (reset) reset.addEventListener('click', function (e) {
      state.q = ''; state.col = -1; state.dir = 1; state.page = 1;
      if (search) search.value = '';
      render();
      if (!hasFilters) e.preventDefault();   // nothing to clear on the server: stay on the page
    });
    if (search) search.addEventListener('input', function () { state.q = search.value; state.page = 1; render(); });
    if (pager) pager.addEventListener('click', function (e) {
      var a = e.target.closest('a'); if (!a) return;
      e.preventDefault();
      if (a.classList.contains('off')) return;
      state.page += a.classList.contains('tp-next') ? 1 : -1;
      render();
      card.scrollIntoView({ block: 'nearest' });
    });
    render();
  }
  initTable();

  // Dashboard: drill down without reloading, so the page stays where it is
  var root = document.getElementById('dash-root');
  function dashHref(u) {
    try { var x = new URL(u, location.href); return x.origin === location.origin && x.pathname === location.pathname ? x.href : null; }
    catch (e) { return null; }
  }
  function swap(url, push) {
    var card = document.getElementById('breakdown');
    var before = card ? card.getBoundingClientRect().top : null;
    return fetch(url, { headers: { 'X-Requested-With': 'fetch' }, credentials: 'same-origin' })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.text(); })
      .then(function (html) {
        var doc = new DOMParser().parseFromString(html, 'text/html');
        var fresh = doc.getElementById('dash-root');
        if (!fresh) throw new Error('no dashboard');
        root.innerHTML = fresh.innerHTML;
        document.title = doc.title;
        if (push) history.pushState({ dash: 1 }, '', url);
        initCharts(); initTable();
        var nc = document.getElementById('breakdown');
        if (before !== null && nc) window.scrollBy(0, nc.getBoundingClientRect().top - before);
      })
      .catch(function () { location.href = url; });
  }
  if (root) {
    history.replaceState({ dash: 1 }, '');
    window.addEventListener('popstate', function (e) { if (e.state && e.state.dash) swap(location.href, false); });
  }

  // Clickable table rows (and in-dashboard links)
  document.addEventListener('click', function (e) {
    if (e.defaultPrevented || e.button || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    var a = e.target.closest('a'), tr = e.target.closest('tr.click[data-href]');
    var href = a ? a.getAttribute('href') : (tr ? tr.getAttribute('data-href') : null);
    if (!href) return;
    if (root && root.contains(e.target) && !(a && a.target) && dashHref(href) && href.indexOf('#') !== 0) {
      e.preventDefault(); swap(dashHref(href), true); return;
    }
    if (!a && tr) window.location = href;
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
