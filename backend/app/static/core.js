// Gedeelde stand en navigatie: klantkeuze, tabbladen, rolbepaling.

const tenantSel = document.getElementById("tenant");
const chatTemplate = document.getElementById("chatTemplate");
let conversationId = null;

async function loadChatTemplates() {
  const tid = tenantSel.value;
  if (!tid) return;
  let list = [];
  try { list = await (await fetch(`/tenants/${tid}/templates`)).json(); } catch (e) { list = []; }
  chatTemplate.innerHTML = "";
  if (!list.length) {
    const o = document.createElement("option"); o.value = ""; o.textContent = "(nog geen eigen template)"; chatTemplate.appendChild(o);
    return;
  }
  for (const t of list) {
    const o = document.createElement("option");
    o.value = t.id; o.textContent = "Template: " + t.name + (t.is_default ? " (standaard)" : "");
    chatTemplate.appendChild(o);
  }
  const def = list.find(t => t.is_default) || list[0];
  if (def) chatTemplate.value = def.id;
}

// ---- view switching ----
const views = {
  chat: document.getElementById("chatView"),
  images: document.getElementById("imagesView"),
  newsletters: document.getElementById("newslettersView"),
  templates: document.getElementById("templatesView"),
  companies: document.getElementById("companiesView"),
};
const navButtons = {
  chat: document.getElementById("navChat"),
  images: document.getElementById("navImages"),
  newsletters: document.getElementById("navNewsletters"),
  templates: document.getElementById("navTemplates"),
  companies: document.getElementById("navCompanies"),
};
const chatFooter = document.getElementById("chatFooter");
function showView(name) {
  for (const k in views) views[k].classList.toggle("active", k === name);
  for (const k in navButtons) navButtons[k].classList.toggle("active", k === name);
  chatFooter.style.display = name === "chat" ? "block" : "none";
  if (name === "images") loadCategories();
  if (name === "newsletters") laadNieuwsbrieven();
  if (name === "templates") { loadTemplates(); loadTone(); }
  if (name === "companies") { loadCompanies(); loadUsage(); }
}
for (const k in navButtons) navButtons[k].onclick = () => showView(k);


// ---- meldingen ----
// Terugkoppeling was één grijze regel die steeds werd overschreven: een fout en
// een gelukte opslag zagen er identiek uit. Nu krijgt elke melding een kleur, en
// belangrijke uitkomsten ook een toast, omdat je vaak naar het voorbeeld kijkt
// in plaats van naar het statusregeltje.
function meld(el, tekst, soort = "info") {
  if (!el) return;
  el.textContent = tekst;
  el.classList.remove("ok", "fout");
  if (soort === "ok" || soort === "fout") el.classList.add(soort);
}

let toastVak = null;
function toast(tekst, soort = "info") {
  if (!toastVak) {
    toastVak = document.createElement("div");
    toastVak.id = "toasts";
    document.body.appendChild(toastVak);
  }
  const el = document.createElement("div");
  el.className = "toast " + soort;
  el.textContent = tekst;
  toastVak.appendChild(el);
  setTimeout(() => el.classList.add("weg"), soort === "fout" ? 6000 : 3500);
  setTimeout(() => el.remove(), soort === "fout" ? 6400 : 3900);
}

// ---- bevestigen ----
// Vervangt confirm(): dat blokkeert de pagina, ziet er bij elke browser anders
// uit en past nergens bij. Geeft een belofte terug die true of false oplevert.
function bevestig(vraag, { bevestigTekst = "Ja, doorgaan", gevaarlijk = true } = {}) {
  return new Promise((resolve) => {
    const laag = document.createElement("div");
    laag.className = "overlay";
    laag.innerHTML = `<div class="dialoog" role="dialog" aria-modal="true">
      <p></p>
      <div class="dialoog-knoppen">
        <button class="btn secondary" data-nee>Annuleren</button>
        <button class="btn ${gevaarlijk ? "gevaarlijk" : ""}" data-ja></button>
      </div>
    </div>`;
    laag.querySelector("p").textContent = vraag;
    laag.querySelector("[data-ja]").textContent = bevestigTekst;

    const sluit = (antwoord) => {
      document.removeEventListener("keydown", opToets);
      laag.remove();
      resolve(antwoord);
    };
    const opToets = (e) => {
      if (e.key === "Escape") sluit(false);
      if (e.key === "Enter") sluit(true);
    };

    laag.querySelector("[data-nee]").onclick = () => sluit(false);
    laag.querySelector("[data-ja]").onclick = () => sluit(true);
    laag.onclick = (e) => { if (e.target === laag) sluit(false); };
    document.addEventListener("keydown", opToets);
    document.body.appendChild(laag);
    laag.querySelector("[data-ja]").focus();
  });
}
