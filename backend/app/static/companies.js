// Bedrijven beheren (alleen Dunion): gegevens, sleutels, klant-accounts.

// ---- bedrijven (alleen admin) ----
let editingCompanyId = null;
const CO = (id) => document.getElementById(id);
const companyStatus = document.getElementById("companyStatus");

function slugify(s) {
  return s.toLowerCase().trim().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "");
}
CO("coName").addEventListener("input", () => {
  if (!editingCompanyId) CO("coSlug").value = slugify(CO("coName").value);
});

function addCtRow(vals = {}) {
  const row = document.createElement("div");
  row.className = "ct-row";
  row.innerHTML = `<input type="text" class="ct-name" placeholder="Naam (bv. Cases)">`
    + `<input type="text" class="ct-button" placeholder="Knoptekst (bv. Lees de case)">`
    + `<input type="text" class="ct-source" placeholder="Bron-URL op de site (optioneel)">`
    + `<label class="hint" style="white-space:nowrap;"><input type="checkbox" class="ct-price"> prijs</label>`
    + `<button class="del">weg</button>`;
  row.querySelector(".ct-name").value = vals.name || "";
  row.querySelector(".ct-button").value = vals.button_text || "";
  row.querySelector(".ct-source").value = vals.source_url || "";
  row.querySelector(".ct-price").checked = !!vals.has_price;
  row.querySelector(".del").onclick = (e) => { e.preventDefault(); row.remove(); };
  document.getElementById("ctRows").appendChild(row);
}
document.getElementById("ctAdd").onclick = (e) => { e.preventDefault(); addCtRow(); };

function updateMatchesUrlRow() {
  const voetbal = CO("ctMatches").checked || CO("ctClubs").checked || CO("ctReizen").checked;
  const hasUrl = CO("coMatches").value.trim() !== "";
  document.getElementById("ctMatchesUrlRow").style.display = (voetbal || hasUrl) ? "flex" : "none";
}
for (const id of ["ctMatches", "ctClubs", "ctReizen"]) {
  CO(id).addEventListener("change", updateMatchesUrlRow);
}

function readContentTypes() {
  const types = [];
  if (CO("ctMatches").checked) types.push({ kind: "matches" });
  if (CO("ctClubs").checked) types.push({ kind: "clubs" });
  if (CO("ctReizen").checked) types.push({ kind: "reizen" });
  for (const row of document.querySelectorAll("#ctRows .ct-row")) {
    const name = row.querySelector(".ct-name").value.trim();
    if (!name) continue;
    const t = { kind: "items", name, button_text: row.querySelector(".ct-button").value.trim() || "Lees meer" };
    const src = row.querySelector(".ct-source").value.trim();
    if (src) t.source_url = src;
    if (row.querySelector(".ct-price").checked) t.has_price = true;
    types.push(t);
  }
  return types;
}

const ESP_HINTS = {
  brevo: "Brevo: API-key begint met 'xkeysib-'. Lijst-ID = het nummer van de contactenlijst waar de campagne aan gericht wordt (Brevo -> Contacts -> Lists, het nummer achter de lijstnaam). Optioneel: zonder lijst maakt Brevo het concept ook aan.",
  klaviyo: "Klaviyo: private key (pk_...) met scopes campaigns:write, templates:write en lists:read. Lijst-ID = het ID van de lijst/segment waar de campagne aan gericht wordt (Klaviyo -> Audience -> Lists & Segments -> klik de lijst, het ID staat in de URL). VERPLICHT: zonder audience weigert Klaviyo een concept.",
  activecampaign: "ActiveCampaign: API-key en API-URL staan allebei in ActiveCampaign onder Settings -> Developer. De API-URL is per account (https://account.api-us1.com). Lijst-ID = het nummer van de contactenlijst (of kies hieronder). VERPLICHT: zonder lijst weigert ActiveCampaign een concept.",
};
function updateEspHint() {
  const esp = CO("coEsp").value;
  document.getElementById("espHint").textContent = ESP_HINTS[esp] || "";
  document.getElementById("coAcUrlWrap").style.display = esp === "activecampaign" ? "" : "none";
}
CO("coEsp").addEventListener("change", updateEspHint);
updateEspHint();

