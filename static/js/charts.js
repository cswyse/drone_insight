/* Lightweight SVG charts (no dependencies). Colours come from the theme (CSS variables), so they follow site.json.
   columns: market size with actual / estimate / forecast status
   lines:   multi-series lines with crosshair tooltip
   bars:    grouped vertical bars for categories (used in articles)
   hbars:   ranked horizontal bars (used in articles)
   renderAll(root): draws every .mi-chart block created from ```chart markdown blocks. */
window.MI = (function () {
  var NS = 'http://www.w3.org/2000/svg';
  var FALLBACK = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4'];
  var STATUS_LABEL = { A: 'Actual', E: 'Estimate', F: 'Forecast' };

  function cv(name, fb) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fb;
  }
  function palette() { return FALLBACK.map(function (f, i) { return cv('--series-' + (i + 1), f); }); }
  function statusColors() {
    return { A: cv('--chart-actual', '#051C2C'), E: cv('--chart-estimate', '#2251FF'), F: cv('--chart-forecast', '#9DB4FF') };
  }
  function ink() { return cv('--ink', '#1B2733'); }
  function muted() { return cv('--muted', '#566677'); }
  function grid() { return cv('--line', '#E4E9EF'); }

  var tip = document.createElement('div');
  tip.className = 'tip';
  tip.setAttribute('role', 'status');
  document.body.appendChild(tip);

  function showTip(html, x, y) {
    tip.innerHTML = html;
    tip.classList.add('on');
    var w = tip.offsetWidth, h = tip.offsetHeight;
    var nx = x + 14, ny = y - h - 10;
    if (nx + w > window.innerWidth - 8) nx = x - w - 14;
    if (ny < 8) ny = y + 16;
    tip.style.left = nx + 'px';
    tip.style.top = ny + 'px';
  }
  function hideTip() { tip.classList.remove('on'); }

  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }
  function el(name, attrs, parent) {
    var n = document.createElementNS(NS, name);
    for (var k in attrs) n.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(n);
    return n;
  }
  function niceMax(v) {
    if (v <= 0) return 1;
    var p = Math.pow(10, Math.floor(Math.log10(v))), n = v / p;
    var steps = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10], m = 10;
    for (var k = 0; k < steps.length; k++) { if (n <= steps[k]) { m = steps[k]; break; } }
    return m * p;
  }
  function fmt(v, dec) {
    return Number(v).toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });
  }
  function legendHTML(items) {
    return '<div class="legend">' + items.map(function (i) {
      return '<span><i style="background:' + i.color + '"></i>' + esc(i.label) + '</span>';
    }).join('') + '</div>';
  }
  function mount(container, legend, draw) {
    var host = typeof container === 'string' ? document.getElementById(container) : container;
    if (!host) return;
    function render() {
      host.innerHTML = (legend ? legend() : '') + '<div class="chart-wrap"></div>';
      var wrap = host.querySelector('.chart-wrap');
      draw(wrap, Math.max(280, wrap.clientWidth));
    }
    render();
    var t;
    window.addEventListener('resize', function () { clearTimeout(t); t = setTimeout(render, 150); });
  }
  function axisY(svg, m, W, ih, max, min, dec) {
    for (var i = 0; i <= 4; i++) {
      var v = min + (max - min) * i / 4, y = m.t + ih - ih * i / 4;
      el('line', { x1: m.l, x2: W - m.r, y1: y, y2: y, stroke: grid(), 'stroke-width': 1 }, svg);
      var t = el('text', { x: m.l - 8, y: y + 4, 'text-anchor': 'end', 'font-size': 11, fill: muted() }, svg);
      t.textContent = fmt(v, dec != null ? dec : (max < 10 ? 1 : 0));
    }
  }
  function roundedBar(svg, x, y, w, h, color) {
    var r = Math.min(3, w / 4);
    if (h < 1) h = 1;
    return el('path', { d: 'M' + x + ',' + (y + h) + 'V' + (y + r) + 'Q' + x + ',' + y + ' ' + (x + r) + ',' + y + 'H' + (x + w - r) +
      'Q' + (x + w) + ',' + y + ' ' + (x + w) + ',' + (y + r) + 'V' + (y + h) + 'Z', fill: color }, svg);
  }

  /* Columns: data = [{year, value, status}] */
  function columns(container, data, opt) {
    opt = opt || {};
    var dec = opt.dec == null ? 0 : opt.dec, unit = opt.unit || '';
    mount(container, function () {
      var S = statusColors();
      return legendHTML(['A', 'E', 'F'].filter(function (s) { return data.some(function (d) { return d.status === s; }); })
        .map(function (s) { return { color: S[s], label: STATUS_LABEL[s] }; }));
    }, function (wrap, W) {
      var S = statusColors();
      var H = opt.height || 280, m = { l: 48, r: 8, t: 16, b: 28 };
      var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'img', 'aria-label': opt.label || 'Column chart' }, wrap);
      var max = niceMax(Math.max.apply(null, data.map(function (d) { return d.value; })) * 1.05);
      var iw = W - m.l - m.r, ih = H - m.t - m.b;
      axisY(svg, m, W, ih, max, 0);
      var band = iw / data.length, bw = Math.min(34, band * 0.6);
      data.forEach(function (d, i) {
        var h = ih * d.value / max, x = m.l + band * i + (band - bw) / 2, y = m.t + ih - h;
        roundedBar(svg, x, y, bw, h, S[d.status]);
        var xl = el('text', { x: x + bw / 2, y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: muted() }, svg);
        xl.textContent = d.year;
        if (i === 0 || i === data.length - 1 || d.status === 'E') {
          var vl = el('text', { x: x + bw / 2, y: y - 6, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 600, fill: ink() }, svg);
          vl.textContent = fmt(d.value, dec);
        }
        var hit = el('rect', { x: m.l + band * i, y: m.t, width: band, height: ih, fill: 'transparent' }, svg);
        hit.addEventListener('mousemove', function (e) {
          showTip('<b>' + d.year + ' (' + STATUS_LABEL[d.status].toLowerCase() + ')</b>' + fmt(d.value, dec) + ' ' + esc(unit), e.clientX, e.clientY);
        });
        hit.addEventListener('mouseleave', hideTip);
      });
    });
  }

  /* Lines: years = category labels, series = [{name, values}] */
  function lines(container, years, series, opt) {
    opt = opt || {};
    var dec = opt.dec == null ? 0 : opt.dec, unit = opt.unit || '';
    function pal() { return series.length > 1 ? palette() : [cv('--chart-single', '#2251FF')]; }
    mount(container, function () {
      var P = pal();
      return series.length > 1 ? legendHTML(series.map(function (s, i) { return { color: P[i % P.length], label: s.name }; })) : '';
    }, function (wrap, W) {
      var PAL = pal();
      var H = opt.height || 280, m = { l: 52, r: 16, t: 14, b: 28 };
      var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'img', 'aria-label': opt.label || 'Line chart' }, wrap);
      var all = [].concat.apply([], series.map(function (s) { return s.values; }));
      var lo = opt.zero === false ? Math.min.apply(null, all) : 0, hi = Math.max.apply(null, all);
      if (opt.zero === false) { var pad = (hi - lo) * 0.2 || 1; lo = Math.max(0, lo - pad); hi += pad; }
      var max = opt.zero === false ? hi : niceMax(hi * 1.05), min = lo;
      var iw = W - m.l - m.r, ih = H - m.t - m.b;
      function X(i) { return m.l + iw * i / Math.max(1, years.length - 1); }
      function Y(v) { return m.t + ih - ih * (v - min) / (max - min || 1); }
      var fi = opt.forecastFrom ? years.indexOf(opt.forecastFrom) : -1;
      if (fi > 0) {
        el('rect', { x: X(fi - 0.5), y: m.t, width: W - m.r - X(fi - 0.5), height: ih, fill: cv('--soft', '#F3F5F8') }, svg);
        var fl = el('text', { x: W - m.r - 6, y: m.t + 14, 'text-anchor': 'end', 'font-size': 11, fill: muted() }, svg);
        fl.textContent = 'Forecast';
      }
      axisY(svg, m, W, ih, max, min, max < 10 ? 1 : opt.axisDec || 0);
      years.forEach(function (yr, i) {
        if (iw / years.length < 40 && i % 2 === 1) return;
        var xl = el('text', { x: X(i), y: H - 8, 'text-anchor': 'middle', 'font-size': 11, fill: muted() }, svg);
        xl.textContent = yr;
      });
      series.forEach(function (s, si) {
        var c = PAL[si % PAL.length];
        var d = s.values.map(function (v, i) { return (i ? 'L' : 'M') + X(i) + ',' + Y(v); }).join('');
        el('path', { d: d, fill: 'none', stroke: c, 'stroke-width': 2, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, svg);
        var last = s.values.length - 1;
        el('circle', { cx: X(last), cy: Y(s.values[last]), r: 4, fill: c, stroke: cv('--background', '#fff'), 'stroke-width': 2 }, svg);
      });
      var cross = el('line', { y1: m.t, y2: m.t + ih, stroke: muted(), 'stroke-width': 1, opacity: 0 }, svg);
      var dots = series.map(function (s, si) { return el('circle', { r: 4, fill: PAL[si % PAL.length], stroke: cv('--background', '#fff'), 'stroke-width': 2, opacity: 0 }, svg); });
      var hit = el('rect', { x: m.l, y: m.t, width: iw, height: ih, fill: 'transparent' }, svg);
      hit.addEventListener('mousemove', function (e) {
        var r = svg.getBoundingClientRect(), px = (e.clientX - r.left) * (W / r.width);
        var i = Math.max(0, Math.min(years.length - 1, Math.round((px - m.l) / iw * (years.length - 1))));
        cross.setAttribute('x1', X(i)); cross.setAttribute('x2', X(i)); cross.setAttribute('opacity', 1);
        var html = '<b>' + esc(years[i]) + '</b>';
        series.forEach(function (s, si) {
          dots[si].setAttribute('cx', X(i)); dots[si].setAttribute('cy', Y(s.values[i])); dots[si].setAttribute('opacity', 1);
          html += '<div><i style="background:' + PAL[si % PAL.length] + '"></i>' + (series.length > 1 ? esc(s.name) + ': ' : '') + fmt(s.values[i], dec) + ' ' + esc(unit) + '</div>';
        });
        showTip(html, e.clientX, e.clientY);
      });
      hit.addEventListener('mouseleave', function () {
        hideTip(); cross.setAttribute('opacity', 0); dots.forEach(function (d) { d.setAttribute('opacity', 0); });
      });
    });
  }

  /* Grouped vertical bars: cats = labels, series = [{name, values}] */
  function bars(container, cats, series, opt) {
    opt = opt || {};
    var dec = opt.dec == null ? 0 : opt.dec, unit = opt.unit || '';
    function pal() { return series.length > 1 ? palette() : [cv('--chart-single', '#2251FF')]; }
    mount(container, function () {
      var P = pal();
      return series.length > 1 ? legendHTML(series.map(function (s, i) { return { color: P[i % P.length], label: s.name }; })) : '';
    }, function (wrap, W) {
      var PAL = pal();
      var H = opt.height || 300, m = { l: 52, r: 10, t: 18, b: 40 };
      var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'img', 'aria-label': opt.label || 'Bar chart' }, wrap);
      var all = [].concat.apply([], series.map(function (s) { return s.values; }));
      var max = niceMax(Math.max.apply(null, all) * 1.05);
      var iw = W - m.l - m.r, ih = H - m.t - m.b;
      axisY(svg, m, W, ih, max, 0);
      var band = iw / cats.length, gap = 2, groupW = Math.min(band * 0.72, series.length * 44);
      var bw = (groupW - gap * (series.length - 1)) / series.length;
      var step = Math.ceil(cats.length * 62 / iw) || 1;
      var maxIdx = series[0].values.indexOf(Math.max.apply(null, series[0].values));
      cats.forEach(function (c, i) {
        var gx = m.l + band * i + (band - groupW) / 2;
        series.forEach(function (s, si) {
          var h = ih * s.values[i] / max, x = gx + si * (bw + gap), y = m.t + ih - h;
          roundedBar(svg, x, y, bw, h, PAL[si % PAL.length]);
          if (series.length === 1 && (i === 0 || i === cats.length - 1 || i === maxIdx)) {
            var vl = el('text', { x: x + bw / 2, y: y - 6, 'text-anchor': 'middle', 'font-size': 11, 'font-weight': 600, fill: ink() }, svg);
            vl.textContent = fmt(s.values[i], dec);
          }
        });
        if (i % step === 0) {
          var xl = el('text', { x: m.l + band * i + band / 2, y: H - 14, 'text-anchor': 'middle', 'font-size': 11, fill: muted() }, svg);
          xl.textContent = c.length > 14 ? c.slice(0, 13) + '…' : c;
        }
        var hit = el('rect', { x: m.l + band * i, y: m.t, width: band, height: ih, fill: 'transparent' }, svg);
        hit.addEventListener('mousemove', function (e) {
          var html = '<b>' + esc(c) + '</b>';
          series.forEach(function (s, si) {
            html += '<div><i style="background:' + PAL[si % PAL.length] + '"></i>' + (series.length > 1 ? esc(s.name) + ': ' : '') + fmt(s.values[i], dec) + ' ' + esc(unit) + '</div>';
          });
          showTip(html, e.clientX, e.clientY);
        });
        hit.addEventListener('mouseleave', hideTip);
      });
    });
  }

  /* Horizontal ranked bars (first series): direct value labels */
  function hbars(container, cats, series, opt) {
    opt = opt || {};
    var dec = opt.dec == null ? 0 : opt.dec, unit = opt.unit || '';
    var vals = series[0].values;
    mount(container, null, function (wrap, W) {
      var rowH = 34, m = { l: Math.min(W * 0.36, 190), r: 64, t: 4, b: 4 };
      var H = m.t + m.b + rowH * cats.length;
      var svg = el('svg', { viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'img', 'aria-label': opt.label || 'Ranked bar chart' }, wrap);
      var max = Math.max.apply(null, vals) || 1, iw = W - m.l - m.r, color = cv('--chart-single', '#2251FF');
      cats.forEach(function (c, i) {
        var y = m.t + rowH * i, bw = iw * vals[i] / max;
        var lab = el('text', { x: m.l - 10, y: y + rowH / 2 + 4, 'text-anchor': 'end', 'font-size': 12, fill: ink() }, svg);
        lab.textContent = c.length > 26 ? c.slice(0, 25) + '…' : c;
        el('rect', { x: m.l, y: y + 8, width: Math.max(1, bw), height: rowH - 16, fill: color, rx: Math.min(3, (rowH - 16) / 4) }, svg);
        var v = el('text', { x: m.l + bw + 8, y: y + rowH / 2 + 4, 'font-size': 12, 'font-weight': 600, fill: ink() }, svg);
        v.textContent = fmt(vals[i], dec);
        var hit = el('rect', { x: 0, y: y, width: W, height: rowH, fill: 'transparent' }, svg);
        hit.addEventListener('mousemove', function (e) { showTip('<b>' + esc(c) + '</b>' + fmt(vals[i], dec) + ' ' + esc(unit), e.clientX, e.clientY); });
        hit.addEventListener('mouseleave', hideTip);
      });
    });
  }

  function renderAll(root) {
    (root || document).querySelectorAll('.mi-chart:not([data-drawn])').forEach(function (node) {
      var spec;
      try { spec = JSON.parse(node.getAttribute('data-chart')); } catch (e) { return; }
      node.setAttribute('data-drawn', '1');
      var o = { unit: spec.unit, dec: spec.decimals, label: spec.title || 'Chart' };
      if (spec.type === 'line') lines(node, spec.categories, spec.series, o);
      else if (spec.type === 'hbar') hbars(node, spec.categories, spec.series, o);
      else bars(node, spec.categories, spec.series, o);
    });
  }

  return { columns: columns, lines: lines, bars: bars, hbars: hbars, renderAll: renderAll, palette: palette };
})();
