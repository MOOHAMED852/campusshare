const API_BASE = window.MABIBLIO_API_BASE || "";
const API_ENDPOINT = `${API_BASE}/api/resources`;
const errorMessage = document.querySelector("#detail-error");
const detail = document.querySelector("#resource-detail");

function setMetadata(id, value) {
  document.querySelector(id).textContent = value || "Non renseigné";
}

function getSafeUrl(value) {
  if (!value) return "";
  try {
    const url = new URL(value, window.location.href);
    return ["http:", "https:"].includes(url.protocol) ? url.href : "";
  } catch {
    return "";
  }
}

function getDownloadUrl(resource) {
  return getSafeUrl(resource.downloadUrl || resource.fileUrl || `${API_ENDPOINT}/${encodeURIComponent(resource.id)}/download`);
}

function showDemoResource() {
  document.title = "Exemple de document — MaBiblio";
  setMetadata("#detail-category", "EXEMPLE DE PRÉSENTATION");
  setMetadata("#detail-title", "Votre document apparaîtra ici");
  setMetadata("#detail-path", "Aperçu de démonstration · Aucun document publié");
  [
    "#detail-level",
    "#detail-major",
    "#detail-year",
    "#detail-semester",
    "#detail-module",
    "#detail-document-type",
    "#detail-exam-type",
    "#detail-viewers",
    "#detail-downloads",
  ].forEach((selector) => setMetadata(selector, "—"));

  const cover = document.createElement("div");
  cover.className = "detail-document-cover detail-placeholder-cover";
  const badge = document.createElement("span");
  badge.className = "detail-placeholder-badge";
  badge.textContent = "PDF";
  const title = document.createElement("strong");
  title.textContent = "Aperçu du document";
  const note = document.createElement("span");
  note.textContent = "Le fichier apparaîtra ici après approbation";
  cover.append(badge, title, note);
  document.querySelector("#detail-preview").append(cover);
  document.querySelector("#detail-demo-note").textContent =
    "Cette fiche montre la présentation d’un document. Les informations et statistiques réelles apparaîtront après publication.";
  document.querySelector("#detail-demo-note").hidden = false;
  document.querySelector("#detail-download").hidden = true;
  document.querySelector("#detail-demo-download").hidden = false;
  detail.hidden = false;
}

async function loadResource() {
  const params = new URLSearchParams(window.location.search);
  if (params.get("demo") === "1") {
    showDemoResource();
    return;
  }
  const id = params.get("id");
  if (!id) {
    errorMessage.textContent = "Cette ressource est introuvable.";
    errorMessage.hidden = false;
    return;
  }

  try {
    const response = await fetch(`${API_ENDPOINT}/${encodeURIComponent(id)}?status=approved`, {
      headers: { Accept: "application/json" },
    });
    if (!response.ok) throw new Error(response.status === 404 ? "Cette ressource est introuvable ou n’est pas approuvée." : `Le serveur a répondu ${response.status}.`);
    const payload = await response.json();
    const resource = payload.resource || payload;
    if (!(String(resource.status || "").toLowerCase() === "approved" || resource.approved === true)) {
      throw new Error("Cette ressource n’est pas approuvée.");
    }

    document.title = `${resource.title || "Ressource"} — MaBiblio`;
    const categoryLabels = { Exams: "Examens", Courses: "Cours", "TD & TP": "TD & TP" };
    setMetadata("#detail-category", categoryLabels[resource.category || resource.type] || resource.category || resource.type);
    setMetadata("#detail-title", resource.title);
    setMetadata("#detail-path", [resource.academicLevel, resource.major, resource.academicYear, resource.semester, resource.module].filter(Boolean).join(" · "));
    setMetadata("#detail-level", resource.academicLevel);
    setMetadata("#detail-major", resource.major);
    setMetadata("#detail-year", resource.academicYear);
    setMetadata("#detail-semester", resource.semester);
    setMetadata("#detail-module", resource.module);
    const documentTypeLabels = { Exam: "Examen", Course: "Cours", TD: "TD", TP: "TP", Correction: "Correction" };
    setMetadata("#detail-document-type", documentTypeLabels[resource.documentType] || resource.documentType);
    setMetadata("#detail-exam-type", resource.examType === "Normal Session" ? "Session normale" : resource.examType === "Rattrapage" ? "Rattrapage" : resource.examType);
    setMetadata("#detail-viewers", Number.isSafeInteger(resource.viewerCount) ? resource.viewerCount.toLocaleString("fr-FR") : "—");
    setMetadata("#detail-downloads", Number.isSafeInteger(resource.downloadCount) ? resource.downloadCount.toLocaleString("fr-FR") : "—");
    if (resource.hasCorrection) {
      setMetadata("#detail-correction-downloads", Number.isSafeInteger(resource.correctionDownloadCount) ? resource.correctionDownloadCount.toLocaleString("fr-FR") : "—");
      document.querySelector("#correction-downloads-row").hidden = false;
    }

    const previewUrl = getSafeUrl(resource.previewUrl);
    const previewType = String(resource.previewType || resource.fileType || "").toLowerCase();
    const preview = document.querySelector("#detail-preview");
    if (previewUrl && (/\.pdf(?:[?#]|$)/i.test(previewUrl) || previewType.includes("pdf"))) {
      const frame = document.createElement("iframe");
      frame.src = `${previewUrl}#page=1&toolbar=0&navpanes=0`;
      frame.title = `Aperçu PDF : ${resource.title}`;
      preview.append(frame);
    } else if (previewUrl && (/\.(png|jpe?g|webp|gif|svg)(?:[?#]|$)/i.test(previewUrl) || previewType.includes("image"))) {
      const image = document.createElement("img");
      image.src = previewUrl;
      image.alt = `Aperçu de ${resource.title}`;
      preview.append(image);
    } else {
      const cover = document.createElement("div");
      cover.className = "detail-document-cover";
      cover.textContent = resource.module || resource.fileType || "Document académique";
      preview.append(cover);
    }

    const downloadLink = document.querySelector("#detail-download");
    const url = getDownloadUrl(resource);
    if (!url) throw new Error("Le lien de téléchargement de cette ressource est invalide.");
    downloadLink.href = url;
    downloadLink.setAttribute("download", "");
    if (resource.hasCorrection && getSafeUrl(resource.correctionDownloadUrl)) {
      const correctionLink = document.querySelector("#detail-correction");
      correctionLink.href = getSafeUrl(resource.correctionDownloadUrl);
      correctionLink.setAttribute("download", "");
      correctionLink.hidden = false;
    }
    detail.hidden = false;
  } catch (error) {
    errorMessage.textContent = `Impossible de charger cette ressource : ${error.message}`;
    errorMessage.hidden = false;
  }
}

loadResource();
