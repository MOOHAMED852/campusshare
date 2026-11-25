const LEVELS = ["Tronc Commun", "Licence", "Master", "Cycle Ingénieur"];
const CATEGORIES = ["Exams", "Courses", "TD & TP"];
const DOCUMENT_TYPES = {
  Exams: ["Exam"],
  Courses: ["Course"],
  "TD & TP": ["TD", "TP", "Correction"],
};

const levelGrid = document.querySelector("#level-grid");
const universityStep = document.querySelector("#university-step");
const levelStep = document.querySelector("#level-step");
const majorGrid = document.querySelector("#major-grid");
const majorStep = document.querySelector("#major-step");
const categoryStep = document.querySelector("#category-step");
const browserStep = document.querySelector("#browser-step");
const wizardSteps = [universityStep, levelStep, majorStep, categoryStep, browserStep];
const wizardSummaries = [
  { row: document.querySelector("#university-summary"), value: document.querySelector("#summary-university") },
  { row: document.querySelector("#level-summary"), value: document.querySelector("#summary-level") },
  { row: document.querySelector("#major-summary"), value: document.querySelector("#summary-major") },
  { row: document.querySelector("#category-summary"), value: document.querySelector("#summary-category") },
];
const browseResources = document.querySelector("#browse-resources");
const academicError = document.querySelector("#academic-error");
const homeResourceError = document.querySelector("#home-resource-error");
const uploadForm = document.querySelector("#upload-form");
const uploadStatus = document.querySelector("#upload-status");
const uploadLevel = document.querySelector("#upload-level");
const uploadMajor = document.querySelector("#upload-major");
const uploadYear = document.querySelector("#upload-year");
const uploadCategory = document.querySelector("#upload-category");
const uploadType = document.querySelector("#upload-type");
const uploadExamType = document.querySelector("#upload-exam-type");
const menuToggle = document.querySelector(".menu-toggle");
const mainNav = document.querySelector(".main-nav");

const academicState = { university: "", level: "", major: "", category: "" };
let academicYears = [];
let currentWizardStep = 0;

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

function renderAcademicWizard() {
  const selections = [
    academicState.university,
    academicState.level,
    academicState.major,
    categoryLabel(academicState.category),
  ];
  wizardSteps.forEach((step, index) => {
    step.hidden = index !== currentWizardStep;
  });
  wizardSummaries.forEach(({ row, value }, index) => {
    value.textContent = selections[index];
    row.hidden = index >= currentWizardStep || !selections[index];
  });
}

function showAcademicStep(index) {
  currentWizardStep = index;
  renderAcademicWizard();
}

function formatCount(value) {
  return Number.isSafeInteger(value) && value >= 0 ? value.toLocaleString("fr-FR") : "—";
}

async function apiJson(url, options) {
  const response = await fetch(url, options);
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.error || `Le serveur a répondu ${response.status}.`);
  return payload;
}

function setOptions(select, placeholder, values, selected = "", labelMap = null) {
  const unique = [...new Set(values.filter(Boolean).map(String))];
  select.replaceChildren(new Option(placeholder, ""));
  unique.forEach((value) => select.add(new Option(labelMap && labelMap[value] ? labelMap[value] : value, value)));
  select.value = unique.includes(selected) ? selected : "";
  select.disabled = unique.length === 0;
  return select.value;
}

function categoryLabel(category) {
  return category === "Exams" ? "Examens" : category === "Courses" ? "Cours" : category === "TD & TP" ? "TD & TP" : category;
}

function documentTypeLabel(type) {
  const labels = {
    Exam: "Examen",
    Course: "Cours",
    TD: "TD",
    TP: "TP",
    Correction: "Correction",
  };
  return labels[type] || type;
}

