const $ = (selector) => document.querySelector(selector);

const elements = {
  fileInput: $("#fileInput"),
  dropzone: $("#dropzone"),
  selectedFile: $("#selectedFile"),
  fileName: $("#fileName"),
  fileMeta: $("#fileMeta"),
  clearFile: $("#clearFile"),
  startButton: $("#startButton"),
  modelSize: $("#modelSize"),
  sourceLanguage: $("#sourceLanguage"),
  acceleration: $("#acceleration"),
  cudaOption: $("#cudaOption"),
  burnSubtitles: $("#burnSubtitles"),
  uploadProgress: $("#uploadProgress"),
  uploadLabel: $("#uploadLabel"),
  uploadPercent: $("#uploadPercent"),
  uploadBar: $("#uploadBar"),
  jobsList: $("#jobsList"),
  refreshButton: $("#refreshButton"),
  serviceStatus: $("#serviceStatus"),
  resultPanel: $("#resultPanel"),
  resultVideo: $("#resultVideo"),
  resultBadge: $("#resultBadge"),
  resultTitle: $("#resultTitle"),
  resultDescription: $("#resultDescription"),
  subtitleDownload: $("#subtitleDownload"),
  videoDownload: $("#videoDownload"),
  closeResult: $("#closeResult"),
  toast: $("#toast"),
};

let selectedFile = null;
let jobs = [];
let toastTimer;
let maxUploadBytes = 4096 * 1024 * 1024;
let activeResultId = null;

