// AI-kosten per bedrijf (alleen Dunion-admin): schatting op basis van tokens.
// Alle tekst gaat via textContent de pagina in, nooit via innerHTML: bedrijfs-
// en modelnamen komen uit de database.

const usageDays = document.getElementById("usageDays");
const usageStatus = document.getElementById("usageStatus");
const usageTable = document.getElementById("usageTable");

const DOEL_LABELS = {
  chat: "chat",
  toolproof: "template-controle",
  prefill: "bedrijf automatisch invullen",
  fotobeschrijving: "fotobeschrijving",
};

function formatUsd(bedrag) {
  if (bedrag === null || bedrag === undefined) return "onbekend";
  const decimalen = bedrag > 0 && bedrag < 0.01 ? 4 : 2;
  return new Intl.NumberFormat("nl-NL", {
    style: "currency", currency: "USD",
    minimumFractionDigits: decimalen, maximumFractionDigits: decimalen,
  }).format(bedrag);
}

function formatAantal(n) {
  return new Intl.NumberFormat("nl-NL").format(n || 0);
}

function kostenTekst(rij) {
  const basis = formatUsd(rij.cost_usd);
  return rij.unpriced_calls ? `${basis} + ${rij.unpriced_calls} onbekend` : basis;
}

function cel(tag, tekst, className = "") {
  const el = document.createElement(tag);
  el.textContent = tekst;
  if (className) el.className = className;
  return el;
}

function rij(cellen, className = "") {
  const tr = document.createElement("tr");
  if (className) tr.className = className;
  for (const c of cellen) tr.appendChild(c);
  return tr;
}

function kopRij() {
  const koppen = ["Bedrijf", "Gesprekken", "Calls", "Kosten", "Gemiddeld per gesprek"];
  return rij(koppen.map((k, i) => cel("th", k, i ? "num" : "")));
}

function bedrijfRij(t) {
  return rij([
    cel("td", t.name),
    cel("td", formatAantal(t.conversations), "num"),
    cel("td", formatAantal(t.calls), "num"),
    cel("td", kostenTekst(t), "num"),
    cel("td", t.avg_cost_per_conversation_usd === null ? "-" : formatUsd(t.avg_cost_per_conversation_usd), "num"),
  ], "usage-tenant");
}

function detailRij(r) {
  const doel = DOEL_LABELS[r.purpose] || r.purpose;
  const tokens = `${formatAantal(r.input_tokens)} in / ${formatAantal(r.output_tokens)} uit`
    + ` / ${formatAantal(r.cache_read_tokens)} cache`;
  return rij([
    cel("td", `${r.model}, ${doel}`),
    cel("td", tokens, "hint"),
    cel("td", formatAantal(r.calls), "num"),
    cel("td", formatUsd(r.cost_usd), "num"),
    cel("td", ""),
  ], "usage-detail");
}

function totaalRij(totals) {
  return rij([
    cel("td", "Totaal"),
    cel("td", formatAantal(totals.conversations), "num"),
    cel("td", formatAantal(totals.calls), "num"),
    cel("td", kostenTekst(totals), "num"),
    cel("td", totals.avg_cost_per_conversation_usd === null ? "-" : formatUsd(totals.avg_cost_per_conversation_usd), "num"),
  ], "usage-total");
}

// Klik op een bedrijf: de regels per model en functie klappen open of dicht.
function voegBedrijfToe(tbody, t) {
  const hoofd = bedrijfRij(t);
  const details = t.breakdown.map(detailRij);
  for (const d of details) d.hidden = true;
  hoofd.onclick = () => {
    const open = hoofd.classList.toggle("open");
    for (const d of details) d.hidden = !open;
  };
  tbody.appendChild(hoofd);
  for (const d of details) tbody.appendChild(d);
}

function toonUsage(rapport) {
  usageTable.replaceChildren();
  if (!rapport.tenants.length) {
    usageTable.appendChild(cel("p", "Geen AI-gebruik in deze periode.", "hint"));
    return;
  }
  const table = document.createElement("table");
  table.className = "usage-table";
  const thead = document.createElement("thead");
  thead.appendChild(kopRij());
  const tbody = document.createElement("tbody");
  for (const t of rapport.tenants) voegBedrijfToe(tbody, t);
  const tfoot = document.createElement("tfoot");
  tfoot.appendChild(totaalRij(rapport.totals));
  table.append(thead, tbody, tfoot);
  usageTable.appendChild(table);
}

async function loadUsage() {
  const days = usageDays.value;
  meld(usageStatus, "Kosten laden...");
  try {
    const res = await fetch(`/admin/usage?days=${encodeURIComponent(days)}`);
    if (!res.ok) throw new Error(`status ${res.status}`);
    toonUsage(await res.json());
    meld(usageStatus, "");
  } catch (e) {
    usageTable.replaceChildren();
    meld(usageStatus, "Kon de AI-kosten niet laden. Probeer het later opnieuw.", "fout");
  }
}

usageDays.addEventListener("change", loadUsage);
