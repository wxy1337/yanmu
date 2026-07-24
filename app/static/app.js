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
  return { queued: "等待中", processing: "处理中", completed: "已完成", failed: "失败" }[job.status] || job.status;
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
  const form = new FormData();
  form.append("file", selectedFile);
  form.append("model_size", elements.modelSize.value);
  form.append("acceleration", elements.acceleration.value);
  form.append("burn_subtitles", elements.burnSubtitles.checked ? "true" : "false");

  elements.startButton.disabled = true;
  elements.uploadProgress.hidden = false;
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
  const type = job.is_bilingual ? "上方原文 + 下方简体中文双语字幕" : "简体中文字幕";
  elements.resultBadge.textContent = `${job.language_name || "已识别"} · ${job.is_bilingual ? "双语" : "单语"}字幕`;
  elements.resultTitle.textContent = job.filename;
  const hardware = job.hardware_used ? ` 使用硬件：${job.hardware_used}。` : "";
  elements.resultDescription.textContent = `语种识别完成，已生成${type}。${job.downloads.video ? "同时完成了字幕压制。" : "你可以下载 SRT 文件并导入剪辑软件。"}${hardware}`;
  elements.subtitleDownload.href = job.downloads.subtitle;
  elements.resultVideo.src = job.downloads.video || job.downloads.source;
  if (job.downloads.video) {
    elements.videoDownload.hidden = false;
    elements.videoDownload.href = job.downloads.video;
  } else {
    elements.videoDownload.hidden = true;
  }
  elements.resultPanel.hidden = false;
  elements.resultPanel.scrollIntoView({ behavior: "smooth", block: "start" });
}

elements.dropzone.addEventListener("click", () => elements.fileInput.click());
elements.fileInput.addEventListener("change", () => chooseFile(elements.fileInput.files[0]));
elements.clearFile.addEventListener("click", clearFile);
elements.startButton.addEventListener("click", uploadVideo);
elements.refreshButton.addEventListener("click", () => loadJobs(false));
elements.closeResult.addEventListener("click", () => {
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

elements.jobsList.addEventListener("click", (event) => {
  const item = event.target.closest("[data-job-id]");
  if (item) openResult(jobs.find((job) => job.id === item.dataset.jobId));
});
elements.jobsList.addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") return;
  const item = event.target.closest("[data-job-id]");
  if (item) openResult(jobs.find((job) => job.id === item.dataset.jobId));
});

checkHealth();
loadJobs();
setInterval(() => {
  if (jobs.some((job) => ["queued", "processing"].includes(job.status))) loadJobs();
}, 2000);
