/* Hero: a dotted 3D globe with connections that draw across it, travel, and fade out.
   No countries or labels. Colours come from the theme (CSS variables), so it follows site.json. */
(function () {
  var canvas = document.getElementById('hero-canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

  function rgbVar(name, fb) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim().split(',').map(Number);
    return v.length === 3 && !v.some(isNaN) ? v : fb;
  }
  var C = {};
  function readColors() {
    C.accent = rgbVar('--accent-rgb', [34, 81, 255]);
    C.hl = rgbVar('--highlight-rgb', [0, 169, 244]);
    C.on = rgbVar('--on-primary-rgb', [255, 255, 255]);
    C.bg = rgbVar('--primary-rgb', [5, 28, 44]);
  }
  function rgba(c, a) { return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + a + ')'; }
  function mixc(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t].map(Math.round); }
  function smooth(a, b, x) { var t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); }
  function easeOut(t) { return 1 - Math.pow(1 - t, 3); }
  function easeIn(t) { return t * t * t; }

  // Deterministic random so the globe looks the same on every load
  function mulberry(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; var t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  var rnd = mulberry(11);

  var W, H, R, DPR, cx, cy;
  var yaw = 0.5, tilt = 0.32, targetTilt = 0.32, vel = 0.0016, dragVel = 0, drag = false, lastX = 0, lastT = 0;

  // Surface dots (Fibonacci lattice)
  var dots = [], N = 2800, ga = Math.PI * (3 - Math.sqrt(5));
  for (var i = 0; i < N; i++) {
    var y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = ga * i;
    dots.push([Math.cos(th) * r, y, Math.sin(th) * r]);
  }
  // Connection points scattered over the sphere
  var nodes = [];
  for (var n = 0; n < 48; n++) {
    var z = 2 * rnd() - 1, ph = 2 * Math.PI * rnd(), rr = Math.sqrt(1 - z * z);
    nodes.push([rr * Math.cos(ph), z, rr * Math.sin(ph)]);
  }
  function angle(a, b) { return Math.acos(Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))); }

  var arcs = [], TARGET = 9;
  function spawn(now, startP) {
    for (var tries = 0; tries < 30; tries++) {
      var a = Math.floor(rnd() * nodes.length), b = Math.floor(rnd() * nodes.length);
      if (a === b) continue;
      var ang = angle(nodes[a], nodes[b]);
      if (ang < 0.55 || ang > 1.95) continue;
      var dur = 2600 + rnd() * 2400;
      arcs.push({ a: nodes[a], b: nodes[b], born: now - (startP || 0) * dur, dur: dur, lift: 0.1 + 0.22 * ang / Math.PI });
      return;
    }
  }

  function rot(p) {
    var cy_ = Math.cos(yaw), sy = Math.sin(yaw), ct = Math.cos(tilt), st = Math.sin(tilt);
    var x = p[0] * cy_ + p[2] * sy, z = -p[0] * sy + p[2] * cy_, y = p[1];
    return [x, y * ct - z * st, y * st + z * ct];
  }
  function proj(p) {
    var q = rot(p), k = 3.6 / (3.6 - q[2]);
    return { x: cx + q[0] * R * k, y: cy - q[1] * R * k, z: q[2], k: k };
  }
  function arcPoint(a, b, t, lift) {
    var v = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
    var l = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) || 1, h = 1 + lift * Math.sin(Math.PI * t);
    return [v[0] / l * h, v[1] / l * h, v[2] / l * h];
  }

  function resize() {
    var b = canvas.getBoundingClientRect();
    DPR = Math.min(2, window.devicePixelRatio || 1);
    W = b.width; H = b.height;
    canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR);
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    R = Math.min(W, H) * 0.31; cx = W / 2; cy = H / 2;
  }

  var LIGHT = [-0.45, 0.55, 0.7];
  function draw(now) {
    ctx.clearRect(0, 0, W, H);
    ctx.globalCompositeOperation = 'source-over';

    // soft atmosphere behind the globe
    var g = ctx.createRadialGradient(cx, cy, R * 0.7, cx, cy, R * 1.6);
    g.addColorStop(0, rgba(C.accent, 0.28)); g.addColorStop(0.55, rgba(C.accent, 0.07)); g.addColorStop(1, rgba(C.accent, 0));
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);

    // globe body
    var body = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R * 1.05);
    body.addColorStop(0, rgba(mixc(C.bg, C.accent, 0.35), 0.95)); body.addColorStop(1, rgba(mixc(C.bg, [0, 0, 0], 0.25), 0.95));
    ctx.beginPath(); ctx.arc(cx, cy, R * 1.005, 0, 6.2832); ctx.fillStyle = body; ctx.fill();

    // dots
    var bright = mixc(C.on, C.hl, 0.35), mid = mixc(C.hl, C.accent, 0.5);
    for (var i = 0; i < dots.length; i++) {
      var q = rot(dots[i]);
      if (q[2] < -0.08) continue;
      var k = 3.6 / (3.6 - q[2]);
      var lit = Math.max(0, q[0] * LIGHT[0] + q[1] * LIGHT[1] + q[2] * LIGHT[2]);
      var edge = smooth(-0.08, 0.3, q[2]);
      ctx.globalAlpha = (0.12 + 0.75 * lit) * edge;
      ctx.fillStyle = rgba(lit > 0.55 ? bright : mid, 1);
      var s = (0.8 + 1.0 * lit) * k;
      ctx.fillRect(cx + q[0] * R * k - s / 2, cy - q[1] * R * k - s / 2, s, s);
    }
    ctx.globalAlpha = 1;

    // rim
    ctx.beginPath(); ctx.arc(cx, cy, R * 1.005, 0, 6.2832);
    ctx.strokeStyle = rgba(C.hl, 0.35); ctx.lineWidth = 1; ctx.stroke();

    // connections
    ctx.globalCompositeOperation = 'lighter';
    ctx.lineCap = 'round';
    for (var ai = arcs.length - 1; ai >= 0; ai--) {
      var a = arcs[ai], p = (now - a.born) / a.dur;
      if (p >= 1) { arcs.splice(ai, 1); continue; }
      var head = easeOut(Math.min(1, p / 0.68)), tail = easeIn(Math.max(0, (p - 0.32) / 0.68));
      var fade = p > 0.88 ? (1 - p) / 0.12 : 1;
      if (head - tail > 0.002) {
        var prev = null, steps = 40;
        for (var s2 = 0; s2 <= steps; s2++) {
          var u = tail + (head - tail) * s2 / steps, pt = proj(arcPoint(a.a, a.b, u, a.lift));
          if (prev) {
            var f = s2 / steps, vis = smooth(-0.3, 0.18, Math.min(prev.z, pt.z));
            ctx.strokeStyle = rgba(C.hl, vis * (0.1 + 0.9 * f) * fade);
            ctx.lineWidth = (0.8 + 1.6 * f) * pt.k;
            ctx.beginPath(); ctx.moveTo(prev.x, prev.y); ctx.lineTo(pt.x, pt.y); ctx.stroke();
          }
          prev = pt;
        }
        if (prev && p < 0.8) {
          var hv = smooth(-0.3, 0.18, prev.z) * fade;
          var hg = ctx.createRadialGradient(prev.x, prev.y, 0, prev.x, prev.y, 9 * prev.k);
          hg.addColorStop(0, rgba(C.on, 0.95 * hv)); hg.addColorStop(0.35, rgba(C.hl, 0.5 * hv)); hg.addColorStop(1, rgba(C.hl, 0));
          ctx.fillStyle = hg; ctx.beginPath(); ctx.arc(prev.x, prev.y, 9 * prev.k, 0, 6.2832); ctx.fill();
        }
      }
      // ripples where the connection lands and where it starts
      var ends = [[a.b, (p - 0.62) / 0.38], [a.a, p < 0.3 ? 1 - p / 0.3 : -1]];
      for (var e = 0; e < 2; e++) {
        var rp = ends[e][1];
        if (rp < 0 || rp > 1) continue;
        var ep = proj(ends[e][0]), ev = smooth(-0.1, 0.25, ep.z);
        if (e === 1) rp = 1 - rp;
        ctx.beginPath(); ctx.arc(ep.x, ep.y, (2 + rp * 15) * ep.k, 0, 6.2832);
        ctx.strokeStyle = rgba(C.hl, (1 - rp) * 0.7 * ev); ctx.lineWidth = 1.2; ctx.stroke();
      }
    }
    ctx.globalCompositeOperation = 'source-over';

    // connection points
    for (var ni = 0; ni < nodes.length; ni++) {
      var np = proj(nodes[ni]), nv = smooth(-0.05, 0.3, np.z);
      if (nv <= 0) continue;
      ctx.beginPath(); ctx.arc(np.x, np.y, 1.7 * np.k, 0, 6.2832);
      ctx.fillStyle = rgba(C.on, 0.85 * nv); ctx.fill();
    }

    // orbit ring with a travelling satellite
    var steps2 = 120, ringR = 1.36, prevR = null;
    ctx.lineWidth = 1;
    for (var rI = 0; rI <= steps2; rI++) {
      var ang2 = rI / steps2 * 6.2832;
      var rp3 = proj([Math.cos(ang2) * ringR, Math.sin(ang2) * ringR * 0.22, Math.sin(ang2) * ringR * 0.97]);
      if (prevR) {
        ctx.strokeStyle = rgba(C.on, rp3.z > 0 ? 0.22 : 0.07);
        ctx.beginPath(); ctx.moveTo(prevR.x, prevR.y); ctx.lineTo(rp3.x, rp3.y); ctx.stroke();
      }
      prevR = rp3;
    }
    var sa = now * 0.00028, sp = proj([Math.cos(sa) * ringR, Math.sin(sa) * ringR * 0.22, Math.sin(sa) * ringR * 0.97]);
    ctx.beginPath(); ctx.arc(sp.x, sp.y, 3 * sp.k, 0, 6.2832);
    ctx.fillStyle = rgba(C.hl, sp.z > 0 ? 1 : 0.4); ctx.fill();
  }

  function frame(ts) {
    var dt = lastT ? Math.min(50, ts - lastT) : 16;
    lastT = ts;
    if (!drag) {
      dragVel *= 0.94;
      tilt += (targetTilt - tilt) * 0.03;
    }
    yaw += (vel + dragVel) * dt / 16;
    while (arcs.length < TARGET) spawn(ts, 0);
    draw(ts);
    if (running) requestAnimationFrame(frame);
  }

  var running = false;
  function start() { if (!running) { running = true; lastT = 0; requestAnimationFrame(frame); } }
  function stop() { running = false; }

  readColors(); resize();
  window.addEventListener('resize', function () { resize(); if (reduce) renderStatic(); });

  function renderStatic() {
    var now = 10000;
    arcs = [];
    for (var i = 0; i < TARGET; i++) spawn(now, 0.35 + rnd() * 0.5);
    draw(now);
  }
  if (reduce) { renderStatic(); return; }
  // pre-warm so the first frame already has connections mid-flight
  for (var w = 0; w < TARGET; w++) spawn(0, rnd() * 0.9);

  canvas.addEventListener('pointerdown', function (e) { drag = true; lastX = e.clientX; dragVel = 0; canvas.setPointerCapture(e.pointerId); canvas.style.cursor = 'grabbing'; });
  canvas.addEventListener('pointermove', function (e) {
    var b = canvas.getBoundingClientRect();
    if (drag) {
      var dx = e.clientX - lastX; lastX = e.clientX;
      yaw += dx * 0.008; dragVel = dx * 0.0016;
      tilt = Math.max(-0.1, Math.min(0.8, tilt + (e.movementY || 0) * 0.004));
    } else { targetTilt = 0.15 + ((e.clientY - b.top) / b.height) * 0.4; }
  });
  function up() { drag = false; canvas.style.cursor = 'grab'; }
  canvas.addEventListener('pointerup', up); canvas.addEventListener('pointercancel', up);

  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (es) { es[0].isIntersecting ? start() : stop(); }).observe(canvas);
  } else { start(); }
})();
