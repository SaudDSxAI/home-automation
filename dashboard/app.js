// Home dashboard - works on the local network (HTTP) and from anywhere through the cloud (MQTT)
const $ = (s, r = document) => r.querySelector(s);
const ic = (name) =>
  `<svg viewBox="0 0 24 24" aria-hidden="true">${window.ICONS[name] || ""}</svg>`;
document.querySelectorAll("[data-i]").forEach((el) => (el.innerHTML = ic(el.dataset.i)));

// relay index -> what it is (same order as the Arduino sketch)
const DEVICES = [
  { id: 0, name: "Fan", kind: "fan", c: "--c-fan" },
  { id: 1, name: "Bulb 1", kind: "bulb", c: "--c-bulb" },
  { id: 2, name: "Bulb 2", kind: "bulb", c: "--c-bulb" },
  { id: 3, name: "Bulb 3", kind: "bulb", c: "--c-bulb" },
  { id: 4, name: "Bulb 4", kind: "bulb", c: "--c-bulb" },
  { id: 5, name: "Smoke light", kind: "bulb", c: "--c-smoke", key: "smoke" },
  { id: 6, name: "Temp light", kind: "bulb", c: "--c-temp", key: "temp" },
  { id: 7, name: "Dark light", kind: "bulb", c: "--c-dark", key: "lux" },
];
// everything is OFF and manual until the board reports its real state
const blankState = () => ({ relays: [0,0,0,0,0,0,0,0], auto: [0,0,0], smoke: 0, mq2Ready: false, temp: 0, hum: 0, dhtOk: false,
  lux: 0, luxOk: false, tSmoke: 512, tTemp: 30, tLux: 100 });

/* ---------- settings (kept only in this browser) ---------- */
const DEFAULT_WS = "wss://io.adafruit.com:443";
let cfg = { mode: "", ip: "", user: "", key: "", ws: DEFAULT_WS };
try {
  const saved = JSON.parse(localStorage.getItem("home_cfg") || "null");
  if (saved) cfg = Object.assign(cfg, saved);
  else if (localStorage.getItem("sn_ip")) { cfg.mode = "local"; cfg.ip = localStorage.getItem("sn_ip"); }
} catch (e) {}
// phone setup link:  https://your-page/#cloud=USERNAME:KEY   (saved, then removed from the address bar)
try {
  const m = location.hash.match(/cloud=([^:&]+):([^&]+)/);
  if (m) {
    cfg.mode = "cloud"; cfg.user = decodeURIComponent(m[1]); cfg.key = decodeURIComponent(m[2]);
    saveCfg();
    history.replaceState(null, "", location.pathname + location.search);
  }
} catch (e) {}
function saveCfg() { try { localStorage.setItem("home_cfg", JSON.stringify(cfg)); } catch (e) {} }

const topicStatus = () => `${cfg.user}/feeds/home-status`;
const topicCmd = () => `${cfg.user}/feeds/home-cmd`;

let S = blankState();       // last known status (all OFF until the board reports)
let synced = false;         // true after the first REAL status arrived
let threshInit = false;
let inflight = 0;
let lastStatusAt = 0;       // cloud: when the Arduino last reported
let brokerUp = false;
const desired = {};         // cloud: what you just pressed, until the Arduino confirms

function toast(msg) {
  const t = document.createElement("div");
  t.className = "toast"; t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

/* ---------- local transport (HTTP to the Arduino) ---------- */
let chain = Promise.resolve();
function localApi(path) {
  const run = async () => {
    const ctl = new AbortController();
    const t = setTimeout(() => ctl.abort(), 3500);
    try {
      const r = await fetch("http://" + cfg.ip + path, { signal: ctl.signal, cache: "no-store" });
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.status);
      return j;
    } finally { clearTimeout(t); }
  };
  const p = chain.then(run, run);
  chain = p.catch(() => {});
  return p;
}

/* ---------- cloud transport (MQTT over secure WebSocket) ---------- */
let client = null;
const pubTimes = [];
function allowPublish() {                       // free plans limit messages per minute: stay far below
  const now = Date.now();
  while (pubTimes.length && now - pubTimes[0] > 60000) pubTimes.shift();
  if (pubTimes.length >= 18) return false;
  pubTimes.push(now);
  return true;
}

