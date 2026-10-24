"use strict";
/* Pulsecut – Oberfläche (Assistent + Timeline-Editor). Kein Build-Schritt, reines JavaScript. */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const fmt = s => { s = Math.max(0, Math.round(s || 0)); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
const fmt1 = s => { s = Math.max(0, s || 0); const m = Math.floor(s / 60); return m + ":" + (s - m * 60).toFixed(1).padStart(4, "0"); };
const pl = (n, one, many) => { const w = T(n === 1 ? one : many); return n + " " + (LANG() === "en" ? w.toLowerCase() : w); };   // "1 Szene" / "3 scenes"
const komma = x => LANG() === "en" ? String(x) : String(x).replace(".", ",");
async function api(p, b) {
  const r = await fetch(p, b === undefined ? {} : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(b)});
  const j = await r.json();
  if (!j.ok && !j.kollision) { toast(j.fehler || T("Fehler")); throw new Error(j.fehler || T("Fehler")); }
  return j;
}
function toast(msg, ms = 3500) { const t = $("#toast"); t.textContent = msg; t.classList.add("on"); clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("on"), ms); }
function seg(name, vals, cur) {
  return `<span class="seg" data-f="${name}">` + vals.map(([v, l, cls]) =>
    `<button data-v="${esc(v)}" class="${(String(cur) === String(v) ? "on " : "") + (cls || "")}">${l}</button>`).join("") + "</span>";
}
function onSeg(el, fn) { el.addEventListener("click", e => { const b = e.target.closest("button"); if (b && b.parentElement === el) fn(b.dataset.v); }); }

/* ── Modal-Dialoge ─────────────────────────────────────────── */
function modal(html, buttons) {
  return new Promise(res => {
    const m = $("#modal"), box = $("#mbox");
    box.innerHTML = html + `<div class="weiter">${buttons.map((b, i) => `<button data-i="${i}" class="${b.pri ? "pri" : ""}">${b.t}</button>`).join("")}</div>`;
    m.hidden = false;
    box.querySelectorAll(".weiter button").forEach(b => b.onclick = () => { m.hidden = true; res(buttons[+b.dataset.i].v); });
  });
}
const frage = (text, ja = T("Ja"), nein = T("Abbrechen")) => modal(`<p>${text}</p>`, [{t: nein, v: false}, {t: ja, v: true, pri: true}]);
async function eingabe(text, platzhalter, ok = T("Anlegen")) {
  const p = modal(`<p>${text}</p><input type="text" id="mein" style="width:100%" placeholder="${esc(platzhalter || "")}">`, [{t: T("Abbrechen"), v: false}, {t: ok, v: true, pri: true}]);
  setTimeout(() => { const i = $("#mein"); if (i) { i.focus(); i.onkeydown = e => { if (e.key === "Enter") $("#mbox .weiter .pri").click(); }; } }, 30);
  const r = await p, i = $("#mein");
  return r && i && i.value.trim() ? i.value.trim() : null;
}

/* ── Stichwort einer Szene oder eines Clips ändern (auch: neues Stichwort, ganz raus) ── */
const kwOptionen = (kws, sel) => kws.map(k => `<option value="${k.id}" ${k.id === sel ? "selected" : ""}>${esc(k.name)}</option>`).join("") +
  `<option disabled>──────────</option><option value="__neu__">${T("➕ Neues Stichwort …")}</option><option value="__raus__">${T("✕ Raus – nicht in den Film")}</option>`;
async function kwWahl(v, ziel) {   // ziel: {szene: id} oder {clip: name}; gibt false zurück, wenn abgebrochen
  if (v === "__neu__") {
    const name = await eingabe(T("Wie soll das neue Stichwort heißen?"), T("z. B. Abschlussparty"));
    if (!name) return false;
    await api("/api/stichwort/neu", Object.assign({name}, ziel)); toast(T`Stichwort „${name}“ angelegt`); return true;
  }
  if (v === "__raus__") {
    if (ziel.szene) await api("/api/szene/raus", {id: ziel.szene}); else await api("/api/clip", {name: ziel.clip, prio: "raus"});
    toast(T("Raus – lässt sich unter „Videos“ wieder zurückholen")); return true;
  }
  if (ziel.szene) await api("/api/szene/kw", {id: ziel.szene, kw: v}); else await api("/api/clip", {name: ziel.clip, kat: v});
  return true;
}

/* ── Qt-Brücke (nativer Ordner-Dialog) ─────────────────────── */
let bridge = null;
if (window.qt && window.qt.webChannelTransport && window.QWebChannel) {
  new QWebChannel(qt.webChannelTransport, ch => { bridge = ch.objects.bridge; });
}
async function ordnerWaehlen(titel, start) {
  if (bridge) return new Promise(res => bridge.ordnerWaehlen(titel, start || "", r => res(r || null)));
  return ordnerBrowser(titel, start);
}
async function ordnerBrowser(titel, start) {
  let pfad = start || "";
  return new Promise(res => {
    const m = $("#modal"), box = $("#mbox");
    async function show(p) {
      const d = await api("/api/ls?pfad=" + encodeURIComponent(p || ""));
      pfad = d.pfad;
      box.innerHTML = `<h3>${esc(titel)}</h3><div class="row"><input type="text" id="fbpfad" value="${esc(d.pfad)}" style="flex:1"><button id="fbgo">${T("Gehe")}</button></div>
        <div class="meta" style="margin-top:4px">${T`${d.videos} Videodateien · ${d.audio} Audiodateien in diesem Ordner`}</div>
        <div class="fb"><a href="#" data-p="${esc(d.eltern)}">⬑ ${T("übergeordneter Ordner")}</a>${d.ordner.map(o => `<a href="#" data-p="${esc(d.pfad + "/" + o)}">📁 ${esc(o)}</a>`).join("")}</div>
        <div class="weiter"><button id="fbab">${T("Abbrechen")}</button><button class="pri" id="fbok">${T("Diesen Ordner wählen")}</button></div>`;
      box.querySelectorAll(".fb a").forEach(a => a.onclick = e => { e.preventDefault(); show(a.dataset.p); });
      $("#fbgo").onclick = () => show($("#fbpfad").value);
      $("#fbab").onclick = () => { m.hidden = true; res(null); };
      $("#fbok").onclick = () => { m.hidden = true; res(pfad); };
    }
    m.hidden = false; show(pfad);
  });
}
function oeffnen(pfad) { if (bridge) bridge.oeffnen(pfad); else api("/api/oeffnen", {pfad}); }

/* ── Schritte, Zustand ─────────────────────────────────────── */
const STEPS = [
  ["start", N("Projekt")], ["musik", N("Musik & Takt")], ["laenge", N("Länge")], ["videos", N("Videos")],
  ["ablauf", N("Ablauf beschreiben")], ["erkennung", N("Szenen erkennen")], ["gewichtung", N("Gewichtung & Reihenfolge")],
  ["schnitt", N("Schnitt einstellen")], ["timeline", N("Timeline & Vorschau")], ["export", N("Fertigstellen")]];
let Z = null, step = "start", visited = new Set(["start"]);
const R = {};   // Render-Funktionen je Schritt

function stepState(k) {
  const p = Z && Z.projekt;
  if (k === "start") return {ok: true, fertig: !!p};
  if (!p) return {ok: false};
  const e = p.erledigt || [];
  return {
    musik: {ok: true, fertig: visited.has("laenge") || e.includes("plan")},
    laenge: {ok: p.stuecke > 0, fertig: visited.has("videos") || e.includes("plan")},
    videos: {ok: true, fertig: e.includes("videos")},
    ablauf: {ok: true, fertig: p.stichworte > 0},
    erkennung: {ok: p.stichworte > 0, fertig: p.erkennung},
    gewichtung: {ok: p.erkennung, fertig: visited.has("schnitt") || e.includes("plan")},
    schnitt: {ok: p.erkennung && p.stuecke > 0, fertig: p.timeline},
    timeline: {ok: p.timeline, fertig: (p.exporte || []).length > 0},
    export: {ok: p.timeline, fertig: (p.exporte || []).length > 0},
  }[k];
}
function renderNav() {
  $("#schritte").innerHTML = STEPS.map(([k, l], i) => {
    const s = stepState(k);
    return `<a href="#" data-k="${k}" class="${step === k ? "aktiv " : ""}${s.fertig && step !== k ? "fertig " : ""}${s.ok ? "" : "zu"}"><span class="n">${s.fertig && step !== k ? "✓" : i + 1}</span>${T(l)}</a>`;
  }).join("");
  $$("#schritte a").forEach(a => a.onclick = e => { e.preventDefault(); go(a.dataset.k); });
}
const JOBNAME = {analyse: N("Videos"), musik: N("Musik"), erkennung: N("Erkennung"), sprache: N("Sprache"), export: N("Export"), ki: N("KI"), plan: N("Planung")};
function renderJobs() {
  const p = Z && Z.projekt;
  $("#projektname").textContent = p ? p.name : "";
  let h = "";
  if (p) for (const [n, j] of Object.entries(p.jobs)) if (j.laeuft)
    h += `<span class="jobchip" title="${esc(j.text)}">${T(JOBNAME[n] || n)}: <i><b style="width:${Math.round(j.fortschritt * 100)}%"></b></i>${esc(j.text)}</span>`;
  if (Z && Z.ki.laeuft) h += `<span class="jobchip">${T("KI wird eingerichtet …")}</span>`;
  $("#jobs").innerHTML = h;
}
let lastJobs = {};
async function poll() {
  try {
    const z = await fetch("/api/zustand").then(r => r.json());
    const before = Z; Z = z;
    renderJobs(); renderNav();
    const p = z.projekt;
    if (p) {
      for (const [n, j] of Object.entries(p.jobs)) {   // Job fertig → aktuellen Schritt neu zeichnen
        const was = lastJobs[n];
        if (was && !j.laeuft && (was.laeuft || j.fertig > was.fertig)) {
          if (j.fehler) toast(T(JOBNAME[n] || n) + ": " + j.fehler, 7000);
          if (R[step] && R[step].onJob) R[step].onJob(n, j);
        }
      }
      lastJobs = JSON.parse(JSON.stringify(p.jobs));
      if (R[step] && R[step].onPoll) R[step].onPoll(z);
    }
    if (!before && z.projekt && step === "start") go("musik");
  } catch (e) { /* Server kurz nicht erreichbar */ }
  setTimeout(poll, 1200);
}
function go(k) {
  if (R[step] && R[step].leave) R[step].leave();
  step = k; visited.add(k); renderNav();
  const m = $("#inhalt"); m.scrollTop = 0; m.innerHTML = "";
  R[k].render(m);
}
function weiter(k, txt) { return `<div class="weiter"><button class="pri gross" data-go="${k}">${txt || T("Weiter")} →</button></div>`; }
function bindWeiter(root) { $$("[data-go]", root).forEach(b => b.onclick = () => go(b.dataset.go)); }
function jobBox(name, title) {
  const j = Z && Z.projekt && Z.projekt.jobs[name];
  if (!j) return "";
  if (j.laeuft) return `<div class="box"><b>${title}</b> <span class="meta">${esc(j.text)}</span><div class="fortschritt"><b style="width:${Math.round(j.fortschritt * 100)}%"></b></div></div>`;
  if (j.fehler) return `<div class="fehler"><b>${title}:</b> ${esc(j.fehler)}</div>`;
  return "";
}

/* ── 1 Projekt ─────────────────────────────────────────────── */
R.start = {render(m) {
  const p = Z && Z.projekt, t = Z ? Z.werkzeuge : {};
  const fehlt = ["ffmpeg", "ffprobe"].filter(x => !t[x]);
  m.innerHTML = `<h1>${T("Neues Projekt")}</h1><p class="lead">${T("Wähle den Ordner mit deinen Videos und einen Ordner mit der Musik. Pulsecut analysiert zuerst die Musik (Takt und Beats) und dann alle Videos – das läuft im Hintergrund, du kannst währenddessen weitermachen.")}</p>
   ${fehlt.length ? `<div class="fehler"><b>${T`${fehlt.join(T(" und "))} fehlt.`}</b> ${T("Bitte im Terminal installieren: <code>sudo apt install ffmpeg</code> und Pulsecut neu starten.")}</div>` : ""}
   ${t && !t.melt ? `<div class="hinweis">${T("<b>melt</b> wurde nicht gefunden (kommt normalerweise mit Kdenlive). Ohne melt wird beim Rendern ohne Überblendungen gearbeitet: <code>sudo apt install melt</code>")}</div>` : ""}
   ${t && t.ffmpeg && t.ffmpeg_ok === false ? `<div class="fehler">${T("ffmpeg ist installiert, startet aus Pulsecut heraus aber nicht:")} <code>${esc((t.ffmpeg_fehler || []).join(" "))}</code> ${T("Bitte Pulsecut einmal schließen und neu starten.")}</div>`
     : (t && t.ffmpeg && !t.vpx ? `<div class="hinweis">${T("Dein ffmpeg kann kein VP8 (libvpx) – die Live-Vorschau im Programm funktioniert dann nicht.")}</div>` : "")}
   ${Z && Z.appimage && !Z.desktop ? `<div class="hinweis row"><span style="flex:1">${T("Pulsecut läuft als AppImage. Soll es ins Startmenü eingetragen werden?")}</span><button id="bdesk">${T("Ins Startmenü eintragen")}</button></div>` : ""}
   <div class="box col">
     <label class="lab">${T("Name des Projekts")}</label><input type="text" id="pname" placeholder="${T("z. B. Sommerfreizeit 2026")}" value="${esc(p ? p.name : "")}">
     <label class="lab" style="margin-top:8px">${T("Ordner mit den Videos")}</label>
     <div class="ordnerwahl"><input type="text" id="pvid" value="${esc(p ? p.videos : "")}" placeholder="/home/…/Videos"><button id="bvid">${T("Wählen …")}</button></div>
     <label class="lab" style="margin-top:8px">${T("Ordner mit der Musik")}</label>
     <div class="ordnerwahl"><input type="text" id="pmus" value="${esc(p ? p.musik : "")}" placeholder="${T("/home/…/Musik")}"><button id="bmus">${T("Wählen …")}</button></div>
     <div class="meta">${T("Alle Audiodateien im Musikordner werden verwendet (wav, mp3, flac, m4a, ogg …), die Reihenfolge kannst du im nächsten Schritt ändern. Das Projekt (Zwischenspeicher, Export) landet neben dem Videoordner in „<i>Name</i>_Pulsecut“.")}</div>
     <div class="weiter"><button class="pri gross" id="bneu">${p ? T("Projekt neu öffnen") : T("Projekt anlegen")} →</button></div>
   </div>
   ${(Z && Z.zuletzt.length) ? `<h2>${T("Zuletzt geöffnet")}</h2><div class="box zuletzt">${Z.zuletzt.map(x => `<a href="#" data-o="${esc(x.ordner)}"><b>${esc(x.name)}</b> <span class="meta">${esc(x.ordner)} · ${esc(x.zeit.replace("T", " "))}</span></a>`).join("")}</div>` : ""}
   <div class="row" style="margin-top:12px"><button id="boeffnen">${T("Anderes Projekt öffnen …")}</button><span class="meta">${T("Version")} ${Z ? Z.version : ""}</span></div>`;
  const bd = $("#bdesk"); if (bd) bd.onclick = async () => { await api("/api/desktop", {}); Z.desktop = true; bd.parentElement.remove(); toast(T("Pulsecut steht jetzt im Startmenü (Multimedia).")); };
  const pick = async (inp, title) => { const d = await ordnerWaehlen(title, inp.value || ""); if (d) { inp.value = d; if (inp.id === "pvid" && !$("#pname").value) $("#pname").value = d.split("/").filter(Boolean).slice(-2).join(" "); } };
  $("#bvid").onclick = () => pick($("#pvid"), T("Ordner mit den Videos"));
  $("#bmus").onclick = () => pick($("#pmus"), T("Ordner mit der Musik"));
  $("#bneu").onclick = async () => {
    const videos = $("#pvid").value.trim(), musik = $("#pmus").value.trim();
    if (!videos || !musik) return toast(T("Bitte beide Ordner angeben."));
    await api("/api/projekt/neu", {name: $("#pname").value.trim(), videos, musik});
    visited = new Set(["start"]); lastJobs = {};
    Z = await fetch("/api/zustand").then(r => r.json()); go("musik");
  };
  $$(".zuletzt a").forEach(a => a.onclick = async e => { e.preventDefault(); await api("/api/projekt/oeffnen", {ordner: a.dataset.o}); visited = new Set(["start"]); lastJobs = {}; Z = await fetch("/api/zustand").then(r => r.json()); go(Z.projekt.timeline ? "timeline" : "musik"); });
  $("#boeffnen").onclick = async () => { const d = await ordnerWaehlen(T("Projektordner (…_Pulsecut) öffnen"), ""); if (d) { await api("/api/projekt/oeffnen", {ordner: d}); Z = await fetch("/api/zustand").then(r => r.json()); go("musik"); } };
}};

