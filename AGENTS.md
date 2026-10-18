# AGENT.md — OpenCode Harness Specification
# Project: YT Obsidian & Course Archiver

## 1. ROL Y DIRECTIVAS DE EJECUCIÓN (OPENCODE HARNESS)
Actúas como un Arquitecto de Software Senior especialista en Extensiones de Chrome (Manifest V3), Python Asíncrono (FastAPI) y automatización de conocimiento en Obsidian.
- **Cero Código Incompleto:** Prohibido usar placeholders como `// TODO`, `pass` o `# implementar aquí`. Todo archivo editado debe quedar 100% funcional.
- **Verificación Autónoma:** Después de modificar cualquier archivo Python, ejecuta siempre la validación de sintaxis (`python -m py_compile servidor/server.py`) antes de finalizar tu turno.
- **Idempotencia:** La creación de carpetas y archivos debe ser segura de re-ejecutar sin sobrescribir configuraciones críticas ni corromper descargas previas.

---

## 2. ARQUITECTURA Y ESTRUCTURA DEL REPOSITORIO
Mantén estrictamente este árbol de directorios. No agregues frameworks pesados de frontend (React/Vue); la extensión debe ser Vanilla JS puro y ligero.

```text
.
├── AGENT.md                  # Este arnés de instrucciones
├── extension/                # Frontend: Chrome Extension (Manifest V3)
│   ├── manifest.json         # Permisos: activeTab, storage | Host: 127.0.0.1:8000
│   ├── popup.html            # UI minimalista Dark Mode (360px ancho)
│   ├── styles.css            # Variables CSS nativas (True Dark)
│   └── popup.js              # Lógica de captura, fetch con Auth Token y polling (2s)
└── servidor/                 # Backend: Motor local asíncrono
    ├── server.py             # API FastAPI + Worker FIFO + Motor yt-dlp + Parser Obsidian
    ├── requirements.txt      # fastapi, uvicorn, yt-dlp, pydantic
    └── .env.example          # Plantilla de variables y rutas locales
     
  ```

---

## 3. COMANDOS DEL ENTORNO (COMMANDS)
Usa estos comandos cuando necesites instalar paquetes, iniciar el servidor o probar endpoints desde la terminal:
- **Instalar dependencias:** `pip install fastapi uvicorn yt-dlp pydantic pyinstaller`
- **Verificar sintaxis backend:** `python -m py_compile servidor/server.py`
- **Levantar servidor local:** `uvicorn servidor.server:app --host 127.0.0.1 --port 8000`
- **Healthcheck / Test de estado:**
  `curl -s -H "X-Auth-Token: MI_CLAVE_SECRETA_BLINDADA_2026" http://127.0.0.1:8000/status`

---

## 4. ESPECIFICACIONES FUNCIONALES (ORDEN DE PRIORIDAD)

### P1 (Principal): Extractor de Transcripciones a Markdown para Obsidian
1. **Descarga sin video:** Configurar `yt_dlp` con `skip_download: True`, `writesubtitles: True`, `writeautomaticsub: True`, `subtitleslangs: ["es.*", "es", "en.*", "en"]` y `subtitlesformat: "json3"`.
2. **Limpieza y Agrupación:**
   - Parsear el archivo `.json3`, extraer los segmentos de texto, limpiar saltos de línea rotos y eliminar frases duplicadas consecutivas (típicas de subtítulos autogenerados).
   - Si el video posee capítulos (`chapters` en los metadatos de `yt-dlp`), agrupar los párrafos debajo del título de cada capítulo (`### Nombre del Capítulo ([MM:SS](https://youtu.be/ID?t=XXs))`).
   - Si no posee capítulos, agrupar el texto en bloques cronológicos cada 5 minutos (`300s`) con su enlace de tiempo correspondiente.
