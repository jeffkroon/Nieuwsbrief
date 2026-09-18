// Templates: stijl kiezen, kleuren afleiden, layouts beheren en versies.

// ---- tone of voice ----
const tonePreview = document.getElementById("tonePreview");
const toneStatus = document.getElementById("toneStatus");

async function loadTone() {
  const tid = tenantSel.value;
  if (!tid) return;
  toneStatus.textContent = "";
  try {
    const { tone_of_voice } = await (await fetch(`/tenants/${tid}/tone`)).json();
    tonePreview.textContent = tone_of_voice || "Nog niet geanalyseerd, wordt bij het eerste gesprek automatisch bepaald (of klik hieronder).";
  } catch (e) { tonePreview.textContent = "Kon tone of voice niet laden."; }
}

document.getElementById("toneRefresh").onclick = async () => {
  const tid = tenantSel.value;
  toneStatus.textContent = "Analyseren...";
  const res = await fetch(`/tenants/${tid}/tone/refresh`, { method: "POST" });
  if (!res.ok) { const e = await res.json().catch(() => ({})); meld(toneStatus, "Mislukt: " + (e.detail || res.status), "fout"); return; }
  tonePreview.textContent = (await res.json()).tone_of_voice || "";
  meld(toneStatus, "Bijgewerkt.", "ok");
};

// ---- templates ----
let isAdmin = false;
let templatesCache = [];
const tmplSelect = document.getElementById("tmplSelect");
const tmplStatus = document.getElementById("tmplStatus");
const adminStatus = document.getElementById("adminStatus");
const previewFrame = document.getElementById("tmplPreviewFrame");
const STYLE_INPUTS = {
  font_family: document.getElementById("stFont"),
  text_color: document.getElementById("stText"),
  heading_color: document.getElementById("stHeading"),
  link_color: document.getElementById("stLink"),
  button_bg: document.getElementById("stButtonBg"),
  button_text: document.getElementById("stButtonText"),
  hero_button_bg: document.getElementById("stHeroBtnBg"),
  hero_button_text: document.getElementById("stHeroBtnText"),
  cta_button_bg: document.getElementById("stCtaBtnBg"),
  cta_button_text: document.getElementById("stCtaBtnText"),
  accent: document.getElementById("stAccent"),
  card_border: document.getElementById("stCardBorder"),
  card_bg: document.getElementById("stCardBg"),
  price_color: document.getElementById("stPrice"),
  badge_bg: document.getElementById("stBadge"),
  home_color: document.getElementById("stHome"),
  away_color: document.getElementById("stAway"),
  block_border: document.getElementById("stBlockBorder"),
  page_bg: document.getElementById("stPageBg"),
  footer_bg: document.getElementById("stFooterBg"),
  footer_text: document.getElementById("stFooterText"),
};
const STYLE_DEFAULTS = {
  font_family: "arial", text_color: "#3b3f44", heading_color: "#ffffff", link_color: "#0092ff",
  button_bg: "#ff7200", button_text: "#ffffff", accent: "#ff7200",
  hero_button_bg: "#ff7200", hero_button_text: "#ffffff",
  cta_button_bg: "#ff7200", cta_button_text: "#ffffff",
  card_border: "#e8e8e8", card_bg: "#ffffff", price_color: "#1a3a6e", badge_bg: "#1a3a6e",
  home_color: "#00aeef", away_color: "#1a3a6e", block_border: "#ff7200",
  page_bg: "#ffffff", footer_bg: "#6a6a6b", footer_text: "#ffffff",
};

async function loadRole() {
  try {
    const me = await (await fetch("/me")).json();
    isAdmin = !!me.is_admin;
  } catch (e) { isAdmin = false; }
  document.getElementById("adminCard").style.display = isAdmin ? "block" : "none";
  document.getElementById("navCompanies").style.display = isAdmin ? "" : "none";
  document.getElementById("roleBadge").textContent = isAdmin ? "Dunion-beheerder" : "Bedrijfsaccount";
}