/* ── 2 Musik & Takt ────────────────────────────────────────── */
let MU = null;
R.musik = {
  async render(m) {
    m.innerHTML = `<h1>${T("Musik & Takt prüfen")}</h1><p class="lead">${T("Pulsecut hat jedes Stück vermessen. Hör dir die <b>Klick-Spur</b> an: hoher Klick = Taktanfang („1“), tiefer Klick = Schlag, die Kästchen zählen mit. Sitzt etwas daneben, korrigiere es hier – geschnitten wird später genau auf diese Takte.")}</p><div id="mjob"></div><div class="box" id="mliste">${T("Lade …")}</div>
      <div class="box"><b>${T("Übergang zwischen den Stücken")}</b><div class="row" style="margin-top:8px" id="muebg"></div></div>${weiter("laenge")}`;
    bindWeiter(m);
    await this.load();
  },
  async load() {
    const mj = $("#mjob"); if (mj) mj.innerHTML = jobBox("musik", T("Musik wird analysiert"));
    try { MU = await api("/api/musik"); } catch (e) { return; }
    this.draw();
  },
  onJob(n) { if (n === "musik") this.load(); },
  onPoll() {
    const mj = $("#mjob"); if (!mj) return;
    const a = Z.projekt.jobs.analyse;
    mj.innerHTML = jobBox("musik", T("Musik wird analysiert")) + (a && a.laeuft && !Z.projekt.jobs.musik.laeuft ? `<div class="hinweis">${T("Im Hintergrund werden jetzt leise die Videos analysiert (Vorschaubilder, Perspektiven, Kamerabewegung). Unter „Videos“ kannst du auf volle Leistung schalten.")}</div>` : "");
  },
  draw() {
    const box = $("#mliste"); if (!box) return;
    if (!MU.stuecke.length || MU.laeuft) { box.innerHTML = MU.laeuft ? T("Die Musik wird gerade analysiert …") : `<div class="fehler">${T("Im Musikordner wurde keine Musik gefunden.")}</div>`; return; }
    box.innerHTML = "";
    MU.stuecke.forEach((t, idx) => {
      const el = document.createElement("div"); el.className = "mtrack" + (t.aktiv ? "" : " inaktiv"); el.id = "mt" + t.i;
      const f = t.fix || {}, okt = f.oktave || 0;
      el.innerHTML = `<div class="row"><span class="szmv"><button data-mv="-1" ${idx ? "" : "disabled"}>▲</button><button data-mv="1" ${idx < MU.stuecke.length - 1 ? "" : "disabled"}>▼</button></span>
        <label><input type="checkbox" class="aktiv" ${t.aktiv ? "checked" : ""}> <b>${idx + 1}. ${esc(t.titel)}</b></label>
        <span class="meta">${esc(t.datei)} · ${fmt(t.dauer)} min · ${t.bpm} BPM · ${t.takt} · ${T`Takt ${komma(t.taktlaenge.toFixed(2))} s · ${t.takte} Takte`}${t.oktave_auto < 0 && !okt ? T(" · Tempo automatisch halbiert") : ""}</span>
        ${Object.keys(f).length ? `<span class="fixed">${T("von Hand korrigiert")}</span>` : ""}</div>
        <div class="row" style="margin-top:6px">${t.klick_bereit === false ? `<span class="meta">${T("Klick-Spur wird vorbereitet …")}</span>` : `<audio controls preload="auto" src="${t.klick}"></audio>`}<div class="count">${Array.from({length: t.meter}, (_, k) => `<span class="${k ? "" : "eins"}">${k + 1}</span>`).join("")}</div></div>
        <div class="row" style="margin-top:6px"><span class="lab">${T("Taktanfang")}</span><button data-a="frueher">${T("◀ 1 Schlag früher")}</button><button data-a="spaeter">${T("1 Schlag später ▶")}</button>
          <span class="lab" style="margin-left:10px">${T("Tempo")}</span>${seg("okt", [["-1", T("Halb")], ["0", T("Auto")], ["1", T("Doppelt")]], f.bpm ? "x" : okt)}
          <span class="meta">BPM</span><input type="number" min="40" max="240" step="0.1" placeholder="${T("auto")}" value="${f.bpm || ""}" style="width:76px"></div>
        <div class="row" style="margin-top:6px"><span class="lab">${T("Taktart")}</span>${seg("takt", [["0", T("Auto")], ["3", "3/4"], ["4", "4/4"]], f.takt || 0)}
          <span class="lab" style="margin-left:10px">${T("Feinversatz")}</span><button data-ms="-10">−10 ms</button><span class="meta">${(f.versatz_ms || 0) > 0 ? "+" : ""}${f.versatz_ms || 0} ms</span><button data-ms="10">+10 ms</button>
          <button data-a="zuruecksetzen" style="margin-left:10px">${T("Zurücksetzen")}</button></div>`;
      const au = $("audio", el) || document.createElement("audio"), cells = $$(".count span", el);
      const tick = () => {
        if (au.paused) return;
        const tt = au.currentTime; let lo = 0, hi = t.beats.length - 1, k = -1;
        while (lo <= hi) { const mid = (lo + hi) >> 1; if (t.beats[mid] <= tt + 0.01) { k = mid; lo = mid + 1; } else hi = mid - 1; }
        let pos = -1;
        if (k >= 0) { let j = k; while (j > 0 && !t.down[j]) j--; pos = t.down[j] ? (k - j) % t.meter : -1; }
        cells.forEach((c, q) => c.classList.toggle("on", q === pos && tt - t.beats[k] < 0.15));
        requestAnimationFrame(tick);
      };
      au.onplay = () => { $$("#mliste audio").forEach(a => { if (a !== au) a.pause(); }); requestAnimationFrame(tick); };
      $$("button[data-a]", el).forEach(b => b.onclick = () => this.fix(t, b.dataset.a));
      $$("button[data-ms]", el).forEach(b => b.onclick = () => this.fix(t, "versatz", parseFloat(b.dataset.ms)));
      onSeg($('[data-f="okt"]', el), v => this.fix(t, {"-1": "halb", "0": "tempo_auto", "1": "doppelt"}[v]));
      onSeg($('[data-f="takt"]', el), v => this.fix(t, "takt", v));
      $('input[type=number]', el).onchange = e => this.fix(t, "bpm", e.target.value || 0);
      $(".aktiv", el).onchange = () => this.order();
      $$("[data-mv]", el).forEach(b => b.onclick = () => this.order(idx, +b.dataset.mv));
      box.appendChild(el);
    });
    const u = MU.uebergang;
    $("#muebg").innerHTML = seg("art", [["direkt", T("Direkt nacheinander")], ["blende", T("Dezente Überblendung")]], u.art) +
      (u.art === "blende" ? `<span class="meta">${T("Dauer")}</span><input type="range" id="mbl" min="0.5" max="6" step="0.5" value="${u.dauer}"><span id="mblv">${komma(u.dauer)} s</span>` : "");
    onSeg($('#muebg [data-f="art"]'), async v => { MU = await api("/api/musik/einstellungen", {art: v}); this.draw(); });
    const r = $("#mbl"); if (r) { r.oninput = () => $("#mblv").textContent = komma(r.value) + " s"; r.onchange = async () => { MU = await api("/api/musik/einstellungen", {dauer: +r.value}); }; }
  },
  async fix(t, aktion, wert) {
    const el = $("#mt" + t.i); el.style.opacity = .5;
    const au = $("audio", el), playing = !au.paused, pos = au.currentTime;
    try { MU = await api("/api/musik/fix", {i: t.i, aktion, wert}); } finally { el.style.opacity = 1; }
    this.draw(); toast(T("Neu vermessen"));
    if (playing) { const a = $("#mt" + t.i + " audio"); a.currentTime = Math.max(0, pos - 2); a.play().catch(() => {}); }
  },
  async order(idx, d) {
    const names = MU.stuecke.map(t => t.datei);
    if (idx !== undefined) { const [x] = names.splice(idx, 1); names.splice(idx + d, 0, x); }
    const aktiv = {}; $$("#mliste .mtrack").forEach((el, i) => aktiv[MU.stuecke[i].datei] = $(".aktiv", el).checked);
    MU = await api("/api/musik/stuecke", {reihenfolge: names, aktiv}); this.draw();
  },
  leave() { $$("#mliste audio").forEach(a => a.pause()); }
};

/* ── 3 Länge ───────────────────────────────────────────────── */
function drawWelle(cv, L, opts = {}) {
  const w = cv.clientWidth || 800, h = cv.clientHeight || 70, dpr = devicePixelRatio || 1;
  cv.width = w * dpr; cv.height = h * dpr; const g = cv.getContext("2d"); g.scale(dpr, dpr);
  const T = L.dauer || 1; g.clearRect(0, 0, w, h); g.fillStyle = "#f4f3ef"; g.fillRect(0, 0, w, h);
  g.beginPath(); g.moveTo(0, h); for (const [t, v] of L.kurve) g.lineTo(t / T * w, h - v * (h - 8)); g.lineTo(w, h); g.closePath();
  g.fillStyle = "#b9c3d6"; g.fill();
  g.strokeStyle = "#0003"; g.lineWidth = 1;
  for (const t of L.units) { const x = Math.round(t / T * w) + .5; g.beginPath(); g.moveTo(x, h - 12); g.lineTo(x, h); g.stroke(); }
  g.strokeStyle = "#000"; g.lineWidth = 2; for (const t of L.wechsel) { const x = t / T * w; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); }
  if (opts.pos != null) { g.strokeStyle = "#d62828"; g.lineWidth = 2; const x = opts.pos / T * w; g.beginPath(); g.moveTo(x, 0); g.lineTo(x, h); g.stroke(); }
}
R.laenge = {
  async render(m) {
    m.innerHTML = `<h1>${T("Gesamtlänge")}</h1><p class="lead">${T("So lang ist deine Musik zusammen. Soll der Film kürzer werden, sag hier welches Stück gekürzt wird – vorne oder hinten. Gekürzt wird immer an einem Taktanfang mit weicher Blende.")}</p><div id="lbox">${T("Lade …")}</div>${weiter("videos")}`;
    bindWeiter(m);
    this.kz = null;   // Auswahl „kürzen“ sammeln – schnelle Klicks hintereinander gehen so nicht verloren
    MU = await api("/api/musik"); this.draw();
  },
  onJob(n) { if (n === "musik") api("/api/musik").then(d => { MU = d; this.draw(); }); },
  draw() {
    const b = $("#lbox"); if (!b) return;
    const L = MU.layout;
    if (!L) { b.innerHTML = `<div class="hinweis">${T("Die Musik wird noch analysiert …")}</div>`; return; }
    const inf = L.info, ziel = MU.ziel;
    b.innerHTML = `<div class="box"><div class="row"><b>${T`Musik zusammen: ${fmt(inf.voll)} min`}</b><span class="meta">${pl(MU.stuecke.filter(t => t.aktiv).length, N("Stück"), N("Stücke"))}${MU.uebergang.art === "blende" ? T`, mit ${komma(MU.uebergang.dauer)} s Überblendung` : T(", direkt nacheinander")}</span></div>
      <div class="row" style="margin-top:10px"><span class="lab">${T("Filmlänge")}</span>${seg("mode", [["voll", T("Ganze Musik")], ["ziel", T("Bestimmte Länge")]], ziel ? "ziel" : "voll")}
      ${ziel ? `<input type="text" id="lziel" value="${fmt(ziel)}" style="width:80px"> <span class="meta">min:s</span>` : ""}</div>
      ${inf.noetig > 1 ? `<div class="hinweis" style="margin-top:12px"><b>${T`Die Musik ist ${fmt(inf.noetig)} min länger als gewünscht.`}</b> ${T("Welches Stück soll gekürzt werden?")}${inf.auto_gekuerzt ? T(" (Noch nichts gewählt – vorläufig wird das längste Stück hinten gekürzt.)") : ""}
        <div class="col" style="margin-top:8px">${MU.stuecke.filter(t => t.aktiv).map(t => `<div class="row"><span style="min-width:220px">${esc(t.titel)} <span class="meta">${fmt(t.dauer)}</span></span>${seg("k_" + t.i, [["nein", T("Nicht kürzen")], ["vorne", T("Vorne kürzen")], ["hinten", T("Hinten kürzen")]], (MU.kuerzen || {})[t.datei] || "nein")}</div>`).join("")}</div>
        ${inf.rest > 1 ? `<div class="meta" style="margin-top:6px">${T`Es fehlen noch ${fmt(inf.rest)} min – ein Stück bleibt mindestens 20 s lang. Bitte ein weiteres Stück zum Kürzen wählen.`}</div>` : ""}</div>` : ""}
      <h3>${L.raster === "halbtakt" ? T`Ergebnis: Film ${fmt(L.dauer)} min, ${L.einheiten} Takthälften à ${komma(L.einheit.toFixed(2))} s` : T`Ergebnis: Film ${fmt(L.dauer)} min, ${L.einheiten} Takte à ${komma(L.einheit.toFixed(2))} s`}</h3>
      <div class="meta">${L.segmente.map(s => `${esc(s.titel)}: ${fmt(s.src_in)}–${fmt(s.src_out)}${s.gekuerzt ? " (" + (s.modus === "vorne" ? T`vorne um ${fmt(s.gekuerzt)} gekürzt` : T`hinten um ${fmt(s.gekuerzt)} gekürzt`) + ")" : ""}`).join(" → ")}</div>
      <canvas class="welle" id="lwelle" style="margin-top:8px"></canvas>
      <div class="row" style="margin-top:8px"><audio controls preload="none" id="lmix" src="${L.mix}"></audio><span class="meta">${T("So klingt die Musik im fertigen Film (graue Striche = Takte, schwarz = Wechsel).")}</span></div></div>`;
    const cv = $("#lwelle"), au = $("#lmix");
    drawWelle(cv, L);
    cv.onclick = e => { const r = cv.getBoundingClientRect(); au.currentTime = (e.clientX - r.left) / r.width * L.dauer; au.play(); };
    au.ontimeupdate = () => drawWelle(cv, L, {pos: au.currentTime});
    onSeg($('[data-f="mode"]', b), async v => { MU = await api("/api/musik/einstellungen", {ziel: v === "ziel" ? Math.round(Math.min(inf.voll, 300)) : null}); this.draw(); });
    const zi = $("#lziel"); if (zi) zi.onchange = async () => { const p = zi.value.split(":"); const s = p.length > 1 ? (+p[0]) * 60 + (+p[1]) : +p[0]; if (s > 10) { MU = await api("/api/musik/einstellungen", {ziel: s}); this.draw(); } };
    MU.stuecke.forEach(t => { const s = $(`[data-f="k_${t.i}"]`, b); if (s) onSeg(s, async v => { this.kz = Object.assign({}, this.kz || MU.kuerzen); this.kz[t.datei] = v; MU = await api("/api/musik/einstellungen", {kuerzen: this.kz}); this.draw(); }); });
  },
  leave() { const a = $("#lmix"); if (a) a.pause(); }
};

