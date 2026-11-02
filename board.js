function esc(s) {
  return String(s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  });
}

function ordinal(n) {
  var s = ["th", "st", "nd", "rd"], v = n % 100;
  return n + (s[(v - 20) % 10] || s[v] || s[0]);
}

function fitText(ctx, text, maxW) {
  if (ctx.measureText(text).width <= maxW) return text;
  while (text.length > 1 && ctx.measureText(text + "…").width > maxW) text = text.slice(0, -1);
  return text + "…";
}

/* ---------- shared data for the HTML board and the image ---------- */

var MONTHS = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"];
var DAYS = ["SUNDAY", "MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY"];

// "10/27/2026" or "2026-10-27" -> "OCTOBER 27, 2026 | TUESDAY"; anything else is shown as typed
function fmtDate(s) {
  s = String(s || "").trim();
  if (!s) return "";
  var m, y, mo, d;
  if ((m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})$/))) { y = +m[1]; mo = +m[2]; d = +m[3]; }
  else if ((m = s.match(/^(\d{1,2})\/(\d{1,2})\/(\d{4})$/))) {
    y = +m[3]; mo = +m[1]; d = +m[2];
    if (mo > 12) { var t = mo; mo = d; d = t; }
  } else return s.toUpperCase();
  var dt = new Date(y, mo - 1, d);
  if (mo < 1 || mo > 12 || dt.getMonth() !== mo - 1) return s.toUpperCase();
  return MONTHS[mo - 1] + " " + d + ", " + y + " | " + DAYS[dt.getDay()];
}

function sbModel(rows, meta) {
  var games = meta.games || (rows[0] ? rows[0].games.length : 1);
  var bySlot = {}, maxSlot = 0;
  rows.forEach(function (r) {
    bySlot[r.slot] = r;
    if (r.slot > maxSlot) maxSlot = r.slot;
  });
  var n = Math.max(meta.slots || 0, maxSlot, 1);

  var left = [];
  for (var s = 1; s <= n; s++) {
    var r = bySlot[s];
    if (!r) { left.push({ slot: s, empty: true }); continue; }
    left.push({
      slot: s,
      name: r.name,
      total: r.total,
      games: r.games.map(function (g) { return { ns: g.noshow, pp: g.place_pts, kp: g.points - g.place_pts }; })
    });
  }

  // teams on the same points share a rank
  var lb = rows.map(function (r) {
    var rank = 1;
    rows.forEach(function (o) { if (o.total > r.total) rank++; });
    var scored = r.total > 0;
    var tier = scored && rank <= 3 ? rank : 0;
    var label = !scored ? ordinal(rank) : rank === 1 ? "CHAMPION" : rank <= 3 ? ordinal(rank).toUpperCase() + " PLACE" : ordinal(rank);
    return { rank: rank, label: label, tier: tier, name: r.name, total: r.total };
  });

  return { games: games, n: n, left: left, lb: lb, title: String(meta.title || "").toUpperCase(), date: fmtDate(meta.date) };
}

/* ---------- HTML board (public page and admin) ---------- */

function boardHTML(rows, meta) {
  var m = sbModel(rows, meta), g, i, h = "";
  h += '<div class="sb">';

  h += '<div class="sb-panel"><div class="sb-title">' + esc(m.title || "SCRIM") + '</div><div class="sb-scroll"><table class="sb-t">';
  h += '<tr class="sb-h1"><th colspan="2" class="sb-date sk">' + esc(m.date) + "</th>";
  for (g = 1; g <= m.games; g++) h += '<th colspan="2">GAME ' + g + "</th>";
  h += '<th rowspan="2" class="sb-tot-h">TOTAL</th></tr>';
  h += '<tr class="sb-h2"><th class="sk1">SLOT</th><th class="sk2">TEAMS</th>';
  for (g = 1; g <= m.games; g++) h += "<th>PP</th><th>KP</th>";
  h += "</tr>";
  m.left.forEach(function (r, k) {
    h += '<tr class="' + (k % 2 ? "alt" : "") + (r.empty ? " empty" : "") + '"><td class="sk1">' + r.slot + '</td><td class="l sk2">' + (r.empty ? "" : esc(r.name)) + "</td>";
    for (var q = 0; q < m.games; q++) {
      var c = r.empty ? null : r.games[q];
      if (!c) h += "<td></td><td></td>";
      else if (c.ns) h += '<td colspan="2" class="sb-ns">NO SHOW</td>';
      else h += "<td>" + c.pp + "</td><td>" + c.kp + "</td>";
    }
    h += '<td class="sb-tot">' + (r.empty ? "" : r.total) + "</td></tr>";
  });
  h += "</table></div></div>";

  h += '<div class="sb-panel sb-right"><div class="sb-title">LEADERBOARD</div><table class="sb-t sb-lb">';
  h += '<tr class="sb-hl"><th>RANK</th><th>TEAM NAME</th><th>POINTS</th></tr>';
  for (i = 0; i < m.n; i++) {
    var t = m.lb[i];
    if (!t) { h += '<tr class="' + (i % 2 ? "alt " : "") + 'empty"><td></td><td></td><td></td></tr>'; continue; }
    h += '<tr class="' + (t.tier ? "t" + t.tier : i % 2 ? "alt" : "") + '"><td>' + esc(t.label) + '</td><td class="l">' + esc(t.name) + "</td><td>" + t.total + "</td></tr>";
  }
  h += "</table></div></div>";
  return h;
}

