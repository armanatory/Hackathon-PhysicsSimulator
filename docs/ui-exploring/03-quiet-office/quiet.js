/* QuietOffice — sample model + drawing helpers shared by the sketch pages.
   A small geometric-acoustics stand-in (direct path, first wall reflections, screen diffraction)
   plays the part of the Allsolve harmonic runs. It is not solver output. */
(function () {
  var W = 16, H = 10, C0 = 343;
  var SRC = { x: 2.2, y: 5 };
  var BANDS = [250, 500, 1000, 2000];
  var LOUD = 45; // dB: above this, a desk counts as "in earshot"

  var TYPES = [
    { id: 'divider', name: 'Desk divider', len: 1.2, cap: 8, cost: 100 },
    { id: 'screen', name: 'Acoustic screen', len: 1.8, cap: 14, cost: 180 },
    { id: 'partition', name: 'Movable partition', len: 2.6, cap: 22, cost: 300 }
  ];
  var SCREEN = 1;

  // Candidate positions: [x, y, orientation, description]
  var SLOTS = [
    [3.4, 5.0, 'v', 'Directly in front of the coffee point'],
    [3.4, 3.2, 'v', 'Beside the coffee point, north side'],
    [3.4, 6.8, 'v', 'Beside the coffee point, south side'],
    [5.8, 4.4, 'h', 'Along the aisle edge of the near north desks'],
    [5.2, 5.9, 'h', 'Along the aisle edge of the near south desks'],
    [8.4, 2.7, 'v', 'Centre aisle, north end'],
    [8.4, 5.0, 'v', 'Centre aisle, middle'],
    [8.4, 7.7, 'v', 'Centre aisle, south end'],
    [11.3, 4.5, 'h', 'Along the aisle edge of the far north desks'],
    [11.3, 5.9, 'h', 'Along the aisle edge of the far south desks'],
    [9.6, 2.7, 'v', 'In front of the far north desks'],
    [9.6, 7.7, 'v', 'In front of the far south desks']
  ];

  var DESKS = [];
  [[5, 2], [10.5, 2], [4.4, 7], [10.5, 7]].forEach(function (c) {
    [[0, 0], [1.6, 0], [0, 1.4], [1.6, 1.4]].forEach(function (d) { DESKS.push({ x: c[0] + d[0], y: c[1] + d[1] }); });
  });

  // The talker plus its mirror image in each wall (first reflections).
  var IMAGES = [
    { x: SRC.x, y: SRC.y, a: 1 }, { x: -SRC.x, y: SRC.y, a: 0.36 }, { x: 2 * W - SRC.x, y: SRC.y, a: 0.36 },
    { x: SRC.x, y: -SRC.y, a: 0.36 }, { x: SRC.x, y: 2 * H - SRC.y, a: 0.36 }
  ];

  function segOf(piece) {
    var s = SLOTS[piece[0]], t = TYPES[piece[1]], h = t.len / 2;
    return s[2] === 'v'
      ? { x1: s[0], y1: s[1] - h, x2: s[0], y2: s[1] + h, cap: t.cap, len: t.len }
      : { x1: s[0] - h, y1: s[1], x2: s[0] + h, y2: s[1], cap: t.cap, len: t.len };
  }
  function dist(ax, ay, bx, by) { return Math.sqrt((ax - bx) * (ax - bx) + (ay - by) * (ay - by)); }
  // Extra path length around the nearer end of a screen, or -1 when it is not in the way.
  function detour(sx, sy, rx, ry, g) {
    var gx = g.x2 - g.x1, gy = g.y2 - g.y1, px = rx - sx, py = ry - sy;
    var d1 = gx * (sy - g.y1) - gy * (sx - g.x1), d2 = gx * (ry - g.y1) - gy * (rx - g.x1);
    var d3 = px * (g.y1 - sy) - py * (g.x1 - sx), d4 = px * (g.y2 - sy) - py * (g.x2 - sx);
    if (d1 * d2 >= 0 || d3 * d4 >= 0) return -1;
    return Math.min(dist(sx, sy, g.x1, g.y1) + dist(g.x1, g.y1, rx, ry), dist(sx, sy, g.x2, g.y2) + dist(g.x2, g.y2, rx, ry)) - dist(sx, sy, rx, ry);
  }
  function reverb(segs) {
    var len = 0;
    segs.forEach(function (g) { len += g.len; });
    return Math.pow(10, (38 - 0.8 * len) / 10);
  }
  // Energy per band at a point. With coherent=true the two low bands keep their phase, so the map shows interference.
  function energies(x, y, segs, rev, coherent) {
    var E = [0, 0, 0, 0], re = [0, 0], im = [0, 0];
    for (var s = 0; s < IMAGES.length; s++) {
      var S = IMAGES[s], r = Math.max(dist(S.x, S.y, x, y), 0.3), base = S.a * 1e6 / (r * r);
      var dets = [];
      for (var k = 0; k < segs.length; k++) {
        var d = detour(S.x, S.y, x, y, segs[k]);
        if (d >= 0) dets.push([d, segs[k].cap]);
      }
      for (var b = 0; b < 4; b++) {
        var il = 0;
        for (var q = 0; q < dets.length; q++) il += Math.min(dets[q][1], 10 * Math.log10(3 + 40 * dets[q][0] * BANDS[b] / C0));
        var e = base * Math.pow(10, -Math.min(il, 26) / 10);
        E[b] += e;
        if (coherent && b < 2) {
          var amp = Math.sqrt(e), ph = 2 * Math.PI * BANDS[b] * r / C0;
          re[b] += amp * Math.cos(ph); im[b] += amp * Math.sin(ph);
        }
      }
    }
    for (var b2 = 0; b2 < 4; b2++) {
      if (coherent && b2 < 2) E[b2] = 0.55 * E[b2] + 0.45 * (re[b2] * re[b2] + im[b2] * im[b2]);
      E[b2] += rev;
    }
    return E;
  }
  function levelOf(E, band) {
    return 10 * Math.log10(band === 'all' ? (E[0] + E[1] + E[2] + E[3]) / 4 : E[band]);
  }

  function evaluate(pieces) {
    var segs = pieces.map(segOf), rev = reverb(segs), sum = 0, max = 0;
    var desks = DESKS.map(function (d) {
      var L = levelOf(energies(d.x, d.y, segs, rev, false), 'all'), p = Math.pow(10, L / 20);
      sum += p; if (p > max) max = p;
      return L;
    });
    return {
      pieces: pieces, desks: desks, raw: sum / DESKS.length + 0.5 * max,
      cost: pieces.reduce(function (c, p) { return c + TYPES[p[1]].cost; }, 0)
    };
  }

  var cache = null;
  function all() {
    if (cache) return cache;
    var base = evaluate([]), list = [], n = SLOTS.length, T = TYPES.length, a, b, c, i, j, k;
    // Two pieces in line with each other must not overlap.
    var clash = function (pieces) {
      for (var p = 0; p < pieces.length; p++) for (var q = p + 1; q < pieces.length; q++) {
        var s = SLOTS[pieces[p][0]], t = SLOTS[pieces[q][0]], along = s[2] === 'v' ? 1 : 0;
        if (s[2] === t[2] && s[1 - along] === t[1 - along] &&
          Math.abs(s[along] - t[along]) < (TYPES[pieces[p][1]].len + TYPES[pieces[q][1]].len) / 2 - 0.01) return true;
      }
      return false;
    };
    var add = function (pieces) {
      if (clash(pieces)) return;
      var r = evaluate(pieces); r.score = 100 * r.raw / base.raw; list.push(r);
    };
    for (i = 0; i < n; i++) for (a = 0; a < T; a++) {
      add([[i, a]]);
      for (j = i + 1; j < n; j++) for (b = 0; b < T; b++) {
        add([[i, a], [j, b]]);
        for (k = j + 1; k < n; k++) for (c = 0; c < T; c++) add([[i, a], [j, b], [k, c]]);
      }
    }
    base.score = 100;
    cache = { base: base, list: list };
    return cache;
  }
  function pick(list) { return list.reduce(function (m, r) { return r.score < m.score ? r : m; }); }
  // Every layout of k standard acoustic screens, in the order the search tries them.
  function screenLayouts(k) {
    return all().list.filter(function (r) {
      return r.pieces.length === k && r.pieces.every(function (p) { return p[1] === SCREEN; });
    });
  }
  function bestScreens(k) { return k === 0 ? all().base : pick(screenLayouts(k)); }
  function bestBudget(euro) {
    var ok = all().list.filter(function (r) { return r.cost <= euro; });
    return ok.length ? pick(ok) : all().base;
  }
  function inEarshot(r) { return r.desks.filter(function (L) { return L >= LOUD; }).length; }

  var STOPS = [[36, [241, 243, 236]], [42, [248, 220, 195]], [48, [244, 165, 126]], [54, [224, 86, 106]], [60, [142, 31, 79]]];
  function rgb(L) {
    if (L <= STOPS[0][0]) return STOPS[0][1];
    for (var i = 1; i < STOPS.length; i++) {
      if (L <= STOPS[i][0]) {
        var a = STOPS[i - 1], b = STOPS[i], f = (L - a[0]) / (b[0] - a[0]);
        return [a[1][0] + (b[1][0] - a[1][0]) * f, a[1][1] + (b[1][1] - a[1][1]) * f, a[1][2] + (b[1][2] - a[1][2]) * f];
      }
    }
    return STOPS[STOPS.length - 1][1];
  }
  function css(L) { var c = rgb(L); return 'rgb(' + Math.round(c[0]) + ',' + Math.round(c[1]) + ',' + Math.round(c[2]) + ')'; }

  function paint(canvas, pieces, band) {
    var cw = 320, ch = 200, ctx = canvas.getContext('2d');
    canvas.width = cw; canvas.height = ch;
    var img = ctx.createImageData(cw, ch), segs = pieces.map(segOf), rev = reverb(segs), o = 0;
    for (var py = 0; py < ch; py++) {
      for (var px = 0; px < cw; px++) {
        var c = rgb(levelOf(energies((px + 0.5) * W / cw, (py + 0.5) * H / ch, segs, rev, true), band));
        img.data[o++] = c[0]; img.data[o++] = c[1]; img.data[o++] = c[2]; img.data[o++] = 255;
      }
    }
    ctx.putImageData(img, 0, 0);
  }

  // Floor plan overlay, 10 units per metre. opts.mini drops the labels; opts.slots shows every candidate position.
  function planSVG(result, opts) {
    opts = opts || {};
    var u = 10, h = '<svg viewBox="0 0 ' + W * u + ' ' + H * u + '" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">';
    if (opts.mini) h += '<rect width="' + W * u + '" height="' + H * u + '" fill="#f8f9f5"/>';
    if (opts.slots) {
      SLOTS.forEach(function (s, i) {
        var g = segOf([i, SCREEN]);
        h += '<line x1="' + g.x1 * u + '" y1="' + g.y1 * u + '" x2="' + g.x2 * u + '" y2="' + g.y2 * u + '" stroke="#17302b" stroke-opacity=".35" stroke-width=".8" stroke-dasharray="1.5 1.5"/>';
      });
    }
    DESKS.forEach(function (d, i) {
      var L = result.desks[i];
      h += '<rect x="' + (d.x * u - 6.5) + '" y="' + (d.y * u - 4.5) + '" width="13" height="9" rx="1.6" fill="' + (opts.mini ? css(L) : '#fff') + '" stroke="#17302b" stroke-width=".5"/>';
      if (!opts.mini) {
        h += '<circle cx="' + (d.x * u - 3.4) + '" cy="' + d.y * u + '" r="1.5" fill="' + css(L) + '" stroke="#17302b" stroke-width=".4"/>';
        h += '<text x="' + (d.x * u + 1.9) + '" y="' + (d.y * u + 1.2) + '" font-size="3.3" text-anchor="middle" fill="#17302b" font-weight="' + (L >= LOUD ? 700 : 400) + '">' + L.toFixed(0) + '</text>';
      }
    });
    var sx = SRC.x * u, sy = SRC.y * u;
    h += '<circle cx="' + sx + '" cy="' + sy + '" r="2.2" fill="#17302b"/>';
    [4.5, 7].forEach(function (r) { h += '<path d="M' + (sx + r * 0.6) + ' ' + (sy - r * 0.8) + ' A' + r + ' ' + r + ' 0 0 1 ' + (sx + r * 0.6) + ' ' + (sy + r * 0.8) + '" fill="none" stroke="#17302b" stroke-width=".7"/>'; });
    if (!opts.mini) h += '<text x="' + sx + '" y="' + (sy + 11) + '" font-size="3" text-anchor="middle" fill="#17302b">coffee point</text>';
    (opts.ghost || []).forEach(function (p) {
      var g = segOf(p);
      h += '<line x1="' + g.x1 * u + '" y1="' + g.y1 * u + '" x2="' + g.x2 * u + '" y2="' + g.y2 * u + '" stroke="#17302b" stroke-width="1" stroke-dasharray="2 1.6"/>';
    });
    result.pieces.forEach(function (p) {
      var g = segOf(p);
      h += '<line x1="' + g.x1 * u + '" y1="' + g.y1 * u + '" x2="' + g.x2 * u + '" y2="' + g.y2 * u + '" stroke="#17302b" stroke-width="2.4" stroke-linecap="round"/>';
      h += '<line x1="' + g.x1 * u + '" y1="' + g.y1 * u + '" x2="' + g.x2 * u + '" y2="' + g.y2 * u + '" stroke="#d9a520" stroke-width=".9" stroke-linecap="round"/>';
    });
    h += '<rect x=".5" y=".5" width="' + (W * u - 1) + '" height="' + (H * u - 1) + '" fill="none" stroke="#17302b" stroke-width="1"/>';
    return h + '</svg>';
  }

  // Sound map + floor plan. With opts.before set, the two are split by a draggable divider.
  function mount(el, opts) {
    var band = opts.band === undefined ? 'all' : opts.band;
    var stack = function (cls, r, o) { return '<div class="stack ' + cls + '"><canvas></canvas>' + planSVG(r, o) + '</div>'; };
    var html = '';
    if (opts.before) html += stack('before', opts.before, { ghost: opts.after.pieces });
    html += stack('after', opts.after);
    if (opts.before) {
      html += '<div class="split"><span>before</span><i></i><span>after</span></div>' +
        '<input class="split-input" type="range" min="0" max="100" value="' + (opts.split === undefined ? 50 : opts.split) + '" aria-label="Slide to compare before and after">';
    }
    el.innerHTML = html;
    var cv = el.querySelectorAll('canvas');
    if (opts.before) { paint(cv[0], opts.before.pieces, band); paint(cv[1], opts.after.pieces, band); }
    else paint(cv[0], opts.after.pieces, band);
    if (opts.before) {
      var input = el.querySelector('.split-input');
      var set = function () {
        var v = +input.value;
        el.querySelector('.before').style.clipPath = 'inset(0 ' + (100 - v) + '% 0 0)';
        el.querySelector('.after').style.clipPath = 'inset(0 0 0 ' + v + '%)';
        el.querySelector('.split').style.left = v + '%';
        if (opts.onSplit) opts.onSplit(v);
      };
      input.oninput = set; set();
    }
  }

  window.Quiet = {
    TYPES: TYPES, SLOTS: SLOTS, DESKS: DESKS, BANDS: BANDS, LOUD: LOUD, SCREEN: SCREEN,
    all: all, screenLayouts: screenLayouts, bestScreens: bestScreens, bestBudget: bestBudget,
    inEarshot: inEarshot, css: css, planSVG: planSVG, mount: mount
  };
})();
