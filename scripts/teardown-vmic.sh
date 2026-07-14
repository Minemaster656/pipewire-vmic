#!/usr/bin/env bash
set -euo pipefail

VMIC_SINK="tts-vmic"
VMIC_SOURCE="tts-vmic-source"

pactl list modules short | while read -r mod_id mod_rest; do
    if echo "$mod_rest" | grep -qE "$VMIC_SINK|$VMIC_SOURCE"; then
        pactl unload-module "$mod_id"
        echo "unloaded module #$mod_id"
    fi
done
