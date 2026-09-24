// Gemaakte nieuwsbrieven tonen en openen in het verzendplatform.

// ---- nieuwsbrieven ----
async function laadNieuwsbrieven() {
  const lijst = document.getElementById("nlList");
  if (!tenantSel.value) { lijst.innerHTML = `<p class="hint">Kies eerst een klant.</p>`; return; }
  lijst.innerHTML = `<p class="hint">Laden...</p>`;
  let rijen;
  try {
    const res = await fetch(`/tenants/${tenantSel.value}/newsletters`);
    if (!res.ok) throw new Error("status " + res.status);
    rijen = await res.json();
  } catch (e) {
    lijst.innerHTML = `<p class="hint">Kon de nieuwsbrieven niet laden: ${e.message}</p>`;
    return;
  }
  if (!rijen.length) {
    lijst.innerHTML = `<p class="hint">Nog geen nieuwsbrieven gemaakt voor deze klant.</p>`;
    return;
  }
  lijst.innerHTML = "";
  for (const n of rijen) {
    const el = document.createElement("div");
    el.className = "nl-item";
    const datum = new Date(n.created_at).toLocaleString("nl-NL", { dateStyle: "short", timeStyle: "short" });
    // textContent, geen innerHTML: onderwerp en thema komen uit de chat.
    const kop = document.createElement("div");
    const onderwerp = document.createElement("div");
    onderwerp.textContent = n.subject || "(zonder onderwerp)";
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = datum + (n.theme ? " - " + n.theme : "");
    const cijfers = document.createElement("div");
    cijfers.className = "meta nl-stats";
    cijfers.textContent = resultaatTekst(n.stats);
    kop.append(onderwerp, meta, cijfers);
    el.appendChild(kop);

    const rechts = document.createElement("span");
    rechts.style.marginLeft = "auto";
    el.appendChild(rechts);

    if (n.status === "failed") {
      const mislukt = document.createElement("span");
      mislukt.className = "status-failed";
      mislukt.textContent = "mislukt";
      el.appendChild(mislukt);
    }

    if (n.status === "sent") {
      const verstuurd = document.createElement("span");
      verstuurd.className = "status-sent";
      verstuurd.textContent = "verstuurd";
      el.appendChild(verstuurd);
    }

    if (n.campaign_ref && n.status !== "failed") {
      const resultaten = document.createElement("button");
      resultaten.textContent = "resultaten";
      resultaten.title = "Open- en klikcijfers ophalen uit het verzendplatform (alleen lezen)";
      resultaten.onclick = () => haalResultaten(n.id, resultaten, cijfers);
      el.appendChild(resultaten);
    }

    const bekijk = document.createElement("button");
    bekijk.textContent = "bekijken";
    bekijk.onclick = () => toonNieuwsbrief(n.id);
    el.appendChild(bekijk);

    if (n.conversation_id) {
      const gesprek = document.createElement("button");
      gesprek.textContent = "gesprek openen";
      gesprek.onclick = () => { showView("chat"); hervatGesprek(n.conversation_id); };
      el.appendChild(gesprek);
    }

    if (n.link_url) {
      const link = document.createElement("a");
      link.href = n.link_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = n.link_label;
      // Alleen bij Brevo komt de link op de campagne zelf uit; bij de andere
      // platforms op het overzicht. Dat staat in de tooltip zodat niemand
      // denkt dat er iets stuk is.
      link.title = n.link_is_deeplink
        ? "Opent dit concept in het verzendplatform"
        : "Opent het campagne-overzicht; zoek daar op het onderwerp";
      el.appendChild(link);
    }
    lijst.appendChild(el);
  }
}

function procent(fractie) {
  return (fractie * 100).toLocaleString("nl-NL", { maximumFractionDigits: 1 }) + "%";
}

// Korte regel met de cijfers; leeg als ze nog nooit zijn opgehaald.
function resultaatTekst(stats) {
  if (!stats) return "";
  if (stats.status === "draft") return "Nog niet verstuurd (concept)";
  const delen = [];
  if (stats.sent != null) delen.push(`${stats.sent.toLocaleString("nl-NL")} verzonden`);
  if (stats.open_rate != null) delen.push(`open ${procent(stats.open_rate)}`);
  if (stats.click_rate != null) delen.push(`klik ${procent(stats.click_rate)}`);
  if (stats.unsubscribes != null) delen.push(`${stats.unsubscribes} afmeldingen`);
  return delen.length ? delen.join(" · ") : "Nog geen cijfers beschikbaar";
}

async function haalResultaten(id, knop, doel) {
  knop.disabled = true;
  const oud = knop.textContent;
  knop.textContent = "ophalen...";
  try {
    const res = await fetch(`/tenants/${tenantSel.value}/newsletters/${id}/results`, { method: "POST" });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(body.detail || "status " + res.status);
    doel.textContent = resultaatTekst(body.stats)
      + (body.from_cache ? " (net opgehaald; over een paar minuten opnieuw)" : "");
  } catch (e) {
    doel.textContent = "Kon geen resultaten ophalen: " + e.message;
  } finally {
    knop.disabled = false;
    knop.textContent = oud;
  }
}

async function toonNieuwsbrief(id) {
  const frame = document.getElementById("nlPreviewFrame");
  const leeg = document.getElementById("nlPreviewEmpty");
  try {
    const res = await fetch(`/tenants/${tenantSel.value}/newsletters/${id}/html`);
    if (!res.ok) throw new Error("status " + res.status);
    frame.srcdoc = await res.text();
    frame.style.display = "";
    leeg.style.display = "none";
    frame.scrollIntoView({ behavior: "smooth", block: "center" });
  } catch (e) {
    leeg.textContent = "Kon het voorbeeld niet laden: " + e.message;
  }
}
