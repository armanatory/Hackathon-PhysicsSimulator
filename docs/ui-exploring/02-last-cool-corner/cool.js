/* Last Cool Corner — sample model + drawing helpers shared by the sketch pages.
   The temperatures are a made-up closed-form stand-in for the Allsolve transient results. */
(function () {
  var W = 10, H = 7, STEP = 0.25, PX = 60; // flat is 10 x 7 m; plan drawn at 60 px per metre
  var w = 2 * Math.PI / 24;

  var ROOMS = [
    { id: 'bed', name: 'Bedroom', the: 'the bedroom', r: [0, 0, 4, 4.3], win: ['left'], shelter: 0, sleep: true, color: '#b79cff' },
    { id: 'hall', name: 'Hallway', the: 'the hallway', r: [4, 0, 2, 2], win: [], shelter: 2.5, sleep: true, color: '#7fd6e8' },
    { id: 'bath', name: 'Bathroom', the: 'the bathroom', r: [4, 2, 2, 2.3], win: [], shelter: 1.5, sleep: false, color: '#9a9bc0' },
    { id: 'kit', name: 'Kitchen', the: 'the kitchen', r: [6, 0, 4, 4.3], win: ['right'], shelter: 0, sleep: true, color: '#6fd08c' },
    { id: 'liv', name: 'Living room', the: 'the living room', r: [0, 4.3, 6.2, 2.7], win: ['bottom', 'left'], shelter: 0, sleep: true, color: '#f6a93b' },
    { id: 'kid', name: 'Child’s room', the: 'the child’s room', r: [6.2, 4.3, 3.8, 2.7], win: ['bottom', 'right'], shelter: 0, sleep: true, color: '#f2748b' }
  ];
  // [x1, y1, x2, y2] in metres
  var WALLS = [
    [0, 0, 4.6, 0], [5.4, 0, 10, 0], [10, 0, 10, 7], [10, 7, 0, 7], [0, 7, 0, 0],
    [4, 0, 4, 0.6], [4, 1.4, 4, 4.3], [6, 0, 6, 0.6], [6, 1.4, 6, 4.3],
    [4, 2, 4.6, 2], [5.4, 2, 6, 2], [0, 4.3, 7, 4.3], [9, 4.3, 10, 4.3],
    [6.2, 4.3, 6.2, 4.6], [6.2, 5.4, 6.2, 7]
  ];
  var WINDOWS = [
    [0, 1.2, 0, 3.0], [10, 1.2, 10, 3.0], [1.2, 7, 4.8, 7], [0, 5.0, 0, 6.3], [7.2, 7, 9.0, 7], [10, 5.0, 10, 6.3]
  ];
  var SUN = { N: { peak: 13, amp: 0.12 }, E: { peak: 9, amp: 0.8 }, S: { peak: 13, amp: 1 }, W: { peak: 17.5, amp: 1.1 } };
  var DIRS = ['N', 'E', 'S', 'W'];
  var FLOOR = { ground: -1.2, middle: 0, top: 1.3 };

  var state = { facing: 'S', floor: 'middle', windows: 'open' };
  try {
    var saved = JSON.parse(localStorage.getItem('coolcorner') || '{}');
    ['facing', 'floor', 'windows'].forEach(function (k) { if (saved[k]) state[k] = saved[k]; });
  } catch (e) { /* storage unavailable: defaults are fine */ }
  function save() { try { localStorage.setItem('coolcorner', JSON.stringify(state)); } catch (e) { /* ignore */ } }

  // Which compass direction a side of the drawn plan faces, given where the living room looks.
  function sideDir(side) {
    var k = DIRS.indexOf(state.facing);
    return DIRS[(k + { bottom: 0, left: 1, top: 2, right: 3 }[side]) % 4];
  }
  function sideDist(side, x, y) {
    return side === 'left' ? x : side === 'right' ? W - x : side === 'top' ? y : H - y;
  }
  function outdoor(t) { return 30 + 7 * Math.cos(w * (t - 16)); }

  function tempAt(room, x, y, t) {
    var d = Math.min(x, W - x, y, H - y) + room.shelter;
    var T = 28.3 + FLOOR[state.floor] + 4 * Math.exp(-d / 3) * Math.cos(w * (t - 17 - 0.6 * d));
    if (state.floor === 'top') T += 1.2 * Math.cos(w * (t - 19));
    var nearest = Infinity;
    room.win.forEach(function (side) {
      var df = sideDist(side, x, y), s = SUN[sideDir(side)];
      var c = Math.cos(w * (t - 2 - 0.4 * df - s.peak));
      T += s.amp * (5 * (c > 0 ? c * c : 0) * Math.exp(-df / 1.8) + 3.5 * Math.exp(-df / 3));
      nearest = Math.min(nearest, df);
    });
    if (state.windows === 'open' && nearest < Infinity) {
      var out = outdoor(t);
      if (out < T) T -= 0.45 * (T - out) * Math.exp(-nearest / 4);
    }
    return T;
  }

  var CELLS = [];
  for (var cy = 0; cy < H / STEP; cy++) {
    for (var cx = 0; cx < W / STEP; cx++) {
      var x = (cx + 0.5) * STEP, y = (cy + 0.5) * STEP, ri = 0;
      ROOMS.forEach(function (rm, i) {
        if (x >= rm.r[0] && x < rm.r[0] + rm.r[2] && y >= rm.r[1] && y < rm.r[1] + rm.r[3]) ri = i;
      });
      CELLS.push({ x: x, y: y, room: ri });
    }
  }

  function roomTemp(i, t) {
    var sum = 0, n = 0;
    CELLS.forEach(function (c) { if (c.room === i) { sum += tempAt(ROOMS[i], c.x, c.y, t); n++; } });
    return sum / n;
  }

  var T0 = 12, N = 49; // half-hour steps from noon to noon
  function timeAt(i) { return T0 + i / 2; }
  function summary() {
    var series = ROOMS.map(function (rm, i) {
      var a = [];
      for (var k = 0; k < N; k++) a.push(roomTemp(i, timeAt(k)));
      return a;
    });
    var avg = function (a, from, to) { var s = 0; for (var k = from; k <= to; k++) s += a[k]; return s / (to - from + 1); };
    var rows = ROOMS.map(function (rm, i) {
      return { room: rm, i: i, night: avg(series[i], 22, 38), day: avg(series[i], 2, 14), peak: Math.max.apply(null, series[i]) };
    });
    var night = rows.slice().sort(function (a, b) { return a.night - b.night; });
    var sleepable = night.filter(function (r) { return r.room.sleep; });
    var day = rows.filter(function (r) { return r.room.sleep; }).sort(function (a, b) { return a.day - b.day; });
    var best = sleepable[0], from = null, to = null;
    for (var k = 0; k < N; k++) {
      if (outdoor(timeAt(k)) < series[best.i][k]) { if (from === null) from = timeAt(k); to = timeAt(k); }
    }
    return { series: series, rows: rows, night: night, best: best, worst: sleepable[sleepable.length - 1], day: day[0], vent: from === null ? null : { from: from, to: to } };
  }

  var STOPS = [[25, [43, 127, 208]], [27, [90, 86, 200]], [28.5, [154, 69, 184]], [31, [194, 64, 122]], [34, [240, 128, 60]], [37, [255, 224, 138]]];
  function color(t) {
    if (t <= STOPS[0][0]) return 'rgb(' + STOPS[0][1].join(',') + ')';
    for (var i = 1; i < STOPS.length; i++) {
      if (t <= STOPS[i][0]) {
        var a = STOPS[i - 1], b = STOPS[i], f = (t - a[0]) / (b[0] - a[0]);
        return 'rgb(' + a[1].map(function (c, k) { return Math.round(c + (b[1][k] - c) * f); }).join(',') + ')';
      }
    }
    return 'rgb(' + STOPS[STOPS.length - 1][1].join(',') + ')';
  }
  function hhmm(t) {
    var h = Math.floor(t) % 24, m = Math.round((t - Math.floor(t)) * 60);
    return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
  }

  // Floor plan. opts.rank (array of night rows) draws the flat ranked instead of as a heat field.
  function drawPlan(svg, opts) {
    opts = opts || {};
    var ink = opts.ink || '#ece7f5', p = function (v) { return v * PX; }, h = '';
    svg.setAttribute('viewBox', '-14 -14 ' + (W * PX + 96) + ' ' + (H * PX + 28));

    if (opts.rank) {
      opts.rank.forEach(function (row, n) {
        var r = row.room.r;
        h += '<rect x="' + p(r[0]) + '" y="' + p(r[1]) + '" width="' + p(r[2]) + '" height="' + p(r[3]) + '" fill="' + ink + '" fill-opacity="' + (n === 0 ? 0.92 : 0.04 + 0.05 * n) + '"/>';
      });
    } else {
      h += '<g class="cells">';
      CELLS.forEach(function (c) {
        h += '<rect x="' + (p(c.x) - 7.5) + '" y="' + (p(c.y) - 7.5) + '" width="15.6" height="15.6"/>';
      });
      h += '</g>';
    }
    WALLS.forEach(function (l) {
      h += '<line x1="' + p(l[0]) + '" y1="' + p(l[1]) + '" x2="' + p(l[2]) + '" y2="' + p(l[3]) + '" stroke="' + ink + '" stroke-width="5" stroke-linecap="square"/>';
    });
    WINDOWS.forEach(function (l) {
      h += '<line x1="' + p(l[0]) + '" y1="' + p(l[1]) + '" x2="' + p(l[2]) + '" y2="' + p(l[3]) + '" stroke="' + (opts.rank ? '#fff' : '#12142b') + '" stroke-width="2"/>';
    });
    h += '<text x="' + p(5) + '" y="-4" font-size="11" text-anchor="middle" fill="' + ink + '" opacity=".7">front door</text>';

    h += '<g class="mat"></g>';
    ROOMS.forEach(function (rm, i) {
      var cx = p(rm.r[0] + rm.r[2] / 2), cy = p(rm.r[1] + rm.r[3] / 2);
      if (opts.rank) {
        var n = opts.rank.map(function (r) { return r.i; }).indexOf(i), first = n === 0;
        var fill = first ? '#fff' : ink;
        h += '<text x="' + cx + '" y="' + (cy - 2) + '" font-size="34" font-weight="700" text-anchor="middle" fill="' + fill + '">' + (n + 1) + '</text>';
        h += '<text x="' + cx + '" y="' + (cy + 18) + '" font-size="13" text-anchor="middle" fill="' + fill + '">' + rm.name + '</text>';
      } else {
        h += '<text class="lbl" x="' + cx + '" y="' + (cy - 6) + '" font-size="13" text-anchor="middle">' + rm.name + '</text>';
        h += '<text class="lbl val" data-room="' + i + '" x="' + cx + '" y="' + (cy + 15) + '" font-size="19" font-weight="700" text-anchor="middle"></text>';
      }
    });

    var ang = (2 - DIRS.indexOf(state.facing)) * 90, nx = W * PX + 46;
    h += '<g transform="translate(' + nx + ' 40) rotate(' + ang + ')"><circle r="24" fill="none" stroke="' + ink + '" stroke-opacity=".4"/>' +
      '<path d="M0 -20 L7 6 L0 1 L-7 6 Z" fill="' + ink + '"/></g>';
    h += '<text x="' + nx + '" y="84" font-size="11" text-anchor="middle" fill="' + ink + '" opacity=".7">north</text>';
    svg.innerHTML = h;

    var rects = svg.querySelectorAll('.cells rect'), vals = svg.querySelectorAll('.val');
    return {
      update: function (t) {
        for (var k = 0; k < rects.length; k++) {
          var c = CELLS[k];
          rects[k].setAttribute('fill', color(tempAt(ROOMS[c.room], c.x, c.y, t)));
        }
        [].forEach.call(vals, function (v) { v.textContent = roomTemp(+v.dataset.room, t).toFixed(1) + '°'; });
      },
      mattress: function (row) {
        var best = null;
        CELLS.forEach(function (c) {
          if (c.room !== row.i) return;
          var T = tempAt(row.room, c.x, c.y, 27);
          if (!best || T < best.T) best = { T: T, x: c.x, y: c.y };
        });
        var r = row.room.r, mw = 0.9, mh = 1.9;
        var mx = Math.min(Math.max(best.x - mw / 2, r[0] + 0.2), r[0] + r[2] - mw - 0.2);
        var my = Math.min(Math.max(best.y - mh / 2, r[1] + 0.2), r[1] + r[3] - mh - 0.2);
        // keep clear of the room label in the middle
        if (Math.abs(mx + mw / 2 - (r[0] + r[2] / 2)) < 0.9 && r[2] > 3) mx = best.x > r[0] + r[2] / 2 ? r[0] + r[2] - mw - 0.3 : r[0] + 0.3;
        svg.querySelector('.mat').innerHTML =
          '<rect x="' + p(mx) + '" y="' + p(my) + '" width="' + p(mw) + '" height="' + p(mh) + '" rx="6" fill="#fff" fill-opacity=".16" stroke="#fff" stroke-width="2"/>' +
          '<rect x="' + (p(mx) + 9) + '" y="' + (p(my) + 8) + '" width="' + (p(mw) - 18) + '" height="18" rx="5" fill="none" stroke="#fff" stroke-width="2"/>';
      }
    };
  }

  // The three questions about the flat. Calls onChange after every answer.
  function controls(el, onChange) {
    var groups = [
      ['facing', 'Living room windows face', [['N', 'North'], ['E', 'East'], ['S', 'South'], ['W', 'West']]],
      ['floor', 'Floor', [['ground', 'Ground'], ['middle', 'Middle'], ['top', 'Top']]],
      ['windows', 'Windows at night', [['open', 'Open'], ['shut', 'Shut']]]
    ];
    el.innerHTML = groups.map(function (g) {
      return '<div class="q"><div class="q-label">' + g[1] + '</div><div class="seg" role="group" aria-label="' + g[1] + '">' +
        g[2].map(function (o) { return '<button type="button" data-k="' + g[0] + '" data-v="' + o[0] + '">' + o[1] + '</button>'; }).join('') + '</div></div>';
    }).join('');
    var sync = function () {
      [].forEach.call(el.querySelectorAll('button'), function (b) { b.setAttribute('aria-pressed', state[b.dataset.k] === b.dataset.v); });
    };
    el.onclick = function (e) {
      var b = e.target.closest('button');
      if (!b) return;
      state[b.dataset.k] = b.dataset.v; save(); sync(); onChange();
    };
    sync();
  }

  window.Cool = {
    ROOMS: ROOMS, state: state, outdoor: outdoor, roomTemp: roomTemp, summary: summary, timeAt: timeAt, N: N,
    color: color, hhmm: hhmm, drawPlan: drawPlan, controls: controls
  };
})();
