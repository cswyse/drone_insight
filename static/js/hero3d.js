/* Homepage hero: several 3D styles drawn on one canvas, chosen in Admin > Settings (data-variant on the canvas).
   globe | lattice | rings | mesh | knot. Colours come from the theme (CSS variables), so they follow site.json,
   and the styles adapt to light or dark hero backgrounds. Motion stops with prefers-reduced-motion. */
(function () {
  var canvas = document.getElementById('hero-canvas');
  if (!canvas) return;
  var ctx = canvas.getContext('2d');
  var reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var variant = canvas.getAttribute('data-variant') || 'globe';

  // ---------- colours ----------
  function rgbVar(name, fb) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim().split(',').map(Number);
    return v.length === 3 && !v.some(isNaN) ? v : fb;
  }
  var C = {};
  function lum(c) { var f = function (v) { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]); }
  function mixc(a, b, t) { return [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t].map(Math.round); }
  function readColors() {
    C.accent = rgbVar('--accent-rgb', [34, 81, 255]);
    C.hl = rgbVar('--highlight-rgb', [0, 169, 244]);
    C.on = rgbVar('--on-primary-rgb', [255, 255, 255]);
    C.bg = rgbVar('--primary-rgb', [5, 28, 44]);
    C.light = lum(C.bg) > 0.45;                         // light hero background
    // line / glow colours that stay visible on either kind of background
    C.line = C.light ? mixc(C.accent, [0, 0, 0], 0.15) : C.hl;
    C.glow = C.light ? C.accent : C.hl;
    C.hi = C.light ? mixc(C.accent, [0, 0, 0], 0.45) : C.on;   // brightest marks
    C.mid = C.light ? C.accent : mixc(C.hl, C.accent, 0.5);
    C.blend = C.light ? 'source-over' : 'lighter';
  }
  function rgba(c, a) { return 'rgba(' + c[0] + ',' + c[1] + ',' + c[2] + ',' + Math.max(0, Math.min(1, a)) + ')'; }
  function smooth(a, b, x) { var t = Math.max(0, Math.min(1, (x - a) / (b - a))); return t * t * (3 - 2 * t); }
  function easeOut(t) { return 1 - Math.pow(1 - t, 3); }
  function easeIn(t) { return t * t * t; }
  function mulberry(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; var t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  var rnd = mulberry(11);

  // ---------- shared view: size, rotation, perspective ----------
  var W, H, R, DPR, cx, cy;
  var yaw = 0.5, tilt = 0.32, targetTilt = 0.32, vel = 0.0016, dragVel = 0, drag = false, lastX = 0, lastT = 0;
  var PERSP = 3.6;

  function rot(p) {
    var cy_ = Math.cos(yaw), sy = Math.sin(yaw), ct = Math.cos(tilt), st = Math.sin(tilt);
    var x = p[0] * cy_ + p[2] * sy, z = -p[0] * sy + p[2] * cy_, y = p[1];
    return [x, y * ct - z * st, y * st + z * ct];
  }
  function proj(p) {
    var q = rot(p), k = PERSP / (PERSP - q[2]);
    return { x: cx + q[0] * R * k, y: cy - q[1] * R * k, z: q[2], k: k };
  }
  // extra spin about an axis ('x' | 'y' | 'z') before the shared rotation
  function spin(p, axis, a) {
    var c = Math.cos(a), s = Math.sin(a);
    if (axis === 'y') return [p[0] * c + p[2] * s, p[1], -p[0] * s + p[2] * c];
    if (axis === 'x') return [p[0], p[1] * c - p[2] * s, p[1] * s + p[2] * c];
    return [p[0] * c - p[1] * s, p[0] * s + p[1] * c, p[2]];
  }
  function line(a, b, col, alpha, w) {
    ctx.strokeStyle = rgba(col, alpha); ctx.lineWidth = w;
    ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
  }
  function dot(p, r, col, alpha) {
    ctx.fillStyle = rgba(col, alpha); ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 6.2832); ctx.fill();
  }
  function glow(p, r, col, alpha) {
    var g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, r);
    g.addColorStop(0, rgba(col, alpha)); g.addColorStop(1, rgba(col, 0));
    ctx.fillStyle = g; ctx.beginPath(); ctx.arc(p.x, p.y, r, 0, 6.2832); ctx.fill();
  }
  function backdrop(strength) {
    var out = Math.min(R * 1.9, Math.min(W, H) / 2);   // fade to nothing before the canvas edge, so no box shows
    var g = ctx.createRadialGradient(cx, cy, Math.min(R * 0.5, out * 0.3), cx, cy, out);
    g.addColorStop(0, rgba(C.glow, strength)); g.addColorStop(0.55, rgba(C.glow, strength * 0.25)); g.addColorStop(1, rgba(C.glow, 0));
    ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
  }

  var V = {};   // variants: { setup(), draw(now), label, scale }

  // ================= GLOBE =================
  (function () {
    var dots = [], N = 2800, ga = Math.PI * (3 - Math.sqrt(5)), nodes = [], arcs = [], TARGET = 9;
    var LIGHT = [-0.45, 0.55, 0.7];
    function angle(a, b) { return Math.acos(Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]))); }
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
    function arcPoint(a, b, t, lift) {
      var v = [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t, a[2] + (b[2] - a[2]) * t];
      var l = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]) || 1, h = 1 + lift * Math.sin(Math.PI * t);
      return [v[0] / l * h, v[1] / l * h, v[2] / l * h];
    }
    V.globe = {
      label: 'Animated globe with moving connections', scale: 0.31,
      setup: function (still) {
        if (dots.length) return;
        for (var i = 0; i < N; i++) {
          var y = 1 - (i / (N - 1)) * 2, r = Math.sqrt(1 - y * y), th = ga * i;
          dots.push([Math.cos(th) * r, y, Math.sin(th) * r]);
        }
        for (var n = 0; n < 48; n++) {
          var z = 2 * rnd() - 1, ph = 2 * Math.PI * rnd(), rr = Math.sqrt(1 - z * z);
          nodes.push([rr * Math.cos(ph), z, rr * Math.sin(ph)]);
        }
        if (still) { for (var s = 0; s < TARGET; s++) spawn(10000, 0.35 + rnd() * 0.5); }
        else { for (var w = 0; w < TARGET; w++) spawn(0, rnd() * 0.9); }
      },
      draw: function (now, still) {
        if (!still) while (arcs.length < TARGET) spawn(now, 0);
        backdrop(C.light ? 0.16 : 0.28);
        var body = ctx.createRadialGradient(cx - R * 0.35, cy - R * 0.4, R * 0.1, cx, cy, R * 1.05);
        if (C.light) { body.addColorStop(0, rgba(mixc(C.bg, [255, 255, 255], 0.75), 0.95)); body.addColorStop(1, rgba(mixc(C.bg, C.accent, 0.22), 0.95)); }
        else { body.addColorStop(0, rgba(mixc(C.bg, C.accent, 0.35), 0.95)); body.addColorStop(1, rgba(mixc(C.bg, [0, 0, 0], 0.25), 0.95)); }
        ctx.beginPath(); ctx.arc(cx, cy, R * 1.005, 0, 6.2832); ctx.fillStyle = body; ctx.fill();

        var bright = C.light ? C.hi : mixc(C.on, C.hl, 0.35), mid = C.mid;
        for (var i = 0; i < dots.length; i++) {
          var q = rot(dots[i]);
          if (q[2] < -0.08) continue;
          var k = PERSP / (PERSP - q[2]);
          var lit = Math.max(0, q[0] * LIGHT[0] + q[1] * LIGHT[1] + q[2] * LIGHT[2]);
          var edge = smooth(-0.08, 0.3, q[2]);
          ctx.globalAlpha = ((C.light ? 0.3 : 0.12) + 0.75 * lit) * edge;
          ctx.fillStyle = rgba(lit > 0.55 ? bright : mid, 1);
          var s = (0.8 + 1.0 * lit) * k;
          ctx.fillRect(cx + q[0] * R * k - s / 2, cy - q[1] * R * k - s / 2, s, s);
        }
        ctx.globalAlpha = 1;
        ctx.beginPath(); ctx.arc(cx, cy, R * 1.005, 0, 6.2832);
        ctx.strokeStyle = rgba(C.line, 0.4); ctx.lineWidth = 1; ctx.stroke();

        ctx.globalCompositeOperation = C.blend; ctx.lineCap = 'round';
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
                ctx.strokeStyle = rgba(C.line, vis * (0.1 + 0.9 * f) * fade);
                ctx.lineWidth = (0.8 + 1.6 * f) * pt.k;
                ctx.beginPath(); ctx.moveTo(prev.x, prev.y); ctx.lineTo(pt.x, pt.y); ctx.stroke();
              }
              prev = pt;
            }
            if (prev && p < 0.8) {
              var hv = smooth(-0.3, 0.18, prev.z) * fade, hg = ctx.createRadialGradient(prev.x, prev.y, 0, prev.x, prev.y, 9 * prev.k);
              hg.addColorStop(0, rgba(C.hi, 0.95 * hv)); hg.addColorStop(0.35, rgba(C.glow, 0.5 * hv)); hg.addColorStop(1, rgba(C.glow, 0));
              ctx.fillStyle = hg; ctx.beginPath(); ctx.arc(prev.x, prev.y, 9 * prev.k, 0, 6.2832); ctx.fill();
            }
          }
          var ends = [[a.b, (p - 0.62) / 0.38], [a.a, p < 0.3 ? 1 - p / 0.3 : -1]];
          for (var e = 0; e < 2; e++) {
            var rp = ends[e][1];
            if (rp < 0 || rp > 1) continue;
            var ep = proj(ends[e][0]), ev = smooth(-0.1, 0.25, ep.z);
            if (e === 1) rp = 1 - rp;
            ctx.beginPath(); ctx.arc(ep.x, ep.y, (2 + rp * 15) * ep.k, 0, 6.2832);
            ctx.strokeStyle = rgba(C.line, (1 - rp) * 0.7 * ev); ctx.lineWidth = 1.2; ctx.stroke();
          }
        }
        ctx.globalCompositeOperation = 'source-over';
        for (var ni = 0; ni < nodes.length; ni++) {
          var np = proj(nodes[ni]), nv = smooth(-0.05, 0.3, np.z);
          if (nv > 0) dot({ x: np.x, y: np.y }, 1.7 * np.k, C.hi, 0.85 * nv);
        }
        var steps2 = 120, ringR = 1.36, prevR = null;
        ctx.lineWidth = 1;
        for (var rI = 0; rI <= steps2; rI++) {
          var ang2 = rI / steps2 * 6.2832;
          var rp3 = proj([Math.cos(ang2) * ringR, Math.sin(ang2) * ringR * 0.22, Math.sin(ang2) * ringR * 0.97]);
          if (prevR) line(prevR, rp3, C.light ? C.line : C.on, rp3.z > 0 ? 0.3 : 0.1, 1);
          prevR = rp3;
        }
        var sa = now * 0.00028, sp = proj([Math.cos(sa) * ringR, Math.sin(sa) * ringR * 0.22, Math.sin(sa) * ringR * 0.97]);
        dot(sp, 3 * sp.k, C.glow, sp.z > 0 ? 1 : 0.4);
      }
    };
  })();

  // ================= LATTICE: nested polyhedra =================
  (function () {
    var PHI = (1 + Math.sqrt(5)) / 2;
    function norm(v, r) { var l = Math.sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]); return [v[0] / l * r, v[1] / l * r, v[2] / l * r]; }
    function edgesOf(vs) {
      var d = 1e9, i, j, out = [];
      function dist(a, b) { return Math.sqrt(Math.pow(a[0] - b[0], 2) + Math.pow(a[1] - b[1], 2) + Math.pow(a[2] - b[2], 2)); }
      for (i = 0; i < vs.length; i++) for (j = i + 1; j < vs.length; j++) d = Math.min(d, dist(vs[i], vs[j]));
      for (i = 0; i < vs.length; i++) for (j = i + 1; j < vs.length; j++) if (dist(vs[i], vs[j]) < d * 1.05) out.push([i, j]);
      return out;
    }
    var shapes = [], pulses = [];
    V.lattice = {
      label: 'Rotating nested geometric solids with pulses of light travelling along their edges', scale: 0.34,
      setup: function () {
        if (shapes.length) return;
        var ico = [], s, a, b;
        [[0, 1, PHI], [0, 1, -PHI], [0, -1, PHI], [0, -1, -PHI]].forEach(function (v) { ico.push(norm(v, 1), norm([v[1], v[2], v[0]], 1), norm([v[2], v[0], v[1]], 1)); });
        var cube = [], oct = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]];
        for (a = -1; a <= 1; a += 2) for (b = -1; b <= 1; b += 2) for (s = -1; s <= 1; s += 2) cube.push(norm([a, b, s], 0.64));
        oct = oct.map(function (v) { return norm(v, 0.36); });
        shapes = [
          { v: ico, e: edgesOf(ico), ax: 'y', sp: 0.00020, w: 1.1, a: 0.5 },
          { v: cube, e: edgesOf(cube), ax: 'x', sp: -0.00034, w: 1.1, a: 0.4 },
          { v: oct, e: edgesOf(oct), ax: 'z', sp: 0.00050, w: 1.1, a: 0.6 }
        ];
        for (var i = 0; i < 9; i++) pulses.push({ s: i % 3, e: Math.floor(rnd() * 12), t: rnd() });
      },
      draw: function (now, still) {
        backdrop(C.light ? 0.13 : 0.2);
        ctx.globalCompositeOperation = C.blend; ctx.lineCap = 'round';
        var P = shapes.map(function (sh) {
          var ang = (still ? 4000 : now) * sh.sp;
          return sh.v.map(function (v) { return proj(spin(v, sh.ax, ang)); });
        });
        shapes.forEach(function (sh, si) {
          var pts = P[si];
          sh.e.forEach(function (e) {
            var a = pts[e[0]], b = pts[e[1]], z = (a.z + b.z) / 2;
            line(a, b, si === 2 ? C.hi : C.line, 0.2 + 0.5 * smooth(-1, 1, z), sh.w + (si === 0 ? 0.2 : 0));
          });
          pts.forEach(function (p) { dot(p, (si === 2 ? 2.8 : 2.2) * p.k, C.hi, 0.35 + 0.6 * smooth(-1, 1, p.z)); });
        });
        // links between the outer solid and the cube, so the shapes read as one structure
        for (var i = 0; i < 8; i++) {
          var a = P[1][i], b = P[0][(i * 3 + 1) % 12];
          line(a, b, C.glow, 0.07 + 0.1 * smooth(-1, 1, (a.z + b.z) / 2), 0.8);
        }
        if (!still) pulses.forEach(function (pl) {
          pl.t += 0.006;
          if (pl.t > 1) { pl.t = 0; pl.e = Math.floor(rnd() * shapes[pl.s].e.length); }
          var e = shapes[pl.s].e[pl.e % shapes[pl.s].e.length], A = P[pl.s][e[0]], B = P[pl.s][e[1]];
          var p = { x: A.x + (B.x - A.x) * pl.t, y: A.y + (B.y - A.y) * pl.t, z: (A.z + B.z) / 2, k: A.k };
          glow(p, 13 * p.k, C.glow, 0.7 * Math.sin(Math.PI * pl.t)); dot(p, 2 * p.k, C.hi, Math.sin(Math.PI * pl.t));
        });
        ctx.globalCompositeOperation = 'source-over';
        glow({ x: cx, y: cy }, R * 0.26, C.glow, C.light ? 0.25 : 0.4);
      }
    };
  })();

  // ================= RINGS: gimbal =================
  (function () {
    var rings = [
      { r: 1.0, ax: 'x', sp: 0.00030, a: 0.0, tilt: 1.2, n: 2, w: 1.4 },
      { r: 0.78, ax: 'y', sp: -0.00042, a: 1.0, tilt: 0.3, n: 3, w: 1.2 },
      { r: 0.56, ax: 'z', sp: 0.00058, a: 2.0, tilt: 0.9, n: 2, w: 1.1 }
    ];
    function ringPt(r, th, t, now) {      // point on a ring: circle, tilted, then spun
      var p = [Math.cos(th) * r.r, Math.sin(th) * r.r, 0];
      p = spin(p, 'x', r.tilt);
      return spin(p, r.ax, r.a + now * r.sp);
    }
    V.rings = {
      label: 'Interlocking rotating rings with points orbiting a glowing core', scale: 0.33,
      setup: function () {},
      draw: function (now, still) {
        var t = still ? 5000 : now;
        backdrop(C.light ? 0.14 : 0.22);
        ctx.globalCompositeOperation = C.blend; ctx.lineCap = 'round';
        rings.forEach(function (r, ri) {
          var steps = 110, prev = null;
          for (var i = 0; i <= steps; i++) {
            var p = proj(ringPt(r, i / steps * 6.2832, 0, t));
            if (prev) line(prev, p, C.line, 0.14 + 0.5 * smooth(-1, 1, (p.z + prev.z) / 2), r.w);
            prev = p;
          }
          for (var k = 0; k < r.n; k++) {              // orbiting markers with a short comet tail
            var th0 = t * (0.0005 + ri * 0.00018) * (ri % 2 ? -1 : 1) + k * 6.2832 / r.n;
            for (var s = 0; s < 14; s++) {
              var q = proj(ringPt(r, th0 - s * 0.06 * (ri % 2 ? -1 : 1), 0, t));
              dot(q, (3.2 - s * 0.18) * q.k, C.hi, (1 - s / 14) * (0.4 + 0.6 * smooth(-1, 1, q.z)));
            }
            var h = proj(ringPt(r, th0, 0, t)); glow(h, 16 * h.k, C.glow, 0.6);
          }
        });
        ctx.globalCompositeOperation = 'source-over';
        // faceted core
        var core = [[1, 0, 0], [-1, 0, 0], [0, 1, 0], [0, -1, 0], [0, 0, 1], [0, 0, -1]].map(function (v) { return proj(spin(spin([v[0] * 0.2, v[1] * 0.2, v[2] * 0.2], 'y', t * 0.0008), 'x', t * 0.0005)); });
        [[0, 2], [0, 3], [0, 4], [0, 5], [1, 2], [1, 3], [1, 4], [1, 5], [2, 4], [4, 3], [3, 5], [5, 2]].forEach(function (e) { line(core[e[0]], core[e[1]], C.hi, 0.8, 1); });
        glow({ x: cx, y: cy }, R * 0.34, C.glow, C.light ? 0.3 : 0.5);
      }
    };
  })();

  // ================= MESH: rippling wave surface =================
  (function () {
    var G = 34;
    function h(x, z, t) {
      var d = Math.sqrt(x * x + z * z);
      return 0.16 * Math.sin(d * 5.2 - t * 0.0016) * Math.exp(-d * 0.55) + 0.07 * Math.sin(x * 3.1 + t * 0.0009) * Math.cos(z * 2.7 - t * 0.0007);
    }
    V.mesh = {
      label: 'A rippling three-dimensional wave surface', scale: 0.4,
      setup: function () { targetTilt = tilt = 0.95; },
      draw: function (now, still) {
        var t = still ? 6000 : now, grid = [], i, j;
        backdrop(C.light ? 0.1 : 0.16);
        for (i = 0; i <= G; i++) {
          grid.push([]);
          for (j = 0; j <= G; j++) {
            var x = (i / G - 0.5) * 3.0, z = (j / G - 0.5) * 3.0, y = h(x, z, t);
            var p = proj([x * 0.82, y * 1.7, z * 0.82]);
            p.y_ = y; p.fade = Math.max(0, 1 - Math.pow(Math.sqrt(x * x + z * z) / 1.5, 2.4));
            grid[i].push(p);
          }
        }
        ctx.lineCap = 'round'; ctx.globalCompositeOperation = C.blend;
        function seg(a, b) {
          var al = Math.min(a.fade, b.fade);
          if (al <= 0.02) return;
          var m = smooth(-0.14, 0.2, (a.y_ + b.y_) / 2);
          line(a, b, mixc(C.line, C.hi, m * 0.8), al * (0.22 + 0.7 * m), 1.1);
        }
        for (i = 0; i <= G; i++) for (j = 0; j <= G; j++) {
          if (i < G) seg(grid[i][j], grid[i + 1][j]);
          if (j < G) seg(grid[i][j], grid[i][j + 1]);
        }
        for (i = 0; i <= G; i += 2) for (j = 0; j <= G; j += 2) {
          var p = grid[i][j], m = smooth(0.02, 0.2, p.y_);
          if (m > 0.1 && p.fade > 0.1) dot(p, 1.8 * p.k, C.hi, m * p.fade * 0.9);
        }
        ctx.globalCompositeOperation = 'source-over';
      }
    };
  })();

  // ================= KNOT: a (2,3) torus knot drawn as flowing strands =================
  (function () {
    var N = 360, S = 3;
    function knot(u, ph) {
      var r = Math.cos(3 * u) + 2.1, k = 0.4;
      var x = r * Math.cos(2 * u), y = r * Math.sin(2 * u), z = -Math.sin(3 * u) * 1.05;
      var off = 0.1;
      return [(x + off * Math.cos(ph) * Math.cos(2 * u)) * k, (y + off * Math.cos(ph) * Math.sin(2 * u)) * k, (z + off * Math.sin(ph)) * k];
    }
    V.knot = {
      label: 'A slowly turning torus knot made of flowing light strands', scale: 0.31,
      setup: function () {},
      draw: function (now, still) {
        var t = still ? 5000 : now;
        backdrop(C.light ? 0.12 : 0.2);
        ctx.globalCompositeOperation = C.blend; ctx.lineCap = 'round';
        for (var s = 0; s < S; s++) {
          var ph = s * 6.2832 / S + t * 0.0004, prev = null;
          for (var i = 0; i <= N; i++) {
            var u = i / N * 6.2832, p = proj(spin(knot(u, ph + u * 3), 'z', t * 0.00012));
            if (prev) {
              var flow = 0.5 + 0.5 * Math.sin(u * 3 - t * 0.0014 + s * 2.1);
              line(prev, p, mixc(C.line, C.hi, flow * 0.7), (0.1 + 0.6 * smooth(-0.9, 0.9, p.z)) * (0.35 + 0.65 * flow), 1 + 0.9 * flow);
            }
            prev = p;
          }
        }
        for (var m = 0; m < 3; m++) {                     // bright beads running along the knot
          var u2 = ((t * 0.00035 + m / 3) % 1) * 6.2832, b = proj(spin(knot(u2, 0), 'z', t * 0.00012));
          glow(b, 15 * b.k, C.glow, 0.7); dot(b, 2.6 * b.k, C.hi, 0.95);
        }
        ctx.globalCompositeOperation = 'source-over';
      }
    };
  })();

  // ---------- loop and interaction ----------
  var cur = V[variant] || V.globe;
  canvas.setAttribute('aria-label', cur.label);
  var running = false;

  function resize() {
    var b = canvas.getBoundingClientRect();
    DPR = Math.min(2, window.devicePixelRatio || 1);
    W = b.width; H = b.height;
    canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR);
    ctx.setTransform(DPR, 0, 0, DPR, 0, 0);
    R = Math.min(W, H) * cur.scale; cx = W / 2; cy = H / 2;
  }
  function render(now, still) {
    ctx.clearRect(0, 0, W, H);
    ctx.globalCompositeOperation = 'source-over';
    cur.draw(now, still);
  }
  function frame(ts) {
    var dt = lastT ? Math.min(50, ts - lastT) : 16;
    lastT = ts;
    if (!drag) { dragVel *= 0.94; tilt += (targetTilt - tilt) * 0.03; }
    yaw += (vel + dragVel) * dt / 16;
    render(ts, false);
    if (running) requestAnimationFrame(frame);
  }
  function start() { if (!running) { running = true; lastT = 0; requestAnimationFrame(frame); } }
  function stop() { running = false; }

  readColors();
  cur.setup(reduce);
  resize();
  var meshLike = variant === 'mesh';
  window.addEventListener('resize', function () { resize(); if (reduce) render(10000, true); });
  if (reduce) { render(10000, true); return; }

  canvas.addEventListener('pointerdown', function (e) { drag = true; lastX = e.clientX; dragVel = 0; canvas.setPointerCapture(e.pointerId); canvas.style.cursor = 'grabbing'; });
  canvas.addEventListener('pointermove', function (e) {
    var b = canvas.getBoundingClientRect();
    if (drag) {
      var dx = e.clientX - lastX; lastX = e.clientX;
      yaw += dx * 0.008; dragVel = dx * 0.0016;
      tilt = Math.max(-0.1, Math.min(meshLike ? 1.35 : 0.8, tilt + (e.movementY || 0) * 0.004));
    } else if (meshLike) { targetTilt = 0.7 + ((e.clientY - b.top) / b.height) * 0.5; }
    else { targetTilt = 0.15 + ((e.clientY - b.top) / b.height) * 0.4; }
  });
  function up() { drag = false; canvas.style.cursor = 'grab'; }
  canvas.addEventListener('pointerup', up); canvas.addEventListener('pointercancel', up);

  if ('IntersectionObserver' in window) {
    new IntersectionObserver(function (es) { es[0].isIntersecting ? start() : stop(); }).observe(canvas);
  } else { start(); }
})();
