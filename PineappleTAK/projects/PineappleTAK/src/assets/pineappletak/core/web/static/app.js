/* PagerTAK web console. Plain JS + Leaflet, no build step. All text from TAK
   (callsigns, chat) is untrusted and is only ever inserted with textContent. */
"use strict";

const TEAMS = ["White", "Yellow", "Orange", "Magenta", "Red", "Maroon", "Purple", "Dark Blue", "Blue", "Cyan",
  "Teal", "Green", "Dark Green", "Brown"];
const TEAM_RGB = { "White": "#ffffff", "Yellow": "#ffff00", "Orange": "#ff8000", "Magenta": "#ff00ff", "Red": "#ff0000",
  "Maroon": "#800000", "Purple": "#800080", "Dark Blue": "#0000a0", "Blue": "#0050ff", "Cyan": "#00ffff",
  "Teal": "#008080", "Green": "#00c800", "Dark Green": "#006400", "Brown": "#8b4513" };
const ROLES = ["Team Member", "Team Lead", "HQ", "Sniper", "Medic", "Forward Observer", "RTO", "K9"];
const AFF = { f: "#3b8cff", h: "#ff3b30", s: "#ff9500", u: "#ffd60a", n: "#34c759" };
const ALL = "All Chat Rooms";

let S = null;                 // last /api/state
let map, baseLayer, meMarker, meCircle;
const markers = new Map();    // track id -> marker
let sources = [], follow = true, labels = true, pickCb = null;
const PRODUCT = document.title || "PagerTAK";   // PagerTAK, PineappleTAK... (set by the server)
let chatSig = "", chatSeen = 0, alertSeen = 0, tab = "chat", formsFilled = false;

// ---------------------------------------------------------------- helpers
function lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
function el(tag, attrs, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "text") e.textContent = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of kids.flat()) if (c !== null && c !== undefined && c !== false) e.append(c.nodeType ? c : document.createTextNode(c));
  return e;
}
function toast(msg, ok = true) {
  const t = $("#toast");
  t.textContent = msg; t.className = "toast " + (ok ? "ok" : "bad");
  clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.add("hidden"), 4500);
}
async function api(path, body) {
  const opt = { credentials: "same-origin", headers: {} };
  if (body !== undefined) {
    opt.method = "POST"; opt.headers["Content-Type"] = "application/json"; opt.headers["X-PagerTAK"] = "1";
    opt.body = JSON.stringify(body);
  }
  const r = await fetch(path, opt);
  if (r.status === 401 && path !== "/api/login") { showLogin(); throw new Error("login"); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok && path === "/api/login") throw new Error(j.error || "Sign-in failed");
  return j;
}
async function cmd(c, fields = {}, quiet = false) {
  try {
    const r = await api("/api/cmd", Object.assign({ cmd: c }, fields));
    if (!quiet || !r.ok) toast(r.msg || (r.ok ? "Done" : "Failed"), r.ok);
    poll(true);
    return r;
  } catch (e) { if (e.message !== "login") toast("Device not reachable", false); return { ok: false }; }
}
function age(ts) {
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return s + "s"; if (s < 3600) return Math.round(s / 60) + "m"; return Math.round(s / 3600) + "h";
}
function distBrg(a, b) {
  const R = 6371000, r = Math.PI / 180, p1 = a.lat * r, p2 = b.lat * r, dp = p2 - p1, dl = (b.lon - a.lon) * r;
  const h = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  const d = 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
  const y = Math.sin(dl) * Math.cos(p2), x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return [d, (Math.atan2(y, x) / r + 360) % 360];
}
const fmtDist = m => m < 1000 ? Math.round(m) + " m" : m < 10000 ? (m / 1000).toFixed(1) + " km" : Math.round(m / 1000) + " km";
const DIRS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
const ll = (lat, lon) => lat.toFixed(5) + ", " + lon.toFixed(5);
// MGRS (WGS84, 1 m) - same maths as include/geo.awk
function mgrs(lat, lon) {
  if (lat < -80 || lat > 84) return "N/A";
  const a = 6378137, f = 1 / 298.257223563, k0 = 0.9996, e2 = f * (2 - f), ep2 = e2 / (1 - e2), r = Math.PI / 180;
  let zone = Math.min(60, Math.floor((lon + 180) / 6) + 1);
  if (lat >= 56 && lat < 64 && lon >= 3 && lon < 12) zone = 32;
  if (lat >= 72) { if (lon >= 0 && lon < 9) zone = 31; else if (lon >= 9 && lon < 21) zone = 33; else if (lon >= 21 && lon < 33) zone = 35; else if (lon >= 33 && lon < 42) zone = 37; }
  const lon0 = ((zone - 1) * 6 - 180 + 3) * r, phi = lat * r, lam = lon * r;
  const N = a / Math.sqrt(1 - e2 * Math.sin(phi) ** 2), T = Math.tan(phi) ** 2, C = ep2 * Math.cos(phi) ** 2, A = Math.cos(phi) * (lam - lon0);
  const M = a * ((1 - e2 / 4 - 3 * e2 ** 2 / 64 - 5 * e2 ** 3 / 256) * phi - (3 * e2 / 8 + 3 * e2 ** 2 / 32 + 45 * e2 ** 3 / 1024) * Math.sin(2 * phi)
    + (15 * e2 ** 2 / 256 + 45 * e2 ** 3 / 1024) * Math.sin(4 * phi) - (35 * e2 ** 3 / 3072) * Math.sin(6 * phi));
  const E = k0 * N * (A + (1 - T + C) * A ** 3 / 6 + (5 - 18 * T + T * T + 72 * C - 58 * ep2) * A ** 5 / 120) + 500000;
  let Nn = k0 * (M + N * Math.tan(phi) * (A * A / 2 + (5 - T + 9 * C + 4 * C * C) * A ** 4 / 24 + (61 - 58 * T + T * T + 600 * C - 330 * ep2) * A ** 6 / 720));
  if (lat < 0) Nn += 10000000;
  const band = "CDEFGHJKLMNPQRSTUVWXX"[Math.floor((lat + 80) / 8)];
  const set = (zone - 1) % 6 + 1, colL = set % 3 === 1 ? "ABCDEFGH" : set % 3 === 2 ? "JKLMNPQR" : "STUVWXYZ", rowL = "ABCDEFGHJKLMNPQRSTUV";
  const col = colL[Math.floor(E / 100000) - 1], row = rowL[((Math.floor(Nn / 100000) % 20) + (set % 2 === 0 ? 5 : 0)) % 20];
  const p5 = n => String(Math.floor(n) % 100000).padStart(5, "0");
  return zone + band + " " + col + row + " " + p5(E) + " " + p5(Nn);
}
const fmtPos = (lat, lon) => (lsGet("ptak.coords") || "mgrs") === "mgrs" ? mgrs(lat, lon) : ll(lat, lon);

function dtg() {
  const d = new Date(), p = n => String(n).padStart(2, "0");
  const mon = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"][d.getUTCMonth()];
  return p(d.getUTCDate()) + p(d.getUTCHours()) + p(d.getUTCMinutes()) + "Z " + mon + " " + String(d.getUTCFullYear()).slice(2);
}
const haveMe = () => S && S.self && S.self.lat !== null && S.self.lat !== undefined;

// ---------------------------------------------------------------- login
function showLogin(msg) {
  $("#app").classList.add("hidden"); $("#login").classList.remove("hidden");
  $("#login-err").textContent = msg || ""; $("#login-pw").focus();
}
$("#login-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  $("#login-err").textContent = "";
  try { await api("/api/login", { password: $("#login-pw").value }); $("#login-pw").value = ""; start(); }
  catch (e) { $("#login-err").textContent = e.message; }
});
$("#b-logout").addEventListener("click", async () => { await api("/api/logout", {}).catch(() => {}); location.reload(); });

// ---------------------------------------------------------------- map
function tileMode() { const m = lsGet("ptak.tiles"); return ["auto", "device", "direct"].includes(m) ? m : "auto"; }
function srcLayer(src) {
  const mode = tileMode();
  const opts = { maxZoom: 20, maxNativeZoom: Math.min(src.maxz || 18, 19), minZoom: 2, attribution: src.name, keepBuffer: 1 };
  if (/usgs|nationalmap/i.test(src.url)) opts.attribution = "USGS The National Map";
  if (mode === "device") return L.tileLayer("/tiles/" + src.slug + "/{z}/{x}/{y}.png?fetch=1", opts);
  if (mode === "auto") {
    // the Pager serves what it has cached and redirects the rest to the internet (caching a copy behind you);
    // if the browser itself is offline, retry through the Pager
    const lyr = L.tileLayer("/tiles/" + src.slug + "/{z}/{x}/{y}.png", opts);
    lyr.on("tileerror", e => {
      const img = e.tile;
      if (img._retried) return;
      img._retried = true;
      img.src = "/tiles/" + src.slug + "/" + e.coords.z + "/" + e.coords.x + "/" + e.coords.y + ".png?fetch=1";
    });
    return lyr;
  }
  const Direct = L.TileLayer.extend({
    getTileUrl(c) {
      let q = "";
      for (let i = c.z; i > 0; i--) { let d = 0; const m = 1 << (i - 1); if (c.x & m) d++; if (c.y & m) d += 2; q += d; }
      const parts = src.parts && src.parts.length ? src.parts : ["a", "b", "c"];
      return src.url.replace("{z}", c.z).replace("{x}", c.x).replace("{y}", c.y).replace("{q}", q)
        .replace("{s}", parts[(c.x + c.y) % parts.length]);
    }
  });
  return new Direct("", opts);
}
function setSource(slug) {
  const src = sources.find(s => s.slug === slug) || sources[0];
  if (!src) return;
  if (baseLayer) map.removeLayer(baseLayer);
  baseLayer = srcLayer(src).addTo(map);
  $("#m-source").value = src.slug;
  lsSet("ptak.source", src.slug);
}
async function initMap() {
  map = L.map("map", { zoomControl: true, worldCopyJump: true }).setView([39.5, -98.35], 4);
  map.attributionControl.setPrefix("");
  sources = await api("/api/sources").catch(() => []);
  const sel = $("#m-source");
  sel.replaceChildren(...sources.map(s => el("option", { value: s.slug, text: s.name })));
  if (!sources.length) sel.append(el("option", { text: "No basemaps" }));
  sel.addEventListener("change", () => setSource(sel.value));
  const saved = lsGet("ptak.source");
  setSource(saved && sources.some(s => s.slug === saved) ? saved : (sources.find(s => s.name === (S && S.map_source)) || sources[0] || {}).slug);

  map.on("dragstart", () => setFollow(false));
  map.on("mousemove", e => { $("#m-coord").textContent = fmtPos(e.latlng.lat, e.latlng.lng); });
  map.on("click", e => {
    if (pickCb) { const cb = pickCb; if (!cb.multi) endPick(); cb(e.latlng.lat, e.latlng.lng); return; }
    if (measuring) measureAdd(e.latlng);
  });
  map.on("dblclick", e => { if (measuring) { L.DomEvent.stop(e); setMeasure(false); } });
  toolLayer = L.layerGroup().addTo(map); zoneLayer = L.layerGroup().addTo(map); foxLayer = L.layerGroup().addTo(map);
  $("#t-measure").addEventListener("click", () => setMeasure(!measuring));
  $("#t-clear").addEventListener("click", () => { setMeasure(false); toolLayer.clearLayers(); });
  $("#t-zone").addEventListener("click", drawZone);
  map.on("contextmenu", e => mapMenu(e.latlng));
  $("#m-follow").addEventListener("click", () => { setFollow(!follow); if (follow) centerMe(); });
  $("#m-labels").addEventListener("click", () => {
    labels = !labels; $("#m-labels").classList.toggle("on", labels);
    markers.forEach(m => labels ? m.openTooltip() : m.closeTooltip());
  });
  $("#m-pick-cancel").addEventListener("click", endPick);
}
function setFollow(v) { follow = v; $("#m-follow").classList.toggle("on", v); }
function centerMe(zoom) { if (haveMe()) map.setView([S.self.lat, S.self.lon], zoom || Math.max(map.getZoom(), 15)); }
function pick(msg, cb, done) {
  pickCb = cb; $("#m-pick-text").textContent = msg;
  $("#m-pick-done").classList.toggle("hidden", !done); $("#m-pick-done").onclick = done || null;
  $("#m-pick").classList.remove("hidden"); map.getContainer().style.cursor = "crosshair";
}
function endPick() { pickCb = null; $("#m-pick").classList.add("hidden"); map.getContainer().style.cursor = ""; if (endPick.hook) { const h = endPick.hook; endPick.hook = null; h(); } }

function mapMenu(latlng) {
  const box = el("div", {},
    el("div", { text: ll(latlng.lat, latlng.lng) }),
    el("button", { class: "btn small", text: "Set as manual position", onclick: () => {
      map.closePopup(); cmd("settings", { manual_pos: latlng.lat.toFixed(6) + "," + latlng.lng.toFixed(6) });
    } }),
    el("button", { class: "btn small", text: "Report here", onclick: () => { map.closePopup(); reportAt(latlng.lat, latlng.lng); } }),
    el("button", { class: "btn small", text: "Drop marker", onclick: () => markerForm(latlng) }),
    el("button", { class: "btn small", text: "Range rings", onclick: () => { map.closePopup(); rangeRings(latlng); } }),
    el("button", { class: "btn small", text: "Geofence circle", onclick: () => zoneForm(latlng, "circle", null) }));
  box.firstChild.textContent = fmtPos(latlng.lat, latlng.lng) + (lsGet("ptak.coords") === "ll" ? "" : "  (" + ll(latlng.lat, latlng.lng) + ")");
  L.popup().setLatLng(latlng).setContent(box).openOn(map);
}