/* ── 4 Videos ──────────────────────────────────────────────── */
let VI = null, viFilter = "alle";
function hwText(hd) {
  if (!hd || hd.stand === "aus") return T("Dekodierung: Prozessor (Grafikchip mit PULSECUT_HWDEC=0 abgeschaltet)");
  if (hd.stand === "kein_geraet") return T("Dekodierung: Prozessor (kein Grafikchip mit VAAPI gefunden)");
  if (hd.stand === "kein_vaapi") return T`Dekodierung: Prozessor (das installierte ffmpeg kann kein VAAPI für ${hd.geraet})`;
  const pr = hd.profile || [];
  if (!pr.length) return T`Dekodierung: Grafikchip ${hd.geraet} – wird beim ersten Video gemessen`;
  const teile = pr.map(x => x.hw ? (x.faktor ? T`${x.name} über den Grafikchip (${Number(x.faktor).toLocaleString(LANG())}× so schnell)` : T`${x.name} über den Grafikchip`)
    : T`${x.name} auf dem Prozessor (${x.grund})`);
  return T`Dekodierung (${hd.geraet}): ${teile.join(" · ")}`;
}

R.videos = {
  async render(m) {
    m.innerHTML = `<h1>${T("Videos & Reihenfolge")}</h1><p class="lead">${T("Die Videos werden nach Aufnahmezeit (aus den Handy-Metadaten) sortiert – oder nach Dateiname, wenn du sie selbst durchnummeriert hast. Unbrauchbares kannst du hier schon auf „Raus“ setzen, besonders Wichtiges auf „Wichtig“.")}</p>
      <div id="vjob"></div><div id="vboost"></div><div class="box row" id="vkopf"></div><div id="vgrid" class="grid"></div>${weiter("ablauf")}`;
    bindWeiter(m); await this.load();
  },
  async load() { const vj = $("#vjob"); if (vj) vj.innerHTML = jobBox("analyse", T("Videos werden analysiert")); this.boost(); try { VI = await api("/api/videos"); } catch (e) { return; } this.draw(); },
  onJob(n) { if (n === "analyse") this.load(); },
  onPoll() { const vj = $("#vjob"); if (vj) vj.innerHTML = jobBox("analyse", T("Videos werden analysiert")); this.boost(); },
  boost() {
    const el = $("#vboost"); if (!el || !Z || !Z.projekt) return;
    const p = Z.projekt, a = p.jobs.analyse;
    let h = "";
    if (a && a.laeuft) {
      h = p.jobs.musik.laeuft ? `<div class="hinweis">${T("Die Videoanalyse beginnt, sobald die Musik fertig ist.")}</div>`
        : `<div class="box row"><b>${T("Videoanalyse")}</b>${seg("boost", [["0", T("Leise im Hintergrund")], ["1", T("⚡ Volle Leistung")]], p.boost ? "1" : "0")}
           <span class="meta">${p.boost ? T("Alle Prozessorkerne arbeiten – schneller fertig, der Lüfter wird laut.") : T("Ein Kern, niedrigste Priorität – Abspielen und Bedienen bleiben flüssig, dauert aber länger.")}</span></div>`;
    }
    h += `<div class="meta" id="vhw">${esc(hwText(p.hwdec))}</div>`;
    if (el._h === h) return;
    el._h = h; el.innerHTML = h;
    const s = $('[data-f="boost"]', el);
    if (s) onSeg(s, async v => { await api("/api/videos/boost", {an: v === "1"}); Z.projekt.boost = v === "1"; this.boost(); });
  },
  draw() {
    const k = $("#vkopf"); if (!k) return;
    const n = VI.clips.length, dur = VI.clips.reduce((a, c) => a + c.dauer, 0);
    k.innerHTML = `<b>${T`${n} Videos`}</b><span class="meta">${T`${fmt(dur)} min Material`}</span><span class="lab" style="margin-left:14px">${T("Reihenfolge")}</span>${seg("sort", [["zeit", T("nach Aufnahmezeit")], ["name", T("nach Dateiname")]], VI.sortierung)}
      ${seg("filt", [["alle", T("Alle")], ["raus", T("Raus")], ["hoch", T("Wichtig")], ["ohne", T("ohne Aufnahmezeit")]], viFilter)}
      ${VI.ohne_zeit ? `<span class="pill warn">${T`${VI.ohne_zeit} ohne Aufnahmezeit (Dateidatum)`}</span>` : ""}`;
    onSeg($('[data-f="sort"]', k), async v => { VI = await api("/api/videos/sortierung", {art: v}); this.draw(); });
    onSeg($('[data-f="filt"]', k), v => { viFilter = v; this.draw(); });
    const g = $("#vgrid"); g.innerHTML = "";
    if (!n) { g.innerHTML = VI.laeuft ? `<div class="meta">${T("Die Videos werden gerade eingelesen …")}</div>` : `<div class="fehler">${T("Keine Videos gefunden.")}</div>`; return; }
    VI.clips.forEach((c, i) => {
      if (viFilter === "raus" && c.prio !== "raus" || viFilter === "hoch" && c.prio !== "hoch" || viFilter === "ohne" && c.quelle !== "Dateidatum") return;
      const d = document.createElement("div"); d.className = "card"; d.style.borderLeftColor = c.prio === "raus" ? "#b42323" : c.prio === "hoch" ? "#2a7a3a" : "#ccc";
      if (c.prio === "raus") d.style.opacity = .55;
      d.innerHTML = `<div class="strip">${c.bilder.map(b => `<img loading="lazy" src="${b}">`).join("")}</div>
        <div class="meta" style="margin-top:5px"><b style="color:var(--ink)">${i + 1}. ${esc(c.name)}</b><br>${esc(c.zeit)} ${c.quelle === "Dateidatum" ? `<span class="pill warn">${T("Zeit unsicher")}</span>` : ""} · ${fmt(c.dauer)} · ${c.hoch ? T("hochkant") : T("quer")} · ${c.sichten === 1 ? T("1 Perspektive") : T`${c.sichten} Perspektiven`} · ${T`brauchbar ${fmt(c.gut)}`}</div>
        <div class="bar" title="${T("Bildqualität")}"><b style="width:${Math.round(c.q * 100)}%"></b></div>
        <div class="row" style="margin-top:6px">${seg("prio", [["raus", T("Raus"), "raus"], ["", T("Auto")], ["hoch", T("Wichtig"), "hoch"]], c.prio)}
          <span class="meta" title="${T("Originalton dieses Clips: automatisch, bevorzugt oder nie (wo Musik zu hören ist, nie)")}">${T("Ton")}</span>${seg("ton", [["", T("Auto")], ["an", T("An")], ["aus", T("Aus")]], c.ton || "")}</div>`;
      onSeg($('[data-f="prio"]', d), async v => { await api("/api/clip", {name: c.name, prio: v}); c.prio = v; this.draw(); });
      onSeg($('[data-f="ton"]', d), async v => { await api("/api/clip", {name: c.name, ton: v}); c.ton = v; this.draw(); });
      $(".strip", d).onclick = () => vorschauClip(c.name);
      g.appendChild(d);
    });
  }
};
async function vorschauClip(name, t0) {
  const d = await api("/api/clipbilder/" + encodeURIComponent(name));
  await modal(`<h3>${esc(name)}</h3><video src="${d.proxy}" controls autoplay style="width:min(640px,80vw);display:block;border-radius:8px;background:#000" ${t0 ? `onloadedmetadata="this.currentTime=${t0}"` : ""}></video>`, [{t: T("Schließen"), v: 1, pri: true}]);
}

/* ── 5 Ablauf beschreiben ──────────────────────────────────── */
let SW = null, rec = null;
R.ablauf = {
  async render(m) {
    m.innerHTML = `<h1>${T("Ablauf beschreiben")}</h1><p class="lead">${T("Beschreib kurz, was in welcher Reihenfolge passiert ist – sprich es ein oder tipp es. Zum Beispiel: <i>„Am Anfang kommen alle mit dem Bus an, dann Anmeldung mit Armbändern. Jeden Tag Proben, zwischendurch Freizeit mit Fußball. Am Mittwoch Ausflug ins Museum, am Ende das Konzert, danach Gruppenfoto und Abreise.“</i> Daraus werden Stichworte, die die KI in den Videos sucht.")}</p>
      <div class="box"><div class="row" style="margin-bottom:8px"><span class="mic"><button id="bmic">${T("🎤 Aufnehmen")}</button><span class="pegel"><b id="pegel"></b></span><span class="meta" id="mtxt"></span></span></div>
      <textarea id="btext" rows="6" placeholder="${T("Ablauf hier eintippen oder einsprechen …")}"></textarea>
      <div class="row" style="margin-top:8px"><button class="pri" id="bparse">${T("Stichworte daraus machen")}</button><button id="bparse2">${T("Stichworte ergänzen")}</button><span class="meta">${T("„Jeden Tag“, „zwischendurch“, „immer wieder“ → das Stichwort darf mehrmals vorkommen.")}</span></div></div>
      <div class="box"><div class="row"><b>${T("Stichworte")}</b><span class="meta">${T("in der Reihenfolge des Ablaufs – Name kurz, Beschreibung hilft der KI")}</span><span style="flex:1"></span><button id="bneukw">${T("+ Stichwort")}</button></div><div class="kwliste" id="kwl"></div></div>${weiter("erkennung", T("Weiter zur Erkennung"))}`;
    bindWeiter(m);
    SW = await api("/api/stichworte");
    $("#btext").value = SW.beschreibung || "";
    this.list();
    $("#bparse").onclick = () => this.parse(false);
    $("#bparse2").onclick = () => this.parse(true);
    $("#bneukw").onclick = () => { SW.stichworte.push({id: "", name: "", text: "", wiederkehrend: false, gewicht: 1}); this.list(); this.save(); };
    $("#bmic").onclick = () => this.mic();
  },
  async parse(erg) {
    const t = $("#btext").value.trim(); if (!t) return toast(T("Bitte erst den Ablauf beschreiben."));
    if (!erg && SW.stichworte.length && !(await frage(T("Die bisherigen Stichworte werden ersetzt. Fortfahren?"), T("Ersetzen")))) return;
    SW = Object.assign(SW, await api("/api/ablauf", {text: t, ergaenzen: erg})); this.list();
  },
  list() {
    const l = $("#kwl"); if (!l) return;
    if (!SW.stichworte.length) { l.innerHTML = `<div class="meta" style="padding:8px 0">${T("Noch keine Stichworte.")}</div>`; return; }
    l.innerHTML = SW.stichworte.map((k, i) => `<div class="kw" data-i="${i}"><span class="szmv"><button data-mv="-1" ${i ? "" : "disabled"}>▲</button><button data-mv="1" ${i < SW.stichworte.length - 1 ? "" : "disabled"}>▼</button></span>
      <span class="dot" style="background:${KWF[i % KWF.length]}"></span><input type="text" class="kn" value="${esc(k.name)}" placeholder="${T("Name")}"><input type="text" class="kt" value="${esc(k.text)}" placeholder="${T("Was passiert da? (für die KI)")}">
      <label class="meta" title="${T("kommt mehrmals vor (z. B. jeden Tag)")}"><input type="checkbox" class="kr" ${k.wiederkehrend ? "checked" : ""}> ${T("mehrmals")}</label><button class="klein" data-del>✕</button></div>`).join("");
    $$(".kw", l).forEach(row => {
      const i = +row.dataset.i;
      $(".kn", row).onchange = e => { SW.stichworte[i].name = e.target.value; this.save(); };
      $(".kt", row).onchange = e => { SW.stichworte[i].text = e.target.value; this.save(); };
      $(".kr", row).onchange = e => { SW.stichworte[i].wiederkehrend = e.target.checked; this.save(); };
      $("[data-del]", row).onclick = () => { SW.stichworte.splice(i, 1); this.list(); this.save(); };
      $$("[data-mv]", row).forEach(b => b.onclick = () => { const d = +b.dataset.mv; const [x] = SW.stichworte.splice(i, 1); SW.stichworte.splice(i + d, 0, x); this.list(); this.save(); });
    });
  },
  async save() { const r = await api("/api/stichworte", {liste: SW.stichworte}); SW.stichworte = r.stichworte; },
  async mic() {
    const b = $("#bmic");
    if (rec) { rec.stop(); return; }
    if (!Z.ki.bereit) { if (await frage(T("Für die Spracheingabe braucht Pulsecut die KI-Erkennung (einmaliger Download, ca. 1,5 GB). Jetzt einrichten? Du kannst den Ablauf auch einfach eintippen."), T("Einrichten"))) { await api("/api/ki/einrichten", {}); go("erkennung"); } return; }
    let stream;
    try { stream = await navigator.mediaDevices.getUserMedia({audio: true}); } catch (e) { return toast(T("Kein Zugriff auf das Mikrofon: ") + e.message); }
    const chunks = []; rec = new MediaRecorder(stream, {mimeType: MediaRecorder.isTypeSupported("audio/webm;codecs=opus") ? "audio/webm;codecs=opus" : ""});
    const ac = new AudioContext(), src = ac.createMediaStreamSource(stream), an = ac.createAnalyser(); an.fftSize = 512; src.connect(an);
    const buf = new Uint8Array(an.fftSize);
    const meter = () => { if (!rec) return; an.getByteTimeDomainData(buf); let mx = 0; for (const v of buf) mx = Math.max(mx, Math.abs(v - 128)); $("#pegel").style.width = Math.min(100, mx / 1.28) + "%"; requestAnimationFrame(meter); };
    rec.ondataavailable = e => chunks.push(e.data);
    rec.onstop = async () => {
      stream.getTracks().forEach(t => t.stop()); ac.close(); rec = null; b.classList.remove("rec"); b.textContent = T("🎤 Aufnehmen"); $("#pegel").style.width = 0;
      const blob = new Blob(chunks, {type: "audio/webm"});
      $("#mtxt").textContent = T("Wandle in Text um …");
      const r = await fetch("/api/sprache", {method: "POST", headers: {"Content-Type": "audio/webm"}, body: blob}).then(r => r.json());
      if (!r.ok) { $("#mtxt").textContent = ""; return toast(r.fehler); }
      this.waitText = true;
    };
    rec.start(); meter(); b.classList.add("rec"); b.textContent = T("⏹ Aufnahme beenden"); $("#mtxt").textContent = T("Sprich jetzt …");
  },
  onJob(n, j) {
    if (n === "sprache" && this.waitText) {
      this.waitText = false; $("#mtxt").textContent = "";
      const t = Z.projekt.sprache_text;
      if (t) { const ta = $("#btext"); ta.value = (ta.value ? ta.value.trim() + " " : "") + t; toast(T("Text erkannt – prüfen und dann „Stichworte daraus machen“.")); }
    }
  },
  onPoll(z) { const j = z.projekt.jobs.sprache; if (j && j.laeuft && $("#mtxt")) $("#mtxt").textContent = j.text; },
  leave() { if (rec) rec.stop(); }
};
const KWF = ["#7b68c8", "#e76f51", "#f4a261", "#2a9d8f", "#5e60ce", "#e9c46a", "#d62828", "#3a86ff", "#8ac926", "#ff595e", "#6a4c93", "#1982c4", "#ff924c", "#52b788", "#b5179e", "#4d908e", "#c77dff", "#577590"];

