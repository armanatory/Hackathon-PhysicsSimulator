/* Cable Reel Fire Risk — sample model + drawing helpers shared by the sketch pages.
   Everything here is a made-up closed-form stand-in for the Allsolve sweep results. */
(function () {
  var V = 230;        // mains voltage
  var T_LIMIT = 70;   // PVC insulation rating, °C
  var T_REF = 25;     // ambient the label ratings assume

  var REELS = [
    { id: 'r25', name: '25 m reel', spec: '1.5 mm²', length: 25, layers: 6, wound: 4.3, unwound: 13 },
    { id: 'r40', name: '40 m reel', spec: '1.5 mm²', length: 40, layers: 8, wound: 3.9, unwound: 13 },
    { id: 'r50', name: '50 m reel', spec: '2.5 mm²', length: 50, layers: 8, wound: 5.2, unwound: 16 }
  ];

  var APPLIANCES = [
    { name: 'Lawn mower', watts: 1200 },
    { name: 'Pressure washer', watts: 1800 },
    { name: 'Space heater', watts: 2000 },
    { name: 'Kettle', watts: 2200 },
    { name: 'EV trickle charger', watts: 2300 }
  ];

  // Largest current that keeps PVC at the limit, at reference ambient. u = fraction unrolled, 0..1.
  function imaxRef(reel, u) {
    return reel.wound + (reel.unwound - reel.wound) * Math.pow(u, 1.7);
  }
  function ambientFactor(amb) {
    return Math.sqrt(Math.max(T_LIMIT - amb, 0) / (T_LIMIT - T_REF));
  }
  function safeAmps(reel, u, amb) {
    return imaxRef(reel, u) * ambientFactor(amb);
  }
  // Steady-state hottest insulation temperature.
  function hotspot(reel, u, amps, amb) {
    var r = amps / imaxRef(reel, u);
    return amb + (T_LIMIT - T_REF) * r * r;
  }
  // Smallest unrolled fraction that is safe; null if the reel can't carry it at all.
  function minUnroll(reel, amps, amb) {
    var k = ambientFactor(amb);
    if (k <= 0) return null;
    var need = amps / k;
    if (need <= reel.wound) return 0;
    if (need > reel.unwound) return null;
    return Math.pow((need - reel.wound) / (reel.unwound - reel.wound), 1 / 1.7);
  }
  // Minutes until the insulation passes the limit; null if it never does.
  function minutesToLimit(reel, u, amps, amb) {
    var rise = hotspot(reel, u, amps, amb) - amb;
    var allowed = T_LIMIT - amb;
    if (rise <= allowed) return null;
    var tau = 6 + 34 * (1 - u);
    return -tau * Math.log(1 - allowed / rise);
  }

  var STOPS = [
    [20, [43, 76, 111]], [45, [58, 143, 160]], [62, [227, 178, 60]],
    [70, [242, 106, 27]], [90, [200, 38, 27]], [120, [110, 15, 31]]
  ];
  function tempColor(t) {
    if (t <= STOPS[0][0]) return 'rgb(' + STOPS[0][1].join(',') + ')';
    for (var i = 1; i < STOPS.length; i++) {
      if (t <= STOPS[i][0]) {
        var a = STOPS[i - 1], b = STOPS[i], f = (t - a[0]) / (b[0] - a[0]);
        return 'rgb(' + a[1].map(function (c, k) { return Math.round(c + (b[1][k] - c) * f); }).join(',') + ')';
      }
    }
    return 'rgb(' + STOPS[STOPS.length - 1][1].join(',') + ')';
  }
  function fmtTemp(t) { return t > 200 ? '200+' : String(Math.round(t)); }

  // Cut through the drum: every wound turn is a circle coloured by its temperature.
  function drawSection(svg, o) {
    var reel = o.reel, W = 20, L = reel.layers, total = W * L;
    var wound = Math.round((1 - o.u) * total);
    var hot = hotspot(reel, o.u, o.amps, o.amb);
    var nL = wound / W;
    var cy = 200, core = 40, r = 8.2, pitch = 19, lp = 16.4, x0 = 96;
    var inner = x0 + W * pitch + pitch / 2;
    var flange = core + L * lp + 22;

    var turns = [], max = 0;
    for (var j = 0; j < L; j++) {
      for (var i = 0; i < W; i++) {
        var idx = j * W + (j % 2 ? W - 1 - i : i);
        var t = { x: x0 + pitch * (i + 0.5) + (j % 2 ? pitch / 2 : 0), y: core + r + 2 + j * lp, on: idx < wound, s: 0 };
        if (t.on) {
          t.s = Math.max(Math.sin(Math.PI * (j + 0.8) / (nL + 1.1)), 0.15) * (0.6 + 0.4 * Math.sin(Math.PI * (i + 0.5) / W));
          if (t.s > max) { max = t.s; }
        }
        turns.push(t);
      }
    }

    var h = '';
    h += '<rect x="' + (x0 - 16) + '" y="' + (cy - flange) + '" width="16" height="' + flange * 2 + '" rx="4" fill="#14212b"/>';
    h += '<rect x="' + inner + '" y="' + (cy - flange) + '" width="16" height="' + flange * 2 + '" rx="4" fill="#14212b"/>';
    h += '<rect x="' + x0 + '" y="' + (cy - core) + '" width="' + (inner - x0) + '" height="' + core * 2 + '" fill="#33444f"/>';
    h += '<line x1="' + (x0 - 40) + '" x2="' + (inner + 56) + '" y1="' + cy + '" y2="' + cy + '" stroke="#8fa0ab" stroke-width="1" stroke-dasharray="14 4 2 4"/>';

    var best = null;
    turns.forEach(function (t) {
      [-1, 1].forEach(function (side) {
        var y = cy + side * t.y;
        if (!t.on) {
          h += '<circle cx="' + t.x + '" cy="' + y + '" r="' + (r - 1) + '" fill="none" stroke="#c2ccd4" stroke-dasharray="2 3"/>';
          return;
        }
        var temp = o.amb + (hot - o.amb) * t.s / max;
        h += '<circle cx="' + t.x + '" cy="' + y + '" r="' + r + '" fill="' + tempColor(temp) + '"/>';
        h += '<circle cx="' + t.x + '" cy="' + y + '" r="3" fill="#14212b" fill-opacity=".5"/>';
        if (side < 0 && t.s === max && !best) best = { x: t.x, y: y };
      });
    });

    var tx = inner + 34;
    if (best) {
      h += '<circle cx="' + best.x + '" cy="' + best.y + '" r="13" fill="none" stroke="#14212b" stroke-width="2"/>';
      h += '<path d="M' + (best.x + 13) + ' ' + best.y + ' H' + (tx - 6) + '" stroke="#14212b" stroke-width="1.5" fill="none"/>';
      h += '<text x="' + tx + '" y="' + (best.y - 4) + '" font-size="13" fill="#55646f">hot spot</text>';
      h += '<text x="' + tx + '" y="' + (best.y + 18) + '" font-size="22" font-weight="600" fill="#14212b">' + fmtTemp(hot) + ' °C</text>';
    } else {
      h += '<text x="' + (x0 + (inner - x0) / 2) + '" y="' + (cy - core - 30) + '" font-size="14" text-anchor="middle" fill="#55646f">drum empty — cable lies in free air at ' + fmtTemp(hot) + ' °C</text>';
    }
    h += '<text x="' + (inner + 62) + '" y="' + (cy + 4) + '" font-size="12" fill="#8fa0ab">axis</text>';

    svg.setAttribute('viewBox', '40 0 600 400');
    svg.innerHTML = h;
  }

  window.Reel = {
    V: V, T_LIMIT: T_LIMIT, T_REF: T_REF, REELS: REELS, APPLIANCES: APPLIANCES,
    safeAmps: safeAmps, hotspot: hotspot, minUnroll: minUnroll, minutesToLimit: minutesToLimit,
    tempColor: tempColor, fmtTemp: fmtTemp, drawSection: drawSection
  };
})();
