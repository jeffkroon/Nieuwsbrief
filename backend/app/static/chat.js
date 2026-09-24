// De chat: beurt streamen, stappen tonen, gesprekken bewaren en hervatten.

// ---- chat ----
const chat = document.getElementById("chat");
const input = document.getElementById("input");
const send = document.getElementById("send");

function addMsg(role, text) {
  const el = document.createElement("div");
  el.className = "msg " + role;
  el.textContent = text;
  chat.appendChild(el);
  chat.scrollTop = chat.scrollHeight;
  return el;
}

const chatPreview = document.getElementById("chatPreview");
const chatPreviewFrame = document.getElementById("chatPreviewFrame");
const chatPreviewWrap = document.getElementById("chatPreviewWrap");

// Apparaat-weergave: desktop rendert de mail op echte 600px (en schaalt passend in
// het paneel), mobiel op telefoonbreedte zodat de mobiele media-queries actief zijn.
const DEVICE_WIDTHS = { desktop: 620, mobile: 375 };
let previewDevice = "desktop";

function updatePreviewLayout() {
  if (!chatPreviewWrap.classList.contains("show")) return;
  const width = DEVICE_WIDTHS[previewDevice];
  const avail = chatPreviewWrap.clientWidth;
  const scale = Math.min(1, avail / width);
  chatPreviewFrame.style.width = width + "px";
  chatPreviewFrame.style.transform = `scale(${scale})`;
  chatPreviewFrame.style.height = Math.max(200, chatPreviewWrap.clientHeight / scale) + "px";
  chatPreviewFrame.style.marginLeft = (scale >= 1 ? Math.max(0, (avail - width) / 2) : 0) + "px";
}

function setPreviewDevice(device) {
  previewDevice = device;
  document.getElementById("devDesktop").classList.toggle("active", device === "desktop");
  document.getElementById("devMobile").classList.toggle("active", device === "mobile");
  updatePreviewLayout();
}
document.getElementById("devDesktop").onclick = () => setPreviewDevice("desktop");
document.getElementById("devMobile").onclick = () => setPreviewDevice("mobile");
window.addEventListener("resize", updatePreviewLayout);

function showChatPreview(html) {
  if (!html) return;
  chatPreviewFrame.srcdoc = html;
  chatPreviewWrap.classList.add("show");
  chatPreview.classList.add("has-preview");
  updatePreviewLayout();
}

let tenantsCache = [];

async function loadTenants() {
  try {
    const tenants = await (await fetch("/tenants")).json();
    tenantsCache = tenants;
    if (!tenants.length) { addMsg("system", "Geen klanten gevonden."); return; }
    for (const t of tenants) {
      const opt = document.createElement("option");
      opt.value = t.id; opt.textContent = t.name;
      tenantSel.appendChild(opt);
    }
    // Het laatste gesprek van deze klant hervatten; anders schoon beginnen.
    let bewaard = null;
    try { bewaard = localStorage.getItem(chatKey()); } catch (e) { /* prive-modus */ }
    if (bewaard) {
      hervatGesprek(bewaard).catch(() => addMsg("assistant", "Waar wil je dat ik de nieuwsbrief over schrijf?"));
    } else {
      addMsg("assistant", "Waar wil je dat ik de nieuwsbrief over schrijf?");
    }
    laadGesprekken();
    toonSnelstarts(huidigeContentTypes());
    loadChatTemplates();
  } catch (e) { addMsg("system", "Kon klanten niet laden: " + e.message); }
}

function huidigeContentTypes() {
  const t = tenantsCache.find(x => x.id === tenantSel.value) || tenantsCache[0];
  return (t && t.config && t.config.content_types) || [];
}

// Het gesprek van deze klant onthouden, zodat F5 het niet wist.
const chatKey = () => "gesprek:" + (tenantSel.value || "");
function bewaarGesprek(id) {
  conversationId = id;
  try { id ? localStorage.setItem(chatKey(), id) : localStorage.removeItem(chatKey()); } catch (e) { /* prive-modus */ }
}

// Lopende beurt kunnen afbreken.
let lopendeBeurt = null;