function readStyleInputs() {
  const out = {};
  for (const k in STYLE_INPUTS) out[k] = STYLE_INPUTS[k].value;
  return out;
}

// ---- hoofdkleur, palet en leesbaarheid ----
const stPrimary = document.getElementById("stPrimary");
const stBrandNote = document.getElementById("stBrandNote");
const stWarnings = document.getElementById("stWarnings");

// Het palet komt altijd van de server, ook als je zelf een hoofdkleur kiest:
// één plek waar de afleiding staat, geen tweede versie in JavaScript.
async function paletFromServer(primary) {
  const url = `/tenants/${tenantSel.value}/templates/style-suggestion`
    + (primary ? `?primary=${encodeURIComponent(primary)}` : "");
  const res = await fetch(url);
  if (!res.ok) return null;
  return res.json();
}

async function vulUitHuisstijl(primary) {
  if (!tenantSel.value) return;
  const voorstel = await paletFromServer(primary);
  if (!voorstel) { stBrandNote.textContent = "Kon het voorstel niet ophalen."; return; }
  stBrandNote.textContent = voorstel.note || "";
  if (!Object.keys(voorstel.styles).length) return;
  for (const k in voorstel.styles) {
    if (STYLE_INPUTS[k]) STYLE_INPUTS[k].value = voorstel.styles[k];
  }
  if (voorstel.primary_color) stPrimary.value = voorstel.primary_color;
  renderStylePreview();
  checkContrast();
}

document.getElementById("stFromBrand").onclick = () => vulUitHuisstijl(null);
stPrimary.addEventListener("input", () => {
  clearTimeout(stPrimary._timer);
  stPrimary._timer = setTimeout(() => vulUitHuisstijl(stPrimary.value), 250);
});

// Wit op wit kan een klant nu nog gewoon kiezen; dit meldt het, zonder te blokkeren.
let contrastTimer = null;
function scheduleContrast() {
  clearTimeout(contrastTimer);
  contrastTimer = setTimeout(checkContrast, 400);
}

async function checkContrast() {
  if (!tenantSel.value) return;
  try {
    const res = await fetch(`/tenants/${tenantSel.value}/templates/style-check`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ styles: readStyleInputs() }) });
    if (!res.ok) return;
    const { warnings } = await res.json();
    stWarnings.innerHTML = "";
    for (const w of warnings) {
      const div = document.createElement("div");
      div.textContent = w;
      stWarnings.appendChild(div);
    }
    stWarnings.style.display = warnings.length ? "block" : "none";
  } catch (e) { /* leesbaarheidshulp mag de pagina nooit blokkeren */ }
}

function applyStyleInputs(styles) {
  for (const k in STYLE_INPUTS) STYLE_INPUTS[k].value = styles[k] || STYLE_DEFAULTS[k];
  // Banner-/onderste knop volgen de productknop zolang ze zelf niet gezet zijn.
  const btnBg = styles.button_bg || STYLE_DEFAULTS.button_bg;
  const btnText = styles.button_text || STYLE_DEFAULTS.button_text;
  if (!styles.hero_button_bg) STYLE_INPUTS.hero_button_bg.value = btnBg;
  if (!styles.hero_button_text) STYLE_INPUTS.hero_button_text.value = btnText;
  if (!styles.cta_button_bg) STYLE_INPUTS.cta_button_bg.value = btnBg;
  if (!styles.cta_button_text) STYLE_INPUTS.cta_button_text.value = btnText;
  // De hoofdkleur-kiezer volgt de knopkleur; die bepaalt het meeste beeld.
  if (stPrimary) stPrimary.value = btnBg;
  scheduleContrast();
}