function cloudPublish(obj) {
  if (!client || !brokerUp) return Promise.reject(new Error("Not connected to the cloud"));
  if (!allowPublish()) return Promise.reject(new Error("Slow down: too many commands this minute"));
  client.publish(topicCmd(), JSON.stringify(obj));
  return Promise.resolve();
}

function pathToCmd(path) {
  const u = new URL(path, "http://x");
  const q = (k) => u.searchParams.get(k);
  if (u.pathname === "/relay") return { c: "relay", id: +q("id"), s: +q("state") };
  if (u.pathname === "/all") return { c: "all", s: +q("state") };
  if (u.pathname === "/mode") return { c: "mode", id: +q("id"), a: +q("auto") };
  if (u.pathname === "/threshold") return { c: "limits", smoke: +q("smoke"), temp: +q("temp"), lux: +q("lux") };
  return null;
}

function api(path) {
  if (cfg.mode !== "cloud") return localApi(path);
  if (path.startsWith("/status")) return Promise.resolve(S);
  const cmd = pathToCmd(path);
  if (!cmd) return Promise.reject(new Error("unknown command"));
  return cloudPublish(cmd).then(() => S);
}

function cloudConnect() {
  if (client) { try { client.end(true); } catch (e) {} client = null; }
  brokerUp = false;
  if (cfg.mode !== "cloud" || !cfg.user || !cfg.key) return;
  if (typeof mqtt === "undefined") { toast("Cloud library did not load. Check the internet."); return; }
  client = mqtt.connect(cfg.ws || DEFAULT_WS, {
    username: cfg.user, password: cfg.key,
    clientId: "home-web-" + Math.random().toString(16).slice(2, 10),
    reconnectPeriod: 4000, connectTimeout: 10000, keepalive: 30, clean: true,
  });
  client.on("connect", () => {
    brokerUp = true;
    client.subscribe(topicStatus());
    // 1) Adafruit keeps the last status of the feed: "/get" sends it to us at once, so the buttons are ready immediately
    try { client.publish(topicStatus() + "/get", ""); } catch (e) {}
    // 2) ask the Arduino for a fresh state too (repeats until it answers)
    synced = false; askHello();
    updatePill();
  });
  client.on("close", () => { brokerUp = false; updatePill(); });
  client.on("error", () => { brokerUp = false; updatePill(); });
  client.on("message", (topic, payload) => {
    let j;
    try { j = JSON.parse(payload.toString()); } catch (e) { return; }
    if (!j || !j.relays) return;
    lastStatusAt = Date.now();
    synced = true;
    applyDesired(j);
    render(j);
  });
}

// keep what you just pressed on screen until the Arduino confirms it
// ask for the real state; repeat every 3 s until it arrives (the first press is never wasted)
let helloTimer = null, helloTries = 0;
function askHello() {
  clearInterval(helloTimer); helloTries = 0;
  const go = () => {
    if (synced || cfg.mode !== "cloud" || !brokerUp) { clearInterval(helloTimer); return; }
    if (++helloTries > 8) { clearInterval(helloTimer); return; }
    cloudPublish({ c: "hello" }).catch(() => {});
  };
  go(); helloTimer = setInterval(go, 3000);
}

function applyDesired(j) {
  const now = Date.now();
  for (const k of Object.keys(desired)) {
    const d = desired[k];
    const same = d.type === "r" ? j.relays[d.id] === d.val : j.auto[d.id - 5] === d.val;
    if (same || now > d.until) delete desired[k];
    else if (d.type === "r") j.relays[d.id] = d.val;
    else j.auto[d.id - 5] = d.val;
  }
}

/* ---------- connection pill ---------- */
function updatePill() {
  const el = $("#conn");
  let cls = "pill", label = "Offline", icon = "wifi-off";
  if (cfg.mode === "cloud") {
    const fresh = Date.now() - lastStatusAt < 45000;
    if (brokerUp && synced && fresh) { cls += " ok"; label = "Connected"; icon = "wifi"; }
    else if (brokerUp && !synced) { cls += " warn"; label = "Syncing"; icon = "wifi"; }
    else if (brokerUp) { cls += " warn"; label = "Arduino offline"; icon = "wifi-off"; }
  } else if (synced && localOk) { cls += " ok"; label = "Connected"; icon = "wifi"; }
  el.className = cls;
  el.innerHTML = ic(icon) + `<b>${label}</b>`;
}
let localOk = false;
function setConn(ok) { localOk = ok; updatePill(); }