/* ---------- image (canvas) ---------- */

var SB = {
  head1: "#7b2fe0", head2: "#4a1d96", line: "#4a2a8a", row: "#1a0d3a", alt: "#241150",
  tot: "#3b1a7a", ns: "#5a1a8a", nsText: "#ffd6f6", text: "#f2e9ff",
  tiers: { 1: ["#b980ff", "#1a0d3a"], 2: ["#9448ff", "#ffffff"], 3: ["#7b2fe0", "#ffffff"] }
};

function drawBoard(rows, meta) {
  var m = sbModel(rows, meta);
  var pad = 28, gap = 18, rowH = 34, titleH = 58, h1 = 34, h2 = 30, headH = h1 + h2, foot = 46, sc = 2;
  var cSlot = 56, cTeam = 250, cPP = 54, cKP = 54, cTot = 92;
  var cRank = 150, cName = 250, cPts = 100;
  var leftW = cSlot + cTeam + m.games * (cPP + cKP) + cTot;
  var rightW = cRank + cName + cPts;
  var W = pad * 2 + leftW + gap + rightW;
  var H = pad + titleH + headH + m.n * rowH + foot;

  var c = document.createElement("canvas");
  c.width = W * sc;
  c.height = H * sc;
  var x = c.getContext("2d");
  x.scale(sc, sc);

  var bg = x.createLinearGradient(0, 0, W, H);
  bg.addColorStop(0, "#0a0420");
  bg.addColorStop(0.55, "#2b0c52");
  bg.addColorStop(1, "#5a1a8a");
  x.fillStyle = bg;
  x.fillRect(0, 0, W, H);

  var font = '"Segoe UI",Arial,sans-serif';
  x.textBaseline = "middle";
  x.lineWidth = 1;

  function cell(cx, cy, w, h, fill, text, o) {
    o = o || {};
    x.fillStyle = fill;
    x.fillRect(cx, cy, w, h);
    x.strokeStyle = SB.line;
    x.strokeRect(cx + 0.5, cy + 0.5, w - 1, h - 1);
    if (text === "" || text == null) return;
    x.fillStyle = o.color || SB.text;
    x.font = (o.font || "14px ") + font;
    x.textAlign = o.align || "center";
    var tx = o.align === "left" ? cx + 10 : cx + w / 2;
    x.fillText(fitText(x, String(text), w - 16), tx, cy + h / 2 + 1);
  }

  function titleBar(cx, w, text) {
    var g = x.createLinearGradient(cx, 0, cx + w, 0);
    g.addColorStop(0, "#4a1d96");
    g.addColorStop(0.5, "#7b2fe0");
    g.addColorStop(1, "#4a1d96");
    x.fillStyle = g;
    x.fillRect(cx, pad, w, titleH);
    x.strokeStyle = "#9a5cf0";
    x.strokeRect(cx + 0.5, pad + 0.5, w - 1, titleH - 1);
    x.fillStyle = "#ffffff";
    x.font = "800 30px " + font;
    x.textAlign = "center";
    if ("letterSpacing" in x) x.letterSpacing = "2px";
    x.fillText(fitText(x, text, w - 20), cx + w / 2, pad + titleH / 2 + 1);
    if ("letterSpacing" in x) x.letterSpacing = "0px";
  }

  var lx = pad, rx = pad + leftW + gap, y0 = pad + titleH, i, g;

  /* left panel */
  titleBar(lx, leftW, m.title || "SCRIM");
  cell(lx, y0, cSlot + cTeam, h1, SB.head1, m.date, { font: "bold 14px " });
  var gx = lx + cSlot + cTeam;
  for (g = 0; g < m.games; g++) {
    cell(gx + g * (cPP + cKP), y0, cPP + cKP, h1, SB.head1, "GAME " + (g + 1), { font: "bold 15px " });
    cell(gx + g * (cPP + cKP), y0 + h1, cPP, h2, SB.head2, "PP", { font: "bold 13px " });
    cell(gx + g * (cPP + cKP) + cPP, y0 + h1, cKP, h2, SB.head2, "KP", { font: "bold 13px " });
  }
  cell(lx, y0 + h1, cSlot, h2, SB.head2, "SLOT", { font: "bold 13px " });
  cell(lx + cSlot, y0 + h1, cTeam, h2, SB.head2, "TEAMS", { font: "bold 13px " });
  var tx0 = lx + leftW - cTot;
  cell(tx0, y0, cTot, headH, SB.head1, "TOTAL", { font: "800 20px " });

  m.left.forEach(function (r, k) {
    var y = y0 + headH + k * rowH, fill = k % 2 ? SB.alt : SB.row;
    cell(lx, y, cSlot, rowH, fill, r.slot);
    cell(lx + cSlot, y, cTeam, rowH, fill, r.empty ? "" : r.name, { align: "left", font: "600 15px " });
    for (var q = 0; q < m.games; q++) {
      var cx = gx + q * (cPP + cKP), cl = r.empty ? null : r.games[q];
      if (!cl) { cell(cx, y, cPP, rowH, fill, ""); cell(cx + cPP, y, cKP, rowH, fill, ""); }
      else if (cl.ns) cell(cx, y, cPP + cKP, rowH, SB.ns, "NO SHOW", { font: "bold 14px ", color: SB.nsText });
      else { cell(cx, y, cPP, rowH, fill, cl.pp); cell(cx + cPP, y, cKP, rowH, fill, cl.kp); }
    }
    cell(tx0, y, cTot, rowH, SB.tot, r.empty ? "" : r.total, { font: "bold 18px " });
  });

  /* right panel */
  titleBar(rx, rightW, "LEADERBOARD");
  cell(rx, y0, cRank, headH, SB.head1, "RANK", { font: "bold 16px " });
  cell(rx + cRank, y0, cName, headH, SB.head1, "TEAM NAME", { font: "bold 16px " });
  cell(rx + cRank + cName, y0, cPts, headH, SB.head1, "POINTS", { font: "bold 16px " });
  for (i = 0; i < m.n; i++) {
    var y = y0 + headH + i * rowH, t = m.lb[i], fill = i % 2 ? SB.alt : SB.row, col = SB.text, f = "14px ";
    if (t && t.tier) { fill = SB.tiers[t.tier][0]; col = SB.tiers[t.tier][1]; f = "bold 15px "; }
    cell(rx, y, cRank, rowH, fill, t ? t.label : "", { color: col, font: f });
    cell(rx + cRank, y, cName, rowH, fill, t ? t.name : "", { color: col, font: t && t.tier ? "bold 15px " : "600 15px ", align: "left" });
    cell(rx + cRank + cName, y, cPts, rowH, fill, t ? t.total : "", { color: col, font: "bold 16px " });
  }

  var pp = (meta.placement_points || []).map(function (p, k) { return ordinal(k + 1) + " " + p; }).join("  •  ");
  x.textAlign = "center";
  x.fillStyle = "#d9b8ff";
  x.font = "16px " + font;
  x.fillText(fitText(x, "Placement: " + pp + "  •  1 kill = " + meta.kill_points, W - 2 * pad), W / 2, H - foot / 2 - 2);
  return c;
}

function showPreview(rows, meta, container) {
  container.innerHTML = "";
  container.appendChild(drawBoard(rows, meta));
}

function downloadBoard(rows, meta) {
  var c = drawBoard(rows, meta);
  c.toBlob(function (b) {
    var a = document.createElement("a");
    a.href = URL.createObjectURL(b);
    a.download = ((meta.title || "standings").replace(/[^\w]+/g, "_")) + ".png";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  }, "image/png");
}