async function loadTemplates() {
  const tid = tenantSel.value;
  if (!tid) return;
  tmplStatus.textContent = "";
  try {
    templatesCache = await (await fetch(`/tenants/${tid}/templates`)).json();
  } catch (e) { meld(tmplStatus, "Kon templates niet laden: " + e.message, "fout"); return; }
  tmplSelect.innerHTML = "";
  if (!templatesCache.length) {
    const o = document.createElement("option"); o.textContent = "(nog geen template)"; o.value = "";
    tmplSelect.appendChild(o);
  }
  for (const t of templatesCache) {
    const o = document.createElement("option");
    o.value = t.id; o.textContent = t.name + (t.is_default ? " (standaard)" : "");
    tmplSelect.appendChild(o);
  }
  const def = templatesCache.find(t => t.is_default) || templatesCache[0];
  if (def) { tmplSelect.value = def.id; applyStyleInputs(def.styles || {}); renderStylePreview(); }
  else { previewFrame.srcdoc = ""; }
  renderAdminList();
  loadChatTemplates();
}

function selectedTemplate() {
  return templatesCache.find(t => t.id === tmplSelect.value) || null;
}

tmplSelect.addEventListener("change", () => {
  const t = selectedTemplate();
  applyStyleInputs(t ? (t.styles || {}) : {});
  renderStylePreview();
});

async function renderStylePreview() {
  const tid = tenantSel.value;
  const t = selectedTemplate();
  if (!tid || !t) { previewFrame.srcdoc = ""; return; }
  const body = { template_id: t.id, styles: readStyleInputs() };
  try {
    const res = await fetch(`/tenants/${tid}/templates/preview`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) { const e = await res.json().catch(() => ({})); tmplStatus.textContent = "Voorbeeld: " + (e.detail || res.status); return; }
    previewFrame.srcdoc = await res.text();
    tmplStatus.textContent = "";
  } catch (e) { tmplStatus.textContent = "Voorbeeld mislukt: " + e.message; }
}
let stylePreviewTimer = null;
function scheduleStylePreview() { clearTimeout(stylePreviewTimer); stylePreviewTimer = setTimeout(renderStylePreview, 500); }
document.getElementById("tmplPreview").onclick = renderStylePreview;

document.getElementById("tmplSaveStyles").onclick = async () => {
  const tid = tenantSel.value;
  const t = selectedTemplate();
  if (!t) { tmplStatus.textContent = "Geen template gekozen om op te slaan."; return; }
  const res = await fetch(`/tenants/${tid}/templates/${t.id}/styles`, {
    method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ styles: readStyleInputs() }) });
  meld(tmplStatus, res.ok ? "Stijl opgeslagen." : "Opslaan mislukt.", res.ok ? "ok" : "fout");
  toast(res.ok ? "Stijl opgeslagen." : "Stijl opslaan mislukt.", res.ok ? "ok" : "fout");
  if (res.ok) loadTemplates();
};

document.getElementById("tmplSetDefault").onclick = async () => {
  const tid = tenantSel.value;
  const t = selectedTemplate();
  if (!t) return;
  const res = await fetch(`/tenants/${tid}/templates/${t.id}/default`, { method: "POST" });
  meld(tmplStatus, res.ok ? "Standaard ingesteld." : "Mislukt.", res.ok ? "ok" : "fout");
  if (res.ok) loadTemplates();
};

