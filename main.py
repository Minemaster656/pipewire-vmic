import argparse
import asyncio
import sys
from pathlib import Path

from audio import play_audio
from cache import TTSCache
from tts_provider import (
    EdgeTTSProvider,
    PiperTTSProvider,
    SupertonicTTSProvider,
    TTSProvider,
    resolve_voice,
)
from vmic import setup as vmic_setup, teardown as vmic_teardown


def _make_provider(
    name: str,
    proxy: str | None = None,
    gpu: bool = False,
    gpu_provider: str | None = None,
    quality: str = "medium",
    lang: str = "en",
) -> TTSProvider:
    if name == "edge-tts":
        return EdgeTTSProvider(proxy=proxy)
    if name == "piper-tts":
        return PiperTTSProvider(gpu=gpu, gpu_provider=gpu_provider)
    if name == "supertonic":
        return SupertonicTTSProvider(quality=quality, lang=lang)
    raise ValueError(f"unknown provider: {name}")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="ttsspeaker", description="Text-to-Speech CLI")
    p.add_argument("-o", "--output", action="store_true", help="Play to speaker")
    p.add_argument(
        "-m", "--mic", action="store_true", help="Play to virtual microphone"
    )
    p.add_argument("-f", "--file", type=str, help="Save audio to file (.mp3/.ogg/.wav)")
    p.add_argument(
        "-v", "--voice", choices=["male", "female"], default="male", help="Voice gender"
    )
    p.add_argument("-l", "--lang", default="en", help="Language code (en, ru, ...)")
    p.add_argument("--voice-name", type=str, help="Exact voice name (overrides -v/-l)")
    p.add_argument(
        "--provider",
        choices=["edge-tts", "piper-tts", "supertonic"],
        default="edge-tts",
        help="TTS provider",
    )
    p.add_argument(
        "--quality",
        choices=["low", "medium", "high"],
        default="medium",
        help="Voice quality: low=fastest, high=best (piper: model size, supertonic: inference steps)",
    )
    p.add_argument("--gpu", action="store_true", help="Use GPU (CUDA) for Piper")
    p.add_argument(
        "--gpu-provider",
        type=str,
        metavar="PROVIDER",
        help="ONNX execution provider (CUDAExecutionProvider, ROCMExecutionProvider, ...)",
    )
    p.add_argument("--proxy", type=str, help="Proxy URL (default: HTTPS_PROXY env)")
    p.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Playback speed multiplier (0.5-3.0, default 1.0)",
    )
    p.add_argument("--list-voices", action="store_true", help="List available voices")
    p.add_argument(
        "--setup-vmic", action="store_true", help="Create virtual microphone sink"
    )
    p.add_argument(
        "--teardown-vmic", action="store_true", help="Remove virtual microphone sink"
    )
    p.add_argument("--no-cache", action="store_true", help="Disable audio cache")
    p.add_argument("--clear-cache", action="store_true", help="Clear TTS audio cache")
    p.add_argument(
        "-i", "--input-file", type=str, help="Play existing audio file instead of TTS"
    )
    p.add_argument(
        "--volume",
        type=float,
        default=0.7,
        help="Playback volume 0.0-1.0 (default 0.7, applied to -o/-m only)",
    )
    p.add_argument(
        "--interactive",
        action="store_true",
        help="Interactive REPL: read lines from stdin, keep model loaded",
    )
    p.add_argument("text", nargs="?", help="Text to speak")
    return p.parse_args()


async def list_voices(provider: TTSProvider, lang: str | None = None) -> None:
    voices = await provider.list_voices()
    for v in voices:
        if lang and v.locale and not v.locale.startswith(lang):
            continue
        locale_display = v.locale if v.locale else "any"
        print(f"{v.name:50s} {v.gender:8s} {locale_display}")


async def interactive(
    provider: TTSProvider, voice: str, args: argparse.Namespace
) -> None:
    audio_suffix = ".wav" if provider.name in ("piper-tts", "supertonic") else ".mp3"
    loop = asyncio.get_running_loop()

    print(
        f"interactive ({provider.name} — {voice}) — type text, Ctrl+D or empty line to exit",
        file=sys.stderr,
    )

    while True:
        line = await loop.run_in_executor(None, sys.stdin.readline)
        if not line:
            break
        text = line.rstrip("\n")
        if not text:
            continue

        try:
            audio = await provider.synthesize(text, voice, speed=args.speed)
            tasks = []
            if args.output:
                tasks.append(
                    play_audio(audio, sink="", suffix=audio_suffix, volume=args.volume)
                )
            if args.mic:
                tasks.append(
                    play_audio(
                        audio, sink="tts-vmic", suffix=audio_suffix, volume=args.volume
                    )
                )
            if tasks:
                await asyncio.gather(*tasks)
        except Exception as e:
            print(f"error: {e}", file=sys.stderr)


async def run() -> None:
    args = parse_args()

    provider = _make_provider(
        args.provider, args.proxy, args.gpu, args.gpu_provider, args.quality, args.lang
    )

    if args.list_voices:
        await list_voices(provider)
        return

    if args.setup_vmic:
        await vmic_setup()
        return

    if args.teardown_vmic:
        await vmic_teardown()
        return

    if args.clear_cache:
        TTSCache().clear()
        print("cache cleared")
        return

    if args.interactive:
        if not (args.output or args.mic):
            print(
                "error: interactive mode requires -o or -m",
                file=sys.stderr,
            )
            sys.exit(1)
        voice = resolve_voice(
            args.lang, args.voice, args.provider, args.voice_name, args.quality
        )
        await interactive(provider, voice, args)
        return

    if not args.text and not args.input_file:
        print(
            "error: provide text to speak or an audio file via -i",
            file=sys.stderr,
        )
        sys.exit(1)

    if not (args.output or args.mic or args.file):
        print(
            "error: specify at least one output: -o (speaker), -m (mic), -f <file>",
            file=sys.stderr,
        )
        sys.exit(1)

    if args.input_file:
        audio = Path(args.input_file).read_bytes()
        audio_suffix = Path(args.input_file).suffix or ".mp3"
    else:
        audio_suffix = (
            ".wav" if provider.name in ("piper-tts", "supertonic") else ".mp3"
        )
        voice = resolve_voice(
            args.lang, args.voice, args.provider, args.voice_name, args.quality
        )
        cache = TTSCache()
        cache_key_text = f"{args.speed}:{args.text}"
        cached = (
            None if args.no_cache else cache.get(provider.name, voice, cache_key_text)
        )

        if cached is not None:
            audio = cached
        else:
            audio = await provider.synthesize(args.text, voice, speed=args.speed)
            if not args.no_cache:
                cache.set(provider.name, voice, cache_key_text, audio)

    tasks = []
    if args.output:
        tasks.append(
            play_audio(audio, sink="", suffix=audio_suffix, volume=args.volume)
        )
    if args.mic:
        tasks.append(
            play_audio(audio, sink="tts-vmic", suffix=audio_suffix, volume=args.volume)
        )
    if args.file:
        tasks.append(_save_file(audio, args.file))

    if tasks:
        await asyncio.gather(*tasks)


async def _save_file(data: bytes, path: str) -> None:
    Path(path).write_bytes(data)


def main() -> None:
    asyncio.run(run())


if __name__ == "__main__":
    main()
