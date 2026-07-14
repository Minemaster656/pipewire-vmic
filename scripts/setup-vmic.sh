#!/usr/bin/env bash
set -euo pipefail

VMIC_SINK="tts-vmic"
VMIC_SOURCE="tts-vmic-source"

if pactl list modules short | grep -q "$VMIC_SOURCE"; then
    echo "virtual mic '$VMIC_SOURCE' already exists"
    exit 0
fi

REAL_MIC=$(pactl info | sed -n 's/^Default Source: //p')

null_id=$(pactl load-module module-null-sink \
    sink_name="$VMIC_SINK" \
    sink_properties="device.description=TTS-Virtual-Mic")
echo "null-sink loaded as module #$null_id"

loop_id=$(pactl load-module module-loopback \
    source="$REAL_MIC" \
    sink="$VMIC_SINK")
echo "loopback (real mic -> vmic) loaded as module #$loop_id"

vsrc_id=$(pactl load-module module-virtual-source \
    source_name="$VMIC_SOURCE" \
    master="$VMIC_SINK.monitor" \
    source_properties="device.description=TTS-Virtual-Mic")
echo "virtual source loaded as module #$vsrc_id"

echo ""
echo "Select '$VMIC_SOURCE' as your microphone in apps"
