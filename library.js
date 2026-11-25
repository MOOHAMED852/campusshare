const LEVELS = ["Tronc Commun", "Licence", "Master", "Cycle Ingénieur"];
const queryParams = new URLSearchParams(window.location.search);
const filters = {
  level: document.querySelector("#library-level"),
  major: document.querySelector("#library-major"),
  category: document.querySelector("#library-category"),
  year: document.querySelector("#library-year"),
  semester: document.querySelector("#library-semester"),
  module: document.querySelector("#library-module"),
  type: document.querySelector("#library-type"),
  examType: document.querySelector("#library-exam-type"),
};
const track = document.querySelector("#library-track");
const viewport = document.querySelector("#library-carousel");
const previous = document.querySelector("#library-prev");
const next = document.querySelector("#library-next");
const scrollPrevious = document.querySelector("#library-scroll-prev");
const scrollNext = document.querySelector("#library-scroll-next");
let academicYears = [];
let currentPage = 0;
let total = 0;
let searchTerm = queryParams.get("search") || "";

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[character]);
}

async function apiJson(url) {
  const response = await fetch(url);
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `Le serveur a répondu ${response.status}.`);
  return result;
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
  const labels = { Exam: "Examen", Course: "Cours", TD: "TD", TP: "TP", Correction: "Correction" };
  return labels[type] || type;
}

function resourceCard(resource) {
  const title = escapeHtml(resource.title);
  const path = [resource.academicLevel, resource.major, resource.module, resource.semester, resource.academicYear]
    .filter(Boolean).map(escapeHtml).join(" · ");
  const correctionLink = resource.hasCorrection
    ? `<a class="resource-correction" href="${escapeHtml(resource.correctionDownloadUrl)}" download>Correction</a>`
    : "";
  return `<article class="resource-card">
    <a class="resource-detail-link" href="/resource.html?id=${encodeURIComponent(resource.id)}" aria-label="Voir ${title}">
      <div class="resource-cover"><iframe class="resource-preview-frame" src="${escapeHtml(resource.previewUrl)}#page=1&toolbar=0&navpanes=0" title="Aperçu PDF : ${title}" loading="lazy" tabindex="-1"></iframe><span class="file-type">PDF</span></div>
      <div class="resource-info"><div class="resource-label">${escapeHtml(documentTypeLabel(resource.documentType) || categoryLabel(resource.category))}</div><h3>${title}</h3><p class="resource-academic-path">${path}</p>${resource.examType ? `<p class="resource-module">${escapeHtml(resource.examType === "Normal Session" ? "Session normale" : "Rattrapage")}</p>` : ""}</div>
    </a>
    <div class="resource-card-footer">
      <span class="resource-stat" aria-label="${resource.viewerCount} vues"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M2 10s2.8-5 8-5 8 5 8 5-2.8 5-8 5-8-5-8-5Z"/><circle cx="10" cy="10" r="2.2"/></svg>${resource.viewerCount}</span>
      <span class="resource-stat" aria-label="${resource.downloadCount} téléchargements"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="M10 2.5v10m0 0 3.5-3.5M10 12.5 6.5 9M3.5 13v3.5h13V13"/></svg>${resource.downloadCount}</span>
      ${correctionLink}<a class="resource-download" href="${escapeHtml(resource.downloadUrl)}" download aria-label="Télécharger ${title}">Télécharger</a>
    </div>
  </article>`;
}

function setPageArrows() {
  previous.disabled = currentPage <= 0;
  next.disabled = (currentPage + 1) * 8 >= total;
}

function updateScrollArrows() {
  scrollPrevious.disabled = viewport.scrollLeft <= 1;
  scrollNext.disabled = viewport.scrollLeft + viewport.clientWidth >= viewport.scrollWidth - 1;
}

function selectedFilters() {
  return {
    academicLevel: filters.level.value,
    major: filters.major.value,
    category: filters.category.value,
    academicYear: filters.year.value,
    semester: filters.semester.value,
    module: filters.module.value,
    documentType: filters.type.value,
    examType: filters.examType.value,
  };
}

async function updateFilterOptions() {
  const selected = selectedFilters();
  const scope = new URLSearchParams();
  Object.entries(selected).forEach(([key, value]) => {
    if (value) scope.set(key, value);
  });
  const data = await apiJson(`/api/filters?${scope}`);
  const availableMajors = await apiJson(`/api/majors${selected.academicLevel ? `?level=${encodeURIComponent(selected.academicLevel)}` : ""}`);
  setOptions(filters.major, "Toutes les filières", availableMajors.majors.map((major) => major.name), selected.major);
  setOptions(filters.year, "Toutes les années académiques", academicYears, selected.academicYear);
  setOptions(filters.semester, "Tous les semestres", data.semesters, selected.semester);
  setOptions(filters.module, "Tous les modules", data.modules, selected.module);
  setOptions(filters.type, "Tous les types de documents", data.documentTypes, selected.documentType, { Exam: "Examen", Course: "Cours", TD: "TD", TP: "TP", Correction: "Correction" });
  setOptions(filters.examType, "Tous les types d’examen", data.examTypes, selected.examType, { "Normal Session": "Session normale", Rattrapage: "Rattrapage" });
  document.querySelector("#library-year-wrap").hidden = selected.category !== "Exams";
  document.querySelector("#library-exam-wrap").hidden = selected.category !== "Exams";
  document.querySelector("#library-type-wrap").hidden = selected.category !== "TD & TP";
}