function meIcon(team, course, fix) {
  const c = TEAM_RGB[team] || "#2fb5c8";
  const svg = (fix && course !== null && course !== undefined)
    ? `<svg width="26" height="26" viewBox="0 0 26 26"><g transform="rotate(${Math.round(course)} 13 13)"><path d="M13 2 L21 22 L13 17 L5 22 Z" fill="${c}" stroke="#000" stroke-width="1.5"/></g></svg>`
    : `<svg width="22" height="22" viewBox="0 0 22 22"><circle cx="11" cy="11" r="7" fill="${c}" stroke="#000" stroke-width="2"/><circle cx="11" cy="11" r="2.5" fill="#000"/></svg>`;
  return L.divIcon({ className: "me-icon", html: svg, iconSize: [26, 26], iconAnchor: [13, 13] });
}
function trackIcon(t) {
  const aff = (t.type.split("-")[1] || "u").toLowerCase();
  let cls = "ic " + (AFF[aff] ? aff : "u"), color = AFF[aff] || AFF.u;
  const cat = t.cat || "";
  if (cat === "drones") cls = "ic drone";
  else if (cat === "aircraft") cls = "ic tri";
  else if (t.type.startsWith("b-")) { cls = "ic spot"; color = t.type.startsWith("b-r-f-h-c") ? "#ff3b30" : "#9aa5b1"; }
  else if (t.kind === "client" && TEAM_RGB[t.team]) color = TEAM_RGB[t.team];
  if (t.stale && t.stale * 1000 < Date.now()) { color = "#777"; cls += " stale"; }   // like ATAK: greyed, not removed
  const key = cls + color;
  const d = el("div", { class: cls });
  if (cls === "ic tri") d.style.borderBottomColor = color;
  else if (!cls.includes("drone")) d.style.background = color;
  return [key, L.divIcon({ className: "", html: d.outerHTML, iconSize: [16, 16], iconAnchor: [8, 8] })];
}
function trackPopup(t) {
  const box = el("div", {}, el("b", { text: t.cs }), el("div", { class: "hint", text: t.type + (t.team ? " · " + t.team : "") + " · " + age(t.ts) + " ago" + (t.stale && t.stale * 1000 < Date.now() ? " · stale" : "") }));
  if (haveMe()) { const [d, b] = distBrg(S.self, t); box.append(el("div", { text: fmtDist(d) + " " + DIRS[Math.round(b / 45) % 8] + " (" + Math.round(b) + "°) from me" })); }
  box.append(el("div", { class: "hint", text: fmtPos(t.lat, t.lon) }));
  const c = (S.contacts || []).find(c => c.cs === t.cs);
  box.append(el("button", { class: "btn small", text: "Details", onclick: () => { map.closePopup(); cotDetails(t); } }));
  if (c) box.append(el("button", { class: "btn small", text: "Direct message", onclick: () => { map.closePopup(); openDM(c.uid); } }));
  box.append(el("button", { class: "btn small", text: "Report here", onclick: () => { map.closePopup(); reportAt(t.lat, t.lon); } }));
  return box;
}
function drawMap() {
  if (!map || !S) return;
  if (haveMe()) {
    const p = [S.self.lat, S.self.lon];
    const key = S.team + (S.self.fix ? Math.round(S.self.course || 0) : "x") + S.self.fix;
    if (!meMarker) {
      meMarker = L.marker(p, { icon: meIcon(S.team, S.self.course, S.self.fix), zIndexOffset: 1000 }).addTo(map)
        .bindTooltip("", { permanent: true, direction: "left", offset: [-12, 0], className: "lbl" });
      centerMe(15);
    }
    meMarker.setLatLng(p);
    if (meMarker._k !== key) { meMarker.setIcon(meIcon(S.team, S.self.course, S.self.fix)); meMarker._k = key; }
    meMarker.setTooltipContent(S.callsign + (S.self.src === "GPS" ? "" : " (" + S.self.src.toLowerCase() + ")"));
    const ce = S.self.ce;
    if (S.self.fix && ce && ce < 2000) {
      if (!meCircle) meCircle = L.circle(p, { radius: ce, color: "#2fb5c8", weight: 1, fillOpacity: .08, interactive: false }).addTo(map);
      meCircle.setLatLng(p).setRadius(ce);
    } else if (meCircle) { map.removeLayer(meCircle); meCircle = null; }
    if (follow) map.panTo(p, { animate: true });
  }
  const seen = new Set();
  for (const t of S.tracks) {
    seen.add(t.id);
    const [key, icon] = trackIcon(t);
    let m = markers.get(t.id);
    if (!m) {
      m = L.marker([t.lat, t.lon], { icon }).addTo(map)
        .bindTooltip("", { permanent: true, direction: "right", offset: [9, 0], className: "lbl" });
      m.on("click", () => m.bindPopup(trackPopup(m._t)).openPopup());
      markers.set(t.id, m);
      if (!labels) m.closeTooltip();
    }
    m._t = t;
    m.setLatLng([t.lat, t.lon]);
    if (m._k !== key) { m.setIcon(icon); m._k = key; }
    m.setTooltipContent(t.cs);
  }
  for (const [id, m] of markers) if (!seen.has(id)) { map.removeLayer(m); markers.delete(id); }
}

// ---------------------------------------------------------------- top bar + status
function drawTop() {
  $("#t-callsign").textContent = S.callsign || "-";
  $("#t-team").style.background = TEAM_RGB[S.team] || "#555";
  const sv = S.server, tak = $("#p-tak");
  tak.textContent = "TAK " + (sv.state || "?");
  tak.className = "pill " + (sv.state === "connected" ? "ok" : sv.state === "connecting" || sv.state === "starting" ? "warn" : "bad");
  tak.title = sv.host + ":" + sv.port + " " + sv.proto + (sv.error ? " - " + sv.error : "");
  const g = $("#p-gps"), me = S.self;
  g.textContent = me.src === "GPS" ? "GPS fix" + (me.sats && me.sats !== "-" ? " " + me.sats + " sats" : "") : me.src === "LAST" ? "GPS last known" : me.src === "MANUAL" ? "Manual position" : "No position";
  g.className = "pill " + (me.src === "GPS" ? "ok" : me.src === "NONE" ? "bad" : "warn");
  const b = $("#p-batt");
  if (S.battery) { b.textContent = "Batt " + S.battery + "%"; b.classList.remove("hidden"); b.className = "pill " + (S.battery < 20 ? "bad" : ""); }
  const q = $("#p-queue");
  q.textContent = S.queued + " queued"; q.classList.toggle("hidden", !S.queued);
  $("#banner-911").classList.toggle("hidden", !S.emergency);
  if (S.emergency) {
    const d = (S.emergency_info.dest || "").split(",").filter(Boolean).map(x => x.split(":").slice(1).join(":"));
    $("#banner-911-text").textContent = "YOUR ALERT IS ON: " + alertName() + " - sent to " + (d.length ? d.join(", ") : "everyone") + ", repeating until you cancel.";
  }
  $("#b-911").textContent = S.emergency ? "ALERT ON" : "SEND ALERT";
  const rs = $("#m-radius"); if (document.activeElement !== rs) rs.value = String(S.radius_km || 0);
  drawMandown();
  const qs = (S.quick || []).join("|");
  if ($("#quick")._sig !== qs) {
    $("#quick")._sig = qs;
    $("#quick").replaceChildren(...(S.quick || []).map(m => el("button", { class: "btn", text: m, type: "button", onclick: () => sendChat(m) })));
  }
  markRead();
}
function drawStatus() {
  const sv = S.server, rows = [
    ["Device", S.device + " · " + PRODUCT + " " + S.version], ["UID", S.uid], ["Server", sv.host + ":" + sv.port + " (" + sv.proto + ")"],
    ["Connection", sv.state + (sv.error ? " - " + sv.error : "")], ["Last position report", sv.last_sa || "never"],
    ["Position", haveMe() ? ll(S.self.lat, S.self.lon) + " (" + S.self.src + ")" : "none"], ["Queued messages", String(S.queued)]];
  if (S.cert && S.cert.days !== null && S.cert.days !== undefined) rows.push(["Client certificate", (S.cert.cn || "") + (S.cert.days < 0 ? " EXPIRED" : " (" + S.cert.days + " days left)")]);
  $("#status-card").replaceChildren(el("h4", { text: "Status" }), el("div", { class: "kv" }, rows.flat().map(t => el("span", { text: t }))));
  drawCert(); drawSetup();
}

// ---------------------------------------------------------------- chat
// Chat open in a visible tab = read: the Pager sends read receipts and its LED stops blinking
let marking = false;
async function markRead() {
  if (marking || !S || !S.unread || tab !== "chat" || document.hidden) return;
  marking = true;
  try { await api("/api/cmd", { cmd: "chat_read" }); } catch (e) { /* next poll retries */ }
  setTimeout(() => { marking = false; }, 3000);
}
const RCPT = { delivered: "\u2713 delivered", read: "\u2713\u2713 read" };
function openDM(uid) { showTab("chat"); $("#chat-to").value = uid; $("#chat-text").focus(); }
function drawChatTo() {
  const sel = $("#chat-to"), cur = sel.value || ALL;
  const opts = [el("option", { value: ALL, text: "All" })].concat((S.contacts || []).map(c => el("option", { value: c.uid, text: "DM " + c.cs })));
  const sig = opts.map(o => o.value + o.textContent).join("|");
  if (sel._sig !== sig) { sel.replaceChildren(...opts); sel._sig = sig; sel.value = [...sel.options].some(o => o.value === cur) ? cur : ALL; }
}
async function pollChat() {
  if (document.hidden && chatSig) return;
  let r;
  try { r = await api("/api/chat?m=" + encodeURIComponent(chatSig)); } catch (e) { return; }
  if (r.same) return;
  chatSig = r.m || "";
  const rows = r.rows || [];
  const log = $("#chat-log"), atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  log.replaceChildren(...rows.map(r => el("div", { class: "msg " + r.dir },
    el("div", { class: "meta" }, r.t.slice(11) + " ", r.from ? el("b", { text: r.from }) : "", " ", el("span", { class: "room", text: r.room === "All" ? "" : "[" + r.room + "]" }),
      r.id ? el("button", { class: "del", type: "button", title: "Delete this message from the Pager", text: "\u00d7", onclick: () => delMsg(r.id) }) : ""),
    el("div", { class: "text", text: r.text }, r.rcpt ? el("span", { class: "rcpt " + r.rcpt, text: RCPT[r.rcpt] || "" }) : ""))));
  if (atBottom || !chatSeen) log.scrollTop = log.scrollHeight;
  const incoming = rows.filter(r => r.dir === "in").length;
  const lastIn = rows.filter(r => r.dir === "in" || /Alert:/.test(r.text)).pop();
  if (chatSeen && lastIn && lastIn.t + lastIn.text !== pollChat.last) {
    const emerg = /EMERGENCY/.test(lastIn.text);
    notify(emerg ? "ALERT" : "Chat from " + lastIn.from, lastIn.text, emerg);
  }
  if (lastIn) pollChat.last = lastIn.t + lastIn.text;
  if (tab !== "chat" && chatSeen && incoming > chatSeen) { badge("#chat-badge", incoming - chatSeen); setTitle(incoming - chatSeen); }
  if (tab === "chat" || !chatSeen) chatSeen = incoming;
}
async function delMsg(id) {
  const r = await api("/api/chat/delete", { id }).catch(() => ({ ok: false, msg: "Device not reachable" }));
  if (!r.ok) toast(r.msg, false);
  chatSig = ""; pollChat();
}
$("#chat-clear").addEventListener("click", async () => {
  if (!confirm("Delete all chat history on the Pager?\n\nOther TAK devices keep their copies.")) return;
  const r = await cmd("chat_clear"); if (r.ok) { $("#chat-log").replaceChildren(); chatSig = "-"; chatSeen = 0; pollChat(); }
});
function badge(sel, n) { const b = $(sel); b.textContent = n; b.classList.toggle("hidden", !n); }
async function sendChat(text) {
  const to = $("#chat-to").value, c = (S.contacts || []).find(c => c.uid === to);
  const r = await cmd("chat", { text, to_uid: c ? c.uid : "", to_cs: c ? c.cs : "" }, true);
  if (r.ok) { chatSig = ""; setTimeout(pollChat, 300); }
  return r.ok;
}
$("#chat-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const t = $("#chat-text"), v = t.value.trim();
  if (v && await sendChat(v)) t.value = "";
});

