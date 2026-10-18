import os
import re
import sys
import json
import shutil
import asyncio
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional
from fastapi import Depends, FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp

# ================= SOPORTE DE EJECUCIÓN EMPAQUETADA (.exe) =================
# En el ejecutable --noconsole de PyInstaller, sys.stdout/sys.stderr son None y el logging
# de Uvicorn (que escribe en ellos) haría fallar el arranque de forma silenciosa. Los
# redirigimos a un archivo de log junto al .exe: el servidor queda oculto y deja rastro.
if getattr(sys, "frozen", False) and (sys.stdout is None or sys.stderr is None):
    _log_stream = open(Path(sys.executable).resolve().parent / "server.log", "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = _log_stream
    if sys.stderr is None:
        sys.stderr = _log_stream

# ================= CARGA DE VARIABLES DE ENTORNO (.env) =================
def load_env_file(path: Path):
    """Carga un archivo .env sin dependencias extra. No pisa variables ya definidas en el sistema."""
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)

# Directorio de referencia: en un .exe de PyInstaller, __file__ vive en una carpeta temporal,
# así que usamos la carpeta real del ejecutable para poder leer su archivo .env.
if getattr(sys, "frozen", False):
    BASE_DIR = Path(sys.executable).resolve().parent
else:
    BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
load_env_file(PROJECT_ROOT / ".env")
load_env_file(BASE_DIR / ".env")

# ================= CONFIGURACIÓN DE SEGURIDAD Y RUTAS =================
SECRET_TOKEN = os.environ.get("YT_AUTH_TOKEN", "MI_CLAVE_SECRETA_BLINDADA_2026")
MIN_FREE_DISK_GB = float(os.environ.get("YT_MIN_FREE_DISK_GB", "5.0"))
HOST = os.environ.get("YT_HOST", "127.0.0.1")
PORT = int(os.environ.get("YT_PORT", "8000"))
# Navegador del que tomar cookies (chrome/firefox/edge) para saltar verificaciones de bot.
# Vacío = desactivado. Ej.: YT_COOKIES_FROM_BROWSER=chrome
COOKIES_BROWSER = os.environ.get("YT_COOKIES_FROM_BROWSER", "").strip().lower()

BASE_HOME = Path.home()

def _destination_from_env(env_key: str, *default_parts: str) -> Path:
    """Resuelve una ruta de destino desde .env (admite ~) o usa la ruta por defecto."""
    raw_value = os.environ.get(env_key)
    return Path(os.path.expanduser(raw_value)) if raw_value else BASE_HOME.joinpath(*default_parts)

# Ajusta estas rutas en Servidor/.env (plantilla: Servidor/.env.example):
DESTINATIONS = {
    "obsidian": _destination_from_env("YT_DEST_OBSIDIAN", "Documents", "ObsidianVault", "Cursos_YouTube"),
    "gdrive": _destination_from_env("YT_DEST_GDRIVE", "Google Drive", "Cursos_YouTube"),
    "onedrive": _destination_from_env("YT_DEST_ONEDRIVE", "OneDrive", "Cursos_YouTube"),
    "local": _destination_from_env("YT_DEST_LOCAL", "Downloads", "Cursos_YouTube"),
}

# Crear las carpetas automáticamente si no existen (idempotente)
for folder in DESTINATIONS.values():
    folder.mkdir(parents=True, exist_ok=True)

# Valores por defecto cuando la extensión no envía una ruta propia:
#  - Bóveda (para los .md)  -> YT_DEST_OBSIDIAN
#  - Medios (video/audio)   -> YT_DEST_LOCAL (los videos nunca van a la bóveda)
DEFAULT_VAULT = DESTINATIONS["obsidian"]
DEFAULT_MEDIA = DESTINATIONS["local"]

def resolve_user_path(raw_value: Optional[str], default: Path) -> Path:
    """Resuelve una carpeta indicada por el usuario desde la extensión.

    - Vacío => usa la carpeta por defecto del servidor.
    - Admite ~ y exige una ruta absoluta; se crea si no existe (idempotente).
    """
    if not raw_value or not raw_value.strip():
        return default
    expanded = Path(os.path.expanduser(raw_value.strip()))
    if not expanded.is_absolute():
        raise ValueError("La ruta debe ser absoluta (ej: C:\\Users\\TuUsuario\\MiBoveda).")
    try:
        expanded.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ValueError(f"No se pudo crear la carpeta indicada: {exc}")
    return expanded