/* ── 6 Szenen erkennen ─────────────────────────────────────── */
let ER = null;
R.erkennung = {
  async render(m) {
    m.innerHTML = `<h1>${T("Szenen erkennen")}</h1><p class="lead">${T("Die KI schaut sich alle Videos an und ordnet sie deinen Stichworten zu – dabei hilft auch die Reihenfolge, die du beschrieben hast. Danach siehst du die Szenen nach Stichworten gruppiert und kannst alles korrigieren.")}</p><div id="ekopf"></div><div id="eergebnis"></div>`;
    await this.load();
  },
  async load() {
    try { ER = await api("/api/erkennung"); } catch (e) { return; }
    this.kopf(); this.draw();
  },
  onPoll() { this.kopf(); },
  onJob(n) { if (n === "erkennung" || n === "analyse") this.load(); },
  kopf() {
    const k = $("#ekopf"); if (!k) return;
    const ki = Z.ki, p = Z.projekt, ej = p.jobs.erkennung, aj = p.jobs.analyse;
    let h = "";
    if (aj.laeuft) h += jobBox("analyse", T("Videos werden noch analysiert"));
    if (!ki.bereit) {
      h += `<div class="box"><b>${T("KI-Erkennung")}</b> <span class="meta">${T("einmalig einrichten: lädt PyTorch und drei Modelle (Bild, Geräusche, Sprache), ca. 1,5 GB. Danach läuft alles offline auf deinem Rechner – deine Videos verlassen den Rechner nie.")}</span>
        <div class="row" style="margin-top:8px">${ki.laeuft ? `<b>${T("Wird eingerichtet …")}</b>` : `<button class="pri" id="bkiein">${T("KI-Erkennung einrichten")}</button>`}<button id="bohne" ${ej.laeuft || aj.laeuft ? "disabled" : ""}>${T("Ohne KI weiter (Einteilung nach Zeitlücken)")}</button></div>
        ${ki.fehler ? `<div class="fehler">${esc(ki.fehler)}</div>` : ""}${ki.log.length ? `<div class="logbox" style="margin-top:8px">${esc(ki.log.join("\n"))}</div>` : ""}</div>`;
    } else {
      h += `<div class="box row"><b>${T("KI-Erkennung bereit")}</b><button class="pri" id="bstart" ${ej.laeuft || aj.laeuft ? "disabled" : ""}>${ER && ER.erkennung ? T("Erkennung neu starten") : T("Erkennung starten")}</button><span class="meta">${T("Beim ersten Mal werden die Modelle geladen (einige Minuten), danach geht es schneller.")}</span></div>`;
    }
    if (ej.laeuft) h += jobBox("erkennung", T("Erkennung läuft"));
    else if (ej.fehler) h += `<div class="fehler">${esc(ej.fehler)}</div>`;
    if (k._h !== h) { k.innerHTML = h; k._h = h;
      const b1 = $("#bkiein"); if (b1) b1.onclick = () => api("/api/ki/einrichten", {});
      const b2 = $("#bohne"); if (b2) b2.onclick = () => api("/api/erkennung/start", {mit_ki: false});
      const b3 = $("#bstart"); if (b3) b3.onclick = () => api("/api/erkennung/start", {mit_ki: true});
    }
  },
  draw() {
    const box = $("#eergebnis"); if (!box) return;
    const E = ER.erkennung;
    if (!E) { box.innerHTML = ER.stichworte.length ? "" : `<div class="hinweis">${T("Bitte zuerst den Ablauf beschreiben.")}</div>`; return; }
    const kwopt = sel => ER.stichworte.map(k => `<option value="${k.id}" ${k.id === sel ? "selected" : ""}>${esc(k.name)}</option>`).join("");
    let h = "";
    for (const f of E.fragen) {
      const zs = E.szenen.filter(z => f.szenen.includes(z.id));
      h += `<div class="frage" data-l="${esc(f.id || f.label)}"><b>${T`Ist da nicht noch „${esc(f.label)}“ dabei gewesen?`}</b> <span class="meta">${f.szenen.length === 1 ? T`1 Szene (${fmt(f.sekunden)} min) sieht danach aus.` : T`${f.szenen.length} Szenen (${fmt(f.sekunden)} min) sehen danach aus.`}</span>
        <div class="row" style="margin:8px 0">${zs.slice(0, 4).map(z => `<div class="strip" style="width:200px;height:48px">${z.bilder.slice(0, 3).map(b => `<img src="${b}" style="height:48px">`).join("")}</div>`).join("")}</div>
        <div class="row"><button class="pri" data-a="ja">${T("Ja, als Stichwort aufnehmen")}</button><button data-a="nein">${T("Nein")}</button><span class="meta">${T("oder gehört zu")}</span><select><option value="">…</option>${kwopt("")}</select></div></div>`;
    }
    h += `<div class="meta" style="margin:4px 0 10px">${T("Falsch einsortiert? Über die Auswahl unter jeder Szene in ein anderes Stichwort verschieben, ein neues Stichwort anlegen oder die Szene ganz rausnehmen.")}${E.ausgeschlossen ? " " + (E.ausgeschlossen === 1 ? T("1 Video steht unter „Videos“ auf Raus und wird nicht berücksichtigt.") : T`${E.ausgeschlossen} Videos stehen unter „Videos“ auf Raus und werden nicht berücksichtigt.`) : ""}</div>`;
    if (!E.ki) h += `<div class="hinweis">${T("Ohne KI wurden die Videos an den größten Zeitlücken auf die Stichworte verteilt – bitte prüfen und mit der Auswahl je Szene korrigieren.")}</div>`;
    if (E.unklar.length) h += `<div class="hinweis">${E.unklar.length === 1 ? T("<b>1 Szene ist unsicher</b> (gestrichelt umrandet) – bitte kurz prüfen.") : T`<b>${E.unklar.length} Szenen sind unsicher</b> (gestrichelt umrandet) – bitte kurz prüfen.`}</div>`;
    for (const g of E.gruppen) {
      const zs = E.szenen.filter(z => z.kw === g.kw);
      h += `<div class="kwgruppe"><div class="kopf"><span class="dot" style="background:${g.farbe}"></span><b>${esc(g.name)}</b><span class="meta">${pl(g.szenen, N("Szene"), N("Szenen"))} · ${pl(g.clips, N("Clip"), N("Clips"))} · ${fmt(g.sekunden)} min</span></div>
        <div class="szkarten">${zs.length ? zs.map(z => `<div class="szk${E.unklar.includes(z.id) ? " unklar" : ""}" style="border-top-color:${g.farbe}" data-id="${esc(z.id)}">
          <div class="strip">${z.bilder.map(b => `<img loading="lazy" src="${b}">`).join("")}</div>
          <div class="meta" style="margin-top:4px">${esc(z.zeit)} · ${pl(z.n, N("Clip"), N("Clips"))} · ${fmt(z.dauer)}</div>
          <div class="row" style="margin-top:4px"><select class="zkw" title="${T("Stichwort dieser Szene ändern")}">${kwOptionen(ER.stichworte, z.kw)}</select>${E.ki ? `<span class="pill ${z.sicherheit < .55 ? "warn" : "ok"}">${Math.round(z.sicherheit * 100)} %</span>` : ""}</div></div>`).join("") : `<div class="meta">${T("– keine Szene erkannt –")}</div>`}</div></div>`;
    }
    h += weiter("gewichtung", T("Passt so – weiter"));
    box.innerHTML = h; bindWeiter(box);
    $$(".frage", box).forEach(fr => {
      const l = fr.dataset.l;
      $$("button[data-a]", fr).forEach(b => b.onclick = async () => { await api("/api/erkennung/antwort", {id: l, antwort: b.dataset.a}); if (b.dataset.a === "ja") toast(T("Stichwort aufgenommen – Erkennung läuft erneut …")); await this.load(); });
      $("select", fr).onchange = async e => { if (e.target.value) { await api("/api/erkennung/antwort", {id: l, antwort: "zuordnen", kw: e.target.value}); await this.load(); } };
    });
    $$(".szk", box).forEach(c => {
      $(".zkw", c).onchange = async e => { await kwWahl(e.target.value, {szene: c.dataset.id}); await this.load(); };
      $(".strip", c).onclick = () => { const z = E.szenen.find(z => z.id === c.dataset.id); szeneAnsehen(z); };
    });
  }
};
async function szeneAnsehen(z) {
  await modal(`<h3>${T("Szene")} · ${esc(z.zeit)}</h3><div class="col">${z.clipliste.map(c => `<div class="row"><div class="strip" style="width:260px">${c.bilder.map(b => `<img src="${b}">`).join("")}</div><div class="meta"><b>${esc(c.name)}</b><br>${c.zeit} · ${fmt(c.dauer)}</div><button class="klein" data-n="${esc(c.name)}">${T("▶ ansehen")}</button></div>`).join("")}</div>`, [{t: T("Schließen"), v: 1, pri: true}]).then(() => {});
}
document.addEventListener("click", e => { const b = e.target.closest("button[data-n]"); if (b && $("#modal").hidden === false) { $("#modal").hidden = true; vorschauClip(b.dataset.n); } });

