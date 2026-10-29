#!/usr/bin/env bash
# CAD-bot installer: system packages, Blender 4.2 LTS, ffmpeg, Python env,
# settings tuned to this machine, and a real test render at the end.
#
#   ./install.sh                 install everything (safe to re-run)
#   ./install.sh --cron          also schedule rendering/posting with cron
#
# Options:
#   --low-memory      force the 1 GB settings (auto when RAM < 3 GB)
#   --full-quality    never apply the low-memory settings
#   --no-swap         don't create a swap file on small machines
#   --cron            install cron jobs (publish every 15 min, render nightly)
#   --blender PATH    use an existing Blender 4.x executable instead of downloading
#   --skip-test       skip the final test render
#
# Supported: Ubuntu 22.04+, Debian 12+, Oracle Linux / RHEL / Rocky / Alma 8-9,
# Fedora. x86_64 gets the official Blender build; on ARM (aarch64) Blender.org
# has no 4.2 Linux build, so the distro's Blender 4.x is used where available.
set -euo pipefail

BLENDER_VERSION=4.2.3
BLENDER_SERIES=4.2
BLENDER_URL="https://download.blender.org/release/Blender${BLENDER_SERIES}"
FFMPEG_URL="https://johnvansickle.com/ffmpeg/releases"

cd "$(dirname "$(readlink -f "$0")")"
ROOT="$(pwd)"

# ------------------------------------------------------------------ options
LOW_MEMORY=auto
MAKE_SWAP=1
INSTALL_CRON=0
SKIP_TEST=0
BLENDER_PATH=""
while [ $# -gt 0 ]; do
    case "$1" in
        --low-memory) LOW_MEMORY=yes ;;
        --full-quality) LOW_MEMORY=no ;;
        --no-swap) MAKE_SWAP=0 ;;
        --cron) INSTALL_CRON=1 ;;
        --skip-test) SKIP_TEST=1 ;;
        --blender) BLENDER_PATH="${2:?--blender needs a path}"; shift ;;
        -h|--help) sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "Unknown option: $1 (see ./install.sh --help)" >&2; exit 2 ;;
    esac
    shift
done

# ------------------------------------------------------------------ helpers
step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
info() { printf '    %s\n' "$*"; }
warn() { printf '\033[1;33m    ! %s\033[0m\n' "$*"; }
die()  { printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2; exit 1; }

as_root() {
    if [ "$(id -u)" -eq 0 ]; then "$@"
    elif command -v sudo >/dev/null 2>&1; then sudo "$@"
    else die "need root for: $* (install sudo or run as root)"; fi
}

download() {  # url dest
    curl -fL --retry 3 --retry-delay 3 --connect-timeout 30 -o "$2" "$1" \
        || die "download failed: $1"
}

ENV_FILE="$ROOT/.env"
env_has() { grep -Eq "^$1=" "$ENV_FILE" 2>/dev/null; }
env_set() {  # replace or append KEY=VALUE
    local key=$1 value=$2
    if env_has "$key"; then
        local escaped; escaped=$(printf '%s' "$value" | sed 's/[\/&|]/\\&/g')
        sed -i "s|^$key=.*|$key=$escaped|" "$ENV_FILE"
    else
        printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
    fi
}
env_default() { env_has "$1" || env_set "$1" "$2"; }   # never overrides your own settings

# ------------------------------------------------------------------ preflight
step "Checking this machine"
[ -r /etc/os-release ] || die "can't identify the OS (/etc/os-release missing)"
. /etc/os-release
ARCH=$(uname -m)
CPUS=$(nproc 2>/dev/null || echo 1)
RAM_MB=$(awk '/^MemTotal:/ {print int($2/1024)}' /proc/meminfo)
# Inside a container the memory limit is in the cgroup, not /proc/meminfo.
for limit_file in /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory/memory.limit_in_bytes; do
    if [ -r "$limit_file" ]; then
        limit=$(cat "$limit_file")
        case "$limit" in ''|max|*[!0-9]*) ;; *) [ $((limit / 1048576)) -lt "$RAM_MB" ] && RAM_MB=$((limit / 1048576)) ;; esac
    fi
done
SWAP_MB=$(awk '/^SwapTotal:/ {print int($2/1024)}' /proc/meminfo)
DISK_MB=$(df -Pm "$ROOT" | awk 'NR==2 {print $4}')
info "${PRETTY_NAME:-$ID} ($ARCH), $CPUS CPU, ${RAM_MB} MB RAM, ${SWAP_MB} MB swap, ${DISK_MB} MB free disk"

