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