/* ── 7 Gewichtung & Reihenfolge ────────────────────────────── */
let GW = null, dragId = null; const openSz = new Set();
const MENGE = () => [["raus", T("Raus"), "raus"], ["vielweniger", T("Viel weniger")], ["weniger", T("Weniger")], ["", T("Normal")], ["mehr", T("Mehr"), "hoch"], ["viel", T("Viel mehr"), "hoch"]];
R.gewichtung = {
  async render(m) {
    m.innerHTML = `<h1>${T("Gewichtung & Reihenfolge")}</h1><p class="lead">${T("Lege fest, wie viel Platz jedes Stichwort im Film bekommt. Darunter kannst du einzelne Szenen verstärken oder abschwächen, die Reihenfolge ändern (z. B. Gruppenfoto <i>nach</i> dem Konzert) und gezielt Clips abwählen.")}</p>
      <div class="box"><b>${T("Anteil je Stichwort")}</b> <span class="meta">${T("(geschätzte Sekunden im Film bei der aktuellen Musiklänge)")}</span><div id="gwl" style="margin-top:8px"></div></div>
      <div class="box"><div class="row"><b>${T("Szenen in Filmreihenfolge")}</b><span class="meta">${T("Pfeile oder am ⠿ ziehen · „Clips ▾“ zeigt die Clips einer Szene")}</span><span style="flex:1"></span><button id="szreset">${T("Reihenfolge zurücksetzen")}</button></div>
      <div class="row" style="margin:8px 0" id="blockzeile"></div><div class="szlist" id="szl"></div></div>${weiter("schnitt")}`;
    bindWeiter(m);
    GW = await api("/api/gewichtung"); this.draw();
    $("#szreset").onclick = () => this.sz({zuruecksetzen: true});
  },
  draw() { this.weights(); this.blocks(); this.scenes(); },
  weights() {
    const l = $("#gwl"); if (!l || !GW.erkennung) return;
    const col = GW.erkennung.farben;
    l.innerHTML = GW.stichworte.map(k => `<div class="gewicht" data-k="${k.id}"><span class="dot" style="background:${col[k.id]}"></span><span>${esc(k.name)}</span>
      <input type="range" min="0" max="3" step="0.1" value="${k.gewicht}"><span class="meta gv">${k.gewicht.toFixed(1)}×</span><span class="meta ga">${GW.anteile[k.id] ? "≈ " + fmt(GW.anteile[k.id]) + " min" : "–"}</span></div>`).join("");
    $$(".gewicht", l).forEach(row => {
      const r = $("input", row);
      r.oninput = () => $(".gv", row).textContent = (+r.value).toFixed(1) + "×";
      r.onchange = async () => { const k = GW.stichworte.find(x => x.id === row.dataset.k); k.gewicht = +r.value; const res = await api("/api/gewichte", {[k.id]: +r.value}); GW.anteile = res.anteile; this.weights(); };
    });
  },
  blocks() {
    const b = $("#blockzeile"); if (!b) return;
    const opts = GW.stichworte.map(k => `<option value="${k.id}">${esc(k.name)}</option>`).join("");
    b.innerHTML = `<span class="meta">${T("Alle Szenen von")}</span><select id="bk1">${opts}</select><span class="meta">${T("setzen")}</span><select id="bk2"><option value="__anfang__">${T("an den Anfang")}</option><option value="__ende__">${T("ans Ende")}</option>${GW.stichworte.map(k => `<option value="${k.id}">${T`hinter „${esc(k.name)}“`}</option>`).join("")}</select><button id="bkgo">${T("Verschieben")}</button>`;
    $("#bkgo").onclick = async () => { const r = await api("/api/block", {kw: $("#bk1").value, nach: $("#bk2").value}); GW.erkennung = r.erkennung; this.scenes(); toast(T("Szenen verschoben")); };
  },
  async sz(body, changed) { const r = await api("/api/szene", body); GW.erkennung = r.erkennung; GW.anteile = r.anteile; this.weights(); this.scenes(changed); },
  scenes(changed) {
    const box = $("#szl"); if (!box || !GW.erkennung) return;
    const E = GW.erkennung, kwname = Object.fromEntries(GW.stichworte.map(k => [k.id, k.name]));
    const st = box.scrollTop; box.innerHTML = "";
    $("#szreset").style.display = E.von_hand ? "" : "none";
    E.szenen.forEach((z, i) => {
      const r = document.createElement("div");
      r.className = "szrow" + (z.menge === "raus" ? " raus" : "") + (changed === z.id ? " chg" : ""); r.draggable = !openSz.has(z.id); r.dataset.id = z.id; r.style.borderLeftColor = z.farbe;
      const film = z.schnitte ? (z.schnitte === 1 ? T`im Film: <b>1 Schnitt</b> · ${komma(z.sekunden)} s` : T`im Film: <b>${z.schnitte} Schnitte</b> · ${komma(z.sekunden)} s`) : T("noch nicht im Film");
      r.innerHTML = `<span class="grip">⠿</span><span class="szmv"><button data-d="-1" ${i ? "" : "disabled"}>▲</button><button data-d="1" ${i < E.szenen.length - 1 ? "" : "disabled"}>▼</button></span>
        <div><select class="zkw" title="${T("Stichwort dieser Szene ändern")}">${kwOptionen(GW.stichworte, z.kw)}</select> · ${esc(z.zeit)} · ${pl(z.n, N("Clip"), N("Clips"))}<br><span class="meta">${film}</span><button class="klein sztog" style="margin-left:6px">${openSz.has(z.id) ? T("Clips ▴") : T("Clips ▾")} ${z.clipliste.filter(c => c.schnitte.length).length}/${z.n}</button></div>
        <div class="szpics">${z.bilder.map(b => `<img loading="lazy" src="${b}">`).join("")}</div>${seg("menge", MENGE(), z.menge)}`;
      onSeg($(':scope > .seg', r), v => this.sz({id: z.id, menge: v}, z.id));
      $(".zkw", r).onchange = async e => { if (await kwWahl(e.target.value, {szene: z.id})) { GW = await api("/api/gewichtung"); this.draw(); } else this.scenes(); };
      $$(".szmv button", r).forEach(b => b.onclick = () => { const ids = E.szenen.map(x => x.id); ids.splice(i, 1); ids.splice(i + +b.dataset.d, 0, z.id); this.sz({folge: ids}, z.id); });
      $(".sztog", r).onclick = () => { openSz.has(z.id) ? openSz.delete(z.id) : openSz.add(z.id); this.scenes(); };
      $(".szpics", r).onclick = () => szeneAnsehen(z);
      r.ondragstart = e => { dragId = z.id; e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", z.id); };
      r.ondragover = e => { if (!dragId || dragId === z.id) return; e.preventDefault(); const bb = r.getBoundingClientRect(); const vor = e.clientY < bb.top + bb.height / 2; r.classList.toggle("drop-vor", vor); r.classList.toggle("drop-nach", !vor); };
      r.ondragleave = () => r.classList.remove("drop-vor", "drop-nach");
      r.ondrop = e => { e.preventDefault(); const vor = r.classList.contains("drop-vor"); r.classList.remove("drop-vor", "drop-nach"); if (!dragId || dragId === z.id) return;
        const ids = E.szenen.map(x => x.id).filter(x => x !== dragId); ids.splice(ids.indexOf(z.id) + (vor ? 0 : 1), 0, dragId); const mid = dragId; dragId = null; this.sz({folge: ids}, mid); };
      r.ondragend = () => { dragId = null; };
      if (openSz.has(z.id)) {
        const p = document.createElement("div"); p.className = "szclips";
        for (const c of z.clipliste) {
          const e = document.createElement("div"); e.className = "szc" + (c.schnitte.length ? " drin" : "") + (c.prio === "raus" ? " raus" : "");
          e.innerHTML = `<div class="strip" style="height:44px">${c.bilder.map(b => `<img loading="lazy" src="${b}" style="height:44px">`).join("")}</div>
            <div class="meta" style="margin-top:4px"><b>${c.zeit}</b> · ${fmt(c.dauer)} · ${c.hoch ? T("hochkant") : T("quer")} · ${esc(c.name)}</div>
            <div class="meta">${c.schnitte.length ? `<b>${T`${c.schnitte.length}× im Film`}</b>` : (c.nutzbar ? T("nicht im Film") : T("unbrauchbar"))}</div>
            <div class="row" style="margin-top:4px">${seg("prio", [["raus", T("Raus"), "raus"], ["", T("Auto")], ["hoch", T("Wichtig"), "hoch"]], c.prio)}</div>
            <div class="row" style="margin-top:4px"><span class="meta">${T("gehört zu")}</span><select class="ckw">${kwOptionen(GW.stichworte, z.kw)}</select></div>
            <div class="szshots">${c.schnitte.map(u => `<figure><img src="${u.bild || ""}"><button data-id="${u.id}" title="${T("diesen Schnitt rausnehmen")}">✕</button><figcaption>${T("Film")} ${fmt(u.tl)} · ${komma(u.dur.toFixed(1))} s</figcaption></figure>`).join("")}
              ${c.aus.map(u => `<figure class="weg"><img src="${u.bild || ""}"><button data-a="${u.a}" data-b="${u.b}" title="${T("wieder erlauben")}">↺</button><figcaption>${T("abgewählt")}</figcaption></figure>`).join("")}</div>`;
          onSeg($('[data-f="prio"]', e), async v => { await api("/api/clip", {name: c.name, prio: v}); const g = await api("/api/gewichtung"); GW = g; this.scenes(z.id); });
          $(".ckw", e).onchange = async ev => { if (await kwWahl(ev.target.value, {clip: c.name})) { GW = await api("/api/gewichtung"); this.draw(); } else this.scenes(z.id); };
          $(".strip", e).onclick = () => vorschauClip(c.name);
          $$(".szshots button[data-id]", e).forEach(b => b.onclick = async () => { await api("/api/shot/entfernen", {id: b.dataset.id}); GW = await api("/api/gewichtung"); this.scenes(z.id); toast(T("Schnitt raus – an seine Stelle kommt ein anderer")); });
          $$(".szshots button[data-a]", e).forEach(b => b.onclick = async () => { await api("/api/clip", {name: c.name, aus_weg: [+b.dataset.a, +b.dataset.b]}); GW = await api("/api/gewichtung"); this.scenes(z.id); });
          p.appendChild(e);
        }
        r.appendChild(p);
      }
      box.appendChild(r);
    });
    box.scrollTop = st;
  }
};

/* ── 8 Schnitt einstellen ──────────────────────────────────── */
R.schnitt = {
  async render(m) {
    const d = await api("/api/schnitt"); const s = d.schnitt, u = d.einheit;
    const k = s.k || d.k_default;
    const ks = [1, 2, 3, 4, 6, 8].map(n => [String(n), `${n} ${d.raster === "halbtakt" ? (n === 1 ? T("Halbtakt") : T("Halbtakte")) : (n === 1 ? T("Takt") : T("Takte"))} <span class="meta">≈ ${komma((n * u).toFixed(1))} s</span>`]);
    m.innerHTML = `<h1>${T("Schnitt einstellen")}</h1><p class="lead">${T("Geschnitten wird gleichmäßig im Takt der Musik. Hier legst du fest, wie lang ein Schnitt ist und wie die Bilder ineinander übergehen.")}</p>
      <div class="box col">
        <div class="row"><span class="lab">${T("Raster")}</span>${seg("raster", [["takt", T("ganzer Takt")], ["halbtakt", T("halber Takt (bei langsamer Musik)")]], d.raster)}</div>
        <div class="row"><span class="lab">${T("Schnittlänge")}</span>${seg("k", ks, String(k))}<span class="meta">${T`Vorschlag: ${d.k_default}`}</span></div>
        <div class="row"><span class="lab">${T("Übergang")}</span>${seg("ueb", [["hart", T("Harte Schnitte")], ["blende", T("Überblendung")]], s.uebergang)}
          ${s.uebergang === "blende" ? `<input type="range" id="sbl" min="0.2" max="2" step="0.1" value="${s.blende}"><span id="sblv">${komma((+s.blende).toFixed(1))} s</span>` : ""}</div>
        <div class="row"><span class="lab">${T("Kamera&shy;bewegung")}</span><label><input type="checkbox" id="sbew" ${s.bewegung ? "checked" : ""}> ${T("Für gegenläufige Kamerabewegungen (z. B. Schwenk links → Schwenk rechts, Zoom rein → raus) darf innerhalb einer Szene von der zeitlichen Reihenfolge abgewichen werden")}</label></div>
        <div class="meta" style="margin-left:96px">${T("Aus: streng chronologisch, abwechselnde Bewegungen werden trotzdem bevorzugt. Überlappungen gibt es nie.")}</div>
        <div class="row"><span class="lab">${T("Originalton")}</span>${seg("ton", [["aus", T("Nur Musik")], ["dazu", T("Stimmung dazu, Musik bleibt")], ["leiser", T("Stimmung dazu, Musik leiser")]], s.originalton === "aus" ? "aus" : (+s.absenken > 0 ? "leiser" : "dazu"))}</div>
        <div class="meta" style="margin-left:96px">${s.originalton === "aus" ? T("Der Originalton der Videos bleibt stumm, die ausgewählte Musik läuft durch.") : T("Lachen, Applaus, Jubel, Stimmen und Gruppengeräusche werden erkannt und weich ein- und ausgeblendet – nur wo im Video keine Musik läuft (Proben, Konzerte bleiben stumm). Je Clip lässt sich der Ton unter „Videos“ auf An oder Aus stellen, je Schnitt in der Timeline.")}</div>
      </div>
      <div class="box col"><b>${T("Titel & Abspann")}</b>
        <div class="row"><span class="lab">${T("Titel")}</span><input type="text" id="stit" value="${esc(s.titel)}" style="flex:1"></div>
        <div class="row"><span class="lab">${T("Untertitel")}</span><input type="text" id="sunt" value="${esc(s.untertitel)}" style="flex:1"></div>
        <div class="row"><span class="lab">${T("Abspann")}</span><input type="text" id="sabs" value="${esc(s.abspann)}" style="flex:1" placeholder="${T("z. B. Danke an alle!")}"></div>
        <div class="row" style="align-items:flex-start"><span class="lab">${T("Gestaltung")}</span><div class="stilgalerie" id="sgal">${T("Lade …")}</div></div>
        <div class="row"><span class="lab">${T("Schrift")}</span><button id="sfont" class="schriftknopf">${T("Standard")}</button>
          <span class="lab" style="margin-left:12px">${T("Akzentfarbe")}</span><input type="color" id="sfarbe" value="${esc((s.titelstil || {}).farbe || "#ffc23d")}">
          <span class="lab" style="margin-left:12px">${T("Lage")}</span>${seg("spos", [["unten", T("unten")], ["mitte", T("Mitte")]], (s.titelstil || {}).position || "unten")}</div>
        <div class="row"><span class="lab">${T("Schriftgröße")}</span><span class="meta">${T("Titel")}</span><input type="range" id="sgr" min="50" max="200" step="5" value="${(s.titelstil || {}).groesse || 100}"><span class="meta" id="sgrv"></span>
          <span class="meta" style="margin-left:12px">${T("Untertitel")}</span><input type="range" id="sgru" min="50" max="200" step="5" value="${(s.titelstil || {}).groesse_unter || 100}"><span class="meta" id="sgruv"></span>
          <button id="sgr0" title="${T("Standardgröße")}">↺</button></div>
        <div class="row"><span class="lab">${T("Fett")}</span><label><input type="checkbox" id="sfett" ${(s.titelstil || {}).fett === false ? "" : "checked"}> ${T("Titel")}</label>
          <label style="margin-left:12px"><input type="checkbox" id="sfettu" ${(s.titelstil || {}).fett_unter ? "checked" : ""}> ${T("Untertitel")}</label></div>
        <div class="meta" style="margin-left:96px">${T("Die Größe des Titels gilt auch für den Abspann. Wird ein langer Titel breiter als das Bild, verkleinert Pulsecut ihn von selbst.")}</div></div>
      ${Z.projekt.timeline ? `<div class="hinweis">${T("Es gibt schon eine Timeline. „Schnitt erstellen“ plant neu – von dir gesperrte Schnitte (🔒) bleiben erhalten.")}</div>` : ""}
      <div class="weiter"><button class="pri gross" id="splan">${T("Schnitt erstellen")} →</button></div>`;
    const save = async b => { await api("/api/schnitt", b); };
    onSeg($('[data-f="raster"]', m), async v => { await save({raster: v, k: 0}); this.render(m); });
    onSeg($('[data-f="k"]', m), async v => { await save({k: +v}); this.render(m); });
    onSeg($('[data-f="ueb"]', m), async v => { await save({uebergang: v}); this.render(m); });
    onSeg($('[data-f="ton"]', m), async v => { await save(v === "aus" ? {originalton: "aus"} : {originalton: "auto", absenken: v === "leiser" ? 5 : 0}); this.render(m); });
    const bl = $("#sbl"); if (bl) { bl.oninput = () => $("#sblv").textContent = komma((+bl.value).toFixed(1)) + " s"; bl.onchange = () => save({blende: +bl.value}); }
    $("#sbew").onchange = e => save({bewegung: e.target.checked});
    ["stit", "sunt", "sabs"].forEach((id, i) => $("#" + id).onchange = async e => { await save({[["titel", "untertitel", "abspann"][i]]: e.target.value}); this.galerie(); });
    this.galerie(true);
    $("#splan").onclick = async () => {
      const b = $("#splan"); b.disabled = true; b.textContent = T("Plane …");
      try { await api("/api/plan", {behalten: true}); Z = await fetch("/api/zustand").then(r => r.json()); go("timeline"); }
      finally { b.disabled = false; b.textContent = T("Schnitt erstellen") + " →"; }
    };
  }
};

R.schnitt.galerie = async function (first) {
  const box = $("#sgal"); if (!box) return;
  const d = await api("/api/titelstile"), st = d.aktuell;
  const q = `schrift=${encodeURIComponent(st.schrift || "")}&farbe=${encodeURIComponent(st.farbe || "")}&position=${st.position}&g=${st.groesse || 100}-${st.groesse_unter || 100}-${st.fett === false ? 0 : 1}${st.fett_unter ? 1 : 0}&t=${encodeURIComponent(($("#stit") || {}).value || "")}|${encodeURIComponent(($("#sunt") || {}).value || "")}`;
  box.innerHTML = d.stile.map(x => `<button class="stilk ${x.id === st.stil ? "on" : ""}" data-s="${x.id}" title="${esc(x.text)}"><img loading="lazy" src="/media/titelstil/${x.id}.png?${q}" alt=""><span>${esc(x.name)}</span></button>`).join("");
  $$(".stilk", box).forEach(b => b.onclick = async () => { await api("/api/schnitt", {titelstil: {stil: b.dataset.s}}); $$(".stilk", box).forEach(x => x.classList.toggle("on", x === b)); });
  const fb = $("#sfont");
  if (fb) { fb.textContent = st.schrift || T("Standard"); fb.style.fontFamily = st.schrift ? `'${st.schrift}'` : ""; }
  if (first && fb) {
    fb.onclick = async () => {
      const f = await schriftWahl(d.schriften, st.schrift || "", ($("#stit") || {}).value || "");
      if (f === null) return;
      await api("/api/schnitt", {titelstil: {schrift: f}}); st.schrift = f; this.galerie();
    };
    $("#sfarbe").onchange = async e => { await api("/api/schnitt", {titelstil: {farbe: e.target.value}}); this.galerie(); };
    onSeg($('[data-f="spos"]'), async v => { await api("/api/schnitt", {titelstil: {position: v}}); $$('[data-f="spos"] button').forEach(b => b.classList.toggle("on", b.dataset.v === v)); this.galerie(); });
    const zeig = () => { $("#sgrv").textContent = $("#sgr").value + " %"; $("#sgruv").textContent = $("#sgru").value + " %"; };
    zeig();
    for (const [id, k] of [["sgr", "groesse"], ["sgru", "groesse_unter"]]) {
      $("#" + id).oninput = zeig;
      $("#" + id).onchange = async e => { await api("/api/schnitt", {titelstil: {[k]: +e.target.value}}); this.galerie(); };
    }
    for (const [id, k] of [["sfett", "fett"], ["sfettu", "fett_unter"]]) $("#" + id).onchange = async e => { await api("/api/schnitt", {titelstil: {[k]: e.target.checked}}); this.galerie(); };
    $("#sgr0").onclick = async () => { $("#sgr").value = 100; $("#sgru").value = 100; zeig(); await api("/api/schnitt", {titelstil: {groesse: 100, groesse_unter: 100}}); this.galerie(); };
  }
};

function schriftWahl(sch, aktuell, probe) {
  // jede Schrift in sich selbst gezeigt, mit deinem Titel als Probe (das Programm nutzt die installierten Schriften)
  probe = probe || T("Sommerfreizeit 2026");
  const zeile = f => `<button class="schrift ${f === aktuell ? "on" : ""}" data-f="${esc(f)}"><span class="sname">${esc(f || T("Standard"))}</span><span class="sprobe" style="font-family:${f ? `'${esc(f)}'` : "inherit"}">${esc(probe)}</span></button>`;
  return new Promise(res => {
    const m = $("#modal"), box = $("#mbox");
    box.innerHTML = `<p><b>${T("Schrift wählen")}</b></p><input type="search" id="sfsuch" placeholder="${T("Suchen …")}" style="width:100%">
      <div class="schriftliste">${zeile("")}${sch.empfohlen.length ? `<div class="sgrp">${T("Empfohlen")}</div>` + sch.empfohlen.map(zeile).join("") : ""}${sch.weitere.length ? `<div class="sgrp">${T("Weitere Schriften")}</div>` + sch.weitere.map(zeile).join("") : ""}</div>
      <div class="weiter"><button data-x="abbr">${T("Abbrechen")}</button></div>`;
    m.hidden = false;
    const fertig = v => { m.hidden = true; res(v); };
    box.querySelectorAll(".schrift").forEach(b => b.onclick = () => fertig(b.dataset.f));
    box.querySelector('[data-x="abbr"]').onclick = () => fertig(null);
    const su = $("#sfsuch"); su.focus();
    su.oninput = () => { const q = su.value.toLowerCase(); box.querySelectorAll(".schrift").forEach(b => { b.hidden = q && !b.dataset.f.toLowerCase().includes(q); }); };
    const on = box.querySelector(".schrift.on"); if (on) on.scrollIntoView({block: "center"});
  });
}

/* ── 9 Timeline & Live-Vorschau ────────────────────────────── */
class Player {
  constructor(canvas, onTime) {
    this.cv = canvas; this.g = canvas.getContext("2d"); this.onTime = onTime;
    this.W = canvas.width = 960; this.H = canvas.height = 540;
    this.audio = new Audio(); this.audio.preload = "auto";
    this.pool = []; const hid = document.createElement("div"); hid.style.cssText = "position:absolute;width:1px;height:1px;overflow:hidden;opacity:0;pointer-events:none";
    document.body.appendChild(hid); this.hid = hid;
    // eigene Fläche für die Videobilder: ist das nächste Video im Moment des Schnitts noch nicht bereit, bleibt hier das
    // letzte Bild stehen (statt kurz das Standbild oder Schwarz zu zeigen)
    this.buf = document.createElement("canvas"); this.buf.width = this.W; this.buf.height = this.H; this.bg = this.buf.getContext("2d"); this.bufOk = false;
    for (let i = 0; i < 6; i++) { const v = document.createElement("video"); v.muted = true; v.preload = "auto"; v.playsInline = true; hid.appendChild(v); v._shot = null; v._used = 0; v.addEventListener("seeked", () => this.dirty = true); v.addEventListener("loadeddata", () => this.dirty = true); this.pool.push(v); }
    this.t = 0; this.playing = false; this.override = null; this.imgs = {}; this.dirty = true;
    this.audio.addEventListener("ended", () => this.pause());
    const loop = () => { this.frame(); requestAnimationFrame(loop); }; requestAnimationFrame(loop);
  }
  load(tl) {
    this.shots = tl.shots.filter(s => !s.ueber && s.dur > 0); this.xf = tl.xf || 0; this.titles = tl.titel || []; this.D = tl.dauer || 0;
    if (tl.musik && this.audio._src !== tl.musik.mix) { this.audio._src = tl.musik.mix; this.audio.src = tl.musik.mix; }
    // Musik unter dem Originalton absenken (wie im Export: weich mit dem Ein- und Ausblenden des Tons)
    this.duckDb = tl.absenken || 0; this.duck = [];
    for (const s of this.shots) {
      if (!s.atmo) continue;
      const last = this.duck[this.duck.length - 1];
      if (last && last.g === s.atmo.gruppe && Math.abs(last.b - s.tl0) < 0.05) last.b = s.tl1;
      else this.duck.push({g: s.atmo.gruppe, a: s.tl0, b: s.tl1});
    }
    this.dirty = true;
  }
  musicGain(t) {
    let d = 0;
    for (const x of this.duck) if (t > x.a && t < x.b + 0.8) d = Math.max(d, Math.min(1, (t - x.a) / 1.2, (x.b + 0.8 - t) / 1.6));
    return Math.pow(10, -this.duckDb * d / 20);
  }
  destroy() { this.pause(); this.audio.src = ""; this.pool.forEach(v => { v.pause(); v.removeAttribute("src"); v.load(); }); this.hid.remove(); this.dead = true; }
  play() { if (!this.shots || !this.shots.length) return; if (this.t >= this.D - 0.05) this.t = 0; this.audio.currentTime = this.t; this.audio.play().catch(() => {}); this.playing = true; }
  pause() { this.playing = false; this.audio.pause(); this.pool.forEach(v => v.pause()); this.dirty = true; }
  toggle() { this.playing ? this.pause() : this.play(); }
  seek(t) { this.t = Math.max(0, Math.min(this.D, t)); if (this.playing) this.audio.currentTime = this.t; this.bufOk = false; this.dirty = true; }
  idxAt(t) { const s = this.shots; let lo = 0, hi = s.length - 1, k = 0; while (lo <= hi) { const m = (lo + hi) >> 1; if (s[m].tl0 <= t) { k = m; lo = m + 1; } else hi = m - 1; } return k; }
  srcOf(s) { return this.override && this.override.id === s.id ? this.override.src : s.src; }
  layers(t) {
    const s = this.shots, i = this.idxAt(t), h = this.xf / 2, L = [{s: s[i], a: 1}];
    if (h > 0) {
      if (i + 1 < s.length && t > s[i].tl1 - h) L.push({s: s[i + 1], a: Math.min(1, (t - (s[i].tl1 - h)) / this.xf)});
      else if (i > 0 && t < s[i].tl0 + h) { L[0].a = Math.min(1, (t - (s[i].tl0 - h)) / this.xf); L.unshift({s: s[i - 1], a: 1}); }
    }
    return {L, i};
  }
  el(shot, want) {
    let v = this.pool.find(v => v._shot === shot.id);
    if (!v) {
      v = this.pool.filter(v => !want.includes(v._shot)).sort((a, b) => a._used - b._used)[0];
      v._shot = shot.id; if (v._proxy !== shot.proxy) { v._proxy = shot.proxy; v.src = shot.proxy; }
    }
    v._used = performance.now(); return v;
  }
  img(url) { if (!url) return null; let im = this.imgs[url]; if (!im) { im = new Image(); im.onload = () => this.dirty = true; im.src = url; this.imgs[url] = im; } return im.complete && im.naturalWidth ? im : null; }
  frame() {
    if (this.dead || !this.shots || !this.shots.length) return;
    if (this.playing) { this.t = this.audio.currentTime; this.audio.volume = this.musicGain(this.t); if (this.t >= this.D) this.pause(); }
    else if (!this.dirty) return;
    this.dirty = false;
    const t = this.t, {L, i} = this.layers(t), want = L.map(l => l.s.id);
    // die nächsten Schnitte früh vorladen – genau an ihrem Anfang angehalten, damit der Wechsel in eine andere
    // Videodatei sofort klappt
    for (const j of [i + 1, i + 2]) { const n = this.shots[j]; if (n && n.tl0 - t < 6 && !want.includes(n.id)) want.push(n.id); }
    const lay = [];
    for (const id of want) {
      const s = this.shots.find(x => x.id === id), v = this.el(s, want);
      const l = L.find(l => l.s.id === id), start = this.srcOf(s);
      if (!l) {   // vorladen
        if (!v.paused) v.pause();
        if (v.readyState >= 1 && !v.seeking && Math.abs(v.currentTime - start) > 0.04) v.currentTime = Math.max(0, start);
        v.muted = true; continue;
      }
      const mt = start + (t - s.tl0);
      if (v.readyState >= 1) {
        if (this.playing) { if (v.paused) v.play().catch(() => {}); if (Math.abs(v.currentTime - mt) > 0.25 && !v.seeking) v.currentTime = Math.max(0, mt); }
        else { if (!v.paused) v.pause(); if (Math.abs(v.currentTime - mt) > 0.04) v.currentTime = Math.max(0, mt); }
      }
      if (s.atmo && this.playing) { v.muted = false; const e = Math.min(1, (t - s.tl0) / 0.6, (s.tl1 - t) / 0.6); v.volume = Math.max(0, Math.min(1, Math.pow(10, s.atmo.gain_db / 20) * Math.max(0.15, e))); } else v.muted = true;
      lay.push({s, v, a: l.a});
    }
    for (const v of this.pool) if (!want.includes(v._shot) && !v.paused) v.pause();   // Rechenzeit sparen
    const bereit = lay.every(x => x.v.readyState >= 2 && !x.v.seeking);
    // höchstens eine halbe Sekunde das letzte Bild halten, danach lieber das Standbild als ein eingefrorenes Bild
    if (bereit) this.wait0 = 0; else if (!this.wait0) this.wait0 = performance.now();
    const halten = this.playing && this.bufOk && !bereit && performance.now() - this.wait0 < 500;
    if (!halten) {
      const b = this.bg; b.globalAlpha = 1; b.filter = "none"; b.fillStyle = "#000"; b.fillRect(0, 0, this.W, this.H);
      const order = L.map(l => lay.find(x => x.s.id === l.s.id)).filter(Boolean);
      for (const x of order) {
        b.globalAlpha = x.a;
        const src = x.v.readyState >= 2 ? x.v : this.img(x.s.bild);
        if (src) this.draw(b, src, x.s.aspect);
      }
      this.bufOk = bereit;
      if (!bereit) this.dirty = true;
    }
    const g = this.g; g.globalAlpha = 1; g.filter = "none"; g.drawImage(this.buf, 0, 0);
    g.globalAlpha = 1; g.filter = "none";
    for (const ti of this.titles) {
      if (t < ti.t0 || t > ti.t1) continue;
      const a = Math.min(1, (t - ti.t0) / 0.6, (ti.t1 - t) / 0.6); g.globalAlpha = Math.max(0, a);
      const tim = ti.bild ? this.img(ti.bild) : null;   // dasselbe Titelbild wie im Export
      if (tim) { g.drawImage(tim, 0, 0, this.W, this.H); continue; }
      const y = ti === this.titles[0] ? this.H * 0.64 : this.H * 0.78;
      g.fillStyle = "rgba(0,0,0,.45)"; g.fillRect(0, y - 12, this.W, ti.unter ? 120 : 84);
      g.fillStyle = "#fff"; g.textAlign = "center"; g.shadowColor = "#000"; g.shadowBlur = 6; g.font = "bold 46px 'Noto Sans','DejaVu Sans',sans-serif";
      g.fillText(ti.text, this.W / 2, y + 44); if (ti.unter) { g.font = "24px 'Noto Sans','DejaVu Sans',sans-serif"; g.fillText(ti.unter, this.W / 2, y + 88); } g.shadowBlur = 0;
    }
    const fb = this.playing ? Math.max(t < 1 ? 1 - t : 0, t > this.D - 1.5 ? (t - (this.D - 1.5)) / 1.5 : 0) : 0;
    if (fb > 0) { g.globalAlpha = Math.min(1, fb); g.fillStyle = "#000"; g.fillRect(0, 0, this.W, this.H); }
    g.globalAlpha = 1;
    if (this.onTime) this.onTime(t, i);
  }
  draw(g, src, aspect) {
    const W = this.W, H = this.H, A = W / H, a = aspect || A;
    if (Math.abs(a - A) > 0.06) {
      let w = W, h = W / a; if (h < H) { h = H; w = H * a; }
      g.save(); g.filter = "blur(16px) brightness(0.55)"; g.drawImage(src, (W - w) / 2, (H - h) / 2, w, h); g.restore();
    }
    let w = W, h = W / a; if (h > H) { h = H; w = H * a; }
    g.drawImage(src, (W - w) / 2, (H - h) / 2, w, h);
  }
}

let TL = null, PLY = null, SEL = null, pps = 0;
const ICO = {rechts: "→", links: "←", hoch: "↑", runter: "↓", rein: "⊕", raus: "⊖", ruhig: ""};
R.timeline = {
  async render(m) {
    m.innerHTML = `<h1>${T("Timeline & Vorschau")}</h1><p class="lead">${T("Spiel den Film ab – der rote Strich zeigt, wo du bist. Klick einen Schnitt an, um ihn anzupassen: Ausschnitt im Clip verschieben (ziehen oder wischen), Länge verdoppeln, andere Stelle, entfernen oder mit Ziehen in der Timeline umsortieren. Was du änderst, wird gesperrt 🔒 und bleibt beim Neuplanen erhalten.")}</p>
      <div class="tlwrap"><div><div class="player"><canvas id="pcv"></canvas></div>
        <div class="transport"><button id="pplay" class="pri">${T("▶ Abspielen")}</button><button id="pprev" title="${T("vorheriger Schnitt")}">⏮</button><button id="pnext" title="${T("nächster Schnitt")}">⏭</button><span class="zeit" id="pzeit">0:00</span><span style="flex:1"></span><span class="meta">${T("Vorschau")}</span><span id="pgr"></span></div></div>
        <div id="tlinfo"></div></div>
      <div class="tl"><div class="row" style="padding:8px 10px;border-bottom:1px solid var(--line)"><span class="meta">${T("Zoom")}</span><input type="range" id="tzoom" min="4" max="80" step="1">
        <span class="lab" style="margin-left:14px">${T("Originalton")}</span><span id="tton"></span><span style="flex:1"></span>
        <button id="tneu">${T("Neu planen (🔒 bleibt)")}</button><button id="talles">${T("Alles neu planen")}</button><button id="tfill">${T("Auffüllen")}</button></div>
        <div class="tlscroll" id="tls"><div class="tlinner" id="tli"><div class="ruler" id="trul"></div><div class="shots" id="tsh"></div><canvas class="mus" id="tmus"></canvas><div class="playhead" id="tph"></div></div></div></div>
      <div id="insp"></div>${weiter("export", T("Weiter zum Fertigstellen"))}`;
    bindWeiter(m);
    PLY = new Player($("#pcv"), (t, i) => this.time(t, i));
    this.groesse(vorschauGroesse());
    $("#pplay").onclick = () => { PLY.toggle(); this.btn(); };
    $("#pprev").onclick = () => { const s = PLY.shots, i = PLY.idxAt(PLY.t - 0.05); PLY.seek(s[Math.max(0, PLY.t - s[i].tl0 > 0.3 ? i : i - 1)].tl0); };
    $("#pnext").onclick = () => { const s = PLY.shots, i = PLY.idxAt(PLY.t); if (i + 1 < s.length) PLY.seek(s[i + 1].tl0); };
    $("#tneu").onclick = () => this.replan(true);
    $("#talles").onclick = async () => { if (await frage(T("Alles neu planen? Auch deine gesperrten Änderungen gehen verloren."), T("Alles neu"))) this.replan(false); };
    $("#tfill").onclick = async () => { await api("/api/auffuellen", {}); await this.load(); };
    $("#tzoom").oninput = e => { pps = +e.target.value; this.drawTL(); };
    $("#tli").addEventListener("mousedown", e => { if (e.target.closest(".shot")) return; const r = $("#tli").getBoundingClientRect(); PLY.seek((e.clientX - r.left) / pps); });
    this.key = e => { if (step !== "timeline" || e.target.matches("input,textarea,select")) return; if (e.code === "Space") { e.preventDefault(); PLY.toggle(); this.btn(); } if (e.code === "ArrowRight") $("#pnext").click(); if (e.code === "ArrowLeft") $("#pprev").click();
      if ((e.code === "Delete" || e.code === "Backspace") && SEL && $("#modal").hidden) { e.preventDefault(); this.entfernen(SEL); } };
    document.addEventListener("keydown", this.key);
    await this.load();
  },
  leave() { if (PLY) PLY.destroy(); PLY = null; document.removeEventListener("keydown", this.key); },
  groesse(v) {   // Vorschau klein / mittel / groß – kleiner lässt mehr Platz für Timeline und Schnitt-Optionen
    const w = $(".tlwrap"), el = $("#pgr"); if (!w || !el) return;
    w.classList.remove("v-klein", "v-mittel", "v-gross"); w.classList.add("v-" + v);
    el.innerHTML = seg("pgr", [["klein", "S"], ["mittel", "M"], ["gross", "L"]], v);
    onSeg($('[data-f="pgr"]', el), x => { try { localStorage.setItem("pulsecut.vorschau", x); } catch (e) { /* ohne Speicher */ } this.groesse(x); });
  },
  btn() { const b = $("#pplay"); if (b) b.textContent = PLY.playing ? T("⏸ Pause") : T("▶ Abspielen"); },
  async load(keepSel = true) {
    const tl = await api("/api/timeline");
    if (step !== "timeline" || !PLY || !$("#tlinfo")) return;   // inzwischen woanders hin gewechselt
    TL = tl;
    if (!TL.shots.length) { $("#tlinfo").innerHTML = `<div class="hinweis">${T("Noch kein Schnitt – bitte in „Schnitt einstellen“ auf „Schnitt erstellen“ klicken.")}</div>`; return; }
    PLY.load(TL);
    if (!pps) { const w = ($("#tls").clientWidth || 900) - 20; pps = Math.max(4, Math.min(80, Math.round(w / TL.dauer * 2.2))); }
    $("#tzoom").value = pps;
    if (SEL && !TL.shots.find(s => s.id === SEL)) SEL = null;
    this.info(); this.tonSchalter(); this.drawTL(); if (SEL) this.inspect(SEL); else $("#insp").innerHTML = "";
  },
  tonSchalter() {
    const el = $("#tton"); if (!el) return;
    const v = TL.originalton === "aus" ? "aus" : (TL.absenken > 0 ? "leiser" : "dazu");
    el.innerHTML = seg("tton", [["aus", T("Nur Musik")], ["dazu", T("Stimmung dazu")], ["leiser", T("Stimmung dazu, Musik leiser")]], v);
    onSeg($('[data-f="tton"]', el), async w => {
      await api("/api/schnitt", w === "aus" ? {originalton: "aus"} : {originalton: "auto", absenken: w === "leiser" ? 5 : 0});
      await this.load(); toast(w === "aus" ? T("Nur Musik – der Originalton bleibt überall stumm") : T("Originalton an stimmungsvollen Stellen dazu"));
    });
  },
  async entfernen(id) {
    const s = TL.shots.find(x => x.id === id); if (!s) return;
    const o = await api("/api/entfernen?id=" + id);
    let art = merkEntfernen();
    if (!art || !o[art] || !o[art].ok) { art = await entfernenWahl(o); if (!art) return; }
    const r = await api("/api/shot/entfernen", {id, ausgleich: art});
    const i = TL.shots.findIndex(x => x.id === id);
    SEL = null; await this.load();
    const nach = TL.shots[i]; if (nach) { SEL = nach.id; this.drawTL(); this.inspect(nach.id); PLY.seek(nach.tl0 + 0.02); }
    toast(art === "kuerzer" ? T("Entfernt – der Film ist entsprechend kürzer, die Musik blendet am Ende aus")
      : art === "nachbar" ? T("Entfernt – die Schnitte dahinter sind nachgerückt, der nächste ist länger")
      : T("Entfernt – die Schnitte dahinter sind nachgerückt, die Takte sind auf die Kategorien dahinter verteilt"), 5000);
    return r;
  },
  marker() {
    const old = $("#tfix"); if (old) old.remove();
    const m = TL.shots.find(x => x.id === TL.fertig_bis);
    const li = $("#tli"); if (!li) return;
    const d = document.createElement("div"); d.id = "tfix"; d.className = "fertiglinie" + (m ? "" : " leer");
    const x0 = m ? m.tl1 * pps : 0; d.style.left = x0 + "px";
    d.innerHTML = `<span>${m ? T("✓ fertig bis hier") : T("✓ ziehen: fertig bis …")}</span>`;
    d.title = T("Alles links davon ist fertig: Auffüllen, Ausgleichen und Neuplanen ändern dort nichts mehr. Zum Verschieben ziehen.");
    li.appendChild(d);
    d.onmousedown = e => {
      e.preventDefault(); e.stopPropagation(); const r = li.getBoundingClientRect();
      const mv = ev => { d.style.left = Math.max(0, ev.clientX - r.left) + "px"; };
      const up = async ev => {
        document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up);
        const t = (ev.clientX - r.left) / pps;
        let best = null; for (const s of TL.shots) if (!best || Math.abs(s.tl1 - t) < Math.abs(best.tl1 - t)) best = s;
        await api("/api/fertig", {id: t < 0.5 || !best ? null : best.id}); await this.load();
      };
      document.addEventListener("mousemove", mv); document.addEventListener("mouseup", up);
    };
  },
  async replan(keep) { await api("/api/plan", {behalten: keep}); await this.load(); toast(T("Neu geplant")); },
  info() {
    const t = TL, n = t.shots.length, locked = t.shots.filter(s => s.lock).length;
    const pr = t.probleme.filter(p => p.art !== "chronologie"), ch = t.probleme.filter(p => p.art === "chronologie");
    $("#tlinfo").innerHTML = `<div class="box"><b>${T`Film ${fmt(t.dauer)} min`}</b> · ${T`${n} Schnitte`} · ${t.musik && t.musik.raster === "halbtakt" ? T`${t.k} Halbtakte je Schnitt` : T`${t.k} Takte je Schnitt`} · ${t.xf ? T`Überblendung ${komma(t.xf)} s` : T("harte Schnitte")}${locked ? ` · ${locked} 🔒` : ""}
      ${t.differenz < 0 ? `<div class="hinweis">${T`Am Ende fehlen ${-t.differenz} Takte bis zum Musikende – „Auffüllen“ ergänzt passende Schnitte.`}</div>` : ""}
      ${t.differenz > 0 ? `<div class="hinweis">${T`${t.differenz} Takte ragen über das Musikende hinaus (blass dargestellt) – „Auffüllen“ entfernt den Überhang.`}</div>` : ""}
      ${pr.length ? `<div class="fehler">${pr.map(p => esc(p.text)).join("<br>")}</div>` : ""}
      ${ch.length ? `<div class="meta">${T`${ch.length}× von der Zeitfolge abweichend (von dir so gewollt oder durch die Kamerabewegungs-Option).`}</div>` : ""}
      ${(t.warnungen || []).map(w => `<div class="hinweis">${esc(w)}</div>`).join("")}
      ${t.abweichungen && t.abweichungen.length ? `<div class="hinweis" id="tabw"><b>${T("Die Anteile haben sich gegenüber der Planung verschoben:")}</b> ${t.abweichungen.map(d => T`${esc(d.name)} ${d.ist} % statt ${d.soll} %`).join(" · ")}
        <div class="row" style="margin-top:6px"><button id="abwok">${T("So lassen")}</button><button id="abwaus">${T("Hinter „fertig bis hier“ ausgleichen")}</button><button id="abwgw">${T("Gewichtung ändern")}</button></div></div>` : ""}
      ${t.ende_weg ? `<div class="meta" style="margin-top:6px">${t.ende_auto ? T`Die Musik endet ${t.ende_weg} Takte früher (mit Ausblendung) – für die ganze Musik ist nicht genug Material frei.` : T`Die Musik endet ${t.ende_weg} Takte früher (mit Ausblendung).`} <button id="endezur">${T("Zurücknehmen")}</button></div>` : ""}
      ${merkEntfernen() ? `<div class="meta" style="margin-top:6px">${T`Beim Entfernen: ${ENTF_NAME()[merkEntfernen()]}`} · <a href="#" id="entfwieder">${T("wieder fragen")}</a></div>` : ""}
      <div class="meta" style="margin-top:6px">${T("Tasten: Leertaste = Abspielen/Pause, ←/→ = Schnitt zurück/vor, Entf = ausgewählten Schnitt entfernen.")}</div></div>`;
    const b = (id, fn) => { const e = $("#" + id); if (e) e.onclick = fn; };
    b("abwok", async () => { await api("/api/anteile/ok", {}); await this.load(); });
    b("abwaus", async () => { const r = await api("/api/anteile/ausgleichen", {}); await this.load(); toast(r.verbessert ? T("Ausgeglichen") : T("Ausgleichen war nicht möglich – hinter „fertig bis hier“ ist für die fehlenden Kategorien kein Material mehr frei."), 6000); });
    b("abwgw", () => go("gewichtung"));
    b("endezur", async () => { await api("/api/ende/zuruecknehmen", {}); await this.load(); });
    b("entfwieder", e => { e.preventDefault(); try { localStorage.removeItem("pulsecut.entfernen"); } catch (x) { /* ohne Speicher */ } this.info(); });
  },
  drawTL() {
    const t = TL, W = Math.ceil(t.dauer * pps) + 40;
    $("#tli").style.width = W + "px";
    const step = pps >= 30 ? 2 : pps >= 14 ? 5 : pps >= 7 ? 10 : 20;
    let r = ""; for (let s = 0; s <= t.dauer; s += step) r += `<i style="left:${s * pps}px"></i><span style="left:${s * pps}px">${fmt(s)}</span>`;
    $("#trul").innerHTML = r;
    const sh = $("#tsh"); sh.style.width = W + "px"; sh.innerHTML = "";
    t.shots.forEach((s, i) => {
      const d = document.createElement("div");
      d.className = "shot" + (s.id === SEL ? " sel" : "") + (s.problem ? " problem" : "") + (s.ueber ? " ueber" : "") + (s.fertig ? " fertig" : "");
      d.style.left = s.tl0 * pps + "px"; d.style.width = Math.max(3, (s.tl1 - s.tl0) * pps - 2) + "px";
      d.style.borderTopColor = s.farbe; d.style.backgroundImage = s.bild ? `url(${s.bild})` : "";
      d.title = `${fmt1(s.tl0)} · ${s.name} · ${T`${s.clip} ab ${komma(s.src.toFixed(1))} s`} · ${s.bewegung_text}`;
      d.innerHTML = `<span class="ico">${s.lock ? "🔒" : ""}${ICO[s.bewegung] || ""}${s.atmo ? "🔊" : (s.ton === "aus" ? "🔇" : "")}</span><span class="lbl">${esc(s.name)}</span>`;
      d.dataset.i = i; d.dataset.id = s.id;
      d.onmousedown = e => this.dragStart(e, s, i, d);
      sh.appendChild(d);
    });
    const cv = $("#tmus"); cv.style.width = W + "px"; cv.style.height = "56px";
    const L = t.musik; if (L) { const dpr = devicePixelRatio || 1; cv.width = W * dpr; cv.height = 56 * dpr; const g = cv.getContext("2d"); g.scale(dpr, dpr);
      g.fillStyle = "#f4f3ef"; g.fillRect(0, 0, W, 56); g.beginPath(); g.moveTo(0, 56); for (const [x, v] of L.kurve) g.lineTo(x * pps, 56 - v * 48); g.lineTo(t.dauer * pps, 56); g.closePath(); g.fillStyle = "#b9c3d6"; g.fill();
      g.strokeStyle = "#0004"; for (const u of L.units) { const x = Math.round(u * pps) + .5; g.beginPath(); g.moveTo(x, 40); g.lineTo(x, 56); g.stroke(); }
      g.strokeStyle = "#000"; g.lineWidth = 2; for (const w of L.wechsel) { g.beginPath(); g.moveTo(w * pps, 0); g.lineTo(w * pps, 56); g.stroke(); }
      g.fillStyle = "#333"; g.font = "11px sans-serif"; for (const s of L.segmente) g.fillText("♪ " + s.titel, s.tl_start * pps + 4, 12); }
    this.marker();
    this.time(PLY.t);
  },
  time(t, i) {
    const ph = $("#tph"); if (!ph) return;
    ph.style.left = (t * pps) + "px";
    $("#pzeit").textContent = fmt1(t) + " / " + fmt(TL ? TL.dauer : 0);
    if (PLY && PLY.playing) { const sc = $("#tls"), x = t * pps; if (x < sc.scrollLeft + 40 || x > sc.scrollLeft + sc.clientWidth - 80) sc.scrollLeft = x - 80; }
    this.btn();
  },
  dragStart(e, s, i, el) {
    e.preventDefault(); const x0 = e.clientX; let drag = false, target = null;
    const blocks = $$("#tsh .shot");
    const mv = ev => {
      if (!drag && Math.abs(ev.clientX - x0) > 6) { drag = true; el.style.opacity = .5; }
      if (!drag) return;
      const r = $("#tli").getBoundingClientRect(), tt = (ev.clientX - r.left) / pps;
      blocks.forEach(b => b.classList.remove("ziel-vor"));
      let k = TL.shots.findIndex(x => tt < (x.tl0 + x.tl1) / 2); if (k < 0) k = TL.shots.length;
      target = k; const b = blocks[k]; if (b) b.classList.add("ziel-vor");
    };
    const up = async () => {
      document.removeEventListener("mousemove", mv); document.removeEventListener("mouseup", up);
      blocks.forEach(b => b.classList.remove("ziel-vor")); el.style.opacity = 1;
      if (!drag) { SEL = s.id; PLY.seek(s.tl0 + 0.02); $$("#tsh .shot").forEach(b => b.classList.toggle("sel", b.dataset.id === SEL)); this.inspect(s.id); return; }
      if (target === null || target === i || target === i + 1) return;
      await api("/api/shot/verschieben", {id: s.id, index: target > i ? target - 1 : target}); SEL = s.id; await this.load(); toast(T("Verschoben und gesperrt 🔒"));
    };
    document.addEventListener("mousemove", mv); document.addEventListener("mouseup", up);
  },
  async inspect(id) {
    const s = TL.shots.find(x => x.id === id); if (!s) return;
    const [cb, br] = await Promise.all([api("/api/clipbilder/" + encodeURIComponent(s.clip)), api("/api/bereich?id=" + id)]);
    const box = $("#insp"); if (!box || !PLY || step !== "timeline") return;
    const k0 = TL.k, ul = TL.musik ? TL.musik.einheit : 2;
    box.innerHTML = `<div class="inspector"><div class="row"><span class="dot" style="background:${s.farbe}"></span><b>${esc(s.name)}</b><span class="meta">${esc(s.clip)} · ${T`Film ${fmt1(s.tl0)}–${fmt1(s.tl1)} · Ausschnitt ab ${komma(s.src.toFixed(2))} s`} · ${komma(s.dur.toFixed(2))} s (${s.k} ${TL.musik && TL.musik.raster === "halbtakt" ? T("Halbtakte") : T("Takte")}) · ${T("Kamera:")} ${esc(s.bewegung_text)}</span>${s.lock ? `<span class="pill">${T("🔒 gesperrt")}</span>` : ""}</div>
      <div class="meta" style="margin:8px 0 4px">${T("Ausschnitt im Clip verschieben: gelben Rahmen ziehen oder mit dem Mausrad/Touchpad wischen. Rot schraffiert = schon an anderer Stelle im Film verwendet (dort stößt du an).")}</div>
      <div class="filmstrip" id="fs"><div class="bilder"></div></div>
      <div class="row" style="margin-top:6px"><span class="meta" id="fsinfo"></span></div>
      <div class="row" style="margin-top:10px"><span class="lab">${T("Länge")}</span>${[1, 2, 3].map(f => `<button data-k="${k0 * f}" class="${s.k === k0 * f ? "pri" : ""}">${f}× (${komma((k0 * f * ul).toFixed(1))} s)</button>`).join("")}<button data-k="${s.k - 1}" ${s.k <= 1 ? "disabled" : ""}>− 1</button><button data-k="${s.k + 1}">+ 1</button>
        <span class="lab" style="margin-left:12px">${T("Reihenfolge")}</span><button data-mv="-1">${T("◀ früher")}</button><button data-mv="1">${T("später ▶")}</button></div>
      <div class="row" style="margin-top:10px"><span class="lab">${T("Originalton")}</span>${seg("iton", [["", T("Auto")], ["an", T("An")], ["aus", T("Aus")]], s.ton || "")}<span class="meta" id="itoninfo">${esc(tonText(s))}</span></div>
      <div class="row" style="margin-top:8px"><button id="ianders">${T("Andere Stelle vorschlagen")}</button><button id="iweg" title="${T("Taste Entf")}">${T("Entfernen")}</button><button id="ifertig">${T("✓ Bis hier fertig")}</button><button id="iplus">${T("➕ Weiteren Clip danach einfügen")}</button><button id="ilock">${s.lock ? T("🔓 Entsperren (Automatik darf wieder)") : T("🔒 Sperren")}</button><button id="iclip">${T("Ganzen Clip ansehen")}</button></div></div>`;
    const fs = $("#fs"), W = fs.clientWidth, D = cb.dauer, sc = W / D;
    const nimg = Math.max(4, Math.floor(W / 82)), imgs = cb.bilder;
    $(".bilder", fs).innerHTML = imgs.length ? Array.from({length: nimg}, (_, j) => `<img src="${imgs[Math.min(imgs.length - 1, Math.floor((j + .5) / nimg * imgs.length))][1]}">`).join("") : "";
    for (const o of br.andere) { const b = document.createElement("div"); b.className = "block"; b.style.left = o.src * sc + "px"; b.style.width = Math.max(2, o.dur * sc) + "px"; b.innerHTML = `<span>${T("Film")} ${fmt(o.tl)}${o.lock ? " 🔒" : ""}</span>`; fs.appendChild(b); }
    for (const [a, b2] of cb.aus) { const b = document.createElement("div"); b.className = "aus"; b.style.left = a * sc + "px"; b.style.width = (b2 - a) * sc + "px"; fs.appendChild(b); }
    const win = document.createElement("div"); win.className = "fenster"; fs.appendChild(win);
    const rg = br.bereich; let cur = s.src, want = s.src;
    const place = () => { win.style.left = cur * sc + "px"; win.style.width = Math.max(4, s.dur * sc) + "px"; win.innerHTML = `<b>${komma(cur.toFixed(2))} s</b>`; win.classList.toggle("anschlag", Math.abs(want - cur) > 0.05);
      $("#fsinfo").textContent = Math.abs(want - cur) > 0.05 ? T("Anschlag: dahinter liegt ein anderer Schnitt aus diesem Clip. Loslassen fragt, ob du ihn aufgeben willst.") : T`frei verschiebbar von ${komma(rg.lo.toFixed(1))} bis ${komma(rg.hi.toFixed(1))} s`; };
    const setWant = v => { want = Math.max(rg.min, Math.min(rg.max, v)); cur = Math.max(rg.lo, Math.min(rg.hi, want)); if (rg.lo > rg.hi) cur = s.src; place(); PLY.override = {id: s.id, src: cur}; PLY.seek(s.tl0 + Math.min(0.3, s.dur / 2)); };
    place();
    const commit = async () => {
      PLY.override = null;
      if (Math.abs(want - s.src) < 0.02) return;
      if (Math.abs(want - cur) > 0.3) {
        const ok = await frage(T("Dort liegt schon ein anderer Schnitt aus diesem Clip. Diesen Nachbarschnitt aufgeben? Er bekommt automatisch eine neue Stelle in seiner Szene (oder wird ersetzt)."), T("Ja, aufgeben"), T("Nein, am Anschlag lassen"));
        const r = await api("/api/shot/slip", {id: s.id, src: ok ? want : cur, force: ok});
        if (!r.ok && r.kollision) toast(T("Kollision – nicht geändert"));
      } else {
        const r = await api("/api/shot/slip", {id: s.id, src: cur});
        if (r.kollision) { if (await frage(T("Der Ausschnitt würde einen anderen Schnitt überdecken. Den anderen aufgeben?"), T("Aufgeben"))) await api("/api/shot/slip", {id: s.id, src: cur, force: true}); }
      }
      await this.load();
    };
    let px = null, base = 0;
    fs.onpointerdown = e => { fs.setPointerCapture(e.pointerId); px = e.clientX; base = cur; const x = e.clientX - fs.getBoundingClientRect().left; if (x < cur * sc || x > (cur + s.dur) * sc) { base = x / sc - s.dur / 2; setWant(base); } };
    fs.onpointermove = e => { if (px === null) return; setWant(base + (e.clientX - px) / sc); };
    fs.onpointerup = () => { if (px === null) return; px = null; commit(); };
    let wt = null;
    fs.onwheel = e => { e.preventDefault(); const d = (Math.abs(e.deltaX) > Math.abs(e.deltaY) ? e.deltaX : e.deltaY) / 100 * 0.25; setWant(want + d); clearTimeout(wt); wt = setTimeout(commit, 500); };
    $$("button[data-k]", box).forEach(b => b.onclick = async () => {
      const k = +b.dataset.k; let r = await api("/api/shot/laenge", {id: s.id, k});
      if (!r.ok && r.kollision) { if (await frage(T("Für diese Länge reicht der Platz im Clip nicht – dahinter liegt ein anderer Schnitt. Den aufgeben?"), T("Aufgeben"))) r = await api("/api/shot/laenge", {id: s.id, k, force: true}); }
      else if (!r.ok && r.fehler) toast(r.fehler);
      await this.load();
    });
    $$("button[data-mv]", box).forEach(b => b.onclick = async () => { const i = TL.shots.findIndex(x => x.id === s.id); await api("/api/shot/verschieben", {id: s.id, index: i + +b.dataset.mv}); await this.load(); });
    $("#ianders").onclick = async () => { const r = await api("/api/shot/anders", {id: s.id}); if (!r.ok) toast(r.fehler); await this.load(); };
    $("#iweg").onclick = () => this.entfernen(s.id);
    $("#ifertig").onclick = async () => { await api("/api/fertig", {id: s.id}); await this.load(); toast(T("Alles bis hier ist fertig ✓")); };
    $("#ilock").onclick = async () => { await api("/api/shot/sperren", {id: s.id, lock: !s.lock}); await this.load(); };
    $("#iclip").onclick = () => vorschauClip(s.clip, s.src);
    $("#iplus").onclick = async () => {
      const d = await api("/api/szenenclips?id=" + s.id);
      const wahl = await clipWahl(d.clips);
      if (wahl === null) return;
      const r = await api("/api/shot/einfuegen", {id: s.id, clip: wahl});
      if (!r.ok) { toast(r.fehler || T("Nicht möglich")); return; }
      SEL = r.id; await this.load(); toast(T("Eingefügt und gesperrt 🔒 – dafür ist an anderer Stelle ein Schnitt weggefallen"));
    };
    onSeg($('[data-f="iton"]', box), async v => {
      await api("/api/shot/ton", {id: s.id, ton: v}); await this.load();
      if (v) toast(v === "an" ? T("Originalton an – gesperrt 🔒") : T("Originalton aus – gesperrt 🔒"));
    });
  }
};