/* ---------- drawings (SVG) ---------- */
const bulbSvg = () => `<svg class="bulb" viewBox="0 0 100 140" aria-hidden="true">
  <path class="glass" d="M50 8C28 8 14 24 14 44c0 13 6 22 13 30 5 6 8 11 8 18v6h30v-6c0-7 3-12 8-18 7-8 13-17 13-30C86 24 72 8 50 8Z"/>
  <path class="shine" d="M30 26c4-9 12-13 20-13-9 2-16 8-18 18-1 3-4 2-2-5Z"/>
  <path class="fil" d="M40 98V70l6 8 4-12 4 12 6-8v28"/>
  <rect x="35" y="98" width="30" height="9" rx="3" fill="#9aa7b8"/><rect x="36" y="107" width="28" height="8" rx="3" fill="#7d8aa0"/>
  <rect x="37" y="115" width="26" height="8" rx="3" fill="#9aa7b8"/><path d="M42 123h16l-3 9H45Z" fill="#5d6a80"/></svg>`;
const fanSvg = () => `<svg class="fan" viewBox="0 0 100 100" aria-hidden="true">
  <circle class="ring" cx="50" cy="50" r="44"/>
  <g class="blades">
    <path class="blade" d="M50 50C40 36 42 14 50 8c8 6 10 28 0 42Z"/>
    <path class="blade" d="M50 50C64 40 86 42 92 50c-6 8-28 10-42 0Z"/>
    <path class="blade" d="M50 50C60 64 58 86 50 92c-8-6-10-28 0-42Z"/>
    <path class="blade" d="M50 50C36 60 14 58 8 50c6-8 28-10 42 0Z"/>
    <circle cx="50" cy="50" r="7" fill="#c9d4e6"/></g></svg>`;

const SENSORS = [
  { k: "smoke", label: "Smoke", icon: "flame" },
  { k: "temp", label: "Temp", icon: "thermometer" },
  { k: "lux", label: "Light", icon: "sun" },
  { k: "hum", label: "Humidity", icon: "droplets" },
];
$("#sensors").innerHTML = SENSORS.map((s) => `
  <div class="sn" id="sn-${s.k}">
    <div class="l">${ic(s.icon)}${s.label}</div>
    <div class="v na" id="v-${s.k}">--</div>
  </div>`).join("");

$("#devs").innerHTML = DEVICES.map((d) => `
  <div class="dev ${d.key ? "sensorlight" : ""}" id="d-${d.id}" data-relay="${d.id}" style="--c:var(${d.c})" role="button" tabindex="0" aria-label="${d.name}">
    <div class="halo"></div>
    <div class="stage">${d.kind === "fan" ? fanSvg() : bulbSvg()}</div>
    ${d.key ? `<div class="mode"><button data-mode="${d.id}" data-auto="1">Auto</button><button data-mode="${d.id}" data-auto="0">Manual</button></div><div class="hint"></div>` : ""}
    <div class="info"><span class="nm">${d.name}</span><span class="st">OFF</span><span class="sw"></span></div>
  </div>`).join("");

/* ---------- render (updates in place, no rebuild) ---------- */
function setSensor(k, ok, html, hot) {
  const v = $("#v-" + k);
  v.className = "v" + (ok ? "" : " na");
  v.innerHTML = ok ? html : (k === "smoke" && S.mq2Ready === false && synced ? "Warming up" : "No data");
  $("#sn-" + k).classList.toggle("hot", !!(ok && hot));
}

function renderSensors(s) {
  const sm = Math.round((s.smoke / 1023) * 100);
  setSensor("smoke", s.mq2Ready, `${sm}<small>%</small>`, s.smoke > s.tSmoke);
  setSensor("temp", s.dhtOk, `${s.temp.toFixed(1)}<small>°C</small>`, s.temp > s.tTemp);
  setSensor("lux", s.luxOk, `${Math.round(s.lux)}<small>lux</small>`, false);
  setSensor("hum", s.dhtOk, `${s.hum.toFixed(0)}<small>%</small>`, false);
  $("#smokeAlert").classList.toggle("hidden", !(s.mq2Ready && s.smoke > s.tSmoke));
}

function autoHint(d, s) {
  if (d.key === "smoke") return s.mq2Ready ? `Smoke ${Math.round((s.smoke / 1023) * 100)}% · limit ${Math.round((s.tSmoke / 1023) * 100)}%` : "Sensor warming up";
  if (d.key === "temp") return s.dhtOk ? `${s.temp.toFixed(1)}°C · limit ${s.tTemp}°C` : "No sensor";
  return s.luxOk ? `${Math.round(s.lux)} lux · limit ${Math.round(s.tLux)}` : "No sensor";
}