3. **Plantilla de Salida (Obsidian Ready):**
   - Todo archivo `.md` debe iniciar con este bloque **YAML Frontmatter** exacto:
     ```yaml
     ---
     titulo: "<Título comillas limpio sin>"
     canal: "<Autor/Canal>"
     url: "<URL original>"
     duracion: "<HH:MM:SS>"
     fecha_descarga: YYYY-MM-DD
     estado: "#por-procesar"
     tags:
       - youtube
       - curso
     ---
     ```
   - Debajo del YAML, incluir el título `# <Título>`, metadatos rápidos con link al video y una sección `## 📑 Índice del Curso` con viñetas clicables hacia cada minuto exacto en YouTube antes de `## 📝 Transcripción Completa`.

### P2 (Secundaria): Descarga de Cursos Largos (Video / Audio)
1. **Resiliencia:** Usar `continuedl: True`, `retries: 10` y `fragment_retries: 10` para reanudar descargas de varias horas si se corta internet.
2. **Formatos:**
   - Modo `video` o `both`: `bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best` con `merge_output_format: "mp4"`.
   - Modo `audio`: `bestaudio[ext=m4a]/bestaudio`.
3. **División por Capítulos (`split_chapters: true`):**
   - Si el usuario activa el checkbox en la UI, inyectar el postprocesador `{"key": "FFmpegSplitChapters"}` y guardar cada capítulo numerado: `%(section_number)02d - %(section_title)s.%(ext)s`.

### P3: Cola Secuencial (FIFO) y Monitor de Disco Duro
1. **Worker Único:** Implementar `asyncio.Queue()`. Un único loop en segundo plano (`worker_loop`) procesa **1 tarea a la vez** usando `asyncio.to_thread()` para no bloquear el event loop de FastAPI.
2. **Visibilidad de Cola:** El endpoint `GET /status` debe devolver qué video se está procesando ahora mismo (con porcentaje y velocidad extraídos de `progress_hooks`) y el array completo de tareas en espera (`pending_queue`).
3. **Protección de Almacenamiento:** Usar `shutil.disk_usage()`. Si el espacio libre en la ruta destino es menor a `5.0 GB`, rechazar descargas de video (`HTTP 507 Insufficient Storage`) y encender una alerta roja en la extensión.

### P4: Enrutamiento por Carpetas Locales Sincronizadas
Prohibido implementar SDKs complejos de OAuth en la nube. El servidor escribe directamente en carpetas locales del sistema operativo que ya están sincronizadas por las apps de escritorio o por Obsidian:
- `obsidian`: `~/Documents/Cerebro/Cursos_YouTube` *(Ajustable por el usuario)*
- `gdrive`: `~/Google Drive/Cursos_YouTube`
- `onedrive`: `~/OneDrive/Cursos_YouTube`
- `local`: `~/Downloads/Cursos_YouTube`

---

## 5. REGLAS DE DISEÑO UI/UX (MODO OSCURO MINIMALISTA)
- **Paleta de colores estricta:**
  - Fondo Principal: `#0F0F0F` | Tarjetas/Inputs: `#18181B` | Bordes: `#27272A`
  - Texto Principal: `#F4F4F5` | Texto Secundario: `#A1A1AA`
  - Botón Primario: `#3B82F6` (Hover: `#2563EB`) | Indicador Activo/Éxito: `#10B981` | Alerta Disco: `#EF4444`
- **Componentes obligatorios en `popup.html`:**
  1. Cabecera con nombre de la app y badge de espacio libre (`Libre: XX.X GB`).
  2. Título del video detectado automáticamente de la pestaña activa.
  3. Selector de Acción (`md` por defecto, `both`, `video`, `audio`).
  4. Selector de Destino (`obsidian` por defecto, `gdrive`, `onedrive`, `local`).
  5. Checkbox: *"Dividir video por capítulos"*.
  6. Input Text: Para configurar la ruta manual hacia la bóveda de Obsidian (`custom_obsidian_path`).
  7. Panel inferior de **Estado y Cola** mostrando tarea activa en tiempo real y lista numerada de elementos en espera.

---

## 6. CONTRATOS DE LA API (JSON SCHEMAS)

### `POST /enqueue`
- **Headers:** `X-Auth-Token: <SECRET_TOKEN>`, `Content-Type: application/json`
- **Body:**
  ```json
  {
    "url": "[https://www.youtube.com/watch?v=dQw4w9WgXcQ](https://www.youtube.com/watch?v=dQw4w9WgXcQ)",
    "title": "Curso Completo de C",
    "mode": "md",
    "destination": "obsidian",
    "split_chapters": false,
    "custom_obsidian_path": "C:\\Users\\Guille\\Documents\\Cerebro"
  }
  ```