const allowedExtensions = ["mp4", "mov", "mkv", "avi", "webm", "m4v", "mpeg", "mpg", "ts"];

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function formatBytes(bytes) {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index ? 1 : 0)} ${units[index]}`;
}

function formatDate(value) {
  const date = new Date(value);
  return Number.isNaN(date.valueOf())
    ? "刚刚"
    : new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit" }).format(date);
}

function showToast(message, isError = false) {
  clearTimeout(toastTimer);
  elements.toast.textContent = message;
  elements.toast.className = `toast visible${isError ? " error" : ""}`;
  toastTimer = setTimeout(() => (elements.toast.className = "toast"), 3600);
}

function chooseFile(file) {
  if (!file) return;
  const extension = file.name.split(".").pop().toLowerCase();
  if (!allowedExtensions.includes(extension)) {
    showToast("暂不支持这种视频格式，请选择 MP4、MOV、MKV、AVI 或 WebM。", true);
    return;
  }
  if (!file.size || file.size > maxUploadBytes) {
    showToast(`请选择非空文件，最大 ${formatBytes(maxUploadBytes)}。`, true);
    return;
  }
  selectedFile = file;
  elements.fileName.textContent = file.name;
  elements.fileMeta.textContent = `${formatBytes(file.size)} · ${extension.toUpperCase()} 视频`;
  elements.dropzone.hidden = true;
  elements.selectedFile.hidden = false;
  elements.startButton.disabled = false;
}

function clearFile() {
  selectedFile = null;
  elements.fileInput.value = "";
  elements.dropzone.hidden = false;
  elements.selectedFile.hidden = true;
  elements.startButton.disabled = true;
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const health = await response.json();
    maxUploadBytes = health.max_upload_mb * 1024 * 1024;
    $(".drop-subtitle").textContent = `或点击选择本地文件 · 最大 ${formatBytes(maxUploadBytes)}`;
    if (!elements.modelSize.dataset.userSelected &&
        [...elements.modelSize.options].some((option) => option.value === health.default_model)) {
      elements.modelSize.value = health.default_model;
    }
    elements.serviceStatus.className = `service-status ${health.ffmpeg_ready ? "ready" : "warning"}`;
    const cudaReady = Boolean(health.acceleration?.cuda_available);
    const encoderCount = health.acceleration?.video_encoders?.length || 0;
    elements.serviceStatus.querySelector("span:last-child").textContent = health.ffmpeg_ready
      ? `服务已就绪 · ${cudaReady ? "CUDA" : encoderCount ? "GPU 编码" : "CPU"}`
      : "需要安装 FFmpeg";
    elements.serviceStatus.title = health.message;
    elements.cudaOption.textContent = cudaReady
      ? "NVIDIA CUDA · 已就绪"
      : health.acceleration?.cuda_device_count
        ? "NVIDIA CUDA · 运行库未就绪"
        : "NVIDIA CUDA · 未检测";
  } catch {
    elements.serviceStatus.className = "service-status warning";
    elements.serviceStatus.querySelector("span:last-child").textContent = "服务连接失败";
  }
}

function statusLabel(job) {
  return { queued: "等待中", processing: "处理中", completed: "已完成", failed: "失败", cancelling: "正在取消", cancelled: "已取消" }[job.status] || job.status;
}

function renderJobs() {
  if (!jobs.length) {
    elements.jobsList.innerHTML = `
      <div class="empty-state">
        <span>空</span><strong>还没有处理任务</strong><small>上传视频后，进度会显示在这里</small>
      </div>`;
    return;
  }
  elements.jobsList.innerHTML = jobs
    .map(
      (job) => `
      <article class="job-item ${escapeHtml(job.status)}" data-job-id="${escapeHtml(job.id)}" ${job.status === "completed" ? 'role="button" tabindex="0"' : ""}>
        <div class="job-top">
          <div class="job-file">
            <strong title="${escapeHtml(job.filename)}">${escapeHtml(job.filename)}</strong>
            <small>${escapeHtml(job.stage)} · ${formatDate(job.created_at)}</small>
          </div>
          <span class="job-status">${statusLabel(job)}</span>
        </div>
        ${job.status !== "failed" ? `<div class="job-progress"><i style="width:${Math.max(0, Math.min(100, job.progress))}%"></i></div>` : ""}
        <div class="job-actions">
          ${["failed", "cancelled"].includes(job.status) ? '<button type="button" class="secondary-button" data-action="retry">继续重试</button>' : ""}
          ${["queued", "processing"].includes(job.status) ? '<button type="button" class="secondary-button" data-action="cancel">取消任务</button>' : ""}
          ${["completed", "failed", "cancelled"].includes(job.status) ? '<button type="button" class="secondary-button" data-action="delete">删除文件</button>' : ""}
          ${job.downloads.subtitle ? `<a href="${job.downloads.subtitle}" download>下载字幕</a>` : ""}
        </div>
        ${job.error ? `<p class="job-error">${escapeHtml(job.error)}</p>` : ""}
      </article>`,
    )
    .join("");
}

async function loadJobs(silent = true) {
  try {
    const response = await fetch("/api/jobs", { cache: "no-store" });
    if (!response.ok) throw new Error("任务列表加载失败");
    jobs = await response.json();
    renderJobs();
  } catch (error) {
    if (!silent) showToast(error.message, true);
  }
}

function uploadVideo() {
  if (!selectedFile) return;
  if (elements.modelSize.value === "distil-large-v3" && elements.sourceLanguage.value !== "en") {
    showToast("Distil Large v3 仅支持英语，请选择英语或换用其他模型。", true);
    return;
  }
  const form = new FormData();
  form.append("file", selectedFile);
  form.append("model_size", elements.modelSize.value);
  form.append("source_language", elements.sourceLanguage.value);
  form.append("acceleration", elements.acceleration.value);
  form.append("burn_subtitles", elements.burnSubtitles.checked ? "true" : "false");

  elements.startButton.disabled = true;
  elements.uploadProgress.hidden = false;
  elements.uploadLabel.textContent = "正在上传";
  elements.uploadPercent.textContent = "0%";
  elements.uploadBar.style.width = "0%";
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/jobs");
  xhr.upload.addEventListener("progress", (event) => {
    if (!event.lengthComputable) return;
    const value = Math.round((event.loaded / event.total) * 100);
    elements.uploadPercent.textContent = `${value}%`;
    elements.uploadBar.style.width = `${value}%`;
  });
  xhr.addEventListener("load", async () => {
    elements.startButton.disabled = false;
    if (xhr.status >= 200 && xhr.status < 300) {
      elements.uploadLabel.textContent = "上传完成，开始处理";
      elements.uploadPercent.textContent = "100%";
      elements.uploadBar.style.width = "100%";
      showToast("视频已加入处理队列");
      clearFile();
      setTimeout(() => (elements.uploadProgress.hidden = true), 1200);
      await loadJobs(false);
    } else {
      let message = "上传失败，请稍后重试";
      try { message = JSON.parse(xhr.responseText).detail || message; } catch { /* noop */ }
      showToast(message, true);
      elements.uploadProgress.hidden = true;
    }
  });
  xhr.addEventListener("error", () => {
    elements.startButton.disabled = false;
    elements.uploadProgress.hidden = true;
    showToast("网络连接中断，视频上传失败。", true);
  });
  xhr.send(form);
}

function openResult(job) {
  if (!job || job.status !== "completed") return;
  if (editorJobId && editorJobId !== job.id && !closeEditor()) return;
  activeResultId = job.id;
  const type = job.is_bilingual ? "上方原文 + 下方简体中文双语字幕" : "简体中文字幕";
  elements.resultBadge.textContent = `${job.language_name || "已识别"} · ${job.is_bilingual ? "双语" : "单语"}字幕`;
  elements.resultTitle.textContent = job.filename;
  const hardware = job.hardware_used ? ` 使用硬件：${job.hardware_used}。` : "";
  const languageMethod = job.source_language && job.source_language !== "auto" ? "已按指定语言" : "语种识别完成";
  elements.resultDescription.textContent = `${languageMethod}，已生成${type}。${job.downloads.video ? "同时完成了字幕压制。" : "你可以下载 SRT 文件并导入剪辑软件。"}${hardware}`;
  elements.subtitleDownload.href = `${job.downloads.subtitle}?v=${encodeURIComponent(job.updated_at)}`;
  elements.resultVideo.querySelectorAll("track").forEach((track) => track.remove());
  elements.resultVideo.src = `${job.downloads.video || job.downloads.source}?v=${encodeURIComponent(job.updated_at)}`;
  if (!job.downloads.video && job.downloads.preview) {
    const track = document.createElement("track");
    track.kind = "subtitles";
    track.label = job.is_bilingual ? "双语字幕" : "简体中文";
    track.srclang = "zh";
    track.src = `${job.downloads.preview}?v=${encodeURIComponent(job.updated_at)}`;
    track.default = true;
    track.addEventListener("load", () => { track.track.mode = "showing"; });
    elements.resultVideo.appendChild(track);
  }
  $("#assDownload").href = `${job.downloads.ass}?v=${encodeURIComponent(job.updated_at)}`;
  $("#vttDownload").hidden = !job.downloads.preview;
  $("#vttDownload").href = job.downloads.preview || "#";
  if (job.downloads.video) {
    elements.videoDownload.hidden = false;
    elements.videoDownload.href = `${job.downloads.video}?v=${encodeURIComponent(job.updated_at)}`;
  } else {
    elements.videoDownload.hidden = true;
  }
  elements.resultPanel.hidden = false;
  elements.resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

elements.dropzone.addEventListener("click", () => elements.fileInput.click());
elements.fileInput.addEventListener("change", () => chooseFile(elements.fileInput.files[0]));
elements.modelSize.addEventListener("change", () => (elements.modelSize.dataset.userSelected = "true"));
elements.clearFile.addEventListener("click", clearFile);
elements.startButton.addEventListener("click", uploadVideo);
elements.refreshButton.addEventListener("click", () => loadJobs(false));
elements.closeResult.addEventListener("click", () => {
  if (!closeEditor()) return;
  elements.resultPanel.hidden = true;
  elements.resultVideo.pause();
  elements.resultVideo.removeAttribute("src");
  elements.resultVideo.load();
});

["dragenter", "dragover"].forEach((name) =>
  elements.dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    elements.dropzone.classList.add("dragging");
  }),
);
["dragleave", "drop"].forEach((name) =>
  elements.dropzone.addEventListener(name, (event) => {
    event.preventDefault();
    elements.dropzone.classList.remove("dragging");
  }),
);
elements.dropzone.addEventListener("drop", (event) => chooseFile(event.dataTransfer.files[0]));

elements.jobsList.addEventListener("click", async (event) => {
  const button = event.target.closest("[data-action]");
  if (button) {
    event.stopPropagation();
    const id = button.closest("[data-job-id]").dataset.jobId;
    const action = button.dataset.action;
    if (action === "delete" && !confirm("删除此任务及其上传文件和输出文件？此操作无法撤销。")) return;
    button.disabled = true;
    try {
      const response = await fetch(`/api/jobs/${id}${action === "delete" ? "" : `/${action}`}`, {
        method: action === "delete" ? "DELETE" : "POST",
      });
      if (!response.ok) throw new Error((await response.json()).detail || "操作失败");
      if (action === "delete" && activeResultId === id) elements.closeResult.click();
      showToast({ retry: "已加入队列，将复用已完成的步骤", cancel: "正在停止任务", delete: "任务文件已删除" }[action]);
      await loadJobs(false);
    } catch (error) { showToast(error.message, true); button.disabled = false; }
    return;
  }
  if (event.target.closest("a")) return;
  const item = event.target.closest("[data-job-id]");
  if (item) openResult(jobs.find((job) => job.id === item.dataset.jobId));
});
elements.jobsList.addEventListener("keydown", (event) => {
  if (event.target.closest("button, a")) return;
  if (event.key !== "Enter" && event.key !== " ") return;
  const item = event.target.closest("[data-job-id]");
  if (item) openResult(jobs.find((job) => job.id === item.dataset.jobId));
});

checkHealth();
loadJobs();
setInterval(() => {
  if (jobs.some((job) => ["queued", "processing", "cancelling"].includes(job.status))) loadJobs();
}, 2000);

let editorJobId = null;
let editorRevision = null;
let editorDirty = false;
let editorBusy = false;

async function apiJson(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json();
  if (!response.ok) {
    const detail = typeof body.detail === "string" ? body.detail : "请检查时间范围和字幕内容后重试。";
    throw new Error(detail);
  }
  return body;
}

function closeEditor() {
  if (editorBusy) { showToast("正在保存，请稍候。", true); return false; }
  if (editorDirty && !confirm("尚有未保存的字幕修改，放弃这些修改？")) return false;
  $("#subtitleEditor").hidden = true;
  editorJobId = null;
  editorDirty = false;
  return true;
}

$("#editSubtitles").addEventListener("click", async () => {
  if (!activeResultId || !closeEditor()) return;
  const id = activeResultId;
  const button = $("#editSubtitles");
  button.disabled = true;
  try {
    const data = await apiJson(`/api/jobs/${id}/segments`);
    if (activeResultId !== id || elements.resultPanel.hidden) return;
    editorJobId = id;
    editorRevision = data.revision;
    $("#subtitleRows").innerHTML = data.segments.map((segment, index) => `
      <div class="subtitle-row">
        <button class="secondary-button" type="button" data-seek="${index}">第 ${index + 1} 条</button>
        <label>开始时间<input type="number" step="0.01" min="0" data-field="start" value="${segment.start}" /></label>
        <label>结束时间<input type="number" step="0.01" min="0" data-field="end" value="${segment.end}" /></label>
        <label>原文<textarea data-field="text">${escapeHtml(segment.text)}</textarea></label>
        ${data.bilingual ? `<label>中文译文<textarea data-field="translation">${escapeHtml(segment.translation || "")}</textarea></label>` : ""}
      </div>`).join("");
    $("#editorStatus").textContent = `${data.segments.length} 条字幕 · 点击编号跳转到对应视频时间`;
    $("#subtitleEditor").hidden = false;
    $("#subtitleEditor").scrollIntoView({behavior:"smooth", block:"start"});
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; }
});

$("#subtitleRows").addEventListener("input", () => { editorDirty = true; });
$("#subtitleRows").addEventListener("click", (event) => {
  const button = event.target.closest("[data-seek]");
  if (!button) return;
  const row = button.closest(".subtitle-row");
  const start = Number(row.querySelector('[data-field="start"]').value);
  if (Number.isFinite(start) && start >= 0) elements.resultVideo.currentTime = start;
});
$("#closeEditor").addEventListener("click", closeEditor);
$("#saveSubtitles").addEventListener("click", async () => {
  if (!editorJobId || editorBusy) return;
  const segments = [...$("#subtitleRows").querySelectorAll(".subtitle-row")].map((row) => ({
    start: Number(row.querySelector('[data-field="start"]').value),
    end: Number(row.querySelector('[data-field="end"]').value),
    text: row.querySelector('[data-field="text"]').value,
    translation: row.querySelector('[data-field="translation"]')?.value || null,
  }));
  editorBusy = true;
  $("#saveSubtitles").disabled = true;
  $("#subtitleRows").querySelectorAll("input, textarea").forEach((field) => { field.disabled = true; });
  try {
    const result = await apiJson(`/api/jobs/${editorJobId}/segments`, {
      method:"PUT", headers:{"Content-Type":"application/json"},
      body:JSON.stringify({revision:editorRevision, segments}),
    });
    editorRevision = result.revision;
    editorDirty = false;
    $("#editorStatus").textContent = "已保存，字幕下载和预览已更新。带字幕视频需要重新压制。";
    await loadJobs(false);
    openResult(jobs.find((job) => job.id === editorJobId));
    showToast("字幕已保存");
  } catch (error) { showToast(error.message, true); }
  finally {
    editorBusy = false;
    $("#saveSubtitles").disabled = false;
    $("#subtitleRows").querySelectorAll("input, textarea").forEach((field) => { field.disabled = false; });
  }
});
$("#renderVideo").addEventListener("click", async () => {
  if (!activeResultId) return;
  if (editorDirty || editorBusy) { showToast("请先保存字幕修改。", true); return; }
  const button = $("#renderVideo");
  button.disabled = true;
  try {
    await apiJson(`/api/jobs/${activeResultId}/render`, {method:"POST"});
    closeEditor();
    elements.closeResult.click();
    await loadJobs(false);
    showToast("已加入压制队列，复用已有字幕");
  } catch (error) { showToast(error.message, true); }
  finally { button.disabled = false; }
});
window.addEventListener("beforeunload", (event) => {
  if (editorDirty) { event.preventDefault(); event.returnValue = ""; }
});