if command -v apt-get >/dev/null 2>&1; then PKG=apt
elif command -v dnf >/dev/null 2>&1; then PKG=dnf
elif command -v yum >/dev/null 2>&1; then PKG=yum
else die "unsupported system: needs apt (Ubuntu/Debian) or dnf/yum (Oracle Linux/RHEL/Fedora)"; fi
case "$ARCH" in x86_64|aarch64) ;; *) die "unsupported CPU architecture $ARCH (need x86_64 or aarch64)";; esac
[ "$DISK_MB" -ge 3500 ] || die "need ~3.5 GB free disk (Blender is 1.3 GB, plus Python packages and frames); have ${DISK_MB} MB"

if [ "$LOW_MEMORY" = auto ]; then
    if [ "$RAM_MB" -lt 3000 ]; then LOW_MEMORY=yes; else LOW_MEMORY=no; fi
fi

# ------------------------------------------------------------------ system packages
step "Installing system packages ($PKG)"
if [ "$PKG" = apt ]; then
    export DEBIAN_FRONTEND=noninteractive
    as_root apt-get update -y -qq
    as_root apt-get install -y -qq --no-install-recommends \
        ca-certificates curl xz-utils tar util-linux python3 python3-venv python3-pip \
        ffmpeg fonts-dejavu-core \
        libx11-6 libxrender1 libxxf86vm1 libxfixes3 libxi6 libxkbcommon0 libsm6 libice6 libgl1 libxext6 \
        >/dev/null
    [ "$INSTALL_CRON" = 1 ] && as_root apt-get install -y -qq cron >/dev/null
else
    as_root "$PKG" install -y -q \
        ca-certificates curl xz tar util-linux findutils dejavu-sans-fonts \
        libX11 libXrender libXxf86vm libXfixes libXi libxkbcommon libSM libICE mesa-libGL libXext \
        >/dev/null
    [ "$INSTALL_CRON" = 1 ] && as_root "$PKG" install -y -q cronie >/dev/null
fi
info "done"

# ------------------------------------------------------------------ Python 3.10+
step "Finding Python 3.10+"
PYTHON=""
find_python() {
    for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
        if command -v "$candidate" >/dev/null 2>&1 &&
           "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            PYTHON=$(command -v "$candidate"); return 0
        fi
    done
    return 1
}
if ! find_python; then
    if [ "$PKG" != apt ]; then
        info "system Python is too old; installing Python 3.11"
        as_root "$PKG" install -y -q python3.11 python3.11-pip >/dev/null || true
    fi
    find_python || die "Python 3.10+ not found. On Ubuntu 20.04 use a newer release (22.04+), or install python3.11 yourself and re-run."
fi
PY_VER=$("$PYTHON" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')
info "$PYTHON ($PY_VER)"

# ------------------------------------------------------------------ ffmpeg
step "Checking ffmpeg"
ffmpeg_ok() {  # needs the H.264 and AAC encoders
    # Capture first: with pipefail, `ffmpeg | grep -q` fails when grep exits early.
    local encoders
    encoders=$("$1" -hide_banner -encoders 2>/dev/null) || return 1
    grep -qE '\slibx264\s' <<<"$encoders" && grep -qE '\saac\s' <<<"$encoders"
}
FFMPEG_BIN=""
if [ -x "$ROOT/tools/ffmpeg/ffmpeg" ] && ffmpeg_ok "$ROOT/tools/ffmpeg/ffmpeg"; then
    FFMPEG_BIN="$ROOT/tools/ffmpeg/ffmpeg"
elif command -v ffmpeg >/dev/null 2>&1 && ffmpeg_ok ffmpeg && command -v ffprobe >/dev/null 2>&1; then
    FFMPEG_BIN=ffmpeg
elif [ "$PKG" != apt ] && as_root "$PKG" install -y -q ffmpeg >/dev/null 2>&1 && ffmpeg_ok ffmpeg; then
    FFMPEG_BIN=ffmpeg
else
    # Oracle Linux/RHEL ship no ffmpeg (and Fedora's lacks H.264): use a static build.
    case "$ARCH" in x86_64) FF_ARCH=amd64 ;; aarch64) FF_ARCH=arm64 ;; esac
    info "no suitable ffmpeg package; downloading a static build"
    tmp=$(mktemp -d)
    download "$FFMPEG_URL/ffmpeg-release-$FF_ARCH-static.tar.xz" "$tmp/ffmpeg.tar.xz"
    download "$FFMPEG_URL/ffmpeg-release-$FF_ARCH-static.tar.xz.md5" "$tmp/ffmpeg.tar.xz.md5"
    [ "$(md5sum "$tmp/ffmpeg.tar.xz" | cut -d' ' -f1)" = "$(cut -d' ' -f1 "$tmp/ffmpeg.tar.xz.md5")" ] \
        || die "ffmpeg download checksum mismatch"
    rm -rf "$ROOT/tools/ffmpeg" && mkdir -p "$ROOT/tools/ffmpeg"
    tar -xJf "$tmp/ffmpeg.tar.xz" -C "$ROOT/tools/ffmpeg" --strip-components=1
    rm -rf "$tmp"
    FFMPEG_BIN="$ROOT/tools/ffmpeg/ffmpeg"
    ffmpeg_ok "$FFMPEG_BIN" || die "static ffmpeg doesn't work on this machine"