document.getElementById("coTenantPwBtn").onclick = async (e) => {
  e.preventDefault();
  const status = document.getElementById("coTenantPwStatus");
  const pw = document.getElementById("coTenantPw").value;
  if (!editingCompanyId) { status.textContent = "Sla het bedrijf eerst op."; return; }
  if (pw.length < 8) { status.textContent = "Wachtwoord moet minimaal 8 tekens zijn."; return; }
  const r = await fetch(`/tenants/${editingCompanyId}/password`, {
    method: "POST", headers: {"Content-Type": "application/json"},
    body: JSON.stringify({password: pw}),
  });
  status.textContent = r.ok
    ? "Wachtwoord ingesteld. Gebruikersnaam voor de klant: de bedrijfscode."
    : "Instellen mislukt: " + ((await r.json().catch(() => ({}))).detail || r.status);
  if (r.ok) document.getElementById("coTenantPw").value = "";
};

async function loadTenantUsers() {
  const list = document.getElementById("coUserList");
  list.innerHTML = "";
  if (!editingCompanyId) return;
  let users = [];
  try { users = await (await fetch(`/tenants/${editingCompanyId}/users`)).json(); }
  catch (e) { return; }
  if (!Array.isArray(users)) return;
  for (const u of users) {
    const el = document.createElement("div");
    el.className = "company-item";
    const mail = document.createElement("span");
    mail.textContent = u.email;
    const spacer = document.createElement("span");
    spacer.style.marginLeft = "auto";
    const del = document.createElement("button");
    del.className = "del";
    del.textContent = "verwijderen";
    del.onclick = async (e) => {
      e.preventDefault();
      if (!await bevestig(`Account ${u.email} verwijderen? Deze gebruiker kan dan niet meer inloggen.`,
          { bevestigTekst: "Account verwijderen" })) return;
      await fetch(`/tenants/${editingCompanyId}/users/${u.id}`, { method: "DELETE" });
      loadTenantUsers();
    };
    el.append(mail, spacer, del);
    list.appendChild(el);
  }
}

function clearInviteLink() {
  const field = document.getElementById("coUserLink");
  field.value = "";
  field.type = "password";
  document.getElementById("coUserLinkToggle").textContent = "Toon";
  document.getElementById("coUserLinkRow").style.display = "none";
}

document.getElementById("coUserLinkToggle").onclick = (e) => {
  e.preventDefault();
  const field = document.getElementById("coUserLink");
  const masked = field.type === "password";
  field.type = masked ? "text" : "password";
  e.target.textContent = masked ? "Verberg" : "Toon";
};

document.getElementById("coUserLinkBtn").onclick = async (e) => {
  e.preventDefault();
  const status = document.getElementById("coUserStatus");
  const email = document.getElementById("coUserEmail").value.trim();
  if (!editingCompanyId) { status.textContent = "Sla het bedrijf eerst op, en bewerk het daarna om accounts uit te nodigen."; return; }
  if (!/.+@.+\..+/.test(email)) { status.textContent = "Vul een geldig e-mailadres in."; return; }
  const btn = document.getElementById("coUserLinkBtn");
  btn.disabled = true;
  clearInviteLink();
  status.textContent = "Link maken...";
  try {
    const r = await fetch(`/tenants/${editingCompanyId}/users/link`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({email}),
    });
    if (r.ok) {
      const data = await r.json();
      document.getElementById("coUserLink").value = data.invite_link;
      document.getElementById("coUserLinkRow").style.display = "flex";
      status.textContent = `Link voor ${email} klaar. Deel hem alleen met de klant zelf: wie de link heeft kan het account overnemen. Hij wordt maar 1 keer getoond.`;
      document.getElementById("coUserEmail").value = "";
      loadTenantUsers();
    } else {
      status.textContent = "Link maken mislukt: " + ((await r.json().catch(() => ({}))).detail || r.status);
    }
  } catch (err) {
    status.textContent = "Netwerkfout: " + err.message;
  } finally {
    btn.disabled = false;
  }
};