def resolve_vault_path(vault_path: Optional[str] = None) -> Path:
    """Carpeta de la bóveda de Obsidian donde se escriben los archivos .md."""
    return resolve_user_path(vault_path, DEFAULT_VAULT)

def resolve_media_path(media_path: Optional[str] = None) -> Path:
    """Carpeta donde se descargan los videos/audios (nunca dentro de la bóveda)."""
    return resolve_user_path(media_path, DEFAULT_MEDIA)

# Regex estricta para validar solo URLs de YouTube.
# Acepta: youtube.com/watch | /shorts | /embed | /live | /v y youtu.be (con subdominios m. y music.)
YT_REGEX = re.compile(
    r"^https?://(?:www\.|m\.|music\.)?"
    r"(?:youtube\.com/watch\?(?:[^&#]*&)?v=|youtube\.com/(?:shorts/|embed/|live/|v/)|youtu\.be/)"
    r"[\w-]{11}(?:[?&#]\S*)?$"
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Arranca el worker FIFO al iniciar el servidor y lo detiene al cerrarlo (patrón lifespan)."""
    worker = asyncio.create_task(worker_loop())  # worker_loop se define más abajo en el módulo
    try:
        yield
    finally:
        worker.cancel()

app = FastAPI(title="YT Obsidian & Course Archiver Local Server", lifespan=lifespan)

# CORS: solo se responde a la extensión de Chrome (los navegadores envían Origin chrome-extension://ID).
# Cualquier otro origen (páginas web ajenas) queda sin cabecera CORS y el navegador lo bloquea.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"chrome-extension://[a-p]{32}",
    allow_methods=["GET", "POST"],
    allow_headers=["X-Auth-Token", "Content-Type"],
)

# ================= ESTADO DE LA COLA SECUENCIAL =================
task_queue = asyncio.Queue()
pending_tasks_view = []
current_task_view = None
# Resultado de la última tarea terminada (para que el popup muestre éxito o fallo)
last_task_view = None

class TaskRequest(BaseModel):
    url: str
    title: str
    mode: Literal["md", "both", "video", "audio"]
    # Rutas elegidas por el usuario en la extensión (vacío => valor por defecto del servidor).
    vault_path: Optional[str] = None  # carpeta de la bóveda de Obsidian (solo .md)
    media_path: Optional[str] = None  # carpeta de descargas de video/audio
    split_chapters: bool = False
    video_format: Literal["mp4", "mkv"] = "mp4"
    audio_format: Literal["m4a", "mp3"] = "m4a"

# ================= FUNCIONES DE SEGURIDAD Y UTILIDAD =================
def require_token(x_auth_token: Optional[str] = Header(None)):
    """Dependencia de seguridad: corre ANTES de validar el cuerpo de la petición."""
    if x_auth_token != SECRET_TOKEN:
        raise HTTPException(status_code=403, detail="Token de seguridad inválido.")

def sanitize_filename(name: str) -> str:
    """Elimina cualquier carácter peligroso para evitar ataques Path Traversal."""
    clean = re.sub(r'[\\/*?:"<>|.]', "", name)
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean[:120] or "Curso_YouTube"

# Orden de preferencia de idiomas para la transcripción (español primero, luego inglés)
SUBTITLE_LANGUAGE_PRIORITY = (
    "es", "es-419", "es-ES", "es-MX", "es-orig",
    "en", "en-US", "en-GB", "en-orig",
)

def pick_subtitle_language(info: dict) -> Optional[str]:
    """Elige UN solo idioma de subtítulos (manual o automático).

    Pedir varios idiomas a la vez (p. ej. "es.*") obliga a YouTube a servir decenas de
    pistas autotraducidas y provoca errores HTTP 429 (Too Many Requests).
    Prioridad: español (España/LatAm) → inglés → variantes → idioma original del video.
    """
    available = []
    for source in ("subtitles", "automatic_captions"):
        for lang in (info.get(source) or {}):
            if lang not in available:
                available.append(lang)
    if not available:
        return None
    for lang in SUBTITLE_LANGUAGE_PRIORITY:
        if lang in available:
            return lang
    for prefix in ("es", "en"):
        for lang in available:
            if lang.startswith(prefix):
                return lang
    return available[0]

def get_free_space_gb(folder: Path) -> float:
    total, used, free = shutil.disk_usage(folder)
    return round(free / (1024 ** 3), 2)

def format_timestamp(seconds: float) -> str:
    hrs = int(seconds // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hrs:02d}:{mins:02d}:{secs:02d}" if hrs > 0 else f"{mins:02d}:{secs:02d}"

def yaml_escape(value) -> str:
    """Escapa comillas invertidas, comillas y saltos de línea para que el YAML de Obsidian no se rompa."""
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return re.sub(r"[\r\n]+", " ", text).strip()

def apply_cookies(opts: dict) -> dict:
    """Añade --cookies-from-browser si YT_COOKIES_FROM_BROWSER está definido (evasión de bloqueos)."""
    if COOKIES_BROWSER:
        opts["cookiesfrombrowser"] = (COOKIES_BROWSER,)
    return opts

# ================= CONVERSOR DE SUBTÍTULOS A MARKDOWN (OBSIDIAN) =================
def build_obsidian_markdown(info: dict, sub_path: Optional[Path], output_md: Path):
    title = info.get("title", "Sin título")
    uploader = info.get("uploader", "Desconocido")
    webpage_url = info.get("webpage_url", "")
    video_id = info.get("id", "")
    duration_str = format_timestamp(info.get("duration", 0))
    chapters = info.get("chapters") or []
    date_now = datetime.now().strftime("%Y-%m-%d")

    # 1. Parsear archivo JSON3 de subtítulos de yt-dlp
    segments = []
    if sub_path and sub_path.exists():
        with open(sub_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            for event in data.get("events", []):
                if "segs" in event:
                    text = "".join(s.get("utf8", "") for s in event["segs"]).strip()
                    text = text.replace("\n", " ")
                    if text:
                        start_sec = event.get("tStartMs", 0) / 1000.0
                        segments.append((start_sec, text))

    # 2. Construir cabecera YAML Frontmatter para Obsidian
    lines = [
        "---",
        f'titulo: "{yaml_escape(title)}"',
        f'canal: "{yaml_escape(uploader)}"',
        f'url: "{yaml_escape(webpage_url)}"',
        f'duracion: "{duration_str}"',
        f"fecha_descarga: {date_now}",
        "estado: \"#por-procesar\"",
        "tags:",
        "  - youtube",
        "  - curso",
        "---",
        "",
        f"# {title}",
        f"> 🔗 **Video original:** [{webpage_url}]({webpage_url}) | **Canal:** {uploader} | **Duración:** `{duration_str}`",
        ""
    ]

    # 3. Índice de capítulos con links directos al minuto
    if chapters:
        lines.append("## 📑 Índice del Curso")
        for idx, ch in enumerate(chapters, 1):
            ch_title = ch.get("title", f"Capítulo {idx}")
            start_s = int(ch.get("start_time", 0))
            t_str = format_timestamp(start_s)
            lines.append(f"- [{t_str}](https://youtu.be/{video_id}?t={start_s}s) - **{ch_title}**")
        lines.append("\n---\n")

    lines.append("## 📝 Transcripción Completa\n")

    if not segments:
        lines.append("*⚠️ Este video no cuenta con subtítulos disponibles en YouTube.*")
    elif chapters:
        # Agrupar texto por capítulos del curso (dedup consecutivo continuo entre capítulos)
        last_line = ""
        for ch in chapters:
            ch_title = ch.get("title", "Sección")
            start_s = ch.get("start_time", 0)
            end_s = ch.get("end_time", 999999)
            t_str = format_timestamp(start_s)
            lines.append(f"### {ch_title} ([{t_str}](https://youtu.be/{video_id}?t={int(start_s)}s))")

            ch_texts = []
            for seg_time, seg_text in segments:
                if start_s <= seg_time < end_s and seg_text != last_line:
                    ch_texts.append(seg_text)
                    last_line = seg_text
            lines.append(" ".join(ch_texts) + "\n")
    else:
        # Si el video no tiene capítulos definidos, agrupar en bloques de 5 minutos.
        # Al haber silencios largos, saltamos directamente al bloque que contiene al segmento
        # (sin emitir bloques vacíos ni desfasar los enlaces de tiempo).
        block_seconds = 300
        current_block = 0
        block_texts = []
        last_line = ""
        for seg_time, seg_text in segments:
            if seg_time >= current_block + block_seconds:
                if block_texts:
                    t_str = format_timestamp(current_block)
                    lines.append(f"### Bloque [{t_str}](https://youtu.be/{video_id}?t={int(current_block)}s)")
                    lines.append(" ".join(block_texts) + "\n")
                    block_texts = []
                current_block = int(seg_time // block_seconds) * block_seconds
            if seg_text != last_line:
                block_texts.append(seg_text)
                last_line = seg_text
        if block_texts:
            t_str = format_timestamp(current_block)
            lines.append(f"### Bloque [{t_str}](https://youtu.be/{video_id}?t={int(current_block)}s)")
            lines.append(" ".join(block_texts) + "\n")

    with open(output_md, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

# ================= MOTOR DE PROCESAMIENTO (YT-DLP) =================
def process_item_sync(task: TaskRequest) -> dict:
    """Ejecuta la tarea completa.

    El .md se escribe SIEMPRE en la bóveda elegida; los medios (video/audio) se descargan
    SIEMPRE en la carpeta de descargas elegida, NUNCA dentro de la bóveda.
    Devuelve {"title": str, "detail": str} para el panel de estado del popup.
    """
    global current_task_view

    def progress_hook(d):
        if current_task_view is None:
            return
        if d["status"] == "downloading":
            pct = d.get("_percent_str", "").strip()
            spd = d.get("_speed_str", "").strip()
            current_task_view["progress"] = f"Descargando: {pct} ({spd})"
        elif d["status"] == "finished":
            current_task_view["progress"] = "Procesando y empaquetando archivo..."

    # 0. Metadatos del video (título canónico, capítulos y subtítulos disponibles)
    current_task_view["progress"] = "Obteniendo información del video..."
    ydl_info_opts = apply_cookies({"skip_download": True, "noplaylist": True, "quiet": True})
    with yt_dlp.YoutubeDL(ydl_info_opts) as ydl:
        info = ydl.extract_info(task.url, download=False)
    safe_title = sanitize_filename(info.get("title") or task.title)
    detail_parts = []

    # 1. Transcripción a Markdown -> SIEMPRE a la bóveda (plano, sin subcarpetas)
    if task.mode in ("md", "both"):
        vault_dir = resolve_vault_path(task.vault_path)
        current_task_view["progress"] = "Analizando subtítulos y capítulos..."
        chosen_lang = pick_subtitle_language(info)
        if chosen_lang:
            current_task_view["progress"] = f"Descargando subtítulos ({chosen_lang})..."
        else:
            current_task_view["progress"] = "El video no tiene subtítulos; se generará el .md igualmente."
        # Los subtítulos temporales van a una carpeta temporal del sistema para no ensuciar la bóveda.
        temp_dir = Path(tempfile.mkdtemp(prefix="yt_archiver_sub_"))
        try:
            sub_file = None
            if chosen_lang:
                ydl_sub_opts = apply_cookies({
                    "skip_download": True,
                    "writesubtitles": True,
                    "writeautomaticsub": True,
                    "subtitleslangs": [chosen_lang],
                    "subtitlesformat": "json3",
                    "outtmpl": str(temp_dir / "temp_sub"),
                    "noplaylist": True,
                    "quiet": True,
                })
                with yt_dlp.YoutubeDL(ydl_sub_opts) as ydl:
                    ydl.extract_info(task.url, download=True)
                sub_candidates = sorted(temp_dir.glob("temp_sub*.json3"))
                sub_file = sub_candidates[0] if sub_candidates else None
            build_obsidian_markdown(info, sub_file, vault_dir / f"{safe_title}.md")
            detail_parts.append(f"📝 {vault_dir}")
        finally:
            # Limpieza idempotente (aunque la tarea falle)
            shutil.rmtree(temp_dir, ignore_errors=True)

    # 2. Descarga de Video / Audio -> SIEMPRE a la carpeta de descargas elegida
    if task.mode in ("video", "audio", "both"):
        media_dir = resolve_media_path(task.media_path)
        current_task_view["progress"] = "Preparando descarga de medios..."
        # "%%" protege los porcentajes literales dentro del template de yt-dlp
        outtmpl_title = safe_title.replace("%", "%%")
        ydl_media_opts = apply_cookies({
            "continuedl": True,
            "retries": 10,
            "fragment_retries": 10,
            "noplaylist": True,
            "progress_hooks": [progress_hook],
            "quiet": True,
        })
        postprocessors = []
        if task.mode == "audio":
            ydl_media_opts["format"] = "bestaudio[ext=m4a]/bestaudio"
            if task.audio_format == "mp3":
                postprocessors.append({
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                })
        else:
            ydl_media_opts["format"] = "bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best"
            ydl_media_opts["merge_output_format"] = task.video_format

        if task.split_chapters:
            postprocessors.append({"key": "FFmpegSplitChapters"})
            ydl_media_opts["outtmpl"] = {
                "default": str(media_dir / f"{outtmpl_title}.%(ext)s"),
                "chapter": str(media_dir / "%(section_number)02d - %(section_title)s.%(ext)s"),
            }
        else:
            ydl_media_opts["outtmpl"] = str(media_dir / f"{outtmpl_title}.%(ext)s")

        if postprocessors:
            ydl_media_opts["postprocessors"] = postprocessors

        with yt_dlp.YoutubeDL(ydl_media_opts) as ydl:
            ydl.download([task.url])
        detail_parts.append(f"🎬 {media_dir}")
        current_task_view["progress"] = "Descarga de medios completada."

    return {"title": safe_title, "detail": " · ".join(detail_parts)}

async def worker_loop():
    global current_task_view, last_task_view
    while True:
        task: TaskRequest = await task_queue.get()
        if pending_tasks_view:
            pending_tasks_view.pop(0)
        current_task_view = {
            "title": task.title,
            "mode": task.mode,
            "progress": "Iniciando..."
        }
        try:
            result = await asyncio.to_thread(process_item_sync, task)
            last_task_view = {
                "title": result["title"],
                "mode": task.mode,
                "status": "done",
                "detail": f"Guardado en: {result['detail']}"
            }
        except Exception as e:
            detail = re.sub(r"\s+", " ", str(e)).strip()[:300] or e.__class__.__name__
            print(f"[ERROR EN TAREA]: {detail}")
            last_task_view = {
                "title": task.title,
                "mode": task.mode,
                "status": "failed",
                "detail": detail
            }
        finally:
            current_task_view = None
            task_queue.task_done()

# ================= ENDPOINTS DE LA API =================
@app.post("/enqueue", dependencies=[Depends(require_token)])
async def enqueue_task(req: TaskRequest):
    if not YT_REGEX.match(req.url):
        raise HTTPException(status_code=400, detail="URL inválida. Solo se permiten enlaces de YouTube.")

    # Validar las rutas que usará la tarea antes de encolarla (falla rápido con mensaje claro).
    try:
        if req.mode in ("md", "both"):
            resolve_vault_path(req.vault_path)
        if req.mode in ("video", "audio", "both"):
            media_dir = resolve_media_path(req.media_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if req.mode in ("video", "both"):
        free_gb = get_free_space_gb(media_dir)
        if free_gb < MIN_FREE_DISK_GB:
            raise HTTPException(
                status_code=507,
                detail=f"Espacio insuficiente ({free_gb} GB libres). Se requieren al menos {MIN_FREE_DISK_GB} GB para descargar videos largos."
            )

    pending_tasks_view.append({"title": req.title, "mode": req.mode})
    await task_queue.put(req)
    return {"status": "queued", "queue_position": len(pending_tasks_view)}

@app.get("/health")
async def health_check():
    return {"status": "ok"}

@app.get("/status", dependencies=[Depends(require_token)])
async def get_status():
    try:
        # Reportamos el espacio más crítico entre todas las carpetas de destino
        free_gb = min(get_free_space_gb(folder) for folder in DESTINATIONS.values())
    except OSError:
        free_gb = get_free_space_gb(BASE_HOME)
    return {
        "current_task": current_task_view,
        "pending_queue": pending_tasks_view,
        "last_task": last_task_view,
        "free_space_gb": free_gb,
        "min_free_disk_gb": MIN_FREE_DISK_GB,
        "low_disk_warning": free_gb < MIN_FREE_DISK_GB
    }

if __name__ == "__main__":
    import multiprocessing
    import uvicorn
    # 127.0.0.1 (por defecto) blinda el servidor para que nadie en tu red Wi-Fi pueda acceder
    if HOST not in ("127.0.0.1", "localhost", "::1"):
        print(f"[AVISO DE SEGURIDAD] Estás exponiendo el servidor en '{HOST}'. Usa 127.0.0.1 para blindarlo.")
    # Crítico en Windows al empaquetar con PyInstaller: evita el bucle infinito de re-ejecución.
    multiprocessing.freeze_support()
    uvicorn.run(app, host=HOST, port=PORT)