#! /bin/bash
# Baut Lightshow-x86_64.AppImage aus dem Quellbaum.
#
#     ./packaging/appimage/build.sh          -> dist/Lightshow-x86_64.AppImage
#
# Gebraucht werden curl, squashfs-tools und eine Netzverbindung; Python bringt
# das Basisimage mit, die Abhaengigkeiten kommen als manylinux-Wheels. Wer die
# Downloads schon hat, zeigt mit diesen Variablen darauf:
#
#     PYTHON_APPIMAGE=... RUNTIME_FILE=... ./build.sh

set -euo pipefail

# Ohne das loest pip gegen ~/.local/lib/python3.12/site-packages des Bau-
# rechners auf und laesst weg, was dort schon liegt -- das Image haengt dann
# an der Maschine, auf der es gebaut wurde. Genau so fehlte einmal cffi.
export PYTHONNOUSERSITE=1

here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd -- "$here/../.." && pwd)"
work="$repo/build/appimage"
appdir="$work/AppDir"
out="$repo/dist/Lightshow-x86_64.AppImage"

PY_TAG="${PY_TAG:-python3.12}"
cache="$work/cache"

say() { printf '\n== %s\n' "$*"; }

# Ausgepackt wird mit unsquashfs statt mit --appimage-extract: die Images sind
# zstd-komprimiert, und ein installierter AppImageLauncher faengt den Aufruf ab
# und scheitert daran. Der Offset steht im ELF-Kopf -- hinter den Sektionen
# faengt das Dateisystem an.
extract() {                     # extract <appimage> <ziel>
    local offset
    offset="$(python3 -c '
import struct, sys
with open(sys.argv[1], "rb") as image:
    head = image.read(64)
shoff, = struct.unpack_from("<Q", head, 0x28)
shentsize, shnum = struct.unpack_from("<HH", head, 0x3a)
print(shoff + shentsize * shnum)' "$1")"
    rm -rf "$2"
    unsquashfs -q -o "$offset" -d "$2" "$1" >/dev/null
}

for tool in unsquashfs mksquashfs; do
    command -v "$tool" >/dev/null ||
        { echo "$tool fehlt: sudo apt install squashfs-tools" >&2; exit 1; }
done

fetch() {                       # fetch <url> <ziel>
    [ -s "$2" ] && return 0
    mkdir -p "${2%/*}"
    echo "lade $(basename "$2")"
    curl -fL --progress-bar -o "$2.part" "$1"
    mv "$2.part" "$2"
}

# --------------------------------------------------------------- Zutaten ---

say "Zutaten"
mkdir -p "$cache"

if [ -n "${PYTHON_APPIMAGE:-}" ]; then
    python_image="$PYTHON_APPIMAGE"
else
    # Die Patchversion wandert, also beim Release nachfragen statt raten.
    api="https://api.github.com/repos/niess/python-appimage/releases/tags/$PY_TAG"
    url="$(curl -fsSL "$api" | python3 -c '
import json, sys
assets = json.load(sys.stdin)["assets"]
want = [a["browser_download_url"] for a in assets
        if a["name"].endswith("manylinux2014_x86_64.AppImage")]
if not want:
    sys.exit("kein manylinux2014-x86_64-Asset in diesem Release")
print(sorted(want)[-1])')"
    python_image="$cache/$(basename "$url")"
    fetch "$url" "$python_image"
fi

# Die klassische Runtime aus AppImageKit, nicht die neuere aus type2-runtime.
# Letztere laeuft zwar allein, scheitert aber unter AppImageLauncher mit
# "fuse: memory allocation failed" -- und auf Rechnern mit AppImageLauncher
# geht jeder Start ueber binfmt_misc durch ihn hindurch. Diese hier laeuft auf
# beiden Wegen. Sie laedt libfuse.so.2 nach, siehe README.
runtime="${RUNTIME_FILE:-$cache/runtime-appimagekit-x86_64}"
[ -n "${RUNTIME_FILE:-}" ] || fetch \
    "https://github.com/AppImage/AppImageKit/releases/download/continuous/runtime-x86_64" \
    "$runtime"

# ------------------------------------------------------------ Basisimage ---

say "Basisimage auspacken"
mkdir -p "$work"
extract "$python_image" "$appdir"

