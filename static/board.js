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

/* ---------- theme palette & helpers ---------- */

var SB = {
  bg0: "#0a0420", bg1: "#2b0c52", bg2: "#5a1a8a",
  head1: "#7b2fe0", head2: "#4a1d96", border: "#9a5cf0",
  line: "#4a2a8a", row: "#1a0d3a", alt: "#241150",
  tot: "#3b1a7a", ns: "#5a1a8a", nsText: "#ffd6f6",
  dq: "#5b1d2b", dqText: "#ffd6e0",
  text: "#f2e9ff", subText: "#d9b8ff",
  tiers: { 1: ["#b980ff", "#1a0d3a"], 2: ["#9448ff", "#ffffff"], 3: ["#7b2fe0", "#ffffff"] }
};

function hexToHsl(hex) {
  hex = String(hex || "").replace(/^#/, "");
  if (!/^[0-9a-fA-F]{6}$/.test(hex)) hex = "7b2fe0";
  var r = parseInt(hex.slice(0, 2), 16) / 255;
  var g = parseInt(hex.slice(2, 4), 16) / 255;
  var b = parseInt(hex.slice(4, 6), 16) / 255;
  var max = Math.max(r, g, b), min = Math.min(r, g, b);
  var h = 0, s = 0, l = (max + min) / 2;
  if (max !== min) {
    var d = max - min;
    s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
    switch (max) {
      case r: h = (g - b) / d + (g < b ? 6 : 0); break;
      case g: h = (b - r) / d + 2; break;
      case b: h = (r - g) / d + 4; break;
    }
    h = Math.round(h * 60);
  }
  return [h, Math.round(s * 100), Math.round(l * 100)];
}

function hslStr(h, s, l) {
  return "hsl(" + ((h % 360) + 360) % 360 + "," + Math.max(0, Math.min(100, Math.round(s))) + "%," + Math.max(0, Math.min(100, Math.round(l))) + "%)";
}

function buildPalette(theme) {
  var c = (theme && typeof theme === "object" ? theme.color : theme) || "#7b2fe0";
  if (!/^#[0-9a-fA-F]{6}$/.test(String(c))) c = "#7b2fe0";
  var hsl = hexToHsl(c), h = hsl[0], s = Math.max(35, hsl[1]);
  return {
    bg: hslStr(h, s * 0.7, 7),
    bg0: hslStr(h, s * 0.75, 7),
    bg1: hslStr(h, s * 0.75, 18),
    bg2: hslStr(h, s * 0.65, 32),
    card: hslStr(h, s * 0.65, 14),
    cardBorder: hslStr(h, s * 0.55, 28),
    head1: c,
    head2: hslStr(h, s * 0.7, 28),
    border: hslStr(h, Math.min(100, s + 10), 65),
    line: hslStr(h, s * 0.55, 34),
    row: hslStr(h, s * 0.65, 14),
    alt: hslStr(h, s * 0.65, 19),
    tot: hslStr(h, s * 0.65, 26),
    ns: hslStr(h, s * 0.65, 32),
    nsText: hslStr(h, 90, 90),
    dq: "#5b1d2b",
    dqText: "#ffd6e0",
    text: hslStr(h, 60, 96),
    subText: hslStr(h, 75, 85),
    link: hslStr(h, 85, 80),
    tiers: {
      1: [hslStr(h, Math.min(100, s + 15), 75), hslStr(h, s * 0.7, 12)],
      2: [hslStr(h, Math.min(100, s + 10), 60), "#ffffff"],
      3: [c, "#ffffff"]
    }
  };
}

function applyTheme(theme) {
  var p = buildPalette(theme);
  SB.bg0 = p.bg0; SB.bg1 = p.bg1; SB.bg2 = p.bg2;
  SB.head1 = p.head1; SB.head2 = p.head2; SB.border = p.border;
  SB.line = p.line; SB.row = p.row; SB.alt = p.alt;
  SB.tot = p.tot; SB.ns = p.ns; SB.nsText = p.nsText;
  SB.text = p.text; SB.subText = p.subText; SB.tiers = p.tiers;
  if (typeof document !== "undefined" && document.documentElement) {
    var st = document.documentElement.style;
    st.setProperty("--th-bg", p.bg);
    st.setProperty("--th-card", p.card);
    st.setProperty("--th-card-border", p.cardBorder);
    st.setProperty("--th-head1", p.head1);
    st.setProperty("--th-head2", p.head2);
    st.setProperty("--th-border", p.border);
    st.setProperty("--th-line", p.line);
    st.setProperty("--th-row", p.row);
    st.setProperty("--th-alt", p.alt);
    st.setProperty("--th-tot", p.tot);
    st.setProperty("--th-ns", p.ns);
    st.setProperty("--th-ns-text", p.nsText);
    st.setProperty("--th-text", p.text);
    st.setProperty("--th-link", p.link);
    st.setProperty("--th-t1-bg", p.tiers[1][0]);
    st.setProperty("--th-t1-fg", p.tiers[1][1]);
    st.setProperty("--th-t2-bg", p.tiers[2][0]);
    st.setProperty("--th-t2-fg", p.tiers[2][1]);
    st.setProperty("--th-t3-bg", p.tiers[3][0]);
    st.setProperty("--th-t3-fg", p.tiers[3][1]);
  }
}

function fitTeamNames(container) {
  if (!container || !container.querySelectorAll) return;
  var cells = container.querySelectorAll(".sb-t td.l");
  cells.forEach(function (td) {
    var nameEl = td.querySelector(".sb-team-name") || td;
    var text = (nameEl.textContent || "").trim();
    if (text.length > 22) nameEl.style.fontSize = "11px";
    else if (text.length > 16) nameEl.style.fontSize = "12px";
    else nameEl.style.fontSize = "";
  });
}

/* ---------- logo image cache for canvas ---------- */

var LOGO_CACHE = {};

function resolveLogoSrc(logo) {
  logo = String(logo || "").trim();
  if (!logo) return "";
  if (logo.indexOf("/uploads/") === 0) return logo;
  if (logo.indexOf("https://") === 0) return "/api/logo-proxy?u=" + encodeURIComponent(logo);
  return "";
}

function loadLogoImage(logo, onLoaded) {
  var src = resolveLogoSrc(logo);
  if (!src) return null;
  var entry = LOGO_CACHE[src];
  if (entry) {
    if (entry.done) return entry.ok ? entry.img : null;
    if (onLoaded) entry.cbs.push(onLoaded);
    return null;
  }
  var img = new Image();
  img.crossOrigin = "anonymous";
  entry = LOGO_CACHE[src] = { img: img, done: false, ok: false, cbs: onLoaded ? [onLoaded] : [] };
  img.onload = function () {
    entry.done = true;
    entry.ok = true;
    var list = entry.cbs.slice();
    entry.cbs = [];
    list.forEach(function (fn) { try { fn(); } catch (e) {} });
  };
  img.onerror = function () {
    entry.done = true;
    entry.ok = false;
    var list = entry.cbs.slice();
    entry.cbs = [];
    list.forEach(function (fn) { try { fn(); } catch (e) {} });
  };
  img.src = src;
  return null;
}

function ensureLogosLoaded(rows, callback) {
  var urls = [];
  (rows || []).forEach(function (r) {
    var src = resolveLogoSrc(r && r.logo);
    if (src && urls.indexOf(src) === -1) urls.push(src);
  });
  var pending = 0, fired = false;
  function checkDone() {
    if (!fired && pending <= 0) {
      fired = true;
      callback();
    }
  }
  urls.forEach(function (u) {
    var entry = LOGO_CACHE[u];
    if (entry && entry.done) return;
    pending++;
    loadLogoImage(u, function () {
      pending--;
      checkDone();
    });
  });
  checkDone();
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
  meta = meta || {};
  rows = rows || [];
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
      logo: r.logo || "",
      total: r.total,
      games: r.games.map(function (g) {
        return { ns: g.noshow, dq: g.dq, pp: g.place_pts, kp: g.points - g.place_pts };
      })
    });
  }

  // teams on the same points share a rank
  var lb = rows.map(function (r) {
    var rank = 1;
    rows.forEach(function (o) { if (o.total > r.total) rank++; });
    var scored = r.total > 0;
    var tier = scored && rank <= 3 ? rank : 0;
    var label = !scored ? ordinal(rank) : rank === 1 ? "CHAMPION" : rank <= 3 ? ordinal(rank).toUpperCase() + " PLACE" : ordinal(rank);
    return { rank: rank, label: label, tier: tier, name: r.name, logo: r.logo || "", kills: r.kills || 0, place_pts: r.place_pts || 0, total: r.total };
  });

  return { games: games, n: n, left: left, lb: lb, title: String(meta.title || "").toUpperCase(), date: fmtDate(meta.date) };
}