fi
ff_version=$("$FFMPEG_BIN" -version 2>/dev/null | awk 'NR == 1 {print substr($0, 1, 60)}') || true
info "$FFMPEG_BIN: $ff_version"

# ------------------------------------------------------------------ Blender
step "Setting up Blender"
blender_version() {  # prints e.g. 4.2.3, empty if unusable (never fails under set -e)
    local out
    out=$("$1" --background --factory-startup --python-expr \
        'import bpy; print("BLENDER_VERSION", bpy.app.version_string)' 2>/dev/null) || true
    awk '/^BLENDER_VERSION/ && !found {print $2; found = 1}' <<<"$out"
}
BLENDER_BIN=""
if [ -n "$BLENDER_PATH" ]; then
    BLENDER_BIN=$(readlink -f "$BLENDER_PATH")
    v=$(blender_version "$BLENDER_BIN"); [ -n "$v" ] || die "$BLENDER_PATH doesn't run"
    case "$v" in 4.*) ;; *) die "Blender $v at $BLENDER_PATH: this project needs Blender 4.x";; esac
elif [ "$ARCH" = x86_64 ]; then
    BLENDER_BIN="$ROOT/blender/blender"
    if [ "$(blender_version "$BLENDER_BIN")" = "$BLENDER_VERSION" ]; then
        info "Blender $BLENDER_VERSION already installed"
    else
        tarball="blender-${BLENDER_VERSION}-linux-x64.tar.xz"
        info "downloading $tarball (~350 MB)"
        tmp=$(mktemp -d -p "$ROOT")
        download "$BLENDER_URL/$tarball" "$tmp/$tarball"
        download "$BLENDER_URL/blender-${BLENDER_VERSION}.sha256" "$tmp/sums"
        expected=$(awk -v f="$tarball" '$2 == f {print $1}' "$tmp/sums")
        [ -n "$expected" ] && [ "$(sha256sum "$tmp/$tarball" | cut -d' ' -f1)" = "$expected" ] \
            || die "Blender download checksum mismatch"
        info "checksum ok, unpacking"
        mkdir -p "$tmp/unpacked"
        tar -xJf "$tmp/$tarball" -C "$tmp/unpacked" --strip-components=1
        rm -rf "$ROOT/blender" && mv "$tmp/unpacked" "$ROOT/blender" && rm -rf "$tmp"
    fi
else
    # aarch64: no official Blender 4.2 Linux build exists.
    if command -v blender >/dev/null 2>&1; then
        BLENDER_BIN=$(command -v blender)
    elif [ "$PKG" = apt ]; then
        candidate=$(apt-cache policy blender 2>/dev/null | awk '/Candidate:/ {print $2}')
        case "$candidate" in
            *:4.*|4.*) info "installing the distro's Blender $candidate (large download)"
                       as_root apt-get install -y -qq blender >/dev/null
                       BLENDER_BIN=$(command -v blender) ;;
            *) die "no Blender 4.x for ARM here (distro offers '${candidate:-none}'). Use Ubuntu 24.04, an x86_64 server, or --blender PATH" ;;
        esac
    else
        die "no Blender 4.x for ARM on this distro. Use Ubuntu 24.04 (ARM), an x86_64 server, or --blender PATH"
    fi
fi
BLENDER_FOUND=$(blender_version "$BLENDER_BIN")
[ -n "$BLENDER_FOUND" ] || die "Blender at $BLENDER_BIN doesn't start; run it by hand to see why"
info "Blender $BLENDER_FOUND ($BLENDER_BIN)"
case "$BLENDER_FOUND" in 4.2.*) ;; *) warn "Blender $BLENDER_FOUND is not the tested 4.2 LTS; run the test render to be sure" ;; esac

# ------------------------------------------------------------------ Python environment
step "Installing Python packages into .venv"
if [ ! -x "$ROOT/.venv/bin/python" ] || ! "$ROOT/.venv/bin/python" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)'; then
    rm -rf "$ROOT/.venv"
    if ! "$PYTHON" -m venv "$ROOT/.venv" >/dev/null 2>&1; then
        [ "$PKG" = apt ] && as_root apt-get install -y -qq "python${PY_VER}-venv" >/dev/null
        rm -rf "$ROOT/.venv"
        "$PYTHON" -m venv "$ROOT/.venv" || die "can't create a virtual environment with $PYTHON"
    fi