// ---------------------------------------------------------------- contacts
const CAT_NAMES = { users: "TAK users", drones: "Drones and operators", aircraft: "Aircraft", ground: "Ground units, vehicles and incidents", vessels: "Vessels", other: "Markers and other" };
function trackRow(t) {
  return el("div", { class: "item", onclick: () => {
    setFollow(false); map.setView([t.lat, t.lon], Math.max(map.getZoom(), 16)); const m = markers.get(t.id); if (m) m.fire("click");
  } }, el("div", { class: "grow" }, el("div", { class: "t", text: t.cs }), el("div", { class: "s", text: t.type + (t.team ? " · " + t.team : "") })),
    el("div", { class: "r" }, t.d ? fmtDist(t.d[0]) + " " + DIRS[Math.round(t.d[1] / 45) % 8] : "", el("br"), age(t.ts) + " ago"));
}
const withDist = t => Object.assign({ d: haveMe() ? distBrg(S.self, t) : null }, t);
const byDist = (a, b) => (a.d ? a.d[0] : 0) - (b.d ? b.d[0] : 0);
function drawContacts() {
  const people = S.tracks.filter(t => t.cat === "users").map(withDist).sort(byDist);
  $("#contacts").replaceChildren(...(people.length ? people.map(t => {
    const r = trackRow(t), c = (S.contacts || []).find(x => x.cs === t.cs);
    if (c) r.append(el("button", { class: "btn small", text: "Message", onclick: ev => { ev.stopPropagation(); openDM(c.uid); } }));
    return r;
  }) : [el("div", { class: "hint", text: (S.hide || []).includes("users") ? "TAK users are hidden (Items tab)." : "No TAK users seen yet." })]));
}
let catSig = "";
function drawItemsTab() {
  const hide = S.hide || [], counts = S.counts || {}, sig = JSON.stringify([hide, counts]);
  if (sig !== catSig && !document.activeElement.closest("#cat-filters")) {
    catSig = sig;
    $("#cat-filters").replaceChildren(...Object.keys(CAT_NAMES).map(c => {
      const cb = el("input", { type: "checkbox" }); cb.checked = !hide.includes(c);
      cb.addEventListener("change", () => {
        const h = $$("#cat-filters input").map((x, i) => x.checked ? null : Object.keys(CAT_NAMES)[i]).filter(Boolean);
        cmd("settings", { cot_hide: h.join(",") }, true);
      });
      return el("label", {}, cb, CAT_NAMES[c] + " ", el("span", { class: "catcount", text: "(" + (counts[c] || 0) + ")" }));
    }));
  }
  if (document.activeElement.closest("#items-list")) return;
  const all = S.tracks.filter(t => t.cat !== "users").map(withDist).sort(byDist);
  const mine = (S.items || []).map(withDist).sort(byDist).map(it => el("div", { class: "item" },
    el("div", { class: "grow" }, el("div", { class: "t", text: it.name }), el("div", { class: "s", text: sentLabel(it.sent) }), itemActions(it)),
    el("button", { class: "btn small", text: "Show", onclick: () => { setFollow(false); map.setView([it.lat, it.lon], Math.max(map.getZoom(), 16)); } })));
  const sec = (title, rows) => rows.length ? [el("h4", { text: title + " (" + rows.length + ")" })].concat(rows) : [];
  const out = [...sec("My markers", mine)];
  for (const c of ["drones", "aircraft", "ground", "vessels", "other"]) out.push(...sec(CAT_NAMES[c], all.filter(t => t.cat === c).slice(0, 200).map(trackRow)));
  $("#items-list").replaceChildren(...(out.length ? out : [el("div", { class: "hint", text: "Nothing on the map yet." })]));
}
$("#clear-recv").addEventListener("click", () => {
  if (confirm("Clear everything received from TAK on the Pager (users, markers, aircraft, drones, trails)? Your own markers and zones stay. Items still being sent come back on their next update.")) {
    markers.forEach(m => map.removeLayer(m)); markers.clear(); cmd("clear_received");
  }
});

// ---------------------------------------------------------------- reports
let repKind = "salute", repLoc = null;
const opt = (v, t) => el("option", { value: v, text: t === undefined ? v : t });
const sel = (name, items, value) => { const s = el("select", { name }, items.map(i => Array.isArray(i) ? opt(i[0], i[1]) : opt(i))); if (value !== undefined) s.value = value; return s; };
const txt = (name, ph, list, value) => {
  const i = el("input", { name, placeholder: ph || "", maxlength: "200", value: value || "" });
  if (list) { const id = "dl-" + name; i.setAttribute("list", id); return [i, el("datalist", { id }, list.map(v => opt(v)))]; }
  return i;
};
const n = (name, v = 0) => el("input", { name, type: "number", min: "0", max: "999", value: String(v) });
const lab = (t, ...c) => el("label", {}, t, ...c);
const checks = (name, items) => el("div", { class: "checks" }, items.map(v => el("label", {}, el("input", { type: "checkbox", name, value: v }), v)));

function locField() {
  const show = el("div", { class: "hint", id: "rep-loc-show" });
  const upd = () => { show.textContent = repLoc ? "Report location: " + ll(repLoc[0], repLoc[1]) + " (" + repLoc[2] + ")" : "Report location: my position"; };
  upd();
  return el("fieldset", {}, el("legend", { text: "Location" }),
    el("div", { class: "row" },
      el("button", { type: "button", class: "btn small", text: "My position", onclick: () => { repLoc = null; upd(); } }),
      el("button", { type: "button", class: "btn small", text: "Pick on map", onclick: () => pick("Click the report location", (a, b) => { repLoc = [a, b, "picked on map"]; upd(); showTab("reports"); }) }),
      el("button", { type: "button", class: "btn small", text: "Enter lat,lon", onclick: () => {
        const v = prompt("lat,lon", repLoc ? repLoc[0] + "," + repLoc[1] : ""); if (!v) return;
        const [a, b] = v.split(",").map(Number); if (isFinite(a) && isFinite(b) && Math.abs(a) <= 90 && Math.abs(b) <= 180) { repLoc = [a, b, "entered position"]; upd(); } else toast("Bad lat,lon", false);
      } })), show);
}
function reportAt(lat, lon) { repLoc = [lat, lon, "picked on map"]; showTab("reports"); buildReport(); }

const FORMS = {
  salute: () => [locField(),
    el("div", { class: "grid2" }, lab("S - Size", n("size", 1)), lab("S - What", txt("what", "", ["Persons", "Vehicles", "Vessels", "Aircraft", "Drones"], "Persons"))),
    lab("A - Activity", txt("activity", "", ["Stationary", "Moving", "Observing", "Loitering", "Digging/emplacing", "Looting", "Fighting", "Fleeing"], "Stationary")),
    lab("U - Unit / uniform", txt("unit", "", ["Unknown", "Civilian clothes", "Uniformed", "Law enforcement", "Military", "Gang colors"], "Unknown")),
    lab("T - Time (DTG)", el("input", { name: "time", value: dtg() })),
    lab("E - Equipment", txt("equipment", "", ["None seen", "Small arms", "Long guns", "Vehicles", "Tools", "Drones", "Unknown"], "None seen")),
    lab("Mark as", sel("affiliation", ["Suspect", "Hostile", "Unknown", "Neutral"])),
    lab("Notes", txt("notes", "optional"))],
  sitrep: () => [el("div", { class: "hint", text: "Sent at the device's own position." }),
    lab("Status", sel("status", ["All OK", "Minor issues", "Need support", "Under threat"])),
    lab("Situation", txt("situation", "", ["Arrived on site", "Assessment underway", "Assessment complete", "Departing", "Road blocked", "Comms degraded", "Holding position"], "Arrived on site")),
    lab("Personnel (PAX)", n("pax", 1)),
    el("fieldset", {}, el("legend", { text: "Needs" }), checks("needs", ["Water", "Food", "Fuel", "Medical", "Comms", "Transport", "Security", "Shelter"]))],
  medevac: () => [locField(),
    lab("Line 2 - Frequency / callsign", el("input", { name: "freq", value: lsGet("ptak.medfreq") || (S && S.callsign) || "" })),
    el("fieldset", {}, el("legend", { text: "Line 3 - Patients by precedence" }),
      el("div", { class: "grid3" }, lab("Urgent", n("urg")), lab("Urgent surgical", n("urgs")), lab("Priority", n("pri")), lab("Routine", n("rou")), lab("Convenience", n("con")))),
    lab("Line 4 - Special equipment", sel("equip", ["None", "Hoist", "Extraction equipment", "Ventilator", "Other"])),
    el("fieldset", {}, el("legend", { text: "Line 5 - Patients by type" }), el("div", { class: "grid2" }, lab("Litter", n("lit")), lab("Ambulatory", n("amb")))),
    lab("Line 6 - Security at pickup", sel("sec", [[0, "N - No enemy"], [1, "P - Possible enemy"], [2, "E - Enemy, caution"], [3, "X - Armed escort required"]])),
    el("div", { class: "grid2" }, lab("Line 7 - Marking", sel("mark", [[0, "Panels"], [1, "Pyrotechnic"], [2, "Smoke"], [3, "None"], [4, "Other"]], "2")), lab("Other marking", txt("mark_other", "if Other"))),
    el("fieldset", {}, el("legend", { text: "Line 8 - Nationality / status" }),
      el("div", { class: "grid3" }, lab("US military", n("usm")), lab("US civilian", n("usc")), lab("Non-US mil", n("num")), lab("Non-US civ", n("nuc")), lab("EPW", n("epw")), lab("Child", n("chi")))),
    lab("Line 9 - Terrain / NBC", sel("terrain", ["None", "Slope", "Rough", "Loose", "Other"]))],
  damage: () => [locField(),
    lab("Structure", txt("structure", "", ["Residential", "Commercial", "Public building", "School", "Medical", "Utility", "Road", "Bridge"], "Residential")),
    lab("Damage level", sel("damage", ["Destroyed", "Major", "Minor", "Affected", "No damage"], "Major")),
    el("fieldset", {}, el("legend", { text: "Hazards" }), checks("hazards", ["Downed power lines", "Gas leak", "Fire", "Flooding", "Structural collapse", "Hazmat", "Debris on road"])),
    el("div", { class: "grid2" }, lab("Injured", n("injured")), lab("Trapped / missing", n("trapped"))),
    lab("Access", sel("access", ["Open", "Limited", "Blocked"])),
    lab("Notes", txt("notes", "optional"))],
};
function buildReport() {
  $$("#rep-kind button").forEach(b => b.classList.toggle("on", b.dataset.k === repKind));
  const f = $("#rep-form");
  f.replaceChildren(...FORMS[repKind](), el("button", { class: "btn primary", text: "Send " + $("#rep-kind .on").textContent }));
}
$$("#rep-kind button").forEach(b => b.addEventListener("click", () => { repKind = b.dataset.k; buildReport(); }));
$("#rep-form").addEventListener("submit", async ev => {
  ev.preventDefault();
  const fd = new FormData(ev.target), v = { kind: repKind };
  for (const [k, val] of fd.entries()) v[k] = v[k] !== undefined ? v[k] + ", " + val : val;
  if (repKind !== "sitrep") {
    if (repLoc) { v.lat = repLoc[0].toFixed(6); v.lon = repLoc[1].toFixed(6); v.locdesc = repLoc[2]; }
    else if (!haveMe()) { toast("No position - pick the location on the map", false); return; }
  } else if (!haveMe()) { toast("No position - need GPS or a manual position", false); return; }
  if (repKind === "medevac") lsSet("ptak.medfreq", v.freq || "");
  if (!confirm("Send " + $("#rep-kind .on").textContent + " to all TAK users?")) return;
  const r = await cmd("report", v);
  if (r.ok) { repLoc = null; buildReport(); loadReports(); }
});
async function loadReports() {
  const rows = await api("/api/reports").catch(() => []);
  $("#rep-history").replaceChildren(...(rows.length ? rows.map(r => el("div", { class: "item" }, el("div", { class: "grow" }, el("div", { class: "t", text: r.head }), el("pre", { text: r.body })))) : [el("div", { class: "hint", text: "None yet." })]));
}