/* ---------- HTML board (public page and admin) ---------- */

function teamCellHTML(name, logo) {
  if (!name) return "";
  var img = logo ? '<img class="sb-logo" src="' + esc(logo) + '" alt="" loading="lazy" onerror="this.style.display=\'none\'">' : "";
  return '<span class="sb-team-cell">' + img + '<span class="sb-team-name">' + esc(name) + "</span></span>";
}

function boardHTML(rows, meta) {
  if (meta && meta.theme) applyTheme(meta.theme);
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
    h += '<tr class="' + (k % 2 ? "alt" : "") + (r.empty ? " empty" : "") + '"><td class="sk1">' + r.slot + '</td><td class="l sk2">' + (r.empty ? "" : teamCellHTML(r.name, r.logo)) + "</td>";
    for (var q = 0; q < m.games; q++) {
      var c = r.empty ? null : r.games[q];
      if (!c) h += "<td></td><td></td>";
      else if (c.dq) h += '<td colspan="2" class="sb-dq">DQ</td>';
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
    h += '<tr class="' + (t.tier ? "t" + t.tier : i % 2 ? "alt" : "") + '"><td>' + esc(t.label) + '</td><td class="l">' + teamCellHTML(t.name, t.logo) + "</td><td>" + t.total + "</td></tr>";
  }
  h += "</table></div></div>";
  return h;
}