document.getElementById("coUserLinkCopy").onclick = async (e) => {
  e.preventDefault();
  const field = document.getElementById("coUserLink");
  try {
    await navigator.clipboard.writeText(field.value);
    document.getElementById("coUserStatus").textContent = "Link gekopieerd.";
  } catch (err) {
    field.select();
    document.getElementById("coUserStatus").textContent = "Kopieren geblokkeerd door de browser; de link is geselecteerd, kopieer met Cmd+C.";
  }
};

document.getElementById("coUserInviteBtn").onclick = async (e) => {
  e.preventDefault();
  const status = document.getElementById("coUserStatus");
  const email = document.getElementById("coUserEmail").value.trim();
  if (!editingCompanyId) { status.textContent = "Sla het bedrijf eerst op, en bewerk het daarna om accounts uit te nodigen."; return; }
  if (!/.+@.+\..+/.test(email)) { status.textContent = "Vul een geldig e-mailadres in."; return; }
  const btn = document.getElementById("coUserInviteBtn");
  btn.disabled = true;
  clearInviteLink();
  status.textContent = "Uitnodiging versturen...";
  try {
    const r = await fetch(`/tenants/${editingCompanyId}/users`, {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({email}),
    });
    if (r.ok) {
      status.textContent = `Uitnodiging verstuurd naar ${email}. De klant kiest via de mail een wachtwoord.`;
      document.getElementById("coUserEmail").value = "";
      loadTenantUsers();
    } else {
      status.textContent = "Uitnodigen mislukt: " + ((await r.json().catch(() => ({}))).detail || r.status);
    }
  } catch (err) {
    status.textContent = "Netwerkfout: " + err.message;
  } finally {
    btn.disabled = false;
  }
};

document.getElementById("espListsBtn").onclick = async (e) => {
  e.preventDefault();
  const esp = CO("coEsp").value;
  const body = { esp };
  if (esp === "activecampaign") body.api_url = CO("coAcUrl").value.trim();
  const key = CO("coBrevoKey").value.trim();
  if (key) body.api_key = key;
  else if (editingCompanyId) body.tenant_id = editingCompanyId;
  else { companyStatus.textContent = "Plak eerst de API-key (of bewerk een bedrijf met opgeslagen key)."; return; }
  const btn = document.getElementById("espListsBtn");
  btn.disabled = true;
  companyStatus.textContent = "Lijsten ophalen bij " + ({klaviyo: "Klaviyo", activecampaign: "ActiveCampaign"}[esp] || "Brevo") + "...";
  try {
    const res = await fetch("/tenants/esp-lists", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      companyStatus.textContent = "Mislukt: " + (typeof err.detail === "string" ? err.detail : res.status);
      return;
    }
    const { lists } = await res.json();
    const sel = document.getElementById("espListsSelect");
    sel.innerHTML = "";
    if (!lists.length) { sel.style.display = "none"; companyStatus.textContent = "Geen lijsten gevonden in dit account."; return; }
    const ph = document.createElement("option");
    ph.value = ""; ph.textContent = `Kies een lijst (${lists.length} gevonden)`;
    sel.appendChild(ph);
    for (const l of lists) {
      const o = document.createElement("option");
      o.value = l.id; o.textContent = `${l.name} (${l.id})`;
      sel.appendChild(o);
    }
    sel.style.display = "inline-block";
    companyStatus.textContent = "Kies de lijst; het ID wordt automatisch ingevuld.";
  } catch (err) {
    companyStatus.textContent = "Netwerkfout: " + err.message;
  } finally {
    btn.disabled = false;
  }
};
document.getElementById("espListsSelect").addEventListener("change", (e) => {
  if (e.target.value) {
    CO("coBrevoList").value = e.target.value;
    companyStatus.textContent = "Lijst-ID ingevuld.";
  }
});

