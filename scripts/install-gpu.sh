#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== TTS Speaker GPU setup ==="
echo ""

detect_nvidia() {
    if command -v nvidia-smi &>/dev/null; then
        local ver
        ver=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader 2>/dev/null | head -1)
        if [[ -n "$ver" ]]; then
            echo "NVIDIA GPU detected (driver $ver)"
            return 0
        fi
    fi
    return 1
}

detect_rocm() {
    if command -v rocminfo &>/dev/null; then
        echo "AMD ROCm detected"
        return 0
    fi
    if [[ -d /opt/rocm ]]; then
        echo "AMD ROCm detected (/opt/rocm)"
        return 0
    fi
    return 1
}

detect_vulkan() {
    if command -v vulkaninfo &>/dev/null; then
        echo "Vulkan detected"
        return 0
    fi
    return 1
}

if detect_nvidia; then
    echo "  → Installing onnxruntime-gpu (CUDA)..."
    cd "$PROJECT_DIR"
    uv add onnxruntime-gpu
    echo ""
    echo "Done. Use: ttsspeaker --provider piper-tts --gpu"
    echo "Or custom provider: ttsspeaker --provider piper-tts --gpu-provider CUDAExecutionProvider"

elif detect_rocm; then
    echo "  → Installing onnxruntime-gpu (ROCm)..."
    cd "$PROJECT_DIR"
    uv add onnxruntime-gpu
    echo ""
    echo "Done. Use: ttsspeaker --provider piper-tts --gpu-provider ROCMExecutionProvider"

elif detect_vulkan; then
    echo "Vulkan support in onnxruntime requires a custom build."
    echo "See: https://onnxruntime.ai/docs/execution-providers/Vulkan.html"
    echo ""
    echo "Standard CPU fallback will be used."
    exit 1

else
    echo "No GPU detected."
    echo ""
    echo "If you have an NVIDIA GPU, install the proprietary driver and CUDA toolkit:"
    echo "  Ubuntu/Debian:  sudo apt install nvidia-driver-xxx nvidia-cuda-toolkit"
    echo "  Arch Linux:     sudo pacman -S nvidia cuda"
    echo "  Fedora:         sudo dnf install akmod-nvidia xorg-x11-drv-nvidia-cuda"
    echo ""
    echo "If you have an AMD GPU, install ROCm:"
    echo "  https://rocm.docs.amd.com/en/latest/"
    echo ""
    echo "Then re-run this script."
    exit 1
fi
