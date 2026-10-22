#!/usr/bin/env bash

# Script para instalar el bot como servicio permanente en macOS (launchd)
PLIST_NAME="com.gabookautodownloader.plist"
LAUNCH_AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST_PATH="$LAUNCH_AGENTS_DIR/$PLIST_NAME"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_EXEC="$PROJECT_DIR/venv/bin/python"

mkdir -p "$LAUNCH_AGENTS_DIR"

# Descargar servicio anterior si ya existía
if launchctl list | grep -q "com.gabookautodownloader"; then
    echo "Deteniendo servicio previo..."
    launchctl unload "$PLIST_PATH" 2>/dev/null
fi

cat <<EOF > "$PLIST_PATH"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.gabookautodownloader</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_EXEC</string>
        <string>-u</string>
        <string>$PROJECT_DIR/main.py</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
    <key>WorkingDirectory</key>
    <string>$PROJECT_DIR</string>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>$PROJECT_DIR/bot_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>$PROJECT_DIR/bot_stderr.log</string>
</dict>
</plist>
EOF

echo "Registrando servicio en macOS..."
launchctl load "$PLIST_PATH"

echo "✅ Servicio instalado y arrancado correctamente."
echo "Para verificar logs: tail -f \"$PROJECT_DIR/bot_stdout.log\""
echo "Para detenerlo: launchctl unload \"$PLIST_PATH\""