fi
"$ROOT/.venv/bin/python" -m pip install -q --upgrade pip wheel
"$ROOT/.venv/bin/python" -m pip install -q -r "$ROOT/requirements.txt"
info "done ($("$ROOT/.venv/bin/python" --version))"

# ------------------------------------------------------------------ settings
step "Writing settings to .env"
[ -f "$ENV_FILE" ] || cp "$ROOT/.env.example" "$ENV_FILE"
env_set BLENDER_BIN "$BLENDER_BIN"
env_set BLENDER_MODE binary
if [ "$FFMPEG_BIN" != ffmpeg ]; then
    env_set FFMPEG_BIN "$FFMPEG_BIN"
    env_set FFPROBE_BIN "$(dirname "$FFMPEG_BIN")/ffprobe"
fi
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    env_default USE_GPU true; info "NVIDIA GPU found: GPU rendering on"
else
    env_default USE_GPU false
fi
if [ "$LOW_MEMORY" = yes ]; then
    env_default RENDER_SCALE 0.5
    env_default RENDER_SAMPLES 12
    env_default RENDER_DENOISE fast
    [ "$CPUS" -le 1 ] && env_default RENDER_THREADS 1
    info "small machine: low-memory render settings (540x960 upscaled, fast denoise; README \"Small servers\")"
fi
if ! env_has TIMEZONE; then
    tz=$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null || echo UTC)
    env_set TIMEZONE "${tz:-UTC}"
    info "TIMEZONE=${tz:-UTC} (set it to your audience's timezone in .env for better posting times)"
fi
info "settings in $ENV_FILE (your own edits are kept on re-runs)"

# ------------------------------------------------------------------ swap
if [ "$LOW_MEMORY" = yes ] && [ "$MAKE_SWAP" = 1 ] && [ "$RAM_MB" -lt 2000 ] && [ "$SWAP_MB" -lt 1000 ]; then
    step "Adding a 2 GB swap file (safety net for ${RAM_MB} MB RAM)"
    if [ "$(df -Pm / | awk 'NR==2 {print $4}')" -lt 2500 ]; then
        warn "not enough free disk on / for swap; skipping"
    else
        if [ ! -f /swapfile ]; then
            as_root fallocate -l 2G /swapfile 2>/dev/null || as_root dd if=/dev/zero of=/swapfile bs=1M count=2048 status=none
            as_root chmod 600 /swapfile
            as_root mkswap /swapfile >/dev/null
        fi
        if as_root swapon /swapfile 2>/dev/null; then
            grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | as_root tee -a /etc/fstab >/dev/null
            info "swap on"
        else
            warn "couldn't enable swap here (containers usually can't); continuing without it"
        fi
    fi
fi

# ------------------------------------------------------------------ cron
if [ "$INSTALL_CRON" = 1 ]; then
    step "Installing cron jobs"
    command -v crontab >/dev/null 2>&1 || die "crontab not available"
    if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
        as_root systemctl enable --now cron >/dev/null 2>&1 || as_root systemctl enable --now crond >/dev/null 2>&1 || true
    fi
    PER_NIGHT=3; [ "$LOW_MEMORY" = yes ] && PER_NIGHT=1
    PYBIN="$ROOT/.venv/bin/python"
    block="# BEGIN cadbot
*/15 * * * * cd $ROOT && flock -n /tmp/cadbot-publish.lock $PYBIN main.py publish >> logs/cron.log 2>&1
30 1 * * * cd $ROOT && flock -n /tmp/cadbot-produce.lock sh -c '$PYBIN main.py scan && $PYBIN main.py produce -n $PER_NIGHT && $PYBIN main.py schedule && $PYBIN main.py collect' >> logs/cron.log 2>&1
# END cadbot"
    mkdir -p "$ROOT/logs"
    { crontab -l 2>/dev/null | sed '/# BEGIN cadbot/,/# END cadbot/d'; echo "$block"; } | crontab -
    info "publish every 15 min; render $PER_NIGHT video(s) nightly at 01:30 (logs/cron.log)"
fi

# ------------------------------------------------------------------ verify
if [ "$SKIP_TEST" = 0 ]; then
    step "Checking the installation with a test render"
    "$ROOT/.venv/bin/python" main.py doctor --render-test || die "the check above failed"
fi

step "Installed"
cat <<EOF
    Next:
      source .venv/bin/activate
      python main.py scan                    # find and score models in data/stl_files
      python main.py produce -n 1            # make a video -> data/output_videos, data/exports
    Connect YouTube/Instagram/TikTok in .env (README "Connecting platforms").
EOF
