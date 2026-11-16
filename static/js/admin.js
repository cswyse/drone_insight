/* Admin: article editor (image upload, chart snippets, preview) and the settings live preview. */
(function () {
  function $(s, r) { return (r || document).querySelector(s); }
  function $$(s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); }
  var csrfEl = $('input[name=_csrf]');
  var csrf = csrfEl ? csrfEl.value : '';

  /* ---------------- Editor ---------------- */
  var form = $('#editor-form');
  if (form) {
    var body = $('#body'), status = $('#upload-status');
    var snippets = JSON.parse($('#snippets').textContent);

    function insertAtCursor(text) {
      var s = body.selectionStart, e = body.selectionEnd, v = body.value;
      var pre = v.slice(0, s), post = v.slice(e);
      if (pre && !/\n\n$/.test(pre)) pre += pre.endsWith('\n') ? '\n' : '\n\n';
      body.value = pre + text + (post.startsWith('\n') ? '' : '\n') + post;
      var pos = (pre + text).length;
      body.focus(); body.setSelectionRange(pos, pos);
    }
    function upload(file, done) {
      status.textContent = 'Uploading…';
      var fd = new FormData(); fd.append('file', file);
      fetch(form.dataset.uploadUrl, { method: 'POST', body: fd, headers: { 'X-CSRF-Token': csrf } })
        .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
        .then(function (res) {
          if (!res.ok) { status.textContent = res.j.error || 'Upload failed.'; return; }
          status.textContent = 'Uploaded.'; done(res.j.url);
        })
        .catch(function () { status.textContent = 'Upload failed. Check your connection and try again.'; });
    }

    $('#btn-image').addEventListener('click', function () { $('#file-body').click(); });
    $('#file-body').addEventListener('change', function (e) {
      var f = e.target.files[0]; if (!f) return;
      upload(f, function (url) { insertAtCursor('![Describe the image](' + url + ' "Caption")'); });
      e.target.value = '';
    });
    $('#btn-cover').addEventListener('click', function () { $('#file-cover').click(); });
    $('#file-cover').addEventListener('change', function (e) {
      var f = e.target.files[0]; if (!f) return;
      upload(f, function (url) { $('#cover').value = url; });
      e.target.value = '';
    });
    $$('[data-snippet]').forEach(function (b) {
      b.addEventListener('click', function () { insertAtCursor(snippets[b.dataset.snippet].trim()); });
    });

    var pane = $('#preview-pane'), pbtn = $('#btn-preview');
    pbtn.addEventListener('click', function () {
      if (!pane.hidden) { pane.hidden = true; pbtn.textContent = 'Preview'; return; }
      var fd = new FormData(); fd.append('body', body.value);
      fetch(form.dataset.previewUrl, { method: 'POST', body: fd, headers: { 'X-CSRF-Token': csrf } })
        .then(function (r) { return r.text(); })
        .then(function (html) {
          pane.innerHTML = html || '<p class="muted">Nothing to preview yet.</p>';
          pane.hidden = false; pbtn.textContent = 'Hide preview';
          if (window.MI) MI.renderAll(pane);
          pane.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
    });
  }

  /* ---------------- Settings ---------------- */
  var sform = $('#settings-form');
  if (sform) {
    var live = $('#live');
    function lum(hex) {
      var h = hex.replace('#', ''); if (h.length !== 6) return 1;
      var c = [0, 2, 4].map(function (i) { var v = parseInt(h.substr(i, 2), 16) / 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
      return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    }
    function onColor(hex) { return lum(hex) < 0.35 ? '#FFFFFF' : '#0B1620'; }
    var VARS = { primary: '--primary', accent: '--accent', highlight: '--highlight', ink: '--ink', muted: '--muted', line: '--line', soft: '--soft', background: '--background', positive: '--pos', negative: '--neg' };
    function validHex(v) { return /^#[0-9a-fA-F]{6}$/.test(v); }

    function applyLive() {
      $$('input[data-var]').forEach(function (inp) {
        var k = inp.dataset.var, v = inp.value.trim();
        if (VARS[k]) { if (validHex(v)) live.style.setProperty(VARS[k], v); }
        else if (k === 'serif' || k === 'sans') live.style.setProperty('--' + k, v);
      });
      $$('select[data-var]').forEach(function (s) { live.style.setProperty('--' + s.dataset.var, s.value); });
      var p = $('#color_primary').value, a = $('#color_accent').value;
      if (validHex(p)) live.style.setProperty('--on-primary', onColor(p));
      if (validHex(a)) live.style.setProperty('--on-accent', onColor(a));
    }
    $$('input[type=color]').forEach(function (pick) {
      var txt = document.getElementById(pick.dataset.for);
      pick.addEventListener('input', function () { txt.value = pick.value.toUpperCase(); applyLive(); });
      txt.addEventListener('input', function () { if (validHex(txt.value.trim())) pick.value = txt.value.trim(); applyLive(); });
    });
    $$('#settings-form input[data-var], #settings-form select[data-var]').forEach(function (el) {
      el.addEventListener('input', applyLive); el.addEventListener('change', applyLive);
    });
    $$('.preset').forEach(function (b) {
      b.addEventListener('click', function () {
        var p = JSON.parse(b.dataset.preset);
        Object.keys(p).forEach(function (k) {
          var t = document.getElementById('color_' + k); if (!t) return;
          t.value = p[k];
          var pick = $('input[type=color][data-for="color_' + k + '"]'); if (pick) pick.value = p[k];
        });
        applyLive();
      });
    });
    var nameInp = $('#name');
    nameInp.addEventListener('input', function () { $('.live-name', live).textContent = nameInp.value; });
    applyLive();
  }
})();
