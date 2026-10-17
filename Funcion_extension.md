# ROL Y OBJETIVO
Actúa como un Arquitecto de Software Senior especialista en Extensiones de Chrome (Manifest V3), Python (FastAPI) y gestión de conocimiento en Obsidian. Diseña y escribe el código completo de "YT Obsidian & Course Archiver".

# ARQUITECTURA DEL SISTEMA (HÍBRIDA Y SEGURA)
1. **Frontend (Extensión de Chrome - Manifest V3):** Interfaz minimalista en modo oscuro que extrae la URL del video y se comunica con el servidor local en `http://127.0.0.1:8000` enviando un header `X-Auth-Token`.
2. **Backend Local (Python FastAPI + yt-dlp):** Corre en segundo plano en la PC. Procesa las tareas en una cola secuencial (FIFO - una a la vez), extrae transcripciones limpias hacia Markdown compatibles con Obsidian y descarga videos de larga duración en carpetas locales (que pueden ser carpetas sincronizadas de Google Drive, OneDrive o una Bóveda de Obsidian).

# FUNCIONALIDADES PRINCIPALES (ORDEN DE PRIORIDAD)
1. **FUNCIÓN PRINCIPAL - Extractor de Transcripciones para Obsidian (.md):**
   - Descarga subtítulos manuales o autogenerados sin bajar el video.
   - Limpia etiquetas XML/VTT, elimina líneas duplicadas y agrupa el texto por los capítulos del video de YouTube.
   - Genera un archivo `.md` con **YAML Frontmatter** nativo de Obsidian (título, canal, URL, duración, fecha, tags), un índice con enlaces clicables al minuto exacto de YouTube (`https://youtu.be/ID?t=XXs`) y el cuerpo de la transcripción dividido por capítulos.
2. **FUNCIÓN SECUNDARIA - Descarga de Cursos Largos (Video/Audio):**
   - Descarga videos de varias horas en MP4/MKV o Solo Audio (MP3/M4A) usando `yt-dlp` y `ffmpeg` con flag `--continue` para reanudar si cae la red.
   - Opción "Dividir video por capítulos" (`--split-chapters`) para guardar cada tema del curso como un archivo numerado independiente.
3. **Sistema de Cola Secuencial (FIFO) y Monitor de Espacio:**
   - Un trabajador asíncrono procesa 1 tarea a la vez.
   - La interfaz de la extensión muestra en tiempo real la tarea actual y la lista de videos "En espera".
   - Verifica el espacio libre en el disco duro antes de iniciar descargas de video (alerta si queda menos de 5 GB libres).
4. **Enrutamiento por Carpetas Locales:**
   - Permite elegir entre rutas locales preconfiguradas: Bóveda de Obsidian, Carpeta de Google Drive en PC, Carpeta de OneDrive en PC o Descargas.

# SEGURIDAD BLINDADA (HARDENING)
- **Autenticación Local:** Header obligatorio `X-Auth-Token` validado en cada petición.
- **Aislamiento de Red:** El servidor escucha exclusivamente en `127.0.0.1` (bloqueado para la red Wi-Fi/LAN).
- **Anti-Inyección de Comandos:** Prohibido usar `shell=True`. Validar mediante Regex que la URL pertenezca estrictamente a `youtube.com` o `youtu.be`.
- **Sanitización de Archivos (Anti Path-Traversal):** Limpiar títulos de videos eliminando caracteres especiales (`..`, `/`, `\`, `:`) para impedir escritura fuera de las carpetas autorizadas.
- **Evasión de bloqueos:** Soporte opcional para `--cookies-from-browser chrome` para saltar bloqueos de bot o edad sin exponer contraseñas.