function clipWahl(clips) {
  return new Promise(res => {
    const m = $("#modal"), box = $("#mbox");
    box.innerHTML = `<p><b>${T("Weiteren Clip aus dieser Szene danach einfügen")}</b><br><span class="meta">${T("Der neue Schnitt kommt direkt hinter den ausgewählten und wird gesperrt. Die Filmlänge bleibt – dafür fällt ein ungesperrter Schnitt einer anderen Szene weg.")}</span></p>
      <div class="clipwahl">${clips.map(c => `<button data-clip="${esc(c.name)}" ${c.frei ? "" : "disabled"} title="${esc(c.name)}">${c.bild ? `<img src="${c.bild}">` : ""}<b>${esc(c.name)}</b><span class="meta">${esc(c.zeit)} · ${komma(c.dauer)} s · ${c.im_film ? T`${c.im_film}× im Film` : T("noch nicht im Film")}${c.frei ? "" : " · " + T("nichts mehr frei")}</span></button>`).join("")}</div>
      <div class="weiter"><button data-x="abbr">${T("Abbrechen")}</button><button class="pri" data-x="auto" ${clips.some(c => c.frei) ? "" : "disabled"}>${T("Automatisch wählen")}</button></div>`;
    m.hidden = false;
    const fertig = v => { m.hidden = true; res(v); };
    box.querySelectorAll("[data-clip]").forEach(b => b.onclick = () => fertig(b.dataset.clip));
    box.querySelector('[data-x="abbr"]').onclick = () => fertig(null);
    box.querySelector('[data-x="auto"]').onclick = () => fertig("");
  });
}

