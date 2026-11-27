const levels = ["Tronc Commun", "Licence", "Master", "Cycle Ingénieur"];
const loginPanel = document.querySelector("#admin-login-panel");
const dashboard = document.querySelector("#admin-dashboard");
const publicInformation = document.querySelector("#admin-public-information");
const publicContactEmail = document.querySelector("#admin-contact-email");
const pageTitle = document.querySelector("#admin-page-title");
const tokenInput = document.querySelector("#admin-token");
const resourcesPanel = document.querySelector("#admin-resources");
const studentsPanel = document.querySelector("#admin-students");
const studentActivityPanel = document.querySelector("#admin-student-activity");
const errorPanel = document.querySelector("#admin-error");
const statusMessage = document.querySelector("#admin-status");
const adminUploadForm = document.querySelector("#admin-upload-form");
const adminUploadLevel = document.querySelector("#admin-upload-level");
const adminUploadMajor = document.querySelector("#admin-upload-major");
const adminUploadCategory = document.querySelector("#admin-upload-category");
const adminUploadYear = document.querySelector("#admin-upload-year");
const adminUploadSemester = document.querySelector("#admin-upload-semester");
const adminUploadType = document.querySelector("#admin-upload-type");
const adminUploadExamType = document.querySelector("#admin-upload-exam-type");
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

function setOptions(select, placeholder, values) {
  select.replaceChildren(new Option(placeholder, ""));
  values.forEach((value) => select.add(new Option(value, value)));
  select.disabled = values.length === 0;
}

async function updateAdminUploadMajors() {
  adminUploadMajor.disabled = true;
  setOptions(adminUploadMajor, "Chargement des filières…", []);
  if (!adminUploadLevel.value) {
    adminUploadMajor.replaceChildren(new Option("Sélectionnez d’abord un niveau", ""));
    return;
  }
  const result = await adminRequest(`/api/majors?level=${encodeURIComponent(adminUploadLevel.value)}`);
  setOptions(
    adminUploadMajor,
    result.majors.length ? "Sélectionnez une filière" : "Aucune filière disponible",
    result.majors.map((major) => major.name),
  );
}

function updateAdminUploadCategoryFields() {
  const types = {
    Exams: ["Exam"],
    Courses: ["Course"],
    "TD & TP": ["TD", "TP", "Correction"],
  }[adminUploadCategory.value] || [];
  setOptions(adminUploadType, "Sélectionnez un type de document", types);
  const isExam = adminUploadCategory.value === "Exams";
  document.querySelector("#admin-upload-exam-wrap").hidden = !isExam;
  document.querySelector("#admin-upload-correction-wrap").hidden = !isExam;
  adminUploadExamType.required = isExam;
  adminUploadExamType.disabled = !isExam;
  if (!isExam) adminUploadExamType.value = "";
}