// ---------------------------------------------------------------- sensors
function sw(on, onchange) {
  const i = el("input", { type: "checkbox" }); i.checked = on; i.addEventListener("change", () => onchange(i.checked));
  return el("label", { class: "switch" }, i, el("span"));
}
function card(title, running, on, toggle, ...body) {
  return el("div", { class: "card" }, el("div", { class: "head" }, el("span", { class: "dot" + (running ? " on" : ""), title: running ? "running" : "stopped" }), el("span", { class: "t", text: title }), toggle ? sw(on, toggle) : ""), ...body);
}
let sensorSig = "";
function drawSensors() {
  const s = S.sensors, av = s.available, sig = JSON.stringify(s);
  if (sig === sensorSig) return; sensorSig = sig;
  const out = [];
  if (av.includes("watch")) out.push(card("Evil-twin / rogue AP watch", s.watch.running, s.watch.on, v => cmd("sensor", { name: "watch", on: v }),
    el("div", { class: "hint", text: "Site profile: " + (s.watch.profile || "none yet") + ". Alerts when one of your networks shows up from an unknown access point, or weaker than learned. Needs Recon running." }),
    watchLearn(s)));
  if (av.includes("trk")) {
    const body = [el("div", { class: "hint", text: "AirTag / Find My, Tile, SmartTag, Google FMDN, Flock, Axon. Alerts when one follows you." })];
    if (!s.trk.tools) body.push(el("div", { class: "row" },
      el("button", { class: "btn", text: s.installing ? "Installing..." : "Install Bluetooth tools", disabled: s.installing, onclick: () => cmd("sensor_install", { name: "trk" }) }),
      el("span", { class: "hint", text: " needs internet" })));
    else if (!s.trk.adapter) body.push(el("div", { class: "hint warn", text: "No Bluetooth adapter found. Plug in a USB Bluetooth adapter (then restart PineappleTAK if it still isn't seen)." }));
    out.push(card("Trackers / counter-surveillance", s.trk.running, s.trk.on, v => cmd("sensor", { name: "trk", on: v }), ...body));
  }
  if (av.includes("rid")) {
    const ch = sel("rid_channel", [1, 6, 11].map(String), s.rid.channel || "6");
    ch.addEventListener("change", () => cmd("settings", { rid_channel: ch.value }));
    out.push(card("Drone Remote ID", s.rid.running, s.rid.on, v => cmd("sensor", { name: "rid", on: v }),
      el("div", { class: "row" }, el("span", { class: "hint", text: "Wi-Fi channel " }), ch),
      el("div", { class: "hint", text: "Listens for drone Remote ID broadcasts over Wi-Fi (on this channel)" + (s.trk.tools ? " and Bluetooth." : ".") + (s.rid.tools ? "" : " Needs tcpdump (opkg install tcpdump).") })));
  }
  out.push(card("Sensor stats in position reports", s.recon.on, s.recon.on, v => cmd("sensor", { name: "recon", on: v })));
  if (av.includes("survey")) {
    const body = [];
    if (s.survey.running) {
      const up = el("input", { type: "checkbox", checked: true });
      body.push(el("div", { class: "hint", text: "Recording: " + s.survey.dir }), el("div", { class: "checks" }, el("label", {}, up, "Build and upload the data package to TAK")),
        el("button", { class: "btn primary", text: "Stop survey", onclick: () => cmd("survey_stop", { upload: up.checked }) }));
    } else {
      const name = el("input", { placeholder: "Survey name (site)", value: s.watch.profile || "Site" });
      body.push(el("div", { class: "row" }, name, el("button", { class: "btn primary", text: "Start", onclick: () => cmd("survey_start", { name: name.value }) })));
    }
    body.push(el("div", { id: "surveys", class: "list small" }));
    out.push(card("Site survey", s.survey.running, false, null, ...body));
    loadSurveys();
  }
  $("#sensors").replaceChildren(...out);
}
// Evil-twin watch: learn the site from what recon heard, tick your networks, save
const WL = { rows: null, pick: new Set(), mins: "15", profile: null };
function watchLearn(s) {
  if (WL.profile === null) WL.profile = s.watch.profile || "Site";
  const mins = sel("watch_mins", ["5", "15", "60", "240"], WL.mins);
  mins.style.width = "auto"; mins.style.flex = "0 0 auto";
  mins.addEventListener("change", () => { WL.mins = mins.value; });
  const find = el("button", { class: "btn", text: "Find networks", onclick: async () => {
    const r = await cmd("watch_scan", { mins: WL.mins });
    WL.rows = r.ok ? await api("/api/watch/scan").catch(() => []) : null;
    WL.pick = new Set(); sensorSig = ""; drawSensors();
  } });
  const box = [el("div", { class: "row" }, el("span", { class: "hint", text: "Learn from the last" }), mins, el("span", { class: "hint grow", text: "minutes of recon" }), find)];
  if (WL.rows && WL.rows.length) {
    const name = el("input", { placeholder: "Site profile name", value: WL.profile });
    name.addEventListener("input", () => { WL.profile = name.value; });
    const list = el("div", { class: "checks list small" }, ...WL.rows.map(r => {
      const c = el("input", { type: "checkbox" }); c.checked = WL.pick.has(r.hex); c.disabled = r.hex === "-";
      c.addEventListener("change", () => { if (c.checked) WL.pick.add(r.hex); else WL.pick.delete(r.hex); });
      return el("label", {}, c, (r.ssid || "(hidden)") + " - " + r.aps + " AP, " + r.enc);
    }));
    box.push(el("div", { class: "hint", text: "Tick the networks that are YOURS (hidden networks can't be protected by name):" }), list,
      el("div", { class: "row" }, name, el("button", { class: "btn primary", text: "Save", onclick: async () => {
        const r = await cmd("watch_save", { profile: WL.profile, ssids: [...WL.pick].join(",") });
        if (r.ok) { WL.rows = null; sensorSig = ""; drawSensors(); }
      } })));
  }
  return el("div", {}, ...box);
}
async function loadSurveys() {
  const rows = await api("/api/surveys").catch(() => []);
  const box = $("#surveys"); if (!box) return;
  box.replaceChildren(...rows.map(r => el("div", { class: "item" }, el("div", { class: "grow" }, el("div", { class: "t", text: r.name + (r.active ? " (recording)" : "") }),
    el("div", { class: "s", text: new Date(r.start * 1000).toLocaleString() })),
    el("div", { class: "r" }, r.zips.map(z => el("a", { href: "/download/surveys/" + encodeURIComponent(r.dir) + "/" + encodeURIComponent(z), text: "zip", download: z }))))));
}
function drawAlerts() {
  $("#alerts").replaceChildren(...(S.alerts.length ? S.alerts.map(a => el("div", { class: "item sev-" + a.sev },
    el("div", { class: "grow", text: a.text }), el("div", { class: "r", text: age(a.ts) + " ago" }))) : [el("div", { class: "hint", text: "No alerts." })]));
  const top = S.alerts.length ? S.alerts[0].ts : 0;
  if (drawAlerts.top && top > drawAlerts.top) { const a = S.alerts[0]; notify(a.kind, a.text, a.sev === "high"); }
  drawAlerts.top = Math.max(drawAlerts.top || 0, top) || 1;
  if (!alertSeen) alertSeen = top || 1;
  if (tab === "sensors") alertSeen = Math.max(alertSeen, top);
  badge("#alert-badge", S.alerts.filter(a => a.ts > alertSeen).length);
}