const ENTF_NAME = () => ({rest: T("Rest des Films ausgleichen"), nachbar: T("Nachbarn länger"), kuerzer: T("Film kürzer")});
function merkEntfernen() { try { const v = localStorage.getItem("pulsecut.entfernen"); return ["rest", "nachbar", "kuerzer"].includes(v) ? v : ""; } catch (e) { return ""; } }
function entfernenWahl(o) {
  const n = ENTF_NAME();
  const neu = (o.rest.log || []).filter(x => x.art === "neu").map(x => x.kw), lg = (o.rest.log || []).find(x => x.art === "laenger");
  const was = [neu.length ? T`neue Schnitte: ${[...new Set(neu)].join(", ")}` : "", lg ? T`${lg.n} Takte auf Schnitte dahinter` : ""].filter(Boolean).join(" · ");
  const opt = [
    ["rest", n.rest, T("Die freien Takte gehen an die Kategorien hinter dieser Stelle, nach deiner Gewichtung – chronologisch eingereiht, nie aus einer früheren Szene.") + (was ? ` <i>(${esc(was)})</i>` : ""), o.rest.ok ? "" : T("Hinter dieser Stelle ist nicht genug Material frei.")],
    ["nachbar", n.nachbar, T("Der folgende Schnitt wird um diese Takte länger (z. B. doppelt so lang), alles andere bleibt."), o.nachbar.ok ? "" : T("Die Clips dahinter reichen nicht für längere Schnitte.")],
    ["kuerzer", n.kuerzer, T`Der Film wird ${komma(o.sekunden)} s kürzer: Die Musik endet ${o.takte} Takte früher, mit Ausblendung am Taktanfang.`, o.kuerzer.ok ? "" : T("Der Film ist dafür zu kurz.")],
  ];
  return new Promise(res => {
    const m = $("#modal"), box = $("#mbox");
    box.innerHTML = `<p><b>${T("Schnitt entfernen")}</b><br><span class="meta">${T("Die Schnitte dahinter rücken nach, alles davor gilt als fertig. Wohin mit den freien Takten?")}</span></p>
      <div class="entfwahl">${opt.map(([v, t, d, nein]) => `<button data-v="${v}" ${nein ? "disabled" : ""}><b>${t}</b><span>${d}</span>${nein ? `<span class="nein">${nein}</span>` : ""}</button>`).join("")}</div>
      <label class="meta"><input type="checkbox" id="entfmerk"> ${T("Immer so – nicht mehr fragen")}</label>
      <div class="weiter"><button data-x="abbr">${T("Abbrechen")}</button></div>`;
    m.hidden = false;
    const fertig = v => { m.hidden = true; if (v && $("#entfmerk").checked) { try { localStorage.setItem("pulsecut.entfernen", v); } catch (e) { /* ohne Speicher */ } } res(v); };
    box.querySelectorAll(".entfwahl button").forEach(b => b.onclick = () => fertig(b.dataset.v));
    box.querySelector('[data-x="abbr"]').onclick = () => fertig(null);
  });
}

