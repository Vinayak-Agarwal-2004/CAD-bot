#!/usr/bin/env bash
# Kept for old instructions; the installer is install.sh.
exec "$(dirname "$(readlink -f "$0")")/install.sh" "$@"
