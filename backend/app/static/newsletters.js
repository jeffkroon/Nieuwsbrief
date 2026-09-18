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
    const kop = document.createElement("div");
    kop.innerHTML = `<div>${n.subject || "(zonder onderwerp)"}</div>`
      + `<div class="meta">${datum}${n.theme ? " - " + n.theme : ""}</div>`;
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