async function sendMessage() {
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  addMsg("user", text);
  send.disabled = true; input.disabled = true;
  document.getElementById("stop").style.display = "";

  // Stappenpaneel: laat zien waar de assistent mee bezig is.
  const stappen = document.createElement("div");
  stappen.className = "msg steps";
  const bezig = document.createElement("div");
  bezig.className = "busy";
  bezig.textContent = "Aan het werk...";
  stappen.appendChild(bezig);
  chat.appendChild(stappen);
  chat.scrollTop = chat.scrollHeight;

  lopendeBeurt = new AbortController();
  try {
    const res = await fetch("/conversations/stream", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: lopendeBeurt.signal,
      body: JSON.stringify({
        tenant_id: tenantSel.value,
        message: text,
        template_id: chatTemplate.value || null,
        conversation_id: conversationId,
      }),
    });
    if (!res.ok || !res.body) {
      const err = await res.json().catch(() => ({}));
      stappen.remove();
      addMsg("system", "Fout (" + res.status + "): " + (err.detail || "onbekend"));
      return;
    }
    await leesStroom(res.body, stappen, bezig);
  } catch (e) {
    stappen.remove();
    if (e.name === "AbortError") addMsg("system", "Gestopt. Je vorige antwoorden blijven staan.");
    else addMsg("system", "Netwerkfout: " + e.message);
  } finally {
    lopendeBeurt = null;
    document.getElementById("stop").style.display = "none";
    send.disabled = false; input.disabled = false; input.focus();
    laadGesprekken();
  }
}

// Server-sent events lezen: elke "data: {...}"-regel is een gebeurtenis.
async function leesStroom(body, stappen, bezig) {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const delen = buffer.split("\n\n");
    buffer = delen.pop();
    for (const deel of delen) {
      const regel = deel.split("\n").find(r => r.startsWith("data: "));
      if (!regel) continue;
      let e;
      try { e = JSON.parse(regel.slice(6)); } catch (err) { continue; }
      if (e.type === "start") {
        bewaarGesprek(e.conversation_id);
      } else if (e.type === "step") {
        const stap = document.createElement("div");
        stap.textContent = e.text;
        stappen.insertBefore(stap, bezig);
        chat.scrollTop = chat.scrollHeight;
      } else if (e.type === "done") {
        bezig.remove();
        if (!stappen.childElementCount) stappen.remove();
        addMsg("assistant", e.reply);
        if (e.preview_html) showChatPreview(e.preview_html);
      } else if (e.type === "error") {
        bezig.remove();
        addMsg("system", e.detail);
      } else if (e.type === "cancelled") {
        bezig.remove();
        addMsg("system", "Gestopt.");
      }
    }
  }
}

document.getElementById("stop").onclick = () => {
  if (lopendeBeurt) lopendeBeurt.abort();
};

// ---- gesprekken: lijst in de sidebar (zoals ChatGPT), hervatten, nieuw, verwijderen ----
const convList = document.getElementById("convList");
const OPENING = "Waar wil je dat ik de nieuwsbrief over schrijf?";

// Groepen zoals ChatGPT: Vandaag, Gisteren, Vorige 7 dagen, Vorige 30 dagen, Ouder.
function periodeVan(datum) {
  const vandaag = new Date(); vandaag.setHours(0, 0, 0, 0);
  const dag = new Date(datum); dag.setHours(0, 0, 0, 0);
  const dagen = Math.round((vandaag - dag) / 86400000);
  if (dagen <= 0) return "Vandaag";
  if (dagen === 1) return "Gisteren";
  if (dagen <= 7) return "Vorige 7 dagen";
  if (dagen <= 30) return "Vorige 30 dagen";
  return "Ouder";
}

const PRULLENBAK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 14H6L5 6"/></svg>';

function gesprekRegel(g) {
  const regel = document.createElement("div");
  regel.className = "conv-item" + (g.id === conversationId ? " active" : "");
  regel.dataset.id = g.id;
  regel.title = g.title;
  const titel = document.createElement("span");
  titel.className = "conv-title";
  titel.textContent = g.title;  // textContent: de titel is het eerste chatbericht
  const weg = document.createElement("button");
  weg.className = "conv-del";
  weg.title = "Gesprek verwijderen";
  weg.innerHTML = PRULLENBAK;  // vaste, eigen SVG; geen gebruikersinvoer
  weg.onclick = (e) => { e.stopPropagation(); verwijderGesprek(g.id, weg); };
  regel.append(titel, weg);
  regel.onclick = () => {
    showView("chat");
    hervatGesprek(g.id).catch(() => addMsg("system", "Kon dit gesprek niet openen."));
  };
  return regel;
}

