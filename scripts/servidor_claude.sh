#!/bin/sh
# Arranca el servidor MCP del monitor para Claude Code (nube, Linux o Mac).
# Si todavía no está el entorno virtual, lo crea e instala el proyecto (la primera vez tarda ~1 minuto).
# Todo lo que se imprime va a stderr: stdout es el canal del protocolo MCP.
cd "$(dirname "$0")/.." || exit 1
if [ ! -x .venv/bin/monitor-claude ]; then
  echo "Instalando el monitor de mercado (solo la primera vez)..." >&2
  python3 -m venv .venv >&2 && .venv/bin/pip install -q -e ".[claude]" >&2 || exit 1
fi
exec .venv/bin/monitor-claude
