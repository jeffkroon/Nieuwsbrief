// Beeldbank per bedrijf: categorieen, uploaden, verwijderen.

// ---- images ----
const uploadCategory = document.getElementById("uploadCategory");
const viewCategory = document.getElementById("viewCategory");
const imageGrid = document.getElementById("imageGrid");
const uploadStatus = document.getElementById("uploadStatus");

async function loadCategories() {
  const tid = tenantSel.value;
  if (!tid) return;
  try {
    const { categories } = await (await fetch(`/tenants/${tid}/image-categories`)).json();
    for (const sel of [uploadCategory, viewCategory]) {
      const cur = sel.value;
      sel.innerHTML = "";
      for (const c of categories) {
        const o = document.createElement("option"); o.value = c; o.textContent = c; sel.appendChild(o);
      }
      if (categories.includes(cur)) sel.value = cur;
    }
    loadImages();
  } catch (e) { uploadStatus.textContent = "Kon categorieën niet laden: " + e.message; }
}

async function loadImages() {
  const tid = tenantSel.value;
  const cat = viewCategory.value;
  if (!tid || !cat) { imageGrid.innerHTML = ""; return; }
  const imgs = await (await fetch(`/tenants/${tid}/images?category=${encodeURIComponent(cat)}`)).json();
  imageGrid.innerHTML = imgs.length ? "" : `<p class="hint">Nog geen foto&#39;s in deze categorie.</p>`;
  for (const im of imgs) {
    const el = document.createElement("div");
    el.className = "thumb";
    el.innerHTML = `<img src="${im.url}" alt=""><div class="meta"><div class="name">${im.filename}</div>`
      + `<button data-id="${im.id}">verwijderen</button></div>`;
    el.querySelector("button").onclick = async () => {
      await fetch(`/tenants/${tid}/images/${im.id}`, { method: "DELETE" });
      loadImages();
    };
    imageGrid.appendChild(el);
  }
}
viewCategory.addEventListener("change", loadImages);

document.getElementById("uploadBtn").onclick = async () => {
  const tid = tenantSel.value;
  const files = document.getElementById("uploadFiles").files;
  if (!files.length) { uploadStatus.textContent = "Kies eerst een of meer bestanden."; return; }
  const fd = new FormData();
  fd.append("category", uploadCategory.value);
  const desc = document.getElementById("uploadDesc").value.trim();
  for (const f of files) { fd.append("files", f); if (desc) fd.append("descriptions", desc); }
  uploadStatus.textContent = "Uploaden...";
  const res = await fetch(`/tenants/${tid}/images`, { method: "POST", body: fd });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    uploadStatus.textContent = "Fout (" + res.status + "): " + (err.detail || "onbekend");
  } else {
    const created = await res.json();
    uploadStatus.textContent = `${created.length} foto('s) geüpload.`;
    document.getElementById("uploadFiles").value = "";
    if (viewCategory.value === uploadCategory.value) loadImages(); else { viewCategory.value = uploadCategory.value; loadImages(); }
  }
};
