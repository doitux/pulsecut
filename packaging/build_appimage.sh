#!/bin/bash
# Builds Pulsecut-<version>-x86_64.AppImage (or Pulsecut-nightly-<build>-<commit>-x86_64.AppImage)
#   PY=…/python (with PySide6, numpy, pyinstaller)  UV=…/uv  TOOLS=folder with appimagetool (+ optional runtime-x86_64)
#   In CI this is called by packaging/ci_build.sh.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"; ROOT="$(dirname "$HERE")"
OUT="${OUT:-$ROOT/dist}"; WORK="${WORK:-$OUT/build}"
VERSION=$("$PY" -c "import sys; sys.path.insert(0,'$ROOT'); import pulsecut; print(pulsecut.VERSION)")
# PULSECUT_BUILD="nightly-<Build>-<Commit>" für Testversionen (Dateiname und Anzeige im Programm), leer für ein Release
BUILD="${PULSECUT_BUILD:-}"
printf 'BUILD = "%s"\n' "$BUILD" > "$ROOT/pulsecut/_build.py"
LABEL="${BUILD:-$VERSION}"
rm -rf "$WORK" "$OUT/pulsecut" "$OUT/AppDir"; mkdir -p "$OUT"
TS_UV="$UV" "$PY" -m PyInstaller --noconfirm --clean --log-level WARN --distpath "$OUT" --workpath "$WORK" "$HERE/pulsecut.spec"
"$PY" "$HERE/prune_qt.py" "$OUT/pulsecut"
A="$OUT/AppDir"; mkdir -p "$A/usr/lib" "$A/usr/share/applications" "$A/usr/share/icons/hicolor/256x256/apps"
mv "$OUT/pulsecut" "$A/usr/lib/pulsecut"
cp "$HERE/pulsecut.desktop" "$A/pulsecut.desktop"; cp "$HERE/pulsecut.desktop" "$A/usr/share/applications/"
cp "$ROOT/pulsecut/ui/icon.png" "$A/pulsecut.png"; cp "$ROOT/pulsecut/ui/icon.png" "$A/usr/share/icons/hicolor/256x256/apps/pulsecut.png"
ln -sf pulsecut.png "$A/.DirIcon"
cat > "$A/AppRun" <<'RUN'
#!/bin/bash
HERE="$(dirname "$(readlink -f "$0")")"
export QTWEBENGINE_DISABLE_SANDBOX=1
exec "$HERE/usr/lib/pulsecut/pulsecut" "$@"
RUN
chmod +x "$A/AppRun"
RT=(); [ -f "$TOOLS/runtime-x86_64" ] && RT=(--runtime-file "$TOOLS/runtime-x86_64")
ARCH=x86_64 APPIMAGE_EXTRACT_AND_RUN=1 "$TOOLS/appimagetool" "${RT[@]}" --comp zstd -n "$A" "$OUT/Pulsecut-$LABEL-x86_64.AppImage"
ls -la "$OUT"/*.AppImage