function companyConfigFromForm() {
  const website = CO("coWebsite").value.trim();
  const social = (id) => CO(id).value.trim() || website;
  const cfg = {
    brand_name: CO("coName").value.trim(),
    brand_email: CO("coEmail").value.trim(),
    brand_adres: CO("coAdres").value.trim(),
    brand_postcode_stad: CO("coPostcode").value.trim(),
    brand_telefoon: CO("coTelefoon").value.trim(),
    brand_kvk: CO("coKvk").value.trim(),
    website_url: website,
    primary_color: CO("coPrimary").value,
    logo_url: CO("coLogo").value.trim(),
    dummy_image_url: CO("coDummy").value.trim(),
    facebook_url: social("coFacebook"),
    instagram_url: social("coInstagram"),
    youtube_url: social("coYoutube"),
    content_types: readContentTypes(),
    esp: CO("coEsp").value,
  };
  if (cfg.esp === "klaviyo") cfg.klaviyo_list_id = CO("coBrevoList").value.trim();
  if (cfg.esp === "activecampaign") {
    cfg.activecampaign_list_id = CO("coBrevoList").value.trim();
    cfg.activecampaign_api_url = CO("coAcUrl").value.trim();
  }
  const matchesUrl = CO("coMatches").value.trim();
  if (matchesUrl) cfg.matches_url = matchesUrl;
  return cfg;
}

function toColorInput(hex) {
  if (!hex) return null;
  hex = hex.toLowerCase().trim();
  if (/^#[0-9a-f]{3}$/.test(hex)) hex = "#" + [...hex.slice(1)].map(c => c + c).join("");
  return /^#[0-9a-f]{6}/.test(hex) ? hex.slice(0, 7) : null;
}

document.getElementById("coPrefill").onclick = async (e) => {
  e.preventDefault();
  const name = CO("coName").value.trim();
  const website = CO("coWebsite").value.trim();
  if (!name || !website) { companyStatus.textContent = "Vul eerst bedrijfsnaam en website in."; return; }
  const btn = document.getElementById("coPrefill");
  btn.disabled = true;
  companyStatus.textContent = "Website scannen en gegevens invullen (kan een halve minuut duren)...";
  try {
    const res = await fetch("/tenants/prefill", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, website_url: website }),
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      companyStatus.textContent = "Mislukt: " + (typeof err.detail === "string" ? err.detail : res.status);
      return;
    }
    const r = await res.json();
    const c = r.config || {};
    CO("coWebsite").value = c.website_url || website;
    CO("coEmail").value = c.brand_email || "";
    CO("coAdres").value = c.brand_adres || "";
    CO("coPostcode").value = c.brand_postcode_stad || "";
    CO("coTelefoon").value = c.brand_telefoon || "";
    CO("coKvk").value = c.brand_kvk || "";
    CO("coLogo").value = c.logo_url || "";
    CO("coDummy").value = c.dummy_image_url || "";
    CO("coMatches").value = c.matches_url || "";
    CO("coFacebook").value = c.facebook_url || "";
    CO("coInstagram").value = c.instagram_url || "";
    CO("coYoutube").value = c.youtube_url || "";
    const color = toColorInput(c.primary_color);
    if (color) CO("coPrimary").value = color;
    document.getElementById("ctRows").innerHTML = "";
    for (const ct of r.content_types || []) addCtRow(ct);
    companyStatus.textContent = (r.notes && r.notes.length)
      ? "Ingevuld. Nog even checken: " + r.notes.join("; ")
      : "Ingevuld vanaf de website. Controleer de velden en klik op Bedrijf opslaan.";
    updateMatchesUrlRow();
    for (const id of ["secContact", "secBeeld", "secSoorten"]) document.getElementById(id).open = true;
  } catch (err) {
    companyStatus.textContent = "Netwerkfout: " + err.message;
  } finally {
    btn.disabled = false;
  }
};

function resetCompanyForm() {
  editingCompanyId = null;
  for (const id of ["coName","coSlug","coWebsite","coEmail","coAdres","coPostcode","coTelefoon","coKvk","coLogo","coDummy","coMatches","coFacebook","coInstagram","coYoutube","coBrevoKey","coBrevoList","coAcUrl"]) CO(id).value = "";
  CO("coPrimary").value = "#ff7200";
  CO("ctMatches").checked = false; CO("ctClubs").checked = false; CO("ctReizen").checked = false;
  CO("coEsp").value = "brevo"; updateEspHint();
  const espSel = document.getElementById("espListsSelect");
  espSel.innerHTML = ""; espSel.style.display = "none";
  CO("coSlug").disabled = false;
  document.getElementById("ctRows").innerHTML = "";
  document.getElementById("coUserList").innerHTML = "";
  document.getElementById("coUserEmail").value = "";
  document.getElementById("coUserStatus").textContent = "";
  clearInviteLink();
  document.getElementById("companyFormTitle").textContent = "Nieuw bedrijf toevoegen";
  document.getElementById("companyReset").style.display = "none";
  companyStatus.textContent = "";
  updateMatchesUrlRow();
  for (const el of document.querySelectorAll("details.co-sec")) el.open = false;
}
document.getElementById("companyReset").onclick = resetCompanyForm;