function renderDevices(s) {
  DEVICES.forEach((d) => {
    const on = s.relays[d.id] === 1;
    const el = $("#d-" + d.id);
    el.classList.toggle("on", on);
    el.querySelector(".st").textContent = on ? "ON" : "OFF";
    if (d.key) {
      const auto = s.auto[d.id - 5] === 1;
      el.classList.toggle("locked", auto);
      el.querySelectorAll(".mode button").forEach((b) => b.classList.toggle("act", (b.dataset.auto === "1") === auto));
      el.querySelector(".hint").textContent = auto ? autoHint(d, s) : "Manual: tap to switch";
    }
  });
}

function initThresholds(s) {
  $("#sSmoke").value = Math.round((s.tSmoke / 1023) * 100);
  $("#sTemp").value = s.tTemp;
  $("#sLux").value = s.tLux;
  updateLabels();
  threshInit = true;
}
function updateLabels() {
  $("#lSmoke").textContent = $("#sSmoke").value + "%";
  $("#lTemp").textContent = $("#sTemp").value + " °C";
  $("#lLux").textContent = $("#sLux").value + " lux";
}

function render(s) {
  if (!s) return;
  S = s; synced = true;
  if (cfg.mode !== "cloud") setConn(true); else updatePill();
  renderSensors(s);
  renderDevices(s);
  if (!threshInit) initThresholds(s);
}

/* ---------- actions: update screen first, then tell the board ---------- */
function failed(err) {
  toast(err && err.message ? err.message : "Could not send");
  if (cfg.mode !== "cloud") poll();
}

function notReady() {
  if (synced) return false;
  toast("Connecting to your home... one second");
  if (cfg.mode === "cloud" && brokerUp) askHello();
  return true;
}

function toggle(id) {
  if (notReady()) return;
  const idx = Number(id);
  if (idx >= 5 && S.auto[idx - 5] === 1) { toast("This light is in Auto. Switch it to Manual first."); return; }
  const next = S.relays[idx] === 1 ? 0 : 1;
  S.relays[idx] = next;                                    // instant feedback
  renderDevices(S);
  inflight++;
  api(`/relay?id=${idx}&state=${next}`)
    .then((j) => { if (cfg.mode === "cloud") desired["r" + idx] = { type: "r", id: idx, val: next, until: Date.now() + 9000 }; if (j) render(j); })
    .catch((e) => { S.relays[idx] = next ? 0 : 1; renderDevices(S); failed(e); })
    .finally(() => { inflight--; });
}

function setAll(on) {
  if (notReady()) return;
  const val = on ? 1 : 0, old = S.relays.slice();
  for (let i = 0; i < 8; i++) if (!(i >= 5 && S.auto[i - 5] === 1)) { S.relays[i] = val; if (cfg.mode === "cloud") desired["r" + i] = { type: "r", id: i, val, until: Date.now() + 9000 }; }
  renderDevices(S);
  inflight++;
  const send = cfg.mode === "cloud"
    ? api(`/all?state=${val}`)
    : Promise.all(S.relays.map((_, i) => (i >= 5 && S.auto[i - 5] === 1) ? null : localApi(`/relay?id=${i}&state=${val}`)).filter(Boolean));
  send.then((j) => { if (j && j.relays) render(j); })
      .catch((e) => { S.relays = old; renderDevices(S); failed(e); })
      .finally(() => { inflight--; });
}

function setMode(id, auto) {
  if (notReady()) return;
  const idx = Number(id), val = Number(auto);
  const old = S.auto[idx - 5];
  S.auto[idx - 5] = val;
  renderDevices(S);
  inflight++;
  api(`/mode?id=${idx}&auto=${val}`)
    .then((j) => { if (cfg.mode === "cloud") desired["m" + idx] = { type: "m", id: idx, val, until: Date.now() + 9000 }; if (j) render(j); })
    .catch((e) => { S.auto[idx - 5] = old; renderDevices(S); failed(e); })
    .finally(() => { inflight--; });
}