async function loadResources() {
  const params = new URLSearchParams();
  Object.entries(selectedFilters()).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  if (searchTerm) params.set("search", searchTerm);
  params.set("limit", "8");
  params.set("offset", String(currentPage * 8));
  const result = await apiJson(`/api/resources?${params}`);
  total = result.total;
  track.innerHTML = result.resources.map(resourceCard).join("");
  document.querySelector("#library-count").textContent = `${total} document${total === 1 ? "" : "s"} approuvé${total === 1 ? "" : "s"}`;
  document.querySelector("#library-empty").hidden = total > 0;
  document.querySelector("#library-page-status").textContent = total
    ? `Page ${currentPage + 1} · Affichage ${currentPage * 8 + 1}–${Math.min(currentPage * 8 + result.resources.length, total)} sur ${total}`
    : "";
  setPageArrows();
  viewport.scrollTo({ left: 0, behavior: "smooth" });
  requestAnimationFrame(updateScrollArrows);
}

async function refresh() {
  document.querySelector("#library-error").hidden = true;
  try {
    await updateFilterOptions();
    await loadResources();
  } catch (error) {
    document.querySelector("#library-error").textContent = `Impossible de charger la bibliothèque : ${error.message}`;
    document.querySelector("#library-error").hidden = false;
  }
}

async function initialize() {
  try {
    const [levelsData, yearsData] = await Promise.all([apiJson("/api/levels"), apiJson("/api/academic-years")]);
    academicYears = yearsData.academicYears;
    setOptions(filters.level, "Tous les niveaux académiques", levelsData.levels || LEVELS, queryParams.get("academicLevel") || "");
    setOptions(filters.category, "Toutes les catégories", ["Exams", "Courses", "TD & TP"], queryParams.get("category") || "", { Exams: "Examens", Courses: "Cours", "TD & TP": "TD & TP" });
    document.querySelector("#library-search").value = searchTerm;
    for (const [parameter, key] of [["major", "major"], ["academicYear", "year"], ["semester", "semester"], ["module", "module"], ["documentType", "type"], ["examType", "examType"]]) {
      if (queryParams.has(parameter)) filters[key].dataset.initialValue = queryParams.get(parameter);
    }
    await updateFilterOptions();
    Object.values(filters).forEach((select) => {
      if (select.dataset.initialValue) {
        select.value = select.dataset.initialValue;
        delete select.dataset.initialValue;
      }
    });
    await updateFilterOptions();
    await loadResources();
  } catch (error) {
    document.querySelector("#library-error").textContent = `Impossible de charger la bibliothèque : ${error.message}`;
    document.querySelector("#library-error").hidden = false;
  }
}

document.querySelector("#library-filters").addEventListener("submit", (event) => {
  event.preventDefault();
  searchTerm = document.querySelector("#library-search").value.trim();
  currentPage = 0;
  refresh();
});

Object.entries(filters).forEach(([key, select]) => {
  select.addEventListener("change", () => {
    currentPage = 0;
    const downstream = {
      level: ["major", "semester", "module", "type", "examType"],
      major: ["semester", "module", "type", "examType"],
      category: ["year", "semester", "module", "type", "examType"],
      year: ["semester", "module", "examType"],
      semester: ["module", "type", "examType"],
      module: ["type", "examType"],
    }[key] || [];
    downstream.forEach((field) => { filters[field].value = ""; });
    refresh();
  });
});

previous.addEventListener("click", () => {
  if (currentPage > 0) {
    currentPage -= 1;
    loadResources().catch((error) => {
      document.querySelector("#library-error").textContent = error.message;
      document.querySelector("#library-error").hidden = false;
    });
  }
});
next.addEventListener("click", () => {
  if ((currentPage + 1) * 8 < total) {
    currentPage += 1;
    loadResources().catch((error) => {
      document.querySelector("#library-error").textContent = error.message;
      document.querySelector("#library-error").hidden = false;
    });
  }
});
viewport.addEventListener("scroll", setPageArrows, { passive: true });
viewport.addEventListener("scroll", updateScrollArrows, { passive: true });
window.addEventListener("resize", updateScrollArrows);
scrollPrevious.addEventListener("click", () => viewport.scrollBy({ left: -viewport.clientWidth * 0.8, behavior: "smooth" }));
scrollNext.addEventListener("click", () => viewport.scrollBy({ left: viewport.clientWidth * 0.8, behavior: "smooth" }));

initialize();