function fillCompanyForm(t) {
  resetCompanyForm();
  editingCompanyId = t.id;
  const c = t.config || {};
  CO("coName").value = t.name || "";
  CO("coSlug").value = t.slug || ""; CO("coSlug").disabled = true;
  CO("coWebsite").value = c.website_url || "";
  CO("coPrimary").value = (c.primary_color || "#ff7200").toLowerCase();
  CO("coEmail").value = c.brand_email || ""; CO("coAdres").value = c.brand_adres || "";
  CO("coPostcode").value = c.brand_postcode_stad || ""; CO("coTelefoon").value = c.brand_telefoon || "";
  CO("coKvk").value = c.brand_kvk || ""; CO("coLogo").value = c.logo_url || "";
  CO("coDummy").value = c.dummy_image_url || "";
  CO("coMatches").value = c.matches_url || "";
  CO("coFacebook").value = c.facebook_url || ""; CO("coInstagram").value = c.instagram_url || "";
  CO("coYoutube").value = c.youtube_url || "";
  CO("coEsp").value = c.esp || "brevo";
  updateEspHint();
  CO("coBrevoList").value = (c.esp === "klaviyo" ? c.klaviyo_list_id
    : c.esp === "activecampaign" ? c.activecampaign_list_id : t.brevo_list_id) ?? "";
  CO("coAcUrl").value = c.activecampaign_api_url || "";
  for (const ct of c.content_types || []) {
    if (ct.kind === "matches") CO("ctMatches").checked = true;
    else if (ct.kind === "clubs") CO("ctClubs").checked = true;
    else if (ct.kind === "reizen") CO("ctReizen").checked = true;
    else addCtRow(ct);
  }
  updateMatchesUrlRow();
  document.getElementById("companyFormTitle").textContent = `Bewerken: ${t.name}`;
  document.getElementById("companyReset").style.display = "inline-block";
  loadTenantUsers();
}

async function refreshTenantSelect() {
  const cur = tenantSel.value;
  try {
    const tenants = await (await fetch("/tenants")).json();
    tenantSel.innerHTML = "";
    for (const t of tenants) tenantSel.appendChild(tenantOptie(t));
    if ([...tenantSel.options].some(o => o.value === cur)) tenantSel.value = cur;
  } catch (e) { /* dropdown blijft zoals hij was */ }
}

async function loadCompanies() {
  const list = document.getElementById("companyList");
  let tenants = [];
  try { tenants = await (await fetch("/tenants")).json(); }
  catch (e) { list.innerHTML = '<p class="hint">Kon bedrijven niet laden.</p>'; return; }
  list.innerHTML = tenants.length ? "" : '<p class="hint">Nog geen bedrijven.</p>';
  for (const t of tenants) {
    const el = document.createElement("div");
    el.className = "company-item";
    el.innerHTML = `<strong>${t.name}</strong><span class="hint">${t.slug}</span>`
      + `<span class="tmpl-health hint">template controleren...</span>`
      + `<span style="margin-left:auto;"></span>`
      + `<button class="edit">bewerken</button><button class="del">verwijderen</button>`;
    el.querySelector(".edit").onclick = () => fillCompanyForm(t);
    toonTemplateGezondheid(t.id, el.querySelector(".tmpl-health"));
    el.querySelector(".del").onclick = async () => {
      if (!await bevestig(`Bedrijf "${t.name}" en alle bijbehorende data verwijderen? Dit kan niet ongedaan worden gemaakt.`,
        { bevestigTekst: "Bedrijf verwijderen" })) return;
      await fetch(`/tenants/${t.id}`, { method: "DELETE" });
      loadCompanies(); refreshTenantSelect();
    };
    list.appendChild(el);
  }
}