async function initializeAdminUploadOptions() {
  const [levelResult, yearResult] = await Promise.all([
    adminRequest("/api/levels"),
    adminRequest("/api/academic-years"),
  ]);
  setOptions(adminUploadLevel, "Sélectionnez un niveau académique", levelResult.levels);
  setOptions(adminUploadMajor, "Sélectionnez d’abord un niveau", []);
  setOptions(adminUploadYear, "Sélectionnez une année académique", yearResult.academicYears);
  setOptions(adminUploadSemester, "Sélectionnez un semestre", Array.from({ length: 10 }, (_, index) => `S${index + 1}`));
  updateAdminUploadCategoryFields();
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
  const submitter = resource.submittedBy ? `<small>Soumis par ${escapeHtml(resource.submittedBy)}</small>` : "";
  return `<article class="admin-resource">
    <div class="admin-resource-copy"><span class="admin-resource-state state-${status}">${statusLabel}</span><h3>${escapeHtml(resource.title)}</h3><p>${path}</p><small>${fileName} · ${resource.createdAt ? new Date(resource.createdAt).toLocaleString("fr-FR") : ""}</small>${submitter}${correctionStatus}</div>
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

function formatAdminDate(value) {
  return value ? new Date(value).toLocaleString("fr-FR") : "Jamais";
}

function formatActiveTime(seconds) {
  const minutes = Math.floor(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const remainingMinutes = minutes % 60;
  if (hours) return `${hours} h ${remainingMinutes} min`;
  if (minutes) return `${minutes} min`;
  return "moins d’une minute";
}

function renderAdminStudent(student) {
  const presence = student.online
    ? '<span class="admin-presence is-online">En ligne</span>'
    : '<span class="admin-presence">Hors ligne</span>';
  const verification = student.emailVerified ? "E-mail vérifié" : "E-mail non vérifié";
  return `<tr>
    <td><strong>${escapeHtml(student.username || "—")}</strong><small>${escapeHtml(student.email)}</small></td>
    <td>${presence}<small>${escapeHtml(verification)}</small></td>
    <td>${escapeHtml(formatAdminDate(student.lastSignInAt))}</td>
    <td>${escapeHtml(formatAdminDate(student.lastSeenAt))}</td>
    <td>${escapeHtml(formatActiveTime(student.activeSeconds))}</td>
    <td>${escapeHtml(student.downloadCount)}</td>
    <td><button class="button button-secondary" type="button" data-action="view-student" data-student-id="${escapeHtml(student.id)}">Voir l’activité</button></td>
  </tr>`;
}

async function loadStudents() {
  try {
    const result = await adminRequest("/api/admin/students");
    studentsPanel.innerHTML = result.students.length
      ? `<div class="admin-students-table-wrap"><table class="admin-students-table">
          <thead><tr><th>Compte</th><th>Statut</th><th>Dernière connexion</th><th>Dernière activité</th><th>Temps actif estimé</th><th>Téléchargements (180 j.)</th><th></th></tr></thead>
          <tbody>${result.students.map(renderAdminStudent).join("")}</tbody>
        </table></div>`
      : '<p class="empty-state">Aucun compte étudiant.</p>';
  } catch (error) {
    showError(error.message);
  }
}

async function loadStudentActivity(studentId) {
  try {
    const result = await adminRequest(`/api/admin/students/${encodeURIComponent(studentId)}/activity`);
    const eventLabels = {
      sign_in: "Connexion",
      sign_out: "Déconnexion",
      download: "Téléchargement d’un PDF",
      correction_download: "Téléchargement d’une correction",
    };
    const events = result.events.length
      ? `<ol class="admin-activity-events">${result.events.map((event) => `
          <li><strong>${escapeHtml(eventLabels[event.eventType] || event.eventType)}</strong>
            ${event.resourceTitle ? `<span>${escapeHtml(event.resourceTitle)}</span>` : ""}
            <time datetime="${escapeHtml(event.createdAt)}">${escapeHtml(formatAdminDate(event.createdAt))}</time>
          </li>`).join("")}</ol>`
      : '<p class="empty-state">Aucune activité enregistrée.</p>';
    studentActivityPanel.innerHTML = `
      <div class="admin-list-heading">
        <h3>${escapeHtml(result.student.username || result.student.email)}</h3>
        <button class="button button-secondary" type="button" id="admin-close-student-activity">Fermer</button>
      </div>
      <p>${escapeHtml(result.student.email)} · ${result.student.emailVerified ? "E-mail vérifié" : "E-mail non vérifié"}</p>
      <p>Compte créé le ${escapeHtml(formatAdminDate(result.student.createdAt))} · Temps actif estimé : ${escapeHtml(formatActiveTime(result.student.activeSeconds))}</p>
      <h4>Activité récente</h4>
      ${events}`;
    studentActivityPanel.hidden = false;
    studentActivityPanel.scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (error) {
    showError(error.message);
  }
}

async function unlockDashboard() {
  await adminRequest("/api/admin/resources?status=pending");
  await initializeAdminUploadOptions();
  await adminRequest("/api/admin/session", { method: "POST" });
  loginPanel.hidden = true;
  publicInformation.hidden = true;
  dashboard.hidden = false;
  pageTitle.textContent = "Gestion des documents";
  errorPanel.hidden = true;
  await Promise.all([loadResources(), loadStudents()]);
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
  publicInformation.hidden = false;
  pageTitle.textContent = "Administration du site";
  resourcesPanel.replaceChildren();
  studentsPanel.replaceChildren();
  studentActivityPanel.replaceChildren();
  studentActivityPanel.hidden = true;
  statusMessage.textContent = "Tableau de bord verrouillé.";
});

document.querySelector("#admin-status-filter").addEventListener("change", loadResources);
document.querySelector("#admin-refresh-students").addEventListener("click", loadStudents);
studentsPanel.addEventListener("click", (event) => {
  const button = event.target.closest("[data-action='view-student']");
  if (button) loadStudentActivity(button.dataset.studentId);
});
studentActivityPanel.addEventListener("click", (event) => {
  if (event.target.closest("#admin-close-student-activity")) {
    studentActivityPanel.hidden = true;
    studentActivityPanel.replaceChildren();
  }
});
adminUploadLevel.addEventListener("change", () => {
  updateAdminUploadMajors().catch((error) => showError(error.message));
});
adminUploadCategory.addEventListener("change", updateAdminUploadCategoryFields);

adminUploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = adminUploadForm.querySelector("button[type='submit']");
  const status = document.querySelector("#admin-upload-status");
  button.disabled = true;
  status.textContent = "Publication du PDF…";
  try {
    const result = await adminRequest("/api/admin/resources", {
      method: "POST",
      body: new FormData(adminUploadForm),
    });
    status.textContent = `Document publié immédiatement (PDF de ${result.pageCount} page(s)).`;
    adminUploadForm.reset();
    await updateAdminUploadMajors();
    updateAdminUploadCategoryFields();
    document.querySelector("#admin-status-filter").value = "approved";
    await loadResources();
  } catch (error) {
    status.textContent = "";
    showError(error.message);
  } finally {
    button.disabled = false;
  }
});
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

async function initializeAdministrationPage() {
  try {
    const publicInfoResponse = await fetch("/api/admin/public-info");
    const publicInfo = await publicInfoResponse.json();
    if (publicInfo.contactEmail) {
      publicContactEmail.textContent = publicInfo.contactEmail;
      publicContactEmail.href = `mailto:${encodeURIComponent(publicInfo.contactEmail)}`;
    }
  } catch (error) {
    showError("Impossible de charger les informations publiques.");
  }

  try {
    const status = await adminRequest("/api/admin/session");
    if (status.authenticated && status.role === "administrator") {
      await unlockDashboard();
    }
  } catch (error) {
    adminToken = "";
  }
}

initializeAdministrationPage();
