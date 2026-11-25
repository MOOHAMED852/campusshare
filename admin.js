const levels = ["Tronc Commun", "Licence", "Master", "Cycle Ingénieur"];
const loginPanel = document.querySelector("#admin-login-panel");
const dashboard = document.querySelector("#admin-dashboard");
const tokenInput = document.querySelector("#admin-token");
const resourcesPanel = document.querySelector("#admin-resources");
const errorPanel = document.querySelector("#admin-error");
const statusMessage = document.querySelector("#admin-status");
let adminToken = "";

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

async function adminRequest(url, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-Admin-Token", adminToken);
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  const response = await fetch(url, { ...options, headers });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `Le serveur a répondu ${response.status}.`);
  return result;
}

function showError(message) {
  errorPanel.textContent = message;
  errorPanel.hidden = false;
}

function renderAdminResource(resource) {
  const categoryLabels = { Exams: "Examens", Courses: "Cours", "TD & TP": "TD & TP" };
  const examTypeLabels = { "Normal Session": "Session normale", Rattrapage: "Rattrapage" };
  const path = [resource.academicLevel, resource.major, categoryLabels[resource.category] || resource.category, resource.academicYear, resource.semester, resource.module, examTypeLabels[resource.examType] || resource.examType]
    .filter(Boolean).map(escapeHtml).join(" · ");
  const status = escapeHtml(resource.status);
  const fileName = escapeHtml(resource.fileName);
  const statusLabel = status === "pending" ? "en attente" : status === "approved" ? "approuvé" : status === "rejected" ? "rejeté" : status;
  const reviewButtons = resource.status === "pending"
    ? `<button class="button button-approve" type="button" data-action="approve" data-id="${resource.id}">Approuver</button><button class="button button-reject" type="button" data-action="reject" data-id="${resource.id}">Rejeter</button>`
    : "";
  const correctionForm = resource.category === "Exams"
    ? `<form class="admin-correction-form" data-id="${resource.id}"><label>Ajouter ou remplacer la correction PDF<input type="file" name="correction" accept="application/pdf,.pdf" required></label><button class="button button-secondary" type="submit">Enregistrer la correction</button></form>`
    : "";
  const correctionStatus = resource.hasCorrection ? "<span class=\"admin-correction-status\">Correction jointe</span>" : "";
  return `<article class="admin-resource">
    <div class="admin-resource-copy"><span class="admin-resource-state state-${status}">${statusLabel}</span><h3>${escapeHtml(resource.title)}</h3><p>${path}</p><small>${fileName} · ${resource.createdAt ? new Date(resource.createdAt).toLocaleString("fr-FR") : ""}</small>${correctionStatus}</div>
    <div class="admin-resource-preview"><iframe src="${escapeHtml(resource.previewUrl)}#page=1&toolbar=0&navpanes=0" title="Aperçu administrateur : ${escapeHtml(resource.title)}" loading="lazy"></iframe></div>
    <div class="admin-resource-actions">${reviewButtons}${correctionForm}<button class="button button-delete" type="button" data-action="delete" data-id="${resource.id}">Supprimer</button></div>
  </article>`;
}

async function loadResources() {
  errorPanel.hidden = true;
  try {
    const status = document.querySelector("#admin-status-filter").value;
    const result = await adminRequest(`/api/admin/resources?status=${encodeURIComponent(status)}`);
    resourcesPanel.innerHTML = result.resources.map(renderAdminResource).join("");
    if (!result.resources.length) resourcesPanel.innerHTML = `<p class="empty-state">Aucun document avec ce statut.</p>`;
  } catch (error) {
    showError(error.message);
  }
}

async function unlockDashboard() {
  await adminRequest("/api/admin/resources?status=pending");
  await adminRequest("/api/admin/session", { method: "POST" });
  loginPanel.hidden = true;
  dashboard.hidden = false;
  errorPanel.hidden = true;
  await loadResources();
}

document.querySelector("#admin-login").addEventListener("submit", async (event) => {
  event.preventDefault();
  adminToken = tokenInput.value;
  try {
    await unlockDashboard();
  } catch (error) {
    adminToken = "";
    showError(error.message);
  }
});

document.querySelector("#admin-logout").addEventListener("click", async () => {
  try {
    await adminRequest("/api/admin/session", { method: "DELETE" });
  } catch (error) {
    showError(error.message);
    return;
  }
  adminToken = "";
  tokenInput.value = "";
  dashboard.hidden = true;
  loginPanel.hidden = false;
  resourcesPanel.replaceChildren();
  statusMessage.textContent = "Tableau de bord verrouillé.";
});

document.querySelector("#admin-status-filter").addEventListener("change", loadResources);
document.querySelector("#admin-level").replaceChildren(
  new Option("Sélectionnez un niveau académique", ""),
  ...levels.map((level) => new Option(level, level)),
);

document.querySelector("#major-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const values = Object.fromEntries(new FormData(form));
    await adminRequest("/api/admin/majors", { method: "POST", body: JSON.stringify(values) });
    form.reset();
    statusMessage.textContent = "Filière ajoutée.";
    await loadResources();
  } catch (error) {
    showError(error.message);
  }
});

document.querySelector("#year-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  try {
    const values = Object.fromEntries(new FormData(form));
    await adminRequest("/api/admin/academic-years", { method: "POST", body: JSON.stringify(values) });
    form.reset();
    statusMessage.textContent = "Année académique ajoutée.";
  } catch (error) {
    showError(error.message);
  }
});

resourcesPanel.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (!button) return;
  const resourceId = button.dataset.id;
  const action = button.dataset.action;
  if (action === "delete" && !window.confirm("Supprimer définitivement ce document et sa correction ?")) return;
  try {
    if (action === "approve" || action === "reject") {
      await adminRequest(`/api/admin/resources/${resourceId}/review`, {
        method: "POST",
        body: JSON.stringify({ status: action === "approve" ? "approved" : "rejected" }),
      });
      statusMessage.textContent = action === "approve" ? "Document approuvé et désormais visible dans la bibliothèque." : "Document rejeté.";
    } else if (action === "delete") {
      await adminRequest(`/api/admin/resources/${resourceId}`, { method: "DELETE" });
      statusMessage.textContent = "Document supprimé.";
    }
    await loadResources();
  } catch (error) {
    showError(error.message);
  }
});

resourcesPanel.addEventListener("submit", async (event) => {
  const form = event.target.closest(".admin-correction-form");
  if (!form) return;
  event.preventDefault();
  try {
    await adminRequest(`/api/admin/resources/${form.dataset.id}/correction`, {
      method: "POST",
      body: new FormData(form),
    });
    statusMessage.textContent = "Correction PDF enregistrée.";
    await loadResources();
  } catch (error) {
    showError(error.message);
  }
});