// ---- admin: layouts beheren ----
function renderAdminList() {
  const list = document.getElementById("tmplList");
  if (!isAdmin) { list.innerHTML = ""; return; }
  list.innerHTML = templatesCache.length ? "" : `<p class="hint">Nog geen templates.</p>`;
  for (const t of templatesCache) {
    const el = document.createElement("div");
    el.className = "tmpl-item";
    el.innerHTML = `<span>${t.name}</span>` + (t.is_default ? `<span class="badge">standaard</span>` : "")
      + `<span style="margin-left:auto;"></span>`;

    const bewerk = document.createElement("button");
    bewerk.className = "edit";
    bewerk.textContent = "bewerken";
    bewerk.onclick = async () => {
      const res = await fetch(`/tenants/${tenantSel.value}/templates/${t.id}`);
      if (!res.ok) { adminStatus.textContent = "Kon de template niet laden."; return; }
      startBewerken(await res.json());
    };
    el.appendChild(bewerk);

    const versies = document.createElement("button");
    versies.className = "ghost";
    versies.textContent = "versies";
    el.appendChild(versies);

    const verwijder = document.createElement("button");
    verwijder.textContent = "verwijderen";
    verwijder.onclick = async () => {
      if (!await bevestig(`Template "${t.name}" verwijderen? De versiegeschiedenis gaat mee.`,
        { bevestigTekst: "Template verwijderen" })) return;
      await fetch(`/tenants/${tenantSel.value}/templates/${t.id}`, { method: "DELETE" });
      if (editingTemplateId === t.id) stopBewerken();
      loadTemplates();
    };
    el.appendChild(verwijder);
    list.appendChild(el);

    const paneel = document.createElement("div");
    paneel.className = "versions";
    paneel.dataset.open = "0";
    list.appendChild(paneel);
    versies.onclick = () => toggleVersies(t, paneel);
  }
}

const adminPreviewFrame = document.getElementById("adminPreviewFrame");
async function renderAdminPreview() {
  const html = document.getElementById("newTmplHtml").value.trim();
  if (!html) { adminPreviewFrame.srcdoc = ""; return; }
  try {
    const res = await fetch(`/tenants/${tenantSel.value}/templates/preview`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ html, styles: readStyleInputs() }) });
    adminPreviewFrame.srcdoc = res.ok
      ? await res.text()
      : `<p style="font-family:sans-serif;color:#c0392b;padding:12px;">Kan voorbeeld niet maken (${res.status}).</p>`;
  } catch (e) { adminPreviewFrame.srcdoc = `<p style="font-family:sans-serif;padding:12px;">Voorbeeld mislukt.</p>`; }
}
let adminPreviewTimer = null;
function scheduleAdminPreview() {
  clearTimeout(adminPreviewTimer);
  adminPreviewTimer = setTimeout(renderAdminPreview, 700);
}
document.getElementById("newTmplHtml").addEventListener("input", scheduleAdminPreview);
document.getElementById("adminPreview").onclick = renderAdminPreview;
for (const k in STYLE_INPUTS) STYLE_INPUTS[k].addEventListener("input", () => {
  scheduleStylePreview();
  scheduleContrast();
  // Na toolproof telt de actuele kiezer-stand: een handmatige kleuraanpassing
  // gaat mee bij het opslaan in plaats van stil te verdwijnen.
  if (toolproofStyles) toolproofStyles = readStyleInputs();
  if (isAdmin && document.getElementById("newTmplHtml").value.trim()) scheduleAdminPreview();
});

document.getElementById("tmplStarter").onclick = async () => {
  const res = await fetch(`/tenants/${tenantSel.value}/templates/starter`);
  if (res.ok) {
    document.getElementById("newTmplHtml").value = (await res.json()).html;
    adminStatus.textContent = "Standaard layout geladen, pas aan en sla op.";
    renderAdminPreview();
  }
};

// Basis-stijl uit de laatste toolproof-run; gaat mee bij Toevoegen zodat de
// template er exact zo uit blijft zien als het origineel.
let toolproofStyles = null;
// Waar de HTML in het tekstvak vandaan komt; belandt in de versiegeschiedenis.
let templateSource = "handmatig";
// Gevuld = we bewerken een bestaande template in plaats van een nieuwe toe te voegen.
let editingTemplateId = null;
document.getElementById("newTmplHtml").addEventListener("input", () => {
  toolproofStyles = null;
  templateSource = "handmatig";
});

// ---- capabilities + diff tonen ----
function toonCapabilities(lijst) {
  const el = document.getElementById("tmplCaps");
  el.innerHTML = "";
  for (const tekst of lijst || []) {
    const span = document.createElement("span");
    span.textContent = tekst;
    el.appendChild(span);
  }
}