### `GET /status`
- **Headers:** `X-Auth-Token: <SECRET_TOKEN>`
- **Response:**
  ```json
  {
    "current_task": {
      "title": "Curso Completo de C",
      "mode": "md",
      "progress": "Extrayendo transcripción y capítulos..."
    },
    "pending_queue": [
      { "title": "Curso de Linux", "mode": "both" }
    ],
    "free_space_gb": 48.25,
    "low_disk_warning": false
  }
  ```

---

## 7. PROTOCOLO DE SEGURIDAD BLINDADA (HARDENING)
1. **Aislamiento de Red (Loopback Only):** El servidor Uvicorn debe enlazar única y exclusivamente a `127.0.0.1`. Nunca usar `0.0.0.0`.
2. **Autenticación Obligatoria:** Validar `X-Auth-Token` en cada endpoint. Si no coincide, devolver `HTTP 403 Forbidden`.
3. **Anti-Command Injection:** Prohibido usar `os.system`, `subprocess.run(..., shell=True)` o concatenar strings de usuario en terminal. Invocar `yt_dlp.YoutubeDL()` exclusivamente como librería nativa de Python.
4. **Validación Estricta de URL:** Aceptar únicamente URLs que pasen el regex: `^https?://(www\.)?(youtube\.com/watch\?v=|youtu\.be/)[\w-]{11}`.
5. **Anti Path-Traversal:** Sanitizar todo título de video o capítulo con `re.sub(r'[\\/*?:"<>|.]', "", name)` antes de crear carpetas o archivos `.md`, garantizando que ningún archivo pueda escribirse fuera del directorio destino autorizado.
6. **Soporte Anti-Bot / Edad:** Dejar preparado en las opciones de `yt_dlp` el parámetro `"cookiesfrombrowser": ("chrome",)` listo para activar si YouTube solicita validación de sesión.

---

## 8. PROTOCOLO DE COMPILACIÓN Y DESPLIEGUE (BUILD & AUTO-START)
Cuando el usuario solicite compilar una nueva versión del servidor, generar el archivo `.exe` o configurar el autoarranque, ejecuta estrictamente esta secuencia sin detenerte:

1. **Validación de Seguridad en Windows (Anti-bucle infinito):**
   - Inspecciona `servidor/server.py`.
   - Verifica que el bloque principal tenga exactamente esta estructura antes de iniciar Uvicorn. Si no la tiene, inyéctala:
     ```python
     if __name__ == "__main__":
         import multiprocessing
         multiprocessing.freeze_support()
         import uvicorn
         uvicorn.run(app, host="127.0.0.1", port=8000)
     ```

2. **Instalación de Dependencias de Empaquetado:**
   - Ejecuta en la terminal: `pip install pyinstaller`

3. **Compilación Silenciosa:**
   - Posiciónate en el directorio `servidor/` (`cd servidor`).
   - Ejecuta la compilación con ocultamiento de ventana: 
     `pyinstaller --onefile --noconsole server.py`
   - El uso de `--noconsole` es obligatorio para que funcione en segundo plano.

4. **Limpieza del Entorno:**
   - Elimina la carpeta temporal `build/` y el archivo `server.spec` que genera PyInstaller. 
   - Conserva únicamente la carpeta `dist/` con el archivo `server.exe` final.

5. **Configuración de Autoarranque (Si el usuario lo requiere):**
   - Para iniciar el servidor silencioso al encender la PC, ejecuta este script exacto de PowerShell en la terminal para crear el acceso directo en la carpeta de inicio de Windows:
     ```powershell
     $WshShell = New-Object -comObject WScript.Shell
     $Shortcut = $WshShell.CreateShortcut("$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\YT_Server.lnk")
     $Shortcut.TargetPath = "$(Resolve-Path .\dist\server.exe)"
     $Shortcut.WindowStyle = 7$Shortcut.Save()
     ```