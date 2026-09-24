// Moderne keuzelijst bovenop een gewone <select>.
//
// De <select> blijft (onzichtbaar) de bron van waarheid: alle bestaande code
// leest tenantSel.value, vult de opties en luistert naar "change". Deze laag
// tekent alleen een mooiere knop met zoekbare lijst, en schrijft een keuze
// terug in de select met een echt change-event. Opties kunnen extra gegevens
// meegeven via data-attributen: data-color, data-logo, data-sub, data-badge.

function initialen(naam) {
  const woorden = String(naam || "?").trim().split(/\s+/).filter(Boolean);
  const letters = woorden.length > 1 ? woorden[0][0] + woorden[1][0] : (woorden[0] || "?").slice(0, 2);
  return letters.toUpperCase();
}

function avatar(optie, variant) {
  const el = document.createElement("span");
  el.className = "pk-avatar" + (variant ? " " + variant : "");
  if (variant === "icon") {
    el.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>';
    return el;
  }
  const kleur = optie && optie.dataset.color;
  if (kleur && /^#[0-9a-f]{3,8}$/i.test(kleur)) el.style.background = kleur;
  el.textContent = initialen(optie ? optie.textContent : "?");
  const logo = optie && optie.dataset.logo;
  if (logo && /^https:\/\//.test(logo)) {
    const img = document.createElement("img");
    img.alt = "";
    img.src = logo;
    img.onload = () => { el.textContent = ""; el.classList.add("has-logo"); el.appendChild(img); };
  }
  return el;
}

function enhanceSelect(select, { label, variant, placeholder, searchFrom = 6 }) {
  const wrap = document.createElement("div");
  wrap.className = "pk";
  const knop = document.createElement("button");
  knop.type = "button";
  knop.className = "pk-btn";
  knop.setAttribute("aria-haspopup", "listbox");
  knop.setAttribute("aria-expanded", "false");
  knop.setAttribute("aria-label", label);
  const paneel = document.createElement("div");
  paneel.className = "pk-pop";
  paneel.hidden = true;
  const zoek = document.createElement("input");
  zoek.type = "search";
  zoek.className = "pk-search";
  zoek.placeholder = "Zoeken...";
  const lijst = document.createElement("div");
  lijst.className = "pk-list";
  lijst.setAttribute("role", "listbox");
  paneel.append(zoek, lijst);
  wrap.append(knop, paneel);
  select.classList.add("pk-native");
  select.tabIndex = -1;
  select.after(wrap);

  let actief = -1;  // toetsenbord-positie in de gefilterde lijst

  function gekozen() { return select.options[select.selectedIndex] || null; }

  function tekenKnop() {
    const optie = gekozen();
    knop.innerHTML = "";
    knop.appendChild(avatar(optie, variant));
    const tekst = document.createElement("span");
    tekst.className = "pk-text";
    const klein = document.createElement("span");
    klein.className = "pk-label";
    klein.textContent = label;
    const naam = document.createElement("span");
    naam.className = "pk-name";
    naam.textContent = optie ? optie.textContent : placeholder;
    tekst.append(klein, naam);
    knop.appendChild(tekst);
    if (optie && optie.dataset.badge) {
      const badge = document.createElement("span");
      badge.className = "pk-badge";
      badge.textContent = optie.dataset.badge;
      knop.appendChild(badge);
    }
    const pijl = document.createElement("span");
    pijl.className = "pk-chevron";
    pijl.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="m6 9 6 6 6-6"/></svg>';
    knop.appendChild(pijl);
    knop.disabled = select.options.length === 0 || (select.options.length === 1 && !select.options[0].value);
  }

  function zichtbareOpties() {
    const term = zoek.value.trim().toLowerCase();
    return [...select.options].filter(o => o.value && (!term || o.textContent.toLowerCase().includes(term)
      || (o.dataset.sub || "").toLowerCase().includes(term)));
  }

  function tekenLijst() {
    lijst.innerHTML = "";
    const opties = zichtbareOpties();
    if (!opties.length) {
      const leeg = document.createElement("div");
      leeg.className = "pk-empty";
      leeg.textContent = "Niets gevonden";
      lijst.appendChild(leeg);
      return;
    }
    opties.forEach((o, i) => {
      const regel = document.createElement("div");
      regel.className = "pk-opt" + (i === actief ? " kb" : "");
      regel.setAttribute("role", "option");
      regel.setAttribute("aria-selected", String(o.value === select.value));
      regel.appendChild(avatar(o, variant));
      const tekst = document.createElement("span");
      tekst.className = "pk-text";
      const naam = document.createElement("span");
      naam.className = "pk-name";
      naam.textContent = o.textContent;
      tekst.appendChild(naam);
      if (o.dataset.sub) {
        const sub = document.createElement("span");
        sub.className = "pk-sub";
        sub.textContent = o.dataset.sub;
        tekst.appendChild(sub);
      }
      regel.appendChild(tekst);
      if (o.dataset.badge) {
        const badge = document.createElement("span");
        badge.className = "pk-badge";
        badge.textContent = o.dataset.badge;
        regel.appendChild(badge);
      }
      if (o.value === select.value) {
        const vink = document.createElement("span");
        vink.className = "pk-check";
        vink.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';
        regel.appendChild(vink);
      }
      regel.onmousedown = (e) => e.preventDefault();  // focus in het zoekveld houden
      regel.onclick = () => kies(o.value);
      lijst.appendChild(regel);
    });
    const kb = lijst.querySelector(".kb");
    if (kb) kb.scrollIntoView({ block: "nearest" });
  }

  function kies(waarde) {
    sluit();
    if (waarde === select.value) return;
    select.value = waarde;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function open() {
    document.querySelectorAll(".pk.open").forEach(p => p !== wrap && p.dispatchEvent(new Event("pk-close")));
    wrap.classList.add("open");
    paneel.hidden = false;
    knop.setAttribute("aria-expanded", "true");
    zoek.value = "";
    zoek.style.display = select.options.length >= searchFrom ? "" : "none";
    actief = zichtbareOpties().findIndex(o => o.value === select.value);
    tekenLijst();
    (zoek.style.display === "none" ? lijst : zoek).focus({ preventScroll: true });
  }

  function sluit() {
    wrap.classList.remove("open");
    paneel.hidden = true;
    knop.setAttribute("aria-expanded", "false");
  }

  knop.onclick = () => (wrap.classList.contains("open") ? sluit() : open());
  wrap.addEventListener("pk-close", sluit);
  zoek.oninput = () => { actief = 0; tekenLijst(); };
  lijst.tabIndex = -1;
  paneel.addEventListener("keydown", (e) => {
    const opties = zichtbareOpties();
    if (e.key === "ArrowDown") { e.preventDefault(); actief = Math.min(opties.length - 1, actief + 1); tekenLijst(); }
    else if (e.key === "ArrowUp") { e.preventDefault(); actief = Math.max(0, actief - 1); tekenLijst(); }
    else if (e.key === "Enter") { e.preventDefault(); if (opties[actief]) kies(opties[actief].value); }
    else if (e.key === "Escape") { e.preventDefault(); sluit(); knop.focus(); }
  });
  document.addEventListener("mousedown", (e) => { if (!wrap.contains(e.target)) sluit(); });

  // Opties worden later gevuld of vervangen (klanten, templates per klant).
  new MutationObserver(() => { tekenKnop(); if (!paneel.hidden) tekenLijst(); })
    .observe(select, { childList: true, subtree: true, attributes: true });
  select.addEventListener("change", tekenKnop);
  // Code zet soms direct select.value = ...; zonder event. Ook dan bijwerken.
  const eigen = Object.getOwnPropertyDescriptor(HTMLSelectElement.prototype, "value");
  Object.defineProperty(select, "value", {
    get() { return eigen.get.call(this); },
    set(v) { eigen.set.call(this, v); tekenKnop(); },
  });
  tekenKnop();
}

// Opties voor een klant: naam plus merkkleur, logo en verzendplatform.
const ESP_NAMEN = { brevo: "Brevo", klaviyo: "Klaviyo", activecampaign: "ActiveCampaign" };
function tenantOptie(t) {
  const o = document.createElement("option");
  o.value = t.id;
  o.textContent = t.name;
  const c = t.config || {};
  if (c.primary_color) o.dataset.color = c.primary_color;
  if (c.logo_url) o.dataset.logo = c.logo_url;
  o.dataset.sub = ESP_NAMEN[c.esp || "brevo"] || c.esp || "";
  return o;
}

enhanceSelect(tenantSel, { label: "Klant", placeholder: "Kies een klant" });
enhanceSelect(chatTemplate, { label: "Template", variant: "icon", placeholder: "Geen template", searchFrom: 8 });