// Eigen mini-renderer voor de unified diff: geen externe bibliotheek nodig.
function toonDiff(diff) {
  const el = document.getElementById("toolproofDiff");
  el.innerHTML = "";
  if (!diff) { el.style.display = "none"; return; }
  for (const regel of diff.split("\n")) {
    const div = document.createElement("div");
    if (regel.startsWith("+++") || regel.startsWith("---")) div.className = "hunk";
    else if (regel.startsWith("@@")) div.className = "hunk";
    else if (regel.startsWith("+")) div.className = "add";
    else if (regel.startsWith("-")) div.className = "del";
    div.textContent = regel;
    el.appendChild(div);
  }
  el.style.display = "block";
}

// ---- uploaden van een .html of .zip ----
const tmplDrop = document.getElementById("tmplDrop");
const tmplFile = document.getElementById("tmplFile");

async function uploadTemplateBestand(bestand) {
  if (!bestand) return;
  if (!tenantSel.value) { adminStatus.textContent = "Kies eerst een bedrijf."; return; }
  adminStatus.textContent = `"${bestand.name}" inlezen...`;
  const body = new FormData();
  body.append("file", bestand);
  try {
    const res = await fetch(`/tenants/${tenantSel.value}/templates/upload`, { method: "POST", body });
    const r = await res.json().catch(() => ({}));
    if (!res.ok) {
      meld(adminStatus, "Niet ingelezen: " + (typeof r.detail === "string" ? r.detail : res.status), "fout");
      return;
    }
    document.getElementById("newTmplHtml").value = r.html;
    templateSource = "upload";
    toolproofStyles = null;
    toonCapabilities(r.capabilities);
    toonDiff("");
    const report = document.getElementById("toolproofReport");
    const regels = [];
    if (r.images.length) regels.push(`${r.images.length} afbeeldingen opgeslagen en in de HTML omgezet:`, ...r.images.map(n => "  = " + n), "");
    if (r.notes.length) regels.push("Let op:", ...r.notes.map(n => "  - " + n));
    report.textContent = regels.join("\n").trim();
    report.style.display = regels.length ? "block" : "none";
    if (!document.getElementById("newTmplName").value.trim()) {
      document.getElementById("newTmplName").value = bestand.name.replace(/\.(zip|html?)$/i, "");
    }
    adminStatus.textContent = "Ingelezen. Maak hem tool-proof of sla hem op.";
    renderAdminPreview();
  } catch (e) {
    meld(adminStatus, "Netwerkfout: " + e.message, "fout");
  }
}

tmplDrop.onclick = () => tmplFile.click();
tmplFile.onchange = () => { uploadTemplateBestand(tmplFile.files[0]); tmplFile.value = ""; };
tmplDrop.addEventListener("dragover", (e) => { e.preventDefault(); tmplDrop.classList.add("over"); });
tmplDrop.addEventListener("dragleave", () => tmplDrop.classList.remove("over"));
tmplDrop.addEventListener("drop", (e) => {
  e.preventDefault();
  tmplDrop.classList.remove("over");
  uploadTemplateBestand(e.dataTransfer.files[0]);
});

// ---- bewerken van een bestaande template ----
function startBewerken(t) {
  editingTemplateId = t.id;
  templateSource = "handmatig";
  toolproofStyles = t.styles && Object.keys(t.styles).length ? t.styles : null;
  document.getElementById("newTmplName").value = t.name;
  document.getElementById("newTmplHtml").value = t.html;
  document.getElementById("tmplCreate").textContent = "Wijziging opslaan";
  document.getElementById("tmplCancelEdit").style.display = "";
  toonCapabilities([]);
  toonDiff("");
  adminStatus.textContent = `"${t.name}" wordt bewerkt. De vorige versie blijft bewaard.`;
  document.getElementById("newTmplHtml").scrollIntoView({ behavior: "smooth", block: "center" });
  renderAdminPreview();
}