# Das Basisimage gibt sich als Python aus -- Name, Icon und Startdatei sind
# unsere Sache.
rm -f "$appdir"/*.desktop "$appdir"/*.png "$appdir"/.DirIcon
rm -rf "$appdir/usr/share/applications" "$appdir/usr/share/icons"
mv "$appdir/AppRun" "$appdir/AppRun.python"

# --------------------------------------------------------------- Bridge ----

say "Bridge installieren"
"$appdir/AppRun.python" -m pip install --no-cache-dir --no-warn-script-location \
    --disable-pip-version-check "$repo/host"

say "Quellbaum mitgeben"
share="$appdir/usr/share/lightshow"
mkdir -p "$share/config"
cp -a "$repo/firmware" "$share/firmware"
cp -a "$repo/tools" "$share/tools"
# Nicht die Beispielkonfiguration aus host/config: die bringt drei Modelle
# und deren Buchsen mit. Ausgeliefert wird ein leerer Anfang.
cp -a "$here/show.yaml" "$share/config/show.yaml"
# Erzeugtes und Gebautes gehoert nicht ins Image.
rm -rf "$share/firmware/plane/generated" "$share/tools/ctest/build"
find "$share" -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true

version="$(git -C "$repo" describe --tags --always --dirty 2>/dev/null || date +%Y%m%d)"
printf '%s\n' "$version" > "$share/VERSION"
echo "Version: $version"

# ------------------------------------------------------------- Verpacken ---

say "Verkleinern"
prune=(usr/lib/python3.12/test usr/lib/python3.12/idlelib usr/lib/python3.12/tkinter
       usr/lib/python3.12/turtledemo usr/lib/python3.12/ensurepip usr/lib/python3.12/lib2to3)
for path in "${prune[@]}"; do rm -rf "${appdir:?}/$path"; done
find "$appdir/usr/lib" -name '__pycache__' -prune -exec rm -rf {} + 2>/dev/null || true

# libasound gehoert dem Host: gegen die falsche Version gelinkt findet ALSA
# keine Karten und der MIDI-Port bleibt weg.
if find "$appdir" -name 'libasound.so*' | grep -q .; then
    echo "warnung: libasound im Image gefunden, wird entfernt" >&2
    find "$appdir" -name 'libasound.so*' -delete
fi

say "Startdateien"
install -m 755 "$here/AppRun"            "$appdir/AppRun"
install -m 644 "$here/lightshow.desktop" "$appdir/lightshow.desktop"
install -m 644 "$here/lightshow.png"     "$appdir/lightshow.png"
cp "$here/lightshow.png" "$appdir/.DirIcon"
install -D -m 644 "$here/lightshow.desktop" \
    "$appdir/usr/share/applications/lightshow.desktop"
install -D -m 644 "$here/lightshow.png" \
    "$appdir/usr/share/icons/hicolor/256x256/apps/lightshow.png"

say "Packen"
mkdir -p "${out%/*}"
# Gepackt wird mit dem mksquashfs des Systems statt mit appimagetool, und zwar
# mit zlib. Das ist keine Geschmacksfrage, sondern die einzige Schnittmenge:
#
#   * die Runtime liest "lzma, zlib";
#   * die libappimage, die AppImageLauncher mitbringt, liest "xz, zlib" und
#     bricht bei zstd mit "Fehler beim Registrieren des AppImages im System"
#     ab, bevor es ueberhaupt zum Mounten kommt. Auf Rechnern mit
#     AppImageLauncher laeuft jeder Start ueber binfmt_misc durch ihn hindurch;
#   * das mksquashfs, das appimagetool mitbringt, kann nur zstd -- und zstd ist
#     genau das, was der Launcher nicht kann.
#
# zlib ist ausserdem das, was am schnellsten mountet.
#
# Bleibt zlib. Ein AppImage ist Runtime und Dateisystem hintereinander, mehr
# ist daran nicht.
desktop-file-validate "$appdir/lightshow.desktop"

mksquashfs "$appdir" "$work/payload.sqfs" -root-owned -noappend -no-progress \
    -comp gzip -b 128K -mkfs-time 0 -all-time 0

cat "$runtime" "$work/payload.sqfs" > "$out"
chmod +x "$out"
rm -f "$work/payload.sqfs"

# ------------------------------------------------------------- Probelauf ---

# Ein Image, das nicht startet, soll hier auffallen und nicht beim Nutzer. Der
# Lauf packt das fertige Erzeugnis noch einmal aus und startet es mit einem
# eigenen HOME, damit er keinen Arbeitsbaum anfasst, der jemandem gehoert.
say "Probelauf"
extract "$out" "$work/check"
rm -rf "$work/checkhome"
mkdir -p "$work/checkhome"
if ! HOME="$work/checkhome" XDG_DATA_HOME="$work/checkhome/share" \
     XDG_STATE_HOME="$work/checkhome/state" \
     "$work/check/AppRun" --check >"$work/check.log" 2>&1; then
    echo "das gebaute Image startet nicht:" >&2
    cat "$work/check.log" >&2
    exit 1
fi
grep -q "configuration ok" "$work/check.log" ||
    { echo "Konfiguration im Image ungueltig:" >&2; cat "$work/check.log" >&2; exit 1; }
grep -q "model '" "$work/check.log" &&
    { echo "das Image bringt Modelle mit -- es soll leer ausgeliefert werden" >&2; exit 1; }
echo "startet, Konfiguration gueltig, keine Modelle"

say "Fertig"
ls -lh "$out"
