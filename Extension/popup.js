const API_URL = "http://127.0.0.1:8000";
const AUTH_TOKEN = "MI_CLAVE_SECRETA_BLINDADA_2026";

let currentUrl = "";
let currentTitle = "";

document.addEventListener("DOMContentLoaded", async () => {
  const titleEl = document.getElementById("video-title");
  const sendBtn = document.getElementById("send-btn");

  // 1. Detectar pestaña actual de YouTube (watch, shorts, live, embed y youtu.be)
  const YT_URL_PATTERNS = [
    "youtube.com/watch",
    "youtube.com/shorts/",
    "youtube.com/live/",
    "youtube.com/embed/",
    "youtu.be/"
  ];
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (tab && tab.url && YT_URL_PATTERNS.some((pattern) => tab.url.includes(pattern))) {
    currentUrl = tab.url;
    currentTitle = tab.title.replace(" - YouTube", "").trim();
    titleEl.textContent = currentTitle;
  } else {
    titleEl.textContent = "⚠️ Abre un video de YouTube primero.";
    sendBtn.disabled = true;
  }

  // 2. Restaurar y persistir las preferencias del usuario (permiso "storage")
  const PREFERENCE_FIELDS = {
    mode: "mode",
    destination: "destination",
    videoFormat: "video-format",
    audioFormat: "audio-format"
  };
  const savedPrefs = await chrome.storage.local.get(
    ["mode", "destination", "videoFormat", "audioFormat", "splitChapters"]
  );
  Object.entries(PREFERENCE_FIELDS).forEach(([key, elementId]) => {
    const select = document.getElementById(elementId);
    const savedValue = savedPrefs[key];
    if (savedValue && Array.from(select.options).some((option) => option.value === savedValue)) {
      select.value = savedValue;
    }
    select.addEventListener("change", () => chrome.storage.local.set({ [key]: select.value }));
  });
  const splitBox = document.getElementById("split-chapters");
  splitBox.checked = Boolean(savedPrefs.splitChapters);
  splitBox.addEventListener("change", () => chrome.storage.local.set({ splitChapters: splitBox.checked }));

  // 3. Enviar tarea al servidor local
  sendBtn.addEventListener("click", async () => {
    const mode = document.getElementById("mode").value;
    const destination = document.getElementById("destination").value;
    const splitChapters = document.getElementById("split-chapters").checked;
    const videoFormat = document.getElementById("video-format").value;
    const audioFormat = document.getElementById("audio-format").value;

    sendBtn.disabled = true;
    sendBtn.textContent = "Añadiendo a la cola...";

    try {
      const res = await fetch(`${API_URL}/enqueue`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Auth-Token": AUTH_TOKEN
        },
        body: JSON.stringify({
          url: currentUrl,
          title: currentTitle,
          mode: mode,
          destination: destination,
          split_chapters: splitChapters,
          video_format: videoFormat,
          audio_format: audioFormat
        })
      });

      if (!res.ok) {
        const err = await res.json();
        const detail = Array.isArray(err.detail)
          ? err.detail.map((item) => item.msg).join("; ")
          : err.detail;
        alert("Error: " + (detail || "No se pudo encolar"));
      }
      await updateStatus();
    } catch (error) {
      alert("No se pudo conectar con el servidor local (127.0.0.1:8000). Asegúrate de que esté encendido.");
    } finally {
      sendBtn.disabled = false;
      sendBtn.textContent = "Enviar a la Cola";
    }
  });

  // 4. Actualizar cola, última tarea y espacio en disco cada 2 segundos
  updateStatus();
  setInterval(updateStatus, 2000);
});

async function updateStatus() {
  try {
    const res = await fetch(`${API_URL}/status`, {
      headers: { "X-Auth-Token": AUTH_TOKEN }
    });
    if (!res.ok) return;
    const data = await res.json();

    // Espacio en disco
    const diskBadge = document.getElementById("disk-badge");
    const diskWarning = document.getElementById("disk-warning");
    const diskThreshold = document.getElementById("disk-threshold");
    diskBadge.textContent = `Libre: ${data.free_space_gb} GB`;
    if (data.min_free_disk_gb !== undefined) {
      diskThreshold.textContent = data.min_free_disk_gb;
    }
    diskWarning.classList.toggle("hidden", !data.low_disk_warning);

    // Tarea actual (textContent evita inyección de HTML desde títulos maliciosos)
    const activeEl = document.getElementById("active-task");
    activeEl.textContent = "";
    if (data.current_task) {
      const head = document.createElement("strong");
      head.textContent = `⚡ Procesando (${data.current_task.mode.toUpperCase()}):`;
      const titleLine = document.createElement("div");
      titleLine.textContent = data.current_task.title;
      const progressLine = document.createElement("span");
      progressLine.style.color = "#10B981";
      progressLine.textContent = data.current_task.progress;
      activeEl.append(head, document.createElement("br"), titleLine, progressLine);
    } else {
      activeEl.textContent = "🟢 Servidor libre. Esperando órdenes.";
    }

    // Resultado de la última tarea terminada (éxito o fallo con motivo)
    const lastEl = document.getElementById("last-task");
    if (data.last_task) {
      lastEl.classList.remove("hidden");
      lastEl.classList.toggle("ok-card", data.last_task.status === "done");
      lastEl.classList.toggle("failed-card", data.last_task.status === "failed");
      lastEl.textContent = "";
      const lastHead = document.createElement("strong");
      lastHead.textContent = data.last_task.status === "done"
        ? "✅ Última tarea completada:"
        : "❌ Última tarea falló:";
      const lastDetail = document.createElement("div");
      lastDetail.textContent = `${data.last_task.mode.toUpperCase()} · ${data.last_task.detail}`;
      lastEl.append(lastHead, document.createElement("br"), lastDetail);
    } else {
      lastEl.classList.add("hidden");
    }

    // Lista en espera
    const queueCount = document.getElementById("queue-count");
    const queueList = document.getElementById("queue-list");
    queueCount.textContent = data.pending_queue.length;
    queueList.textContent = "";

    data.pending_queue.forEach((item, index) => {
      const li = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = `#${index + 1} - ${item.title.substring(0, 28)}...`;
      const modeTag = document.createElement("span");
      modeTag.textContent = `[${item.mode}]`;
      li.append(label, modeTag);
      queueList.appendChild(li);
    });
  } catch (e) {
    document.getElementById("active-task").textContent = "🔴 Servidor local apagado.";
  }
}