function stopBewerken() {
  editingTemplateId = null;
  toolproofStyles = null;
  templateSource = "handmatig";
  document.getElementById("newTmplName").value = "";
  document.getElementById("newTmplHtml").value = "";
  document.getElementById("tmplCreate").textContent = "Toevoegen";
  document.getElementById("tmplCancelEdit").style.display = "none";
  toonCapabilities([]);
  toonDiff("");
  document.getElementById("toolproofReport").style.display = "none";
  adminPreviewFrame.srcdoc = "";
}

document.getElementById("tmplCancelEdit").onclick = () => {
  stopBewerken();
  adminStatus.textContent = "Bewerken gestopt.";
};

// ---- versiegeschiedenis ----
async function toggleVersies(t, paneel) {
  if (paneel.dataset.open === "1") {
    paneel.innerHTML = ""; paneel.dataset.open = "0"; return;
  }
  paneel.dataset.open = "1";
  paneel.innerHTML = `<p class="hint">Versies laden...</p>`;
  const res = await fetch(`/tenants/${tenantSel.value}/templates/${t.id}/versions`);
  if (!res.ok) { paneel.innerHTML = `<p class="hint">Kon de versies niet laden.</p>`; return; }
  const versies = await res.json();
  if (!versies.length) { paneel.innerHTML = `<p class="hint">Nog geen eerdere versies.</p>`; return; }
  paneel.innerHTML = "";
  versies.forEach((v, i) => {
    const rij = document.createElement("div");
    rij.className = "v";
    const datum = new Date(v.created_at).toLocaleString("nl-NL", { dateStyle: "short", timeStyle: "short" });
    rij.innerHTML = `<span>${datum}</span><small>${v.source}${v.actor ? " - " + v.actor : ""}</small>`
      + (i === 0 ? `<small style="margin-left:auto;">huidige</small>` : `<span style="margin-left:auto;"></span>`);
    if (i > 0) {
      const knop = document.createElement("button");
      knop.className = "edit";
      knop.textContent = "terugzetten";
      knop.onclick = async () => {
        if (!await bevestig(`Versie van ${datum} terugzetten? De huidige blijft als versie bewaard.`,
          { bevestigTekst: "Versie terugzetten", gevaarlijk: false })) return;
        const r = await fetch(`/tenants/${tenantSel.value}/templates/${t.id}/versions/${v.id}/restore`, { method: "POST" });
        if (!r.ok) {
          const e = await r.json().catch(() => ({}));
          meld(adminStatus, "Terugzetten mislukt: " + (typeof e.detail === "string" ? e.detail : r.status), "fout");
          return;
        }
        meld(adminStatus, "Versie teruggezet.", "ok");
        toast("Versie teruggezet.", "ok");
        loadTemplates();
      };
      rij.appendChild(knop);
    }
    paneel.appendChild(rij);
  });
}