function documentCard(resource) {
  const title = escapeHtml(resource.title);
  const path = [resource.academicLevel, resource.major, resource.module, resource.semester, resource.academicYear]
    .filter(Boolean).map(escapeHtml).join(" · ");
  const details = `/resource.html?id=${encodeURIComponent(resource.id)}`;
  const preview = escapeHtml(resource.previewUrl || "");
  const download = escapeHtml(resource.downloadUrl || "");
  const correctionLink = resource.hasCorrection
    ? `<a class="resource-correction" href="${escapeHtml(resource.correctionDownloadUrl)}" download>Correction</a>`
    : "";
  return `<article class="resource-card">
    <a class="resource-detail-link" href="${details}" aria-label="Voir ${title}">
      <div class="resource-cover"><iframe class="resource-preview-frame" src="${preview}#page=1&toolbar=0&navpanes=0" title="Aperçu PDF : ${title}" loading="lazy" tabindex="-1"></iframe><span class="file-type">PDF</span></div>
      <div class="resource-info">
        <div class="resource-label">${escapeHtml(documentTypeLabel(resource.documentType) || categoryLabel(resource.category))}</div>
        <h3>${title}</h3>
        <p class="resource-academic-path">${path}</p>
        ${resource.examType ? `<p class="resource-module">${escapeHtml(resource.examType === "Normal Session" ? "Session normale" : "Rattrapage")}</p>` : ""}
      </div>
    </a>
    <div class="resource-card-footer">
      <span class="resource-stat" aria-label="${formatCount(resource.viewerCount)} ${resource.viewerCount === 1 ? "vue" : "vues"}"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M2 10s2.8-5 8-5 8 5 8 5-2.8 5-8 5-8-5-8-5Z"/><circle cx="10" cy="10" r="2.2"/></svg>${formatCount(resource.viewerCount)}</span>
      <span class="resource-stat" aria-label="${formatCount(resource.downloadCount)} ${resource.downloadCount === 1 ? "téléchargement" : "téléchargements"}"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.5v10m0 0 3.5-3.5M10 12.5 6.5 9M3.5 13v3.5h13V13"/></svg>${formatCount(resource.downloadCount)}</span>
      <a class="resource-view" href="${details}" aria-label="Voir le document ${title}">Voir</a>
      ${correctionLink}<a class="resource-download" href="${download}" download aria-label="Télécharger ${title}">Télécharger</a>
    </div>
  </article>`;
}

function emptyDocumentCard(index) {
  return `<article class="resource-card resource-card-placeholder" aria-label="Emplacement de démonstration ${index}, aucun document publié">
    <div class="resource-cover placeholder-cover" aria-hidden="true">
      <svg viewBox="0 0 48 48"><path d="M14 6h13l9 9v27H14z"/><path d="M27 6v10h9M19 25h12M19 31h12M19 37h7"/></svg>
      <span>Aperçu du document</span>
    </div>
    <div class="resource-info" aria-hidden="true">
      <div class="placeholder-line placeholder-label"></div>
      <div class="placeholder-line placeholder-title"></div>
      <div class="placeholder-line placeholder-title-short"></div>
      <div class="placeholder-line placeholder-details"></div>
    </div>
    <div class="resource-card-footer" aria-hidden="true">
      <span class="resource-stat"><svg viewBox="0 0 20 20"><path d="M2 10s2.8-5 8-5 8 5 8 5-2.8 5-8 5-8-5-8-5Z"/><circle cx="10" cy="10" r="2.2"/></svg>—</span>
      <span class="resource-stat"><svg viewBox="0 0 20 20"><path d="M10 2.5v10m0 0 3.5-3.5M10 12.5 6.5 9M3.5 13v3.5h13V13"/></svg>—</span>
      <a class="resource-view" href="/resource.html?demo=1" aria-label="Voir un exemple de page de document">Voir</a>
      <button class="resource-download" type="button" disabled>Télécharger</button>
    </div>
  </article>`;
}

function wireCarousel(viewport, previous, next) {
  const update = () => {
    previous.disabled = viewport.scrollLeft <= 1;
    next.disabled = viewport.scrollLeft + viewport.clientWidth >= viewport.scrollWidth - 1;
  };
  if (viewport.dataset.carouselReady) {
    update();
    return;
  }
  viewport.dataset.carouselReady = "true";
  previous.addEventListener("click", () => viewport.scrollBy({ left: -viewport.clientWidth * 0.8, behavior: "smooth" }));
  next.addEventListener("click", () => viewport.scrollBy({ left: viewport.clientWidth * 0.8, behavior: "smooth" }));
  viewport.addEventListener("scroll", update, { passive: true });
  window.addEventListener("resize", update);
  viewport.updateCarouselArrows = update;
  update();
}

