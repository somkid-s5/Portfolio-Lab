const categorySelect = document.querySelector("#category");
const grid = document.querySelector("#catalog-grid");
const cacheState = document.querySelector("#cache-state");

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function loadCatalog() {
  grid.replaceChildren(element("p", "loading", "Loading synthetic catalog…"));
  try {
    const response = await fetch("/api/catalog?category=" + encodeURIComponent(categorySelect.value), {
      headers: { "X-Lab-Run-ID": "browser-demo" },
      cache: "no-store"
    });
    const cache = response.headers.get("X-Cache") || "UNKNOWN";
    cacheState.textContent = cache + " · " + response.status + " response";
    cacheState.dataset.state = cache.toLowerCase();
    if (!response.ok) throw new Error("Catalog request failed (" + response.status + ")");
    const result = await response.json();
    grid.replaceChildren();
    for (const product of result.items) {
      const card = element("article", "product-card");
      const art = element("div", "product-art");
      art.append(element("span", "product-category", product.category));
      art.append(element("span", "product-number", String(product.id).padStart(4, "0")));
      card.append(art);
      const body = element("div", "product-body");
      body.append(element("p", "product-kicker", "NORTHSTAR / " + product.category.toUpperCase()));
      body.append(element("h3", "", product.name));
      body.append(element("p", "product-description", product.description));
      const footer = element("div", "product-footer");
      footer.append(element("span", "version-chip", "v" + product.version));
      const detail = element("button", "detail-button", "Details ↗");
      detail.type = "button";
      detail.addEventListener("click", () => showDetail(product.id));
      footer.append(detail);
      body.append(footer);
      card.append(body);
      grid.append(card);
    }
  } catch (error) {
    grid.replaceChildren(element("p", "error-message", error.message));
  }
}

async function showDetail(id) {
  try {
    const response = await fetch("/api/products/" + id, {
      headers: { "X-Lab-Run-ID": "browser-demo" },
      cache: "no-store"
    });
    const product = await response.json();
    if (!response.ok) throw new Error(product.error || "Unable to load product.");
    window.alert(product.name + "\nVersion " + product.version + "\n\n" + product.description);
  } catch (error) {
    window.alert(error.message);
  }
}

categorySelect.addEventListener("change", loadCatalog);
loadCatalog();