document.getElementById("tmplToolproof").onclick = async () => {
  const html = document.getElementById("newTmplHtml").value.trim();
  const report = document.getElementById("toolproofReport");
  if (!html) { adminStatus.textContent = "Plak eerst de HTML van de template."; return; }
  adminStatus.textContent = "AI zet de template om naar placeholders (kan een minuut duren)...";
  report.style.display = "none";
  const btn = document.getElementById("tmplToolproof");
  btn.disabled = true;
  try {
    const res = await fetch(`/tenants/${tenantSel.value}/templates/toolproof`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ html }) });
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      meld(adminStatus, "Mislukt: " + (typeof e.detail === "string" ? e.detail : res.status), "fout");
      return;
    }
    const r = await res.json();
    document.getElementById("newTmplHtml").value = r.html;
    templateSource = "toolproof";
    toonDiff(r.diff);
    toonCapabilities(r.capabilities);
    toolproofStyles = r.styles && Object.keys(r.styles).length ? r.styles : null;
    if (toolproofStyles) applyStyleInputs(toolproofStyles);
    const lines = [];
    if (toolproofStyles) {
      lines.push("Overgenomen basisstijl (origineel blijft exact gelijk):",
        ...Object.entries(toolproofStyles).map(([k, v]) => "  = " + k + ": " + v), "");
    }
    if (r.applied.length) lines.push("Vervangen (" + r.applied.length + "):", ...r.applied.map(s => "  + " + s), "");
    if (r.failed.length) lines.push("Niet gelukt (handmatig nakijken):", ...r.failed.map(s => "  ! " + s), "");
    if (r.checks_failed.length) lines.push("Verificatie GEFAALD:", ...r.checks_failed.map(s => "  X " + s), "");
    if (r.checks_passed.length) lines.push("Geverifieerd in code (" + r.checks_passed.length + " checks): alle placeholders stromen door.", "");
    if (r.warnings.length) lines.push("Aandachtspunten:", ...r.warnings.map(s => "  - " + s), "");
    if (r.notes.length) lines.push("Opmerkingen van de AI:", ...r.notes.map(s => "  - " + s));
    report.textContent = lines.join("\n").trim();
    report.style.display = "block";
    adminStatus.textContent = r.checks_failed.length
      ? "Omgezet, maar de verificatie faalde op onderdelen. Bekijk het rapport voordat je opslaat."
      : (r.failed.length
        ? "Omgezet, alle verificatie-checks geslaagd. Enkele voorgestelde vervangingen matchten niet (vaak dubbel voorgesteld), zie rapport."
        : "Tool-proof gemaakt en geverifieerd. Bekijk het voorbeeld en klik Toevoegen om op te slaan.");
    renderAdminPreview();
  } catch (e) {
    meld(adminStatus, "Netwerkfout: " + e.message, "fout");
  } finally {
    btn.disabled = false;
  }
};

document.getElementById("tmplValidate").onclick = async () => {
  const html = document.getElementById("newTmplHtml").value;
  const res = await fetch(`/tenants/${tenantSel.value}/templates/validate`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ html }) });
  const v = await res.json();
  adminStatus.textContent = v.ok
    ? (v.warnings.length ? "OK, maar let op: " + v.warnings.join("; ") : "OK, geen problemen.")
    : "Fout: " + v.errors.join("; ");
};

document.getElementById("tmplCreate").onclick = async () => {
  const name = document.getElementById("newTmplName").value.trim();
  const html = document.getElementById("newTmplHtml").value;
  if (!name || !html) { adminStatus.textContent = "Geef een naam en HTML op."; return; }
  const bewerken = editingTemplateId !== null;
  const url = bewerken
    ? `/tenants/${tenantSel.value}/templates/${editingTemplateId}`
    : `/tenants/${tenantSel.value}/templates`;
  const res = await fetch(url, {
    method: bewerken ? "PUT" : "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, html, styles: toolproofStyles || {}, source: templateSource }) });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    const detail = typeof e.detail === "string" ? e.detail : String(res.status);
    meld(adminStatus, "Niet opgeslagen: de template is ongeldig. Zie het rapport.", "fout");
    toast("Template niet opgeslagen: hij is ongeldig.", "fout");
    const report = document.getElementById("toolproofReport");
    const punten = detail.replace(/^template is ongeldig:\s*/i, "").split("; ");
    report.textContent = ["Deze template is niet opgeslagen omdat hij niet geldig is:",
      ...punten.map(p => "  X " + p), "",
      "Maak de template opnieuw tool-proof of plak hem opnieuw, en sla dan pas op."].join("\n");
    report.style.display = "block";
    return;
  }
  const gelukt = bewerken ? "Wijziging opgeslagen; de vorige versie is bewaard." : "Template toegevoegd.";
  meld(adminStatus, gelukt, "ok");
  toast(gelukt, "ok");
  stopBewerken();
  loadTemplates();
};