function vorschauGroesse() {
  try { const v = localStorage.getItem("pulsecut.vorschau"); if (["klein", "mittel", "gross"].includes(v)) return v; } catch (e) { /* ohne Speicher */ }
  return "gross";
}

function tonText(s) {
  const g = (s.ton_info || {}).grund;
  if (g === "dabei") return (s.ton === "an" ? T("Originalton ist dabei.") : T("Automatisch dabei.")) + (s.ton_info.musik ? " " + T("Achtung: Im Video läuft Musik, sie mischt sich mit deiner Musik.") : "");
  if (g === "musik") return T("Automatisch nicht dabei: Im Video läuft Musik. Mit „An“ trotzdem dazunehmen.");
  if (g === "unauffaellig") return s.ton === "an" ? T("Zu leise für den Originalton.") : T("Automatisch nicht dabei: An dieser Stelle wurde nichts Stimmungsvolles erkannt (Lachen, Applaus, Stimmen).");
  if (g === "kein_ton") return T("Dieses Video hat keinen Ton.");
  if (g === "aus_clip") return T("Aus: Im Schritt „Videos“ für den ganzen Clip abgeschaltet.");
  if (g === "aus_schnitt") return T("Aus für diesen Schnitt.");
  if (g === "aus_gesamt") return T("Oben ist „Nur Musik“ eingestellt.");
  return "";
}

/* ── 10 Fertigstellen ──────────────────────────────────────── */
R.export = {
  async render(m) {
    const d = await api("/api/exporte");
    m.innerHTML = `<h1>${T("Fertigstellen")}</h1><p class="lead">${T("Pulsecut schreibt ein <b>Kdenlive-Projekt</b> (zum Feinschneiden – alle Schnitte, Musik mit Taktmarkern, Titel und Originalton auf eigenen Spuren) und rendert den Film in den gewünschten Formaten.")}</p>
      <div class="box col"><label><input type="checkbox" id="xk" checked> ${T("Kdenlive-Projekt (.kdenlive)")}</label>
        ${Object.entries(d.formate).map(([k, l]) => `<label><input type="checkbox" class="xf" value="${k}" ${k === "1080p" ? "checked" : ""}> ${esc(l)}</label>`).join("")}
        ${d.melt ? "" : `<div class="hinweis">${T("melt fehlt – gerendert wird mit ffmpeg (harte Schnitte statt Überblendungen).")}</div>`}
        <div class="weiter"><button class="pri gross" id="xgo">${T("Fertigstellen")}</button></div></div>
      <div id="xjob"></div><div id="xres"></div>`;
    $("#xgo").onclick = async () => { await api("/api/export", {kdenlive: $("#xk").checked, formate: $$(".xf").filter(x => x.checked).map(x => x.value)}); this.onPoll(); };
    this.files(d.dateien);
  },
  onPoll() { const j = $("#xjob"); if (j) j.innerHTML = jobBox("export", T("Export läuft")); },
  async onJob(n) { if (n === "export") { const d = await api("/api/exporte"); this.files(d.dateien); toast(T("Fertig!")); } },
  files(list) {
    const b = $("#xres"); if (!b) return;
    if (!list || !list.length) { b.innerHTML = ""; return; }
    const dir = list[0].replace(/\/[^/]+$/, "");
    b.innerHTML = `<div class="gut">${T`<b>Fertig.</b> Gespeichert in <code>${esc(dir)}</code>`}</div><div class="box col">${list.map(f => `<div class="row"><span style="flex:1">${esc(f.split("/").pop())}</span><button data-o="${esc(f)}">${f.endsWith(".kdenlive") ? T("In Kdenlive öffnen") : T("Abspielen")}</button></div>`).join("")}
      <div class="row"><button data-o="${esc(dir)}">${T("Ordner öffnen")}</button></div></div>`;
    $$("button[data-o]", b).forEach(x => x.onclick = () => oeffnen(x.dataset.o));
  }
};

/* ── Sprache ───────────────────────────────────────────────── */
function renderLang() {
  const el = $("#lang"); if (!el) return;
  document.documentElement.lang = LANG();
  el.innerHTML = seg("lang", [["de", "DE"], ["en", "EN"]], LANG());
  el.title = T("Sprache der Oberfläche");
  onSeg($('[data-f="lang"]', el), async v => {
    if (v === LANG()) return;
    const r = await api("/api/sprache/oberflaeche", {sprache: v}); Z.sprache = r.sprache;
    renderLang(); renderNav(); renderJobs(); go(step);
  });
}

/* ── Start ─────────────────────────────────────────────────── */
(async function init() {
  try { Z = await fetch("/api/zustand").then(r => r.json()); } catch (e) { Z = null; }
  renderLang();
  if (Z && Z.projekt) { lastJobs = JSON.parse(JSON.stringify(Z.projekt.jobs)); go(Z.projekt.timeline ? "timeline" : "musik"); } else go("start");
  renderJobs(); poll();
})();