/* ---------- image (canvas) ---------- */

function drawBoard(rows, meta, onAsyncLogoLoad) {
  if (meta && meta.theme) applyTheme(meta.theme);
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
  bg.addColorStop(0, SB.bg0);
  bg.addColorStop(0.55, SB.bg1);
  bg.addColorStop(1, SB.bg2);
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
    var logoImg = o.logo ? loadLogoImage(o.logo, onAsyncLogoLoad) : null;
    var padLeft = 10;
    if (logoImg) {
      var lSize = Math.min(h - 8, 22);
      var ly = cy + (h - lSize) / 2;
      try { x.drawImage(logoImg, cx + 8, ly, lSize, lSize); } catch (e) {}
      padLeft = 8 + lSize + 6;
    }
    x.fillStyle = o.color || SB.text;
    x.font = (o.font || "14px ") + font;
    x.textAlign = o.align || "center";
    var tx = o.align === "left" ? cx + padLeft : cx + w / 2;
    var availW = o.align === "left" ? w - padLeft - 8 : w - 16;
    x.fillText(fitText(x, String(text), availW), tx, cy + h / 2 + 1);
  }

  function titleBar(cx, w, text) {
    var g = x.createLinearGradient(cx, 0, cx + w, 0);
    g.addColorStop(0, SB.head2);
    g.addColorStop(0.5, SB.head1);
    g.addColorStop(1, SB.head2);
    x.fillStyle = g;
    x.fillRect(cx, pad, w, titleH);
    x.strokeStyle = SB.border;
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
    cell(lx + cSlot, y, cTeam, rowH, fill, r.empty ? "" : r.name, { align: "left", font: "600 15px ", logo: r.empty ? "" : r.logo });
    for (var q = 0; q < m.games; q++) {
      var cx = gx + q * (cPP + cKP), cl = r.empty ? null : r.games[q];
      if (!cl) { cell(cx, y, cPP, rowH, fill, ""); cell(cx + cPP, y, cKP, rowH, fill, ""); }
      else if (cl.dq) cell(cx, y, cPP + cKP, rowH, SB.dq, "DQ", { font: "bold 14px ", color: SB.dqText });
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
    cell(rx + cRank, y, cName, rowH, fill, t ? t.name : "", { color: col, font: t && t.tier ? "bold 15px " : "600 15px ", align: "left", logo: t ? t.logo : "" });
    cell(rx + cRank + cName, y, cPts, rowH, fill, t ? t.total : "", { color: col, font: "bold 16px " });
  }

  var pp = (meta.placement_points || []).map(function (p, k) { return ordinal(k + 1) + " " + p; }).join("  •  ");
  x.textAlign = "center";
  x.fillStyle = SB.subText;
  x.font = "16px " + font;
  x.fillText(fitText(x, "Placement: " + pp + "  •  1 kill = " + meta.kill_points, W - 2 * pad), W / 2, H - foot / 2 - 2);
  return c;
}

function showPreview(rows, meta, container) {
  if (!container) return;
  var redrawTimer = null;
  function renderCanvas() {
    container.innerHTML = "";
    container.appendChild(drawBoard(rows, meta, function () {
      clearTimeout(redrawTimer);
      redrawTimer = setTimeout(renderCanvas, 60);
    }));
  }
  renderCanvas();
}

function triggerCanvasDownload(canvas, filename) {
  canvas.toBlob(function (b) {
    if (!b) return;
    var a = document.createElement("a");
    a.href = URL.createObjectURL(b);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
  }, "image/png");
}