// ---------------------------------------------------------------- settings
function fillSettings() {
  if (formsFilled) return; formsFilled = true;
  const id = $("#set-identity");
  id.team.replaceChildren(...TEAMS.map(t => opt(t))); id.role.replaceChildren(...ROLES.map(r => opt(r)));
  id.callsign.value = S.callsign; id.team.value = S.team; id.role.value = S.role;
  const p = $("#set-position"); p.manual_pos.value = S.manual_pos; p.interval.value = S.interval;
  const sv = $("#set-server"); sv.host.value = S.server.host; sv.proto.value = S.server.proto; sv.port.value = S.server.port;
  const en = $("#set-enroll"); en.host.value = S.server.host === "tak.example.com" ? "" : S.server.host;
  $("#set-map").tilemode.value = tileMode();
  $("#set-map").coords.value = lsGet("ptak.coords") || "mgrs";
  $("#set-alerts").sound.checked = lsGet("ptak.sound") !== "0";
  const w = S.web || {}; $("#set-access").mode.value = w.listen || "all";
  $("#access-urls").textContent = (w.urls || []).length ? "Reachable at: " + w.urls.join("  ") : "";
  const qf = $("#set-quick"); qf.quick_text.value = (S.quick || []).join("\n"); qf.receipts.checked = S.receipts !== false;
  notifyHint();
}
function formObj(f) { const o = {}; for (const [k, v] of new FormData(f).entries()) if (typeof v === "string") o[k] = v.trim(); return o; }
$("#set-identity").addEventListener("submit", ev => { ev.preventDefault(); cmd("settings", formObj(ev.target)); });
$("#set-quick").addEventListener("submit", ev => {
  ev.preventDefault();
  const f = ev.target, q = f.quick_text.value.split("\n").map(x => x.replace(/\|/g, "/").trim().slice(0, 36)).filter(Boolean).slice(0, 10);
  cmd("settings", { quick: q.join("|"), receipts: f.receipts.checked ? "1" : "0" });
});
$("#quick-reset").addEventListener("click", () => { $("#set-quick").quick_text.value = ""; });
$("#set-position").addEventListener("submit", ev => { ev.preventDefault(); cmd("settings", formObj(ev.target)); });
$("#pos-pick").addEventListener("click", () => pick("Click your position", async (a, b) => {
  // saved right away (like "Set as manual position" on the map); showTab refills the form from the saved values
  const v = a.toFixed(6) + "," + b.toFixed(6);
  const r = await cmd("settings", { manual_pos: v });
  showTab("settings");
  $("#set-position").manual_pos.value = r.ok ? v : (S.manual_pos || "");
}));
$("#pos-clear").addEventListener("click", () => { $("#set-position").manual_pos.value = ""; });
$("#set-server").addEventListener("submit", ev => {
  ev.preventDefault();
  if (confirm("Save the TAK server settings and reconnect?")) cmd("settings", formObj(ev.target));
});
$("#set-map").tilemode.addEventListener("change", ev => { lsSet("ptak.tiles", ev.target.value); setSource($("#m-source").value); });
// ---------------------------------------------------------------- certificates, enrollment, setup
async function upload(path, file, headers = {}) {
  const r = await fetch(path, { method: "POST", credentials: "same-origin", body: file,
    headers: Object.assign({ "X-PagerTAK": "1", "Content-Type": "application/octet-stream" }, headers) });
  return r.json().catch(() => ({ ok: false, msg: "Upload failed (" + r.status + ")" }));
}
function result(id, st) {   // st = "busy|..." / "ok|..." / "err|..."
  const [k, msg] = (st || "").split(/\|(.*)/s), box = $(id);
  if (!k) return;
  box.className = "result " + (k === "ok" ? "ok" : k === "err" ? "bad" : "busy"); box.textContent = msg || "";
}
function watchJob(name, id, n = 0) {
  setTimeout(async () => {
    const r = await api("/api/job/" + name).catch(() => ({}));
    result(id, r.status);
    if ((r.status || "").startsWith("busy") && n < 60) return watchJob(name, id, n + 1);
    poll(true); formsFilled = false; if (tab === "settings") fillSettings();
  }, 2000);
}
$("#set-cert").addEventListener("submit", async ev => {
  ev.preventDefault();
  const f = ev.target, jobs = [["ca", f.ca.files[0]], ["client", f.client.files[0]]].filter(j => j[1]);
  if (!jobs.length) { toast("Choose a file first", false); return; }
  for (const [kind, file] of jobs) {
    if (file.size > 256 * 1024) { toast(file.name + " is too large for a certificate", false); return; }
    toast("Uploading " + file.name + "...");
    const r = await upload("/api/certfile?kind=" + kind, file, { "X-P12-Password": f.password.value || "atakatak" });
    toast(r.msg, r.ok);
    if (!r.ok) return;
  }
  f.reset(); poll(true);
});
$("#set-pkg").addEventListener("submit", async ev => {
  ev.preventDefault();
  const file = ev.target.pkg.files[0];
  if (!file) { toast("Choose the .zip first", false); return; }
  toast("Importing " + file.name + "...");
  const r = await upload("/api/package", file);
  toast(r.msg, r.ok);
  if (r.ok) { ev.target.reset(); formsFilled = false; poll(true); setTimeout(() => { formsFilled = false; fillSettings(); }, 1500); }
});
$("#set-enroll").addEventListener("submit", async ev => {
  ev.preventDefault();
  const o = formObj(ev.target);
  o.host = (o.host || "").trim().replace(/^https?:\/\//i, "").replace(/[\/:].*$/, "");
  if (!/^[A-Za-z0-9.\-]+$/.test(o.host)) { toast("Server must be a host name or IP address", false); return; }
  const r = await cmd("enroll", o, true);
  if (r.ok) { ev.target.password.value = ""; result("#enroll-result", "busy|" + r.msg); watchJob("enroll", "#enroll-result"); }
});
$("#b-test").addEventListener("click", async () => {
  const r = await cmd("tak_test", {}, true);
  if (r.ok) { result("#test-result", "busy|" + r.msg); watchJob("test", "#test-result"); }
});
$("#b-setup-done").addEventListener("click", () => cmd("setup_done"));
function drawCert() {
  const c = S.cert || {}, box = $("#cert-info");
  if (S.server.proto !== "tls") { box.textContent = "TCP/UDP: no certificate needed."; return; }
  if (c.days === null || c.days === undefined) { box.textContent = "No client certificate yet - import a package, enroll, or upload one below."; return; }
  box.textContent = "Client certificate" + (c.cn ? " " + c.cn : "") + (c.days < 0 ? ": EXPIRED" : ": valid " + c.days + " more days");
  box.className = "hint" + (c.days <= 30 ? " warn" : "");
}
function drawSetup() {
  document.body.classList.toggle("setup-mode", !!S.setup);
  $("#banner-setup").classList.toggle("hidden", !S.setup);
  if (S.setup && tab !== "settings") showTab("settings");
}
$("#set-access").addEventListener("submit", async ev => {
  ev.preventDefault();
  const r = await cmd("web_listen", formObj(ev.target));
  if (r.ok) setTimeout(() => location.reload(), 6000);        // the console comes back on the new addresses
});
$("#set-pw").addEventListener("submit", async ev => {
  ev.preventDefault();
  const r = await api("/api/password", formObj(ev.target)).catch(() => ({ ok: false, msg: "Failed" }));
  toast(r.msg, r.ok); if (r.ok) ev.target.reset();
});

// ---------------------------------------------------------------- alerts / SA
$("#b-911").addEventListener("click", () => {
  if (S && S.emergency) { if (confirm("Cancel your " + alertName() + " alert?")) cmd("cancel_emergency"); }
  else alertDialog();
});
$("#b-911-cancel").addEventListener("click", () => { if (confirm("Cancel your " + alertName() + " alert?")) cmd("cancel_emergency"); });
$("#b-sa").addEventListener("click", () => cmd("sa_now"));

// ---------------------------------------------------------------- map tools (browser only)
let measuring = false, measPts = [], measLine = null, toolLayer, zoneLayer, foxLayer;
function setMeasure(v) {
  measuring = v; $("#t-measure").classList.toggle("on", v);
  map.doubleClickZoom[v ? "disable" : "enable"]();
  map.getContainer().style.cursor = v ? "crosshair" : "";
  if (v) { measPts = []; measLine = null; toast("Click points to measure. Double-click to finish."); }
}
function measureAdd(latlng) {
  const prev = measPts[measPts.length - 1];
  if (prev && map.latLngToContainerPoint(prev).distanceTo(map.latLngToContainerPoint(latlng)) < 6) return;  // 2nd click of a double-click
  measPts.push(latlng);
  if (!measLine) measLine = L.polyline(measPts, { color: "#2fb5c8", weight: 3, dashArray: "6 5" }).addTo(toolLayer);
  else measLine.setLatLngs(measPts);
  L.circleMarker(latlng, { radius: 4, color: "#2fb5c8", fillOpacity: 1, interactive: false }).addTo(toolLayer);
  if (measPts.length < 2) return;
  let total = 0;
  for (let i = 1; i < measPts.length; i++) total += distBrg({ lat: measPts[i - 1].lat, lon: measPts[i - 1].lng }, { lat: measPts[i].lat, lon: measPts[i].lng })[0];
  const a = measPts[measPts.length - 2], [d, b] = distBrg({ lat: a.lat, lon: a.lng }, { lat: latlng.lat, lon: latlng.lng });
  L.tooltip({ permanent: true, direction: "right", offset: [8, 0], className: "meas" }).setLatLng(latlng)
    .setContent(fmtDist(d) + " @ " + Math.round(b) + "°" + (measPts.length > 2 ? " · total " + fmtDist(total) : "")).addTo(toolLayer);
}
function niceStep(m) { const p = Math.pow(10, Math.floor(Math.log10(m))); return [1, 2, 2.5, 5, 10].map(k => k * p).find(k => k >= m) || m; }
function rangeRings(c) {
  const b = map.getBounds(), w = map.distance(b.getSouthWest(), b.getSouthEast());
  const v = prompt("Ring spacing in meters (4 rings)", String(niceStep(w / 10)));
  const step = Number(v); if (!step || step <= 0) return;
  for (let i = 1; i <= 4; i++) {
    L.circle(c, { radius: step * i, color: "#ffd60a", weight: 1.5, fill: false, interactive: false }).addTo(toolLayer);
    L.tooltip({ permanent: true, direction: "center", className: "ring-lbl" }).setLatLng(L.latLng(c.lat + (step * i) / 111320, c.lng)).setContent(fmtDist(step * i)).addTo(toolLayer);
  }
  L.circleMarker(c, { radius: 3, color: "#ffd60a", fillOpacity: 1, interactive: false }).addTo(toolLayer);
}

// who to send something to: keep local, everyone, or one contact
function sendPicker(def, name = "send") {
  const o = [opt("", name === "alert" ? "No TAK alert" : "Don't send (only on this map)"), opt("all", "Send to everyone")]
    .concat((S && S.contacts || []).map(c => opt("dm:" + c.uid + ":" + c.cs, "Send only to " + c.cs)));
  const p = el("select", { name }, o); p.value = def === undefined ? "all" : def; return p;
}
function sendFields(v) {
  if (v === "all") return { send: "all" };
  if (v && v.startsWith("dm:")) { const [, uid, ...cs] = v.split(":"); return { send: "dm", to_uid: uid, to_cs: cs.join(":") }; }
  return { send: "" };
}
const sentLabel = s => s === "all" ? "sent to everyone" : s && s.startsWith("dm:") ? "sent to " + s.split(":").slice(2).join(":") : "only on this map";
function itemActions(it, after) {
  const p = sendPicker("all"); p.options[0].remove();
  return el("div", { class: "row" }, p,
    el("button", { class: "btn small", type: "button", text: it.sent ? "Resend" : "Send", onclick: async () => { await cmd("item_send", Object.assign({ id: it.id }, sendFields(p.value))); if (after) after(); } }),
    el("button", { class: "btn small", type: "button", text: "Delete", onclick: async () => {
      if (!confirm("Delete " + it.name + (it.sent ? "? It is also removed for whoever it was sent to." : "?"))) return;
      await cmd("item_del", { id: it.id }); if (after) after();
    } }));
}

// drop a marker -> TAK
const SPOT_COLORS = [["-65536", "Red"], ["-23296", "Orange"], ["-256", "Yellow"], ["-16711936", "Green"], ["-16776961", "Blue"], ["-1", "White"], ["-16777216", "Black"]];
function markerForm(latlng) {
  const f = el("form", { class: "popform" },
    el("b", { text: "Drop marker" }), el("div", { class: "hint", text: fmtPos(latlng.lat, latlng.lng) }),
    el("input", { name: "name", placeholder: "Name", maxlength: "40", required: true }),
    sel("kind", [["spot", "Spot (color)"], ["hostile", "Hostile"], ["suspect", "Suspect"], ["unknown", "Unknown"], ["neutral", "Neutral"], ["friendly", "Friendly"]]),
    sel("color", SPOT_COLORS),
    el("input", { name: "remarks", placeholder: "Remarks (optional)", maxlength: "300" }),
    sendPicker("all"),
    el("button", { class: "btn primary small", text: "Save" }));
  f.kind.addEventListener("change", () => { f.color.disabled = f.kind.value !== "spot"; });
  f.addEventListener("submit", async ev => {
    ev.preventDefault();
    const r = await cmd("marker", Object.assign({ name: f.name.value, kind: f.kind.value, color: f.color.value, remarks: f.remarks.value, lat: latlng.lat.toFixed(6), lon: latlng.lng.toFixed(6) }, sendFields(f.send.value)));
    if (r.ok) map.closePopup();
  });
  L.popup({ minWidth: 220 }).setLatLng(latlng).setContent(f).openOn(map);
  setTimeout(() => f.name.focus(), 50);
}

// geofences
function zoneForm(latlng, shape, pts) {
  const f = el("form", { class: "popform" }, el("b", { text: shape === "circle" ? "Geofence circle" : "Geofence zone" }),
    el("input", { name: "name", placeholder: "Zone name (e.g. Gate 2)", maxlength: "40", required: true }),
    shape === "circle" ? lab("Radius (m)", el("input", { name: "radius", type: "number", min: "10", max: "50000", value: "100" })) : "",
    lab("Alert on", sel("who", [["people", "TAK users"], ["drones", "Drones"], ["all", "Anything that moves"], ["me", "Me"]])),
    el("div", { class: "checks" }, el("label", {}, el("input", { type: "checkbox", name: "chat" }), "GeoChat the alert")),
    lab("Show the zone in TAK", sendPicker("")),
    lab("TAK alert (Geo-fence Breached) when something enters", sendPicker("", "alert")),
    el("button", { class: "btn primary small", text: "Save zone" }));
  let preview = null;
  if (shape === "circle") {
    preview = L.circle(latlng, { radius: 100, color: "#ff3b30", weight: 2, dashArray: "5 4", fillOpacity: .08 }).addTo(toolLayer);
    f.radius.addEventListener("input", () => preview.setRadius(Number(f.radius.value) || 0));
  }
  f.addEventListener("submit", async ev => {
    ev.preventDefault();
    const data = shape === "circle" ? latlng.lat.toFixed(6) + "," + latlng.lng.toFixed(6) + "," + Math.round(Number(f.radius.value))
      : pts.map(p => p.lat.toFixed(6) + "," + p.lng.toFixed(6)).join(";");
    const a = sendFields(f.alert.value);
    const r = await cmd("geofence_add", Object.assign({ name: f.name.value, shape, data, who: f.who.value, chat: f.chat.checked,
      alert: a.send, alert_uid: a.to_uid || "", alert_cs: a.to_cs || "" }, sendFields(f.send.value)));
    if (r.ok) { map.closePopup(); toolLayer.clearLayers(); }
  });
  L.popup({ minWidth: 230 }).setLatLng(latlng).setContent(f).openOn(map)
    .on("remove", () => { if (preview) toolLayer.removeLayer(preview); });
  setTimeout(() => f.name.focus(), 50);
}
function drawZone() {
  setMeasure(false);
  const pts = [], line = L.polygon([], { color: "#ff3b30", weight: 2, dashArray: "5 4", fillOpacity: .08 }).addTo(toolLayer);
  const cb = (a, b) => { pts.push(L.latLng(a, b)); line.setLatLngs(pts); L.circleMarker([a, b], { radius: 4, color: "#ff3b30", fillOpacity: 1 }).addTo(toolLayer); };
  cb.multi = true;
  $("#t-zone").classList.add("on");
  endPick.hook = () => { $("#t-zone").classList.remove("on"); };
  pick("Click the corners of the zone, then Finish", cb, () => {
    endPick();
    if (pts.length < 3) { toast("A zone needs at least 3 points", false); toolLayer.removeLayer(line); return; }
    zoneForm(line.getBounds().getCenter(), "poly", pts.slice());
  });
}
let itemSig = "", itemLayer = null;
function drawItems() {
  const its = S.items || [], sig = JSON.stringify(its);
  if (sig === itemSig) return; itemSig = sig;
  if (!itemLayer) itemLayer = L.layerGroup().addTo(map);
  itemLayer.clearLayers();
  for (const it of its) {
    const [, icon] = trackIcon({ type: it.type, kind: "marker", team: "" });
    let ic = icon;
    if (it.type === "b-m-p-s-m") {
      const c = "#" + ((Number(it.color) >>> 0) & 0xffffff).toString(16).padStart(6, "0");
      const d = el("div", { class: "ic spot" }); d.style.background = c;
      ic = L.divIcon({ className: "", html: d.outerHTML, iconSize: [16, 16], iconAnchor: [8, 8] });
    }
    const m = L.marker([it.lat, it.lon], { icon: ic }).addTo(itemLayer)
      .bindTooltip(it.name, { permanent: true, direction: "right", offset: [9, 0], className: "lbl" });
    m.on("click", () => m.bindPopup(el("div", {}, el("b", { text: it.name }), el("div", { class: "hint", text: it.type + " · " + sentLabel(it.sent) }),
      it.remarks ? el("div", { text: it.remarks }) : "", el("div", { class: "hint", text: fmtPos(it.lat, it.lon) }),
      itemActions(it, () => map.closePopup()))).openPopup());
    if (!labels) m.closeTooltip();
  }
}
let zoneSig = "";
function drawZones() {
  drawItems();
  const zs = S.geofences || [], sig = JSON.stringify(zs);
  if (sig === zoneSig) return; zoneSig = sig;
  zoneLayer.clearLayers();
  const who = { people: "TAK users", drones: "drones", all: "anything", me: "me" };
  for (const z of zs) {
    const st = { color: "#ff3b30", weight: 2, fillOpacity: .07 };
    const shape = z.shape === "circle" && z.pts[0] ? L.circle([z.pts[0][0], z.pts[0][1]], Object.assign({ radius: z.pts[0][2] || 100 }, st)) : L.polygon(z.pts.map(p => [p[0], p[1]]), st);
    shape.bindTooltip(z.name, { sticky: true }).addTo(zoneLayer);
  }
  $("#geo-list").replaceChildren(...(zs.length ? zs.map(z => el("div", { class: "item" },
    el("div", { class: "grow" }, el("div", { class: "t", text: z.name }), el("div", { class: "s", text: (z.shape === "circle" ? "circle " + fmtDist(z.pts[0] ? z.pts[0][2] : 0) : z.pts.length + "-point zone") + " · alerts on " + (who[z.who] || "one contact") + (z.chat ? " · GeoChat" : "") + " · " + sentLabel(z.sent) + (z.alert ? " · TAK alert " + sentLabel(z.alert).replace("sent ", "") : "") }),
      itemActions(z)),
    el("button", { class: "btn small", text: "Show", onclick: () => { setFollow(false); map.fitBounds(L.latLngBounds(z.pts.map(p => [p[0], p[1]])).pad(z.shape === "circle" ? 2 : .3)); } })))
    : [el("div", { class: "hint", text: "No zones yet." })]));
}

// ---------------------------------------------------------------- browser alerts
let audioCtx = null;
document.addEventListener("click", () => { if (!audioCtx && window.AudioContext) { try { audioCtx = new AudioContext(); } catch (e) { /* no audio */ } } }, { once: true });
function beep(urgent) {
  if (!audioCtx || lsGet("ptak.sound") === "0") return;
  const n = urgent ? 3 : 1;
  for (let i = 0; i < n; i++) {
    const o = audioCtx.createOscillator(), g = audioCtx.createGain(), t = audioCtx.currentTime + i * 0.25;
    o.frequency.value = urgent ? 1046 : 784; o.connect(g); g.connect(audioCtx.destination);
    g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(0.25, t + 0.02); g.gain.exponentialRampToValueAtTime(0.0001, t + 0.18);
    o.start(t); o.stop(t + 0.2);
  }
}
function notify(title, body, urgent) {
  beep(urgent);
  if (document.hidden && window.Notification && Notification.permission === "granted") {
    try { new Notification(PRODUCT + ": " + title, { body, tag: urgent ? undefined : "ptak", requireInteraction: !!urgent }); } catch (e) { /* ignore */ }
  }
}
function setTitle(n) { document.title = (n ? "(" + n + ") " : "") + PRODUCT; }
function notifyHint() {
  const h = $("#notify-hint"), b = $("#notify-on");
  if (!window.Notification || !window.isSecureContext) { h.textContent = PRODUCT === "PagerTAK" ? "Pop-up notifications need HTTPS (Pager: Settings > Web console > HTTPS). Sound works without it." : "Pop-up notifications need HTTPS. Sound works without it."; b.disabled = true; }
  else if (Notification.permission === "granted") { h.textContent = "Pop-ups are on when this tab is in the background."; b.disabled = true; }
  else if (Notification.permission === "denied") { h.textContent = "This browser blocked notifications for this page."; b.disabled = true; }
  else h.textContent = "";
}
$("#notify-on").addEventListener("click", async () => { try { await Notification.requestPermission(); } catch (e) { /* ignore */ } notifyHint(); });
$("#set-alerts").sound.addEventListener("change", ev => { lsSet("ptak.sound", ev.target.checked ? "1" : "0"); if (ev.target.checked) beep(false); });
$("#set-map").coords.addEventListener("change", ev => { lsSet("ptak.coords", ev.target.value); });

// ---------------------------------------------------------------- TAK channels
let chanGroups = [];
$("#chan-load").addEventListener("click", async () => {
  $("#chan-list").replaceChildren(el("div", { class: "hint", text: "Asking the TAK Server..." }));
  const r = await api("/api/channels").catch(() => ({ ok: false, msg: "Device not reachable", groups: [] }));
  if (!r.ok) { $("#chan-list").replaceChildren(el("div", { class: "hint", text: r.msg })); return; }
  chanGroups = r.groups;
  const names = [...new Set(chanGroups.map(g => g.name))].sort();
  $("#chan-list").replaceChildren(...(names.length ? names.map(nm => {
    const row = el("div", { class: "chanrow" }, el("span", { text: nm }));
    for (const dir of ["IN", "OUT"]) {
      const g = chanGroups.find(x => x.name === nm && x.direction === dir);
      if (!g) { row.append(el("span")); continue; }
      const cb = el("input", { type: "checkbox" }); cb.checked = g.active; cb.addEventListener("change", () => { g.active = cb.checked; });
      row.append(el("label", {}, cb, dir === "IN" ? "In" : "Out"));
    }
    return row;
  }) : [el("div", { class: "hint", text: "No groups returned." })]));
  $("#chan-save").classList.toggle("hidden", !names.length);
});
$("#chan-save").addEventListener("click", async () => {
  if (!chanGroups.some(g => g.active && g.direction === "OUT")) { if (!confirm("No Out channel is on - nobody will see your position or chat. Save anyway?")) return; }
  await cmd("channels_set", { groups: chanGroups.map(g => ({ name: g.name, direction: g.direction, active: g.active })) });
});

// ---------------------------------------------------------------- SIGINT
let wifiKind = "aps", wifiData = null, sigTick = 0, foxHist = [];
const isRand = mac => /^.[26ae]/i.test(mac);
const sigColor = d => d >= -50 ? "#3fb950" : d >= -65 ? "#9be15d" : d >= -75 ? "#d29922" : "#f85149";
async function sigintTick(force) {
  if (tab !== "sigint" || document.hidden) return;
  sigTick++;
  const fox = await api("/api/sigint/fox").catch(() => null);
  if (fox) drawFox(fox);
  if (force || sigTick % 3 === 0) { const r = await api("/api/sigint/radio").catch(() => null); if (r) drawRadio(r); }
  if (force || sigTick % 4 === 0) {
    wifiData = await api("/api/sigint/wifi?mins=" + $("#wifi-mins").value).catch(() => wifiData);
    drawWifi();
  }
}
function drawRadio(r) {
  const mode = r.hop === 0 || (r.hop === null && r.owner) ? "Locked to channel " + (r.channel || "?") : r.hop === 200 ? "Hopping (fast)" : r.hop === 1000 ? "Hopping (slow)" : r.channel ? "On channel " + r.channel : "Unknown";
  const ch = el("input", { type: "number", min: "1", max: "177", value: String(r.channel || 6), style: "width:80px" });
  const busy = r.rid ? "Drone watch is using the radio" : r.owner && r.owner.startsWith("fox") ? "Fox hunt is using the radio" : "";
  $("#radio-card").replaceChildren(
    el("div", { class: "head" }, el("span", { class: "t", text: "Radio (" + r.iface + ")" }), el("span", { class: "hint", text: mode })),
    busy ? el("div", { class: "hint", text: busy }) : "",
    el("div", { class: "row" }, ch,
      el("button", { class: "btn small", text: "Lock", disabled: !!busy, onclick: () => { if (confirm("Lock the radio to channel " + ch.value + "? Recon will only hear that channel until you set hopping again.")) cmd("radio", { action: "lock", channel: ch.value }); } }),
      el("button", { class: "btn small", text: "Hop fast", disabled: !!busy, onclick: () => cmd("radio", { action: "fast" }) }),
      el("button", { class: "btn small", text: "Hop slow", disabled: !!busy, onclick: () => cmd("radio", { action: "slow" }) })),
    r.pineap ? "" : el("div", { class: "hint", text: "_pineap not found - radio control needs the Pager firmware's tools." }));
}
function drawFox(f) {
  const card = $("#fox-card");
  foxLayer.clearLayers();
  if (f.track.length) {
    for (const t of f.track) L.circleMarker([t[1], t[2]], { radius: 5, stroke: false, fillColor: sigColor(t[3]), fillOpacity: .85, interactive: false }).addTo(foxLayer);
    if (f.best_pos) L.circleMarker(f.best_pos, { radius: 9, color: "#fff", weight: 2, fillColor: sigColor(f.best), fillOpacity: 1 }).bindTooltip("Strongest " + f.best + " dBm", { permanent: true, direction: "right", className: "lbl" }).addTo(foxLayer);
  }
  if (!f.running) {
    foxHist = [];
    if (card.dataset.mode === "idle") return;
    card.dataset.mode = "idle";
    const mac = el("input", { placeholder: "Target MAC aa:bb:cc:dd:ee:ff", maxlength: "17" }), lock = el("input", { type: "checkbox", checked: true });
    card.replaceChildren(el("div", { class: "head" }, el("span", { class: "t", text: "Fox hunt" })),
      el("div", { class: "hint", text: "Follow one device by signal strength. Pick it from the Wi-Fi list below (Hunt) or type its MAC." + (f.track.length ? " The last hunt's trail is on the map." : "") }),
      el("div", { class: "row" }, mac, el("button", { class: "btn primary small", text: "Start", onclick: () => startFox(mac.value.trim(), "", lock.checked, 0) })),
      el("div", { class: "checks" }, el("label", {}, lock, "Lock the radio to the target's channel (faster readings)")));
    return;
  }
  card.dataset.mode = "run";
  if (f.dbm !== null && f.ts !== foxHist.ts) { foxHist.push(f.dbm); foxHist.ts = f.ts; if (foxHist.length > 90) foxHist.shift(); }
  const pct = f.dbm === null ? 0 : Math.max(0, Math.min(100, (f.dbm + 95) / 65 * 100));
  const age = f.ts ? Math.round(Date.now() / 1000 - f.ts) : null;
  const cv = el("canvas", { class: "spark", width: "320", height: "50" });
  card.replaceChildren(
    el("div", { class: "head" }, el("span", { class: "t", text: "Fox hunt: " + (f.label || f.target) }), el("button", { class: "btn small danger", text: "Stop", onclick: () => cmd("fox_stop") })),
    el("div", { class: "hint", text: f.target }),
    el("div", { class: "gauge" }, el("span", { class: "big", text: f.dbm === null ? "--" : String(f.dbm) }), el("span", { text: "dBm" }),
      el("span", { class: "hint", text: f.best !== null ? "best " + f.best + " · " + f.n + " readings" + (age !== null && age > 5 ? " · last " + age + "s ago" : "") : "waiting for the device to transmit..." })),
    el("div", { class: "bar" }, Object.assign(el("div"), { style: "width:" + pct + "%;background:" + (f.dbm === null ? "#555" : sigColor(f.dbm)) })),
    cv,
    el("div", { class: "hint", text: f.track.length ? "Trail: colored dots at your GPS positions, white ring = strongest reading." : "No GPS fix: readings only, no trail." }));
  const g = cv.getContext("2d"); g.strokeStyle = "#2fb5c8"; g.lineWidth = 2; g.beginPath();
  foxHist.forEach((v, i) => { const x = i * 320 / 89, y = 50 - Math.max(0, Math.min(50, (v + 95) / 65 * 50)); i ? g.lineTo(x, y) : g.moveTo(x, y); });
  g.stroke();
}
async function startFox(mac, label, lock, ch) {
  if (!/^([0-9a-f]{2}:){5}[0-9a-f]{2}$/i.test(mac)) { toast("Enter a MAC like aa:bb:cc:dd:ee:ff", false); return; }
  $("#fox-card").dataset.mode = ""; foxHist = [];
  await cmd("fox_start", { mac, label, lock: !!lock, channel: ch || 0 });
  sigintTick(true);
}
function drawWifi() {
  const d = wifiData, list = $("#wifi-list"), q = $("#wifi-q").value.trim().toLowerCase();
  if (!d) return;
  if (!d.db && !d.clients.length) { $("#wifi-sum").textContent = "No recon data. Start Recon first (and install sqlite3-cli)."; list.replaceChildren(); return; }
  const match = (...v) => !q || v.some(x => String(x || "").toLowerCase().includes(q));
  let rows = [];
  if (wifiKind === "aps") {
    const aps = d.aps.filter(a => match(a.ssid, a.mac));
    $("#wifi-sum").textContent = d.aps.length + " access points · " + d.aps.filter(a => a.enc === "Open").length + " open · " + d.aps.filter(a => a.hidden).length + " hidden";
    rows = aps.slice(0, 150).map(a => el("div", { class: "wrow" },
      el("div", { class: "t" }, a.hidden ? el("i", { text: "hidden" }) : a.ssid, el("span", { class: "tag" + (a.enc === "Open" ? " open" : ""), text: a.enc })),
      el("div", { class: "sig", style: "color:" + sigColor(a.sig), text: a.sig + " dBm" }),
      el("div", { class: "m", text: a.mac + " · ch " + a.ch }), el("div", { class: "hint", text: age(a.ts) + " ago" }),
      el("div", { class: "acts" }, el("button", { class: "btn small", text: "Hunt", onclick: () => startFox(a.mac, a.ssid || "hidden AP", true, 0) }))));
  } else if (wifiKind === "clients") {
    const cl = d.clients.filter(c => match(c.mac, c.ap, c.ssid));
    $("#wifi-sum").textContent = d.clients.length + " clients seen by recon" + (d.clients.length ? "" : " (needs the Pager's _pineap tool)");
    const apName = mac => { const a = d.aps.find(x => x.mac === mac); return a ? (a.ssid || "hidden") : ""; };
    rows = cl.slice(0, 150).map(c => el("div", { class: "wrow" },
      el("div", { class: "t" }, c.mac, isRand(c.mac) ? el("span", { class: "tag rand", text: "random MAC" }) : ""),
      el("div", { class: "sig", style: "color:" + sigColor(c.sig), text: c.sig ? c.sig + " dBm" : "" }),
      el("div", { class: "m", text: c.ap ? "on " + (c.ssid || apName(c.ap) || "") + " " + c.ap : "not associated" }), el("div"),
      el("div", { class: "acts" }, el("button", { class: "btn small", text: "Hunt", onclick: () => startFox(c.mac, "client", true, c.ch || ((d.aps.find(x => x.mac === c.ap) || {}).ch) || 0) }))));
  } else {
    const by = new Map();
    for (const p of d.probes) {
      if (!by.has(p.mac)) by.set(p.mac, { mac: p.mac, ssids: [], ts: 0, sig: p.sig });
      const e = by.get(p.mac); if (p.ssid) e.ssids.push(p.ssid); if (p.ts > e.ts) { e.ts = p.ts; e.sig = p.sig; }
    }
    const devs = [...by.values()].filter(e => match(e.mac, ...e.ssids)).sort((a, b) => b.ts - a.ts);
    $("#wifi-sum").textContent = by.size + " devices probing · " + d.probes.filter(p => p.ssid).length + " named networks asked for";
    rows = devs.slice(0, 150).map(e => el("div", { class: "wrow" },
      el("div", { class: "t" }, e.mac, isRand(e.mac) ? el("span", { class: "tag rand", text: "random MAC" }) : ""),
      el("div", { class: "sig", style: "color:" + sigColor(e.sig), text: e.sig ? e.sig + " dBm" : "" }),
      el("div", { class: "m", text: e.ssids.length ? "looking for: " + [...new Set(e.ssids)].join(", ") : "broadcast probes only" }), el("div", { class: "hint", text: age(e.ts) + " ago" }),
      el("div", { class: "acts" }, el("button", { class: "btn small", text: "Hunt", onclick: () => startFox(e.mac, "probing device", false, 0) }))));
  }
  list.replaceChildren(...(rows.length ? rows : [el("div", { class: "hint", text: "Nothing matches." })]));

}
$$("#wifi-kind button").forEach(b => b.addEventListener("click", () => { wifiKind = b.dataset.k; $$("#wifi-kind button").forEach(x => x.classList.toggle("on", x === b)); drawWifi(); }));
$("#wifi-q").addEventListener("input", drawWifi);
$("#wifi-mins").addEventListener("change", () => sigintTick(true));

// ---------------------------------------------------------------- modal
function modal(...kids) { $("#modal-box").replaceChildren(...kids); $("#modal").classList.remove("hidden"); }
function closeModal() { $("#modal").classList.add("hidden"); $("#modal-box").replaceChildren(); }
$("#modal").addEventListener("click", ev => { if (ev.target.id === "modal" && !modal.locked) closeModal(); });

// ---------------------------------------------------------------- alert dialog
const EMERG = [["911", "911 Alert"], ["bell", "Ring The Bell"], ["geo", "Geo-fence Breached"], ["contact", "Troops In Contact"], ["custom", "Custom..."]];
function contactChecks(name, picked) {
  const cs = (S && S.contacts) || [];
  if (!cs.length) return el("div", { class: "hint", text: "No TAK users seen yet." });
  return el("div", { class: "checks" }, cs.map(c => {
    const i = el("input", { type: "checkbox", name, value: c.uid + ":" + c.cs }); i.checked = (picked || []).includes(c.uid);
    return el("label", {}, i, c.cs);
  }));
}
function alertDialog() {
  let kind = "911";
  const label = el("input", { placeholder: "Alert name (e.g. Shelter in place)", maxlength: "30", class: "hidden" });
  const types = el("div", { class: "types" }, EMERG.map(([k, t]) => el("button", { type: "button", class: "btn" + (k === "911" ? " on" : ""), text: t, onclick: ev => {
    kind = k; $$(".types .btn").forEach(b => b.classList.toggle("on", b === ev.target)); label.classList.toggle("hidden", k !== "custom"); if (k === "custom") label.focus();
  } })));
  const who = sel("who", [["all", "Everyone"], ["some", "Only the people I pick"]]);
  const list = el("div", { class: "hidden" }, contactChecks("to"));
  who.addEventListener("change", () => list.classList.toggle("hidden", who.value !== "some"));
  modal(el("h3", { text: "Send an alert" }), types, label, lab("Send to", who), list,
    el("div", { class: "hint", text: "You get 5 seconds to cancel after pressing Send. The alert repeats with your position until you cancel it." }),
    el("div", { class: "row" }, el("button", { class: "btn danger huge", text: "Send", onclick: () => {
      const to = who.value === "some" ? $$("input[name=to]:checked", list).map(i => i.value) : [];
      if (who.value === "some" && !to.length) { toast("Pick at least one person", false); return; }
      if (kind === "custom" && !label.value.trim()) { toast("Name the custom alert", false); label.focus(); return; }
      countdown(kind, label.value.trim(), to);
    } }), el("button", { class: "btn", text: "Close", onclick: closeModal })));
}
function countdown(kind, label, to) {
  let n = 5, timer;
  const num = el("div", { class: "countdown", text: "5" });
  const name = kind === "custom" ? label : EMERG.find(e => e[0] === kind)[1];
  modal.locked = true;
  modal(el("h3", { text: "Sending " + name + " to " + (to.length ? to.length + " people" : "everyone") }), num,
    el("button", { class: "btn huge", text: "CANCEL", onclick: () => { clearInterval(timer); modal.locked = false; closeModal(); toast("Alert not sent"); } }));
  timer = setInterval(async () => {
    n--; num.textContent = String(n);
    if (n > 0) return;
    clearInterval(timer); modal.locked = false; closeModal();
    await cmd("emergency", { kind, label, to: to.join(",") });
  }, 1000);
}
function alertName() { const e = S && S.emergency_info; if (!e) return ""; return e.kind === "custom" ? (e.label || "Custom") : (EMERG.find(x => x[0] === e.kind) || [0, "911 Alert"])[1]; }

// ---------------------------------------------------------------- man-down watchdog
let mdSig = "";
function drawMandown() {
  const md = S.sensors.md, sig = JSON.stringify([md, (S.contacts || []).map(c => c.uid)]);
  const b = $("#banner-md");
  if (md.state === "warn") {
    b.classList.remove("hidden");
    $("#banner-md-text").textContent = "MAN-DOWN CHECK: no movement for " + md.min + " min. An alert is sent in " + Math.max(0, Math.round(md.deadline - Date.now() / 1000)) + " s.";
  } else b.classList.add("hidden");
  if (sig === mdSig || document.activeElement.closest("#md-card")) return; mdSig = sig;
  const on = el("input", { type: "checkbox" }); on.checked = md.on;
  const me = el("input", { type: "checkbox" }); me.checked = md.me;
  const chat = el("input", { type: "checkbox" }); chat.checked = md.chat;
  const mins = el("input", { type: "number", min: "1", max: "240", value: String(md.min), style: "width:80px" });
  const people = contactChecks("mdwho", md.who);
  $("#md-card").replaceChildren(
    el("div", { class: "head" }, el("span", { class: "dot" + (md.running ? " on" : "") }), el("span", { class: "t", text: "Man-down watchdog" })),
    el("div", { class: "hint", text: "You: no movement and no button press for the set time warns you, then sends a 911 alert after 60 s. " + (PRODUCT === "PagerTAK" ? "Any Pager button or I'M OK" : "I'M OK") + " resets it. Others: alerts you when someone you pick stops moving or stops reporting." }),
    el("div", { class: "checks" }, el("label", {}, on, "Watchdog on"), el("label", {}, me, "Watch me"), el("label", {}, chat, "GeoChat check-ons")),
    el("div", { class: "row" }, el("span", { class: "hint", text: "Minutes without movement" }), mins),
    el("h4", { text: "Watch these TAK users" }), people,
    el("button", { class: "btn primary small", text: "Save watchdog", onclick: () => cmd("settings", {
      md: on.checked, md_me: me.checked, md_chat: chat.checked, md_min: mins.value,
      md_who: $$("input[name=mdwho]:checked", $("#md-card")).map(i => i.value.split(":")[0]).join(",") }) }));
}
$("#b-imok").addEventListener("click", () => cmd("imok"));

// ---------------------------------------------------------------- radius filter
$("#m-radius").addEventListener("change", ev => cmd("settings", { cot_radius: ev.target.value }, true));

// ---------------------------------------------------------------- CoT details
const AFFN = { f: "Friendly", h: "Hostile", s: "Suspect", u: "Unknown", n: "Neutral", p: "Pending", a: "Assumed friend", j: "Joker", k: "Faker", o: "None" };
const DIMN = { P: "Space", A: "Air", G: "Ground", S: "Sea surface", U: "Subsurface", F: "SOF" };
const FUNCN = [[/^a-.-G-U-C/, "Ground unit, combat"], [/^a-.-G-E-V/, "Ground vehicle"], [/^a-.-G-I/, "Installation"], [/^a-.-A-M-F-Q/, "Military UAV (fixed wing)"],
  [/^a-.-A-M-H-Q/, "Military UAV (rotary)"], [/^a-.-A-M-F/, "Military fixed wing"], [/^a-.-A-M-H/, "Military rotary wing"], [/^a-.-A-C-F/, "Civil fixed wing"],
  [/^a-.-A-C-H/, "Civil rotary wing"], [/^a-.-A/, "Air track"], [/^a-.-G-E-S-E/, "Drone operator / emitter"], [/^a-.-S/, "Vessel"], [/^b-m-p-s-m/, "Spot map marker"],
  [/^b-m-p-w/, "Waypoint"], [/^b-r-f-h-c/, "MEDEVAC request"], [/^b-a-o-tbl/, "911 alert"], [/^u-d-/, "Drawing"]];
function describeType(t) {
  const p = t.split("-"), f = (FUNCN.find(x => x[0].test(t)) || [0, ""])[1];
  if (p[0] !== "a") return f || t;
  return [AFFN[p[1]] || p[1], DIMN[p[2]] || p[2], f].filter(Boolean).join(" · ");
}
const HOWN = { "m-g": "GPS", "h-e": "entered by hand", "h-g-i-g-o": "placed on map", "m-f": "fused", "m-r": "reckoned", "h-c": "calculated" };
async function cotDetails(t) {
  const d = await api("/api/cot/" + encodeURIComponent(t.id)).catch(() => null);
  const rows = [["Callsign", t.cs], ["Type", t.type + "  (" + describeType(t.type) + ")"], ["Position", fmtPos(t.lat, t.lon) + "   " + ll(t.lat, t.lon)]];
  if (haveMe()) { const [m, b] = distBrg(S.self, t); rows.push(["From me", fmtDist(m) + " at " + Math.round(b) + "°"]); }
  rows.push(["Last update", age(t.ts) + " ago"]);
  if (d && !d.error) {
    const e = d.event || {}, pt = d.point || {};
    rows.push(["UID", e.uid || ""], ["How", (e.how || "") + (HOWN[e.how] ? " (" + HOWN[e.how] + ")" : "")], ["Time", e.time || ""], ["Stale", e.stale || ""]);
    if (pt.hae && pt.hae !== "9999999.0") rows.push(["Height (HAE)", Math.round(pt.hae) + " m"]);
    if (pt.ce && pt.ce !== "9999999.0") rows.push(["Accuracy (CE)", Math.round(pt.ce) + " m"]);
    if (d.track) rows.push(["Course / speed", Math.round(+d.track.course || 0) + "° / " + ((+d.track.speed || 0) * 3.6).toFixed(1) + " km/h"]);
    if (d.group) rows.push(["Team / role", (d.group.name || "") + " / " + (d.group.role || "")]);
    if (d.status && d.status.battery) rows.push(["Battery", d.status.battery + "%"]);
    if (d.takv) rows.push(["Device", [d.takv.device, d.takv.platform, d.takv.version, d.takv.os].filter(Boolean).join(" · ")]);
    if (d.contact && d.contact.endpoint) rows.push(["Endpoint", d.contact.endpoint]);
    if (d.contact && d.contact.phone) rows.push(["Phone", d.contact.phone]);
    if (d.remarks) rows.push(["Remarks", d.remarks]);
  }
  const raw = d && d.raw ? el("details", {}, el("summary", { text: "Raw CoT" }), el("pre", { class: "raw", text: d.raw })) : el("div", { class: "hint", text: "No raw event saved for this item." });
  modal(el("h3", { text: t.cs }), el("div", { class: "kvx" }, rows.flat().map(x => el("span", { text: String(x) }))), raw,
    el("div", { class: "row" }, el("button", { class: "btn", text: "Show on map", onclick: () => { closeModal(); setFollow(false); map.setView([t.lat, t.lon], Math.max(map.getZoom(), 16)); } }),
      el("button", { class: "btn", text: "Close", onclick: closeModal })));
}

// ---------------------------------------------------------------- photo / file to TAK
$("#chat-file").addEventListener("click", () => $("#chat-file-in").click());
$("#chat-file-in").addEventListener("change", async ev => {
  const f = ev.target.files[0]; ev.target.value = "";
  if (!f) return;
  if (f.size > 8 * 1024 * 1024) { toast("Up to 8 MB", false); return; }
  const to = $("#chat-to").value, c = (S.contacts || []).find(x => x.uid === to);
  const q = new URLSearchParams({ name: f.name, send: c ? "dm" : "all", to_uid: c ? c.uid : "", to_cs: c ? c.cs : "" });
  if (!confirm("Send " + f.name + " (" + Math.round(f.size / 1024) + " KB) to " + (c ? c.cs : "everyone") + " as a TAK data package?\n\nIt is sent automatically - the result shows in the chat.")) return;
  toast("Uploading " + f.name + " to the Pager...");
  try {
    const r = await fetch("/api/share?" + q, { method: "POST", credentials: "same-origin", headers: { "X-PagerTAK": "1", "Content-Type": "application/octet-stream" }, body: f });
    const j = await r.json().catch(() => ({ ok: false, msg: "Upload failed (" + r.status + ")" }));
    toast(j.msg, j.ok);
    if (j.ok) watchShare();
  } catch (e) { toast("Upload failed", false); }
});
function watchShare(n = 0) {
  setTimeout(async () => {
    const r = await api("/api/share").catch(() => ({}));
    const [st, msg] = (r.status || "").split(/\|(.*)/s);
    if (st === "busy" && n < 100) return watchShare(n + 1);
    if (msg) toast(msg, st === "ok");
  }, 3000);
}

// ---------------------------------------------------------------- layers: trails + overlays
let trailsOn = lsGet("ptak.trails") === "1", trailLayer = null, ovLayers = {};
function layersDialog() {
  const tr = el("input", { type: "checkbox" }); tr.checked = trailsOn;
  tr.addEventListener("change", () => { trailsOn = tr.checked; lsSet("ptak.trails", trailsOn ? "1" : "0"); drawTrails(); });
  const list = el("div", { class: "list small" }), file = el("input", { type: "file", accept: ".kml,.kmz" });
  const refresh = async () => {
    const ovs = await api("/api/overlays").catch(() => []);
    list.replaceChildren(...(ovs.length ? ovs.map(o => {
      const cb = el("input", { type: "checkbox" }); cb.checked = ovEnabled(o.name);
      cb.addEventListener("change", () => { ovSet(o.name, cb.checked); loadOverlays(); });
      return el("div", { class: "item" }, el("label", { class: "grow" }, cb, " " + o.name + " (" + Math.round(o.size / 1024) + " KB)"),
        el("button", { class: "btn small", text: "Delete", onclick: async () => {
          if (!confirm("Delete overlay " + o.name + " from the Pager?")) return;
          const r = await api("/api/overlays/delete", { name: o.name }); toast(r.msg, r.ok); ovSet(o.name, false); loadOverlays(); refresh();
        } }));
    }) : [el("div", { class: "hint", text: "No overlays yet." })]));
  };
  file.addEventListener("change", async () => {
    const f = file.files[0]; if (!f) return;
    if (f.size > 4 * 1024 * 1024) { toast("Up to 4 MB", false); return; }
    const r = await fetch("/api/overlays?name=" + encodeURIComponent(f.name), { method: "POST", credentials: "same-origin", headers: { "X-PagerTAK": "1" }, body: f });
    const j = await r.json().catch(() => ({ ok: false, msg: "Upload failed" }));
    toast(j.msg, j.ok); if (j.ok) { ovSet(j.name || f.name, true); refresh(); loadOverlays(); }
    file.value = "";
  });
  modal(el("h3", { text: "Layers" }), el("div", { class: "checks" }, el("label", {}, tr, "Breadcrumb trails (last hour: you, TAK users, drones)")),
    el("h4", { text: "KML / KMZ overlays (stored on the Pager, shown in this browser)" }), list, lab("Add an overlay", file),
    el("button", { class: "btn", text: "Close", onclick: closeModal }));
  refresh();
}
const ovEnabled = n => (JSON.parse(lsGet("ptak.ov") || "[]")).includes(n);
function ovSet(n, on) { const a = new Set(JSON.parse(lsGet("ptak.ov") || "[]")); on ? a.add(n) : a.delete(n); lsSet("ptak.ov", JSON.stringify([...a])); }
async function drawTrails() {
  if (!trailLayer) trailLayer = L.layerGroup().addTo(map);
  if (!trailsOn) { trailLayer.clearLayers(); return; }
  const t = await api("/api/trails").catch(() => null); if (!t) return;
  trailLayer.clearLayers();
  for (const [id, pts] of Object.entries(t)) {
    const tr = S && S.tracks.find(x => x.id === id);
    const color = id === "self" ? "#2fb5c8" : tr && tr.cat === "drones" ? "#b388ff" : tr && tr.cat === "aircraft" ? "#ffd60a" : tr && TEAM_RGB[tr.team] ? TEAM_RGB[tr.team] : "#9aa5b1";
    if (id !== "self" && !tr) continue;
    L.polyline(pts, { color, weight: 2, opacity: .8, dashArray: "4 4", interactive: false }).addTo(trailLayer);
  }
}
async function unzipFirstKml(buf) {
  const v = new DataView(buf), u8 = new Uint8Array(buf);
  let eocd = -1;
  for (let i = buf.byteLength - 22; i >= Math.max(0, buf.byteLength - 70000); i--) if (v.getUint32(i, true) === 0x06054b50) { eocd = i; break; }
  if (eocd < 0) throw new Error("not a zip");
  let p = v.getUint32(eocd + 16, true);
  const n = v.getUint16(eocd + 10, true), dec = new TextDecoder();
  for (let k = 0; k < n; k++) {
    const method = v.getUint16(p + 10, true), csize = v.getUint32(p + 20, true), nl = v.getUint16(p + 28, true), xl = v.getUint16(p + 30, true), cl = v.getUint16(p + 32, true), off = v.getUint32(p + 42, true);
    const name = dec.decode(u8.subarray(p + 46, p + 46 + nl));
    p += 46 + nl + xl + cl;
    if (!/\.kml$/i.test(name)) continue;
    const start = off + 30 + v.getUint16(off + 26, true) + v.getUint16(off + 28, true), data = u8.subarray(start, start + csize);
    if (method === 0) return dec.decode(data);
    const ds = new Blob([data]).stream().pipeThrough(new DecompressionStream("deflate-raw"));
    return await new Response(ds).text();
  }
  throw new Error("no .kml inside");
}
function kmlColor(c, def) { if (!c || c.length < 8) return [def, 1]; return ["#" + c.slice(6, 8) + c.slice(4, 6) + c.slice(2, 4), parseInt(c.slice(0, 2), 16) / 255]; }
function renderKml(text, group) {
  const doc = new DOMParser().parseFromString(text, "application/xml");
  const q = (n, tag) => Array.from(n.getElementsByTagNameNS("*", tag));
  const styles = {};
  for (const s of q(doc, "Style")) styles[s.getAttribute("id")] = s;
  for (const m of q(doc, "StyleMap")) { const pr = q(m, "Pair").find(x => (q(x, "key")[0] || {}).textContent === "normal"); if (pr) styles[m.getAttribute("id")] = styles[((q(pr, "styleUrl")[0] || {}).textContent || "").replace("#", "")]; }
  const coords = s => s.trim().split(/\s+/).map(c => c.split(",").map(Number)).filter(c => c.length >= 2 && isFinite(c[0]) && isFinite(c[1])).map(c => [c[1], c[0]]);
  let count = 0;
  for (const pm of q(doc, "Placemark")) {
    if (++count > 5000) break;
    const name = (q(pm, "name")[0] || {}).textContent || "";
    const descHtml = (q(pm, "description")[0] || {}).textContent || "";
    const desc = descHtml ? new DOMParser().parseFromString(descHtml, "text/html").body.textContent.trim().slice(0, 500) : "";
    const st = styles[((q(pm, "styleUrl")[0] || {}).textContent || "").replace("#", "")] || q(pm, "Style")[0];
    const [lc, la] = kmlColor(st && (q(st, "LineStyle")[0] ? (q(q(st, "LineStyle")[0], "color")[0] || {}).textContent : ""), "#ffd60a");
    const [pc, pa] = kmlColor(st && (q(st, "PolyStyle")[0] ? (q(q(st, "PolyStyle")[0], "color")[0] || {}).textContent : ""), lc);
    const pop = el("div", {}, el("b", { text: name }), desc ? el("div", { text: desc }) : "");
    for (const g of q(pm, "Point")) { const c = coords((q(g, "coordinates")[0] || {}).textContent || ""); if (c[0]) L.circleMarker(c[0], { radius: 5, color: lc, fillOpacity: .8 }).bindPopup(pop).bindTooltip(name, { className: "lbl" }).addTo(group); }
    for (const g of q(pm, "LineString")) { const c = coords((q(g, "coordinates")[0] || {}).textContent || ""); if (c.length > 1) L.polyline(c, { color: lc, opacity: la, weight: 3 }).bindPopup(pop).addTo(group); }
    for (const g of q(pm, "Polygon")) {
      const outer = q(g, "outerBoundaryIs")[0] || g, c = coords((q(outer, "coordinates")[0] || {}).textContent || "");
      if (c.length > 2) L.polygon(c, { color: lc, opacity: la, weight: 2, fillColor: pc, fillOpacity: Math.min(.5, pa * .5) }).bindPopup(pop).bindTooltip(name, { sticky: true }).addTo(group);
    }
  }
}
async function loadOverlays() {
  const ovs = await api("/api/overlays").catch(() => []);
  for (const [n, g] of Object.entries(ovLayers)) if (!ovEnabled(n) || !ovs.some(o => o.name === n)) { map.removeLayer(g); delete ovLayers[n]; }
  for (const o of ovs) {
    if (!ovEnabled(o.name) || ovLayers[o.name]) continue;
    try {
      const buf = await (await fetch("/overlays/" + encodeURIComponent(o.name), { credentials: "same-origin" })).arrayBuffer();
      const text = /\.kmz$/i.test(o.name) ? await unzipFirstKml(buf) : new TextDecoder().decode(buf);
      const g = L.layerGroup(); renderKml(text, g); g.addTo(map); ovLayers[o.name] = g;
    } catch (e) { toast("Could not read " + o.name + ": " + e.message, false); }
  }
}
$("#t-layers").addEventListener("click", layersDialog);

// ---------------------------------------------------------------- offline area download
function offlineDialog() {
  const b = map.getBounds(), z = map.getZoom(), src = $("#m-source").value;
  const zmax = sel("zmax", [...Array(20).keys()].filter(i => i >= z && i <= 19).map(String), String(Math.min(19, z + 3)));
  const info = el("div", { class: "hint", text: "" });
  const body = () => ({ slug: src, s: b.getSouth(), w: b.getWest(), n: b.getNorth(), e: b.getEast(), zmin: Math.max(0, z - 2), zmax: Number(zmax.value) });
  const check = async () => { const r = await api("/api/tiles/job", Object.assign({ check: true }, body())); info.textContent = r.ok ? r.count.toLocaleString() + " tiles, about " + Math.ceil(r.count * 20 / 1024) + " MB (tiles already saved are skipped)" : r.msg; };
  zmax.addEventListener("change", check);
  modal(el("h3", { text: "Save this area for offline use" }),
    el("div", { class: "hint", text: "Downloads the area on screen (" + ($("#m-source").selectedOptions[0] || {}).textContent + ") onto the Pager, from zoom " + Math.max(0, z - 2) + " up to the zoom you pick. The Pager map and this page then work without internet there." }),
    lab("Most detailed zoom", zmax), info,
    el("div", { class: "row" }, el("button", { class: "btn primary", text: "Download", onclick: async () => { const r = await api("/api/tiles/job", body()); toast(r.msg, r.ok); if (r.ok) { closeModal(); jobPoll(); } } }),
      el("button", { class: "btn", text: "Close", onclick: closeModal })));
  check();
}
async function jobPoll() {
  const j = await api("/api/tiles/job").catch(() => null), bar = $("#m-job");
  if (!j || j.state === "idle") { bar.classList.add("hidden"); return; }
  bar.classList.remove("hidden");
  if (j.state === "running") {
    bar.replaceChildren("Offline download: " + j.done + " / " + j.total + " tiles ", el("button", { class: "btn small", text: "Stop", onclick: () => api("/api/tiles/cancel", {}) }));
    setTimeout(jobPoll, 3000);
  } else {
    bar.replaceChildren((j.state === "done" ? "Offline download finished: " : "Offline download stopped: ") + j.got + " new tiles ", el("button", { class: "btn small", text: "OK", onclick: () => bar.classList.add("hidden") }));
  }
}
$("#t-offline").addEventListener("click", offlineDialog);

// ---------------------------------------------------------------- tabs + loop
function showTab(t) {
  tab = t;
  $$(".tabs button").forEach(b => b.classList.toggle("on", b.dataset.tab === t));
  $$(".tab").forEach(d => d.classList.toggle("hidden", d.id !== "tab-" + t));
  if (t === "chat") { badge("#chat-badge", 0); chatSig = ""; pollChat(); markRead(); }
  if (t === "sensors") { alertSeen = Date.now() / 1000; badge("#alert-badge", 0); sensorSig = ""; if (S) drawSensors(); }
  if (t === "reports") loadReports();
  if (t === "items" && S) { catSig = ""; drawItemsTab(); }
  if (t === "contacts" && S) drawContacts();
  if (t === "sigint") sigintTick(true);
  if (t === "chat") setTitle(0);
  if (t === "settings" && S) { formsFilled = false; drawStatus(); fillSettings(); }
  if (map) setTimeout(() => map.invalidateSize(), 50);
}
$$(".tabs button").forEach(b => b.addEventListener("click", () => showTab(b.dataset.tab)));

let polling = false, stateSig = "";
async function poll(force) {
  if (polling || (document.hidden && !force && S)) return; polling = true;
  try {
    const r = await api("/api/state?v=" + (force ? "" : stateSig));
    if (r.same) return;
    S = r; stateSig = r.v || "";
    drawTop(); drawSetup(); drawMap(); drawChatTo();
    if (tab === "contacts" && !document.activeElement.closest("#contacts")) drawContacts();
    if (tab === "items") drawItemsTab();
    if (tab === "sensors") drawSensors();
    if (tab === "settings") { drawStatus(); fillSettings(); }
    drawAlerts(); if (zoneLayer) drawZones();
  } catch (e) {
    if (e.message !== "login") { const t = $("#p-tak"); t.textContent = "Device offline"; t.className = "pill bad"; }
  } finally { polling = false; }
}
let started = false;
async function start() {
  $("#login").classList.add("hidden"); $("#app").classList.remove("hidden");
  if (started) { poll(); return; }
  started = true;
  await poll();
  await initMap();
  drawMap(); drawZones();             // zones and your markers: the first state arrived before the map existed
  buildReport();
  pollChat();
  loadOverlays(); jobPoll(); drawTrails();
  setInterval(drawTrails, 15000);
  setInterval(poll, 3000);
  setInterval(pollChat, 3000);
  setInterval(sigintTick, 1500);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) { poll(true); pollChat(); setTitle(0); } });
}
(async () => {
  try {
    const s = await api("/api/session");
    if (s.authed) start(); else showLogin(s.configured ? "" : "No password set - set one on the Pager first.");
  } catch (e) { showLogin("Device not reachable"); }
})();