async function loadHomeDocuments() {
  const track = document.querySelector("#home-resource-track");
  const viewport = document.querySelector("#home-carousel");
  const previous = document.querySelector("#home-prev");
  const next = document.querySelector("#home-next");
  const empty = document.querySelector("#empty-home-resources");
  try {
    const data = await apiJson("/api/resources?limit=8");
    track.innerHTML = data.resources.length
      ? data.resources.map(documentCard).join("")
      : Array.from({ length: 4 }, (_, index) => emptyDocumentCard(index + 1)).join("");
    empty.textContent = data.resources.length
      ? ""
      : "Exemple d’affichage : ces emplacements seront remplacés par des documents approuvés.";
    empty.hidden = data.resources.length > 0;
    document.querySelector("#home-gallery-count").textContent = `${data.total} document${data.total === 1 ? "" : "s"} approuvé${data.total === 1 ? "" : "s"}`;
    wireCarousel(viewport, previous, next);
    viewport.updateCarouselArrows();
  } catch (error) {
    homeResourceError.textContent = `Impossible de charger les documents approuvés : ${error.message}`;
    homeResourceError.hidden = false;
  }
}

function showAcademicError(error) {
  academicError.textContent = error.message || String(error);
  academicError.hidden = false;
}

function clearAcademicError() {
  academicError.hidden = true;
  academicError.textContent = "";
}

async function loadLevels() {
  try {
    const data = await apiJson("/api/levels");
    const levels = data.levels.length ? data.levels : LEVELS;
    levelGrid.innerHTML = levels.map((level, index) =>
      `<button class="level-card" type="button" data-level="${escapeHtml(level)}"><span class="level-card-index">0${index + 1}</span><strong>${escapeHtml(level)}</strong><span>Parcourir les ressources <b aria-hidden="true">→</b></span></button>`
    ).join("");
  } catch (error) {
    showAcademicError(error);
    levelGrid.innerHTML = LEVELS.map((level, index) =>
      `<button class="level-card" type="button" data-level="${escapeHtml(level)}"><span class="level-card-index">0${index + 1}</span><strong>${escapeHtml(level)}</strong><span>Parcourir les ressources <b aria-hidden="true">→</b></span></button>`
    ).join("");
  }
}