document.addEventListener("click", (e) => {
  const m = e.target.closest("[data-mode]");
  if (m) { e.stopPropagation(); return setMode(m.dataset.mode, m.dataset.auto); }
  const r = e.target.closest("[data-relay]");
  if (r) return toggle(r.dataset.relay);
});
document.addEventListener("keydown", (e) => {
  if ((e.key === "Enter" || e.key === " ") && e.target.matches && e.target.matches("[data-relay]")) { e.preventDefault(); toggle(e.target.dataset.relay); }
});
$("#allOn").addEventListener("click", () => setAll(true));
$("#allOff").addEventListener("click", () => setAll(false));

["#sSmoke", "#sTemp", "#sLux"].forEach((id) => $(id).addEventListener("input", updateLabels));
$("#limBtn").addEventListener("click", () => $("#limModal").classList.remove("hidden"));
$("#limClose").addEventListener("click", () => $("#limModal").classList.add("hidden"));
$("#apply").addEventListener("click", () => {
  if (notReady()) return;
  const smoke = Math.round(($("#sSmoke").value / 100) * 1023);
  const b = $("#apply");
  api(`/threshold?smoke=${smoke}&temp=${$("#sTemp").value}&lux=${$("#sLux").value}`)
    .then((s) => {
      if (s && s.relays) render(s);
      b.classList.add("done"); b.textContent = "Saved";
      setTimeout(() => { b.classList.remove("done"); b.textContent = "Apply limits"; $("#limModal").classList.add("hidden"); }, 900);
    })
    .catch(failed);
});

/* ---------- settings dialog ---------- */
const modal = $("#modal");
function showMode() {
  const cloud = $("#mCloud").checked;
  $("#cloudBox").classList.toggle("hidden", !cloud);
  $("#localBox").classList.toggle("hidden", cloud);
}
function openModal() {
  $("#mCloud").checked = cfg.mode !== "local";
  $("#mLocal").checked = cfg.mode === "local";
  $("#cUser").value = cfg.user; $("#cKey").value = cfg.key;
  $("#cWs").value = cfg.ws || DEFAULT_WS; $("#ipInput").value = cfg.ip;
  showMode();
  modal.classList.remove("hidden");
}
function closeModal() { modal.classList.add("hidden"); }
$("#ipBtn").addEventListener("click", openModal);
$("#ipCancel").addEventListener("click", closeModal);
$("#mCloud").addEventListener("change", showMode);
$("#mLocal").addEventListener("change", showMode);
$("#ipSave").addEventListener("click", () => {
  cfg.mode = $("#mCloud").checked ? "cloud" : "local";
  cfg.user = $("#cUser").value.trim(); cfg.key = $("#cKey").value.trim();
  cfg.ws = $("#cWs").value.trim() || DEFAULT_WS;
  cfg.ip = $("#ipInput").value.trim().replace(/^https?:\/\//, "").replace(/\/$/, "");
  saveCfg();
  threshInit = false; S = blankState(); synced = false; lastStatusAt = 0; renderSensors(S); renderDevices(S);
  closeModal();
  start();
});

/* ---------- polling (local mode only) ---------- */
let polling = false;
async function poll() {
  if (cfg.mode !== "local" || !cfg.ip) return;
  if (polling || inflight > 0) return;
  polling = true;
  try { const s = await localApi("/status"); if (inflight === 0) render(s); }
  catch (e) { setConn(false); }
  polling = false;
}

function tick() {
  $("#clock").textContent = new Date().toLocaleString([], { weekday: "long", hour: "2-digit", minute: "2-digit" });
  if (cfg.mode === "cloud") updatePill();
}

function start() {
  synced = false; S = blankState(); renderSensors(S); renderDevices(S);
  if (client) { try { client.end(true); } catch (e) {} client = null; }
  brokerUp = false;
  if (cfg.mode === "cloud") cloudConnect();
  updatePill();
  poll();
}

// when you come back to the page, ask the Arduino for a fresh status
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && cfg.mode === "cloud" && Date.now() - lastStatusAt > 25000) { synced = false; askHello(); }
});

tick(); setInterval(tick, 30000); setInterval(() => { if (cfg.mode === "cloud") updatePill(); }, 5000);
setInterval(poll, 1500);
renderSensors(S); renderDevices(S);
if (!cfg.mode || (cfg.mode === "cloud" && (!cfg.user || !cfg.key))) openModal();
start();
if ("serviceWorker" in navigator && location.protocol.startsWith("http")) navigator.serviceWorker.register("sw.js").catch(() => {});