// Heeft dit bedrijf een bruikbare eigen template? Zonder valt de nieuwsbrief
// terug op de neutrale standaard, en dat zie je nu meteen in de lijst.
async function toonTemplateGezondheid(tenantId, el) {
  try {
    const res = await fetch(`/tenants/${tenantId}/templates/health`);
    if (!res.ok) { el.textContent = ""; return; }
    const h = await res.json();
    if (h.ok) {
      el.textContent = "template in orde";
      el.style.color = "#2e9e5b";
    } else {
      const redenen = [h.reden, ...(h.opslag_fouten || [])].filter(Boolean);
      if ((h.ontbrekende_brand_velden || []).length) {
        redenen.push(`bedrijfsgegevens ontbreken: ${h.ontbrekende_brand_velden.join(", ")}`);
      }
      el.textContent = redenen[0] || "template nakijken";
      el.style.color = "var(--danger)";
      el.title = redenen.join("; ") || "Controleer de template van dit bedrijf.";
    }
  } catch (e) { el.textContent = ""; }
}

document.getElementById("companySave").onclick = async () => {
  const required = { coName: "bedrijfsnaam", coSlug: "slug", coWebsite: "website", coEmail: "e-mail", coLogo: "logo-URL", coDummy: "fallback-foto-URL" };
  const missing = Object.entries(required).filter(([id]) => !CO(id).value.trim()).map(([, n]) => n);
  if (missing.length) { companyStatus.textContent = "Vul eerst in: " + missing.join(", "); return; }

  const esp = CO("coEsp").value;
  const listRaw = CO("coBrevoList").value.trim();
  if (esp === "klaviyo" && !listRaw) {
    companyStatus.textContent = "Klaviyo vereist een lijst-ID (list- of segment-id).";
    return;
  }
  if (esp === "activecampaign") {
    const acUrl = CO("coAcUrl").value.trim();
    if (!listRaw || !acUrl) {
      companyStatus.textContent = "ActiveCampaign vereist een API-URL en een lijst-ID.";
      return;
    }
    if (!/^https:\/\//.test(acUrl)) {
      companyStatus.textContent = "De ActiveCampaign API-URL moet met https:// beginnen (bv. https://account.api-us1.com).";
      return;
    }
  }
  companyStatus.textContent = "Opslaan...";
  const formConfig = companyConfigFromForm();
  const listId = esp === "brevo" && listRaw ? parseInt(listRaw, 10) : null;
  let tenantId = editingCompanyId;
  let res;
  if (editingCompanyId) {
    // Config mergen zodat tone of voice, stijlen en fotocategorieën behouden blijven.
    const current = await (await fetch(`/tenants/${editingCompanyId}`)).json();
    res = await fetch(`/tenants/${editingCompanyId}`, {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: CO("coName").value.trim(), brevo_list_id: listId, config: { ...(current.config || {}), ...formConfig } }),
    });
  } else {
    res = await fetch("/tenants", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug: CO("coSlug").value.trim(), name: CO("coName").value.trim(), brevo_list_id: listId, config: formConfig }),
    });
  }
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    companyStatus.textContent = "Fout: " + (typeof e.detail === "string" ? e.detail : res.status);
    return;
  }
  const saved = await res.json();
  tenantId = saved.id;
  const espKey = CO("coBrevoKey").value.trim();
  if (espKey) {
    const kind = {klaviyo: "klaviyo_api_key", activecampaign: "activecampaign_api_key"}[esp] || "brevo_api_key";
    const sres = await fetch(`/tenants/${tenantId}/secrets`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ kind, value: espKey }),
    });
    if (!sres.ok) { companyStatus.textContent = "Bedrijf opgeslagen, maar de API-key zetten mislukte."; loadCompanies(); refreshTenantSelect(); return; }
  }
  const wasEditing = !!editingCompanyId;
  resetCompanyForm();
  const uitkomst = wasEditing ? "Bedrijf bijgewerkt." : "Bedrijf toegevoegd.";
  meld(companyStatus, uitkomst, "ok");
  toast(uitkomst, "ok");
  loadCompanies();
  refreshTenantSelect();
};