async function selectLevel(level) {
  if (!academicState.university) {
    showAcademicStep(0);
    document.querySelector("#academic-path").scrollIntoView({ behavior: "smooth", block: "start" });
    return;
  }
  academicState.level = level;
  academicState.major = "";
  academicState.category = "";
  showAcademicStep(2);
  document.querySelector("#selected-level").textContent = `${academicState.university} · ${level}`;
  document.querySelector("#selected-major").textContent = "";
  document.querySelector("#empty-majors").hidden = true;
  majorGrid.replaceChildren();
  clearAcademicError();
  try {
    const data = await apiJson(`/api/majors?level=${encodeURIComponent(level)}`);
    majorGrid.innerHTML = data.majors.map((major) =>
      `<button class="major-card" type="button" data-major="${escapeHtml(major.name)}"><span>${escapeHtml(level)}</span><strong>${escapeHtml(major.name)}</strong><span>Choisir la filière <b aria-hidden="true">→</b></span></button>`
    ).join("");
    document.querySelector("#empty-majors").hidden = data.majors.length > 0;
  } catch (error) {
    showAcademicError(error);
  }
  majorStep.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function selectUniversity(university) {
  academicState.university = university;
  academicState.level = "";
  academicState.major = "";
  academicState.category = "";
  document.querySelector("#selected-university").textContent = university;
  showAcademicStep(1);
  levelStep.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function selectMajor(major) {
  if (!academicState.university || !academicState.level) {
    showAcademicStep(academicState.university ? 1 : 0);
    wizardSteps[currentWizardStep].scrollIntoView({ behavior: "smooth", block: "nearest" });
    return;
  }
  academicState.major = major;
  academicState.category = "";
  document.querySelector("#selected-major").textContent = `${academicState.university} · ${academicState.level} · ${major}`;
  showAcademicStep(3);
  categoryStep.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function selectedBrowseFilters() {
  const query = new URLSearchParams({
    academicLevel: academicState.level,
    major: academicState.major,
    category: academicState.category,
  });
  const values = {
    academicYear: document.querySelector("#browse-year").value,
    semester: document.querySelector("#browse-semester").value,
    module: document.querySelector("#browse-module").value,
    documentType: document.querySelector("#browse-type").value,
    examType: document.querySelector("#browse-exam-type").value,
  };
  Object.entries(values).forEach(([key, value]) => {
    if (value) query.set(key, value);
  });
  return { query, values };
}

async function refreshBrowse() {
  if (!academicState.university || !academicState.level || !academicState.major || !academicState.category) {
    browserStep.hidden = true;
    return;
  }
  const { query, values } = selectedBrowseFilters();
  try {
    const filters = await apiJson(`/api/filters?${query}`);
    const yearSelect = document.querySelector("#browse-year");
    const semesterSelect = document.querySelector("#browse-semester");
    const moduleSelect = document.querySelector("#browse-module");
    const typeSelect = document.querySelector("#browse-type");
    const examSelect = document.querySelector("#browse-exam-type");
    const year = setOptions(yearSelect, "Choisir une année académique", academicYears, values.academicYear);
    const semester = setOptions(semesterSelect, "Choisir un semestre", filters.semesters, values.semester);
    const module = setOptions(moduleSelect, "Choisir un module", filters.modules, values.module);
    const documentType = setOptions(typeSelect, "Tous les types de documents", filters.documentTypes, values.documentType, { Exam: "Examen", Course: "Cours", TD: "TD", TP: "TP", Correction: "Correction" });
    const examType = setOptions(examSelect, "Choisir un type d’examen", filters.examTypes, values.examType, { "Normal Session": "Session normale", Rattrapage: "Rattrapage" });
    document.querySelector("#year-filter-wrap").hidden = academicState.category !== "Exams";
    document.querySelector("#type-filter-wrap").hidden = academicState.category !== "TD & TP";
    document.querySelector("#exam-filter-wrap").hidden = academicState.category !== "Exams";
    document.querySelector("#browser-title").textContent = categoryLabel(academicState.category);

    const requiredSelections = academicState.category === "Exams"
      ? year && semester && module && examType
      : semester && module;
    if (!requiredSelections) {
      browseResources.replaceChildren();
      document.querySelector("#browse-gallery-count").textContent = "";
      document.querySelector("#browse-view-all").href = "/library.html";
      document.querySelector("#empty-browse").textContent = academicState.category === "Exams"
        ? "Choisissez une année académique, un semestre, un module et un type d’examen pour voir les examens correspondants."
        : "Choisissez un semestre et un module pour voir les documents correspondants.";
      document.querySelector("#empty-browse").hidden = false;
      return;
    }

    const { query: resourceQuery } = selectedBrowseFilters();
    resourceQuery.set("limit", "8");
    const data = await apiJson(`/api/resources?${resourceQuery}`);
    browseResources.innerHTML = data.resources.map(documentCard).join("");
    const browseViewport = document.querySelector("#browse-carousel");
    browseViewport.scrollLeft = 0;
    wireCarousel(browseViewport, document.querySelector("#browse-prev"), document.querySelector("#browse-next"));
    browseViewport.updateCarouselArrows();
    document.querySelector("#browse-gallery-count").textContent = `${data.total} document${data.total === 1 ? "" : "s"} approuvé${data.total === 1 ? "" : "s"}`;
    document.querySelector("#browse-view-all").href = `/library.html?${resourceQuery.toString()}`;
    document.querySelector("#empty-browse").textContent = "Aucun document approuvé ne correspond à ces critères.";
    document.querySelector("#empty-browse").hidden = data.resources.length > 0;
  } catch (error) {
    showAcademicError(error);
  }
}

async function selectCategory(category) {
  if (!academicState.university || !academicState.level || !academicState.major) {
    showAcademicStep(!academicState.university ? 0 : !academicState.level ? 1 : 2);
    wizardSteps[currentWizardStep].scrollIntoView({ behavior: "smooth", block: "nearest" });
    return;
  }
  academicState.category = category;
  showAcademicStep(4);
  ["browse-year", "browse-semester", "browse-module", "browse-type", "browse-exam-type"].forEach((id) => {
    document.querySelector(`#${id}`).value = "";
  });
  document.querySelector("#browse-breadcrumb").textContent = `${academicState.university} · ${academicState.level} · ${academicState.major} · ${categoryLabel(category)}`;
  document.querySelector("#year-filter-wrap").hidden = category !== "Exams";
  document.querySelector("#type-filter-wrap").hidden = category !== "TD & TP";
  document.querySelector("#exam-filter-wrap").hidden = category !== "Exams";
  const { query } = selectedBrowseFilters();
  try {
    const data = await apiJson(`/api/filters?${query}`);
    setOptions(document.querySelector("#browse-year"), "Choisir une année académique", academicYears);
    setOptions(document.querySelector("#browse-semester"), "Choisir un semestre", data.semesters);
    setOptions(document.querySelector("#browse-module"), "Choisir un module", data.modules);
    setOptions(document.querySelector("#browse-type"), "Tous les types de documents", data.documentTypes, "", { Exam: "Examen", Course: "Cours", TD: "TD", TP: "TP", Correction: "Correction" });
    setOptions(document.querySelector("#browse-exam-type"), "Choisir un type d’examen", data.examTypes, "", { "Normal Session": "Session normale", Rattrapage: "Rattrapage" });
    document.querySelector("#empty-browse").textContent = category === "Exams"
      ? "Choisissez une année académique, un semestre, un module et un type d’examen pour voir les examens correspondants."
      : "Choisissez un semestre et un module pour voir les documents correspondants.";
    document.querySelector("#empty-browse").hidden = false;
    browseResources.replaceChildren();
  } catch (error) {
    showAcademicError(error);
  }
  browserStep.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

async function loadAcademicOptions() {
  try {
    const [levelsData, yearsData] = await Promise.all([apiJson("/api/levels"), apiJson("/api/academic-years")]);
    academicYears = yearsData.academicYears;
    setOptions(uploadLevel, "Sélectionnez un niveau académique", levelsData.levels);
    setOptions(uploadYear, "Sélectionnez une année académique", academicYears);
    const semesterSelect = uploadForm.elements.semester;
    setOptions(semesterSelect, "Sélectionnez un semestre", Array.from({ length: 10 }, (_, index) => `S${index + 1}`));
  } catch (error) {
    uploadStatus.textContent = `Impossible de charger les options de téléversement : ${error.message}`;
  }
}

async function updateUploadMajors() {
  uploadMajor.disabled = true;
  setOptions(uploadMajor, "Chargement des filières…", []);
  if (!uploadLevel.value) {
    uploadMajor.replaceChildren(new Option("Sélectionnez d’abord un niveau", ""));
    return;
  }
  try {
    const data = await apiJson(`/api/majors?level=${encodeURIComponent(uploadLevel.value)}`);
    setOptions(uploadMajor, data.majors.length ? "Sélectionnez une filière" : "Aucune filière disponible", data.majors.map((major) => major.name));
  } catch (error) {
    uploadStatus.textContent = error.message;
  }
}

function updateUploadCategoryFields() {
  const category = uploadCategory.value;
  const types = DOCUMENT_TYPES[category] || [];
  setOptions(uploadType, "Sélectionnez un type de document", types, "", {
    Exam: "Examen",
    Course: "Cours",
    TD: "TD",
    TP: "TP",
    Correction: "Correction",
  });
  document.querySelector("#upload-exam-wrap").hidden = category !== "Exams";
  document.querySelector("#correction-wrap").hidden = category !== "Exams";
  uploadExamType.required = category === "Exams";
  uploadExamType.disabled = category !== "Exams";
  if (category !== "Exams") uploadExamType.value = "";
}

async function submitUpload(event) {
  event.preventDefault();
  uploadStatus.textContent = "Téléversement du PDF…";
  const submitButton = uploadForm.querySelector("button[type='submit']");
  submitButton.disabled = true;
  try {
    const response = await fetch("/api/resources", { method: "POST", body: new FormData(uploadForm) });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || `The server responded ${response.status}.`);
    uploadStatus.textContent = "Document reçu. Il est en attente d’approbation et apparaîtra dans la bibliothèque une fois approuvé.";
    uploadForm.reset();
    await updateUploadMajors();
    updateUploadCategoryFields();
  } catch (error) {
    uploadStatus.textContent = `Échec du téléversement : ${error.message}`;
  } finally {
    submitButton.disabled = false;
  }
}

document.addEventListener("click", (event) => {
  const universityButton = event.target.closest("[data-university]");
  const levelButton = event.target.closest("[data-level]");
  const majorButton = event.target.closest("[data-major]");
  const categoryButton = event.target.closest("#category-grid [data-category]");
  if (universityButton) selectUniversity(universityButton.dataset.university);
  else if (levelButton) selectLevel(levelButton.dataset.level);
  else if (majorButton) selectMajor(majorButton.dataset.major);
  else if (categoryButton) selectCategory(categoryButton.dataset.category);
});

document.querySelectorAll("[data-edit-step]").forEach((button) => {
  button.addEventListener("click", () => {
    const step = Number(button.dataset.editStep);
    showAcademicStep(step);
    wizardSteps[step].scrollIntoView({ behavior: "smooth", block: "nearest" });
  });
});

["browse-year", "browse-semester", "browse-module", "browse-type", "browse-exam-type"].forEach((id) => {
  document.querySelector(`#${id}`).addEventListener("change", refreshBrowse);
});

document.querySelector("#search-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const query = document.querySelector("#resource-search").value.trim();
  window.location.href = `/library.html${query ? `?search=${encodeURIComponent(query)}` : ""}`;
});
document.querySelectorAll("[data-search]").forEach((button) => {
  button.addEventListener("click", () => {
    window.location.href = `/library.html?search=${encodeURIComponent(button.dataset.search)}`;
  });
});

uploadLevel.addEventListener("change", updateUploadMajors);
uploadCategory.addEventListener("change", updateUploadCategoryFields);
uploadForm.addEventListener("submit", submitUpload);
menuToggle.addEventListener("click", () => {
  const isOpen = menuToggle.getAttribute("aria-expanded") === "true";
  menuToggle.setAttribute("aria-expanded", String(!isOpen));
  menuToggle.setAttribute("aria-label", isOpen ? "Ouvrir la navigation" : "Fermer la navigation");
  mainNav.classList.toggle("open", !isOpen);
});
mainNav.querySelectorAll("a").forEach((link) => {
  link.addEventListener("click", () => {
    menuToggle.setAttribute("aria-expanded", "false");
    menuToggle.setAttribute("aria-label", "Ouvrir la navigation");
    mainNav.classList.remove("open");
  });
});
document.addEventListener("click", (event) => {
  if (!event.target.closest(".home-site-header")) {
    menuToggle.setAttribute("aria-expanded", "false");
    menuToggle.setAttribute("aria-label", "Ouvrir la navigation");
    mainNav.classList.remove("open");
  }
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && menuToggle.getAttribute("aria-expanded") === "true") {
    menuToggle.setAttribute("aria-expanded", "false");
    menuToggle.setAttribute("aria-label", "Ouvrir la navigation");
    mainNav.classList.remove("open");
    menuToggle.focus();
  }
});

loadHomeDocuments();
loadAcademicOptions();
loadLevels();
renderAcademicWizard();
wireCarousel(
  document.querySelector("#home-carousel"),
  document.querySelector("#home-prev"),
  document.querySelector("#home-next"),
);
wireCarousel(
  document.querySelector("#browse-carousel"),
  document.querySelector("#browse-prev"),
  document.querySelector("#browse-next"),
);