function downloadBoard(rows, meta) {
  ensureLogosLoaded(rows, function () {
    var c = drawBoard(rows, meta);
    var name = (((meta && meta.title) || "standings").replace(/[^\w]+/g, "_")) + ".png";
    triggerCanvasDownload(c, name);
  });
}

/* ---------- Top 3 Podium Poster ---------- */

function drawPodium(rows, meta) {
  if (meta && meta.theme) applyTheme(meta.theme);
  var m = sbModel(rows, meta);
  var W = 960, H = 560, sc = 2;
  var c = document.createElement("canvas");
  c.width = W * sc;
  c.height = H * sc;
  var x = c.getContext("2d");
  x.scale(sc, sc);

  var bg = x.createLinearGradient(0, 0, W, H);
  bg.addColorStop(0, SB.bg0);
  bg.addColorStop(0.5, SB.bg1);
  bg.addColorStop(1, SB.bg2);
  x.fillStyle = bg;
  x.fillRect(0, 0, W, H);

  var font = '"Segoe UI",Arial,sans-serif';
  x.textBaseline = "middle";
  x.textAlign = "center";

  // Header
  x.fillStyle = "#ffffff";
  x.font = "800 34px " + font;
  x.fillText(fitText(x, (m.title || "SCRIM") + " — TOP 3 PODIUM", W - 80), W / 2, 52);
  if (m.date) {
    x.fillStyle = SB.subText;
    x.font = "bold 16px " + font;
    x.fillText(m.date, W / 2, 90);
  }

  // Podium slots: 2nd (left), 1st (center, taller), 3rd (right)
  var top3 = [m.lb[1] || null, m.lb[0] || null, m.lb[2] || null];
  var ranks = [2, 1, 3];
  var labels = ["2ND PLACE", "CHAMPION", "3RD PLACE"];
  var medals = ["#d8e2ef", "#ffd54a", "#e59866"];
  var cardW = 260, gap = 30;
  var startX = (W - (cardW * 3 + gap * 2)) / 2;
  var heights = [310, 355, 285];
  var baseY = 495;

  for (var idx = 0; idx < 3; idx++) {
    var t = top3[idx], rnk = ranks[idx], ch = heights[idx];
    var cx = startX + idx * (cardW + gap), cy = baseY - ch;
    var tierColors = SB.tiers[rnk] || [SB.head1, "#ffffff"];

    // Card background
    x.fillStyle = SB.row;
    x.fillRect(cx, cy, cardW, ch);
    x.strokeStyle = tierColors[0];
    x.lineWidth = 3;
    x.strokeRect(cx + 1.5, cy + 1.5, cardW - 3, ch - 3);

    // Top banner
    x.fillStyle = tierColors[0];
    x.fillRect(cx, cy, cardW, 48);
    x.fillStyle = tierColors[1];
    x.font = "800 18px " + font;
    x.fillText(labels[idx], cx + cardW / 2, cy + 24);

    if (t) {
      var logoImg = t.logo ? loadLogoImage(t.logo) : null;
      var contentY = cy + 115;
      if (logoImg) {
        var lSize = 84;
        try { x.drawImage(logoImg, cx + (cardW - lSize) / 2, cy + 68, lSize, lSize); } catch (e) {}
        contentY = cy + 185;
      } else {
        // Medal circle fallback
        x.beginPath();
        x.arc(cx + cardW / 2, cy + 110, 36, 0, Math.PI * 2);
        x.fillStyle = medals[idx];
        x.fill();
        x.fillStyle = "#1a0d3a";
        x.font = "800 26px " + font;
        x.fillText("#" + rnk, cx + cardW / 2, cy + 111);
        contentY = cy + 180;
      }

      x.fillStyle = "#ffffff";
      x.font = "800 22px " + font;
      x.fillText(fitText(x, t.name, cardW - 24), cx + cardW / 2, contentY);

      x.fillStyle = tierColors[0];
      x.font = "800 32px " + font;
      x.fillText(t.total + " PTS", cx + cardW / 2, contentY + 46);

      x.fillStyle = SB.subText;
      x.font = "600 14px " + font;
      x.fillText(t.place_pts + " PP  •  " + (t.total - t.place_pts) + " KP", cx + cardW / 2, contentY + 80);
    } else {
      x.fillStyle = SB.subText;
      x.font = "600 18px " + font;
      x.fillText("TBD", cx + cardW / 2, cy + ch / 2 + 12);
    }
  }

  return c;
}

function downloadPodium(rows, meta) {
  ensureLogosLoaded(rows, function () {
    var c = drawPodium(rows, meta);
    var name = (((meta && meta.title) || "standings").replace(/[^\w]+/g, "_")) + "_top3.png";
    triggerCanvasDownload(c, name);
  });
}