async function laadGesprekken() {
  if (!tenantSel.value) return;
  try {
    const res = await fetch(`/conversations?tenant_id=${tenantSel.value}`);
    if (!res.ok) return;
    const lijst = await res.json();
    convList.innerHTML = "";
    if (!lijst.length) {
      const leeg = document.createElement("div");
      leeg.className = "conv-empty";
      leeg.textContent = "Nog geen gesprekken";
      convList.appendChild(leeg);
      return;
    }
    let vorige = null;
    for (const g of lijst) {
      const periode = periodeVan(g.updated_at);
      if (periode !== vorige) {
        const kop = document.createElement("div");
        kop.className = "conv-group";
        kop.textContent = periode;
        convList.appendChild(kop);
        vorige = periode;
      }
      convList.appendChild(gesprekRegel(g));
    }
  } catch (e) { /* lijst is bijzaak; de chat moet gewoon werken */ }
}

function markeerActief() {
  for (const el of convList.querySelectorAll(".conv-item")) {
    el.classList.toggle("active", el.dataset.id === conversationId);
  }
}

// Twee klikken in plaats van confirm(): de eerste vraagt "Verwijderen?", de tweede
// verwijdert. Na een paar seconden zonder tweede klik valt de knop terug.
async function verwijderGesprek(id, knop) {
  if (!knop.classList.contains("confirm")) {
    knop.classList.add("confirm");
    knop.textContent = "Verwijderen?";
    setTimeout(() => {
      if (knop.isConnected && knop.classList.contains("confirm")) {
        knop.classList.remove("confirm");
        knop.innerHTML = PRULLENBAK;
      }
    }, 4000);
    return;
  }
  knop.disabled = true;
  try {
    const res = await fetch(`/conversations/${id}`, { method: "DELETE" });
    if (!res.ok && res.status !== 404) throw new Error("status " + res.status);
    if (id === conversationId) nieuwGesprek();
    toast("Gesprek verwijderd", "ok");
  } catch (e) {
    toast("Kon het gesprek niet verwijderen: " + e.message, "fout");
  } finally {
    laadGesprekken();
  }
}

async function hervatGesprek(id) {
  const res = await fetch(`/conversations/${id}`);
  if (!res.ok) { addMsg("system", "Kon dit gesprek niet openen."); return; }
  const g = await res.json();
  chat.innerHTML = "";
  for (const m of g.messages) addMsg(m.role === "user" ? "user" : "assistant", m.content);
  bewaarGesprek(g.id);
  if (g.template_id) chatTemplate.value = g.template_id;
  leegVoorbeeld();
  if (g.preview_html) showChatPreview(g.preview_html);
  chat.scrollTop = chat.scrollHeight;
  markeerActief();
}

// Voorbeeldpaneel terug naar leeg, zodat een ander gesprek niet het voorbeeld
// van het vorige laat zien.
function leegVoorbeeld() {
  chatPreviewFrame.srcdoc = "";
  chatPreviewWrap.classList.remove("show");
  chatPreview.classList.remove("has-preview");
}

function nieuwGesprek() {
  bewaarGesprek(null);
  chat.innerHTML = "";
  leegVoorbeeld();
  addMsg("assistant", OPENING);
  markeerActief();
  input.focus();
}

document.getElementById("newChat").onclick = () => { showView("chat"); nieuwGesprek(); };

// Snelstarts uit de nieuwsbrief-soorten van het bedrijf: scheelt typen en
// stuurt de assistent meteen naar de juiste bron.
function toonSnelstarts(contentTypes) {
  const balk = document.getElementById("quickStarts");
  balk.innerHTML = "";
  for (const soort of (contentTypes || []).slice(0, 3)) {
    if (!soort || !soort.name) continue;
    const knop = document.createElement("button");
    knop.className = "chip";
    knop.textContent = soort.name;
    knop.onclick = () => {
      input.value = `Maak een nieuwsbrief over ${String(soort.name).toLowerCase()}.`;
      input.focus();
    };
    balk.appendChild(knop);
  }
}
send.addEventListener("click", sendMessage);
input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(); } });
tenantSel.addEventListener("change", () => {
  chat.innerHTML = "";
  let bewaard = null;
  try { bewaard = localStorage.getItem(chatKey()); } catch (e) { /* prive-modus */ }
  conversationId = null;
  leegVoorbeeld();
  if (bewaard) {
    hervatGesprek(bewaard).catch(() => addMsg("assistant", "Waar wil je dat ik de nieuwsbrief over schrijf?"));
  } else {
    addMsg("assistant", "Waar wil je dat ik de nieuwsbrief over schrijf?");
  }
  laadGesprekken();
  toonSnelstarts(huidigeContentTypes());
  loadCategories();
  loadChatTemplates();
  if (views.templates.classList.contains("active")) { loadTemplates(); loadTone(); }
});
