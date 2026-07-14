import argparse
import asyncio
import sys
from pathlib import Path

from audio import play_audio
from cache import TTSCache
from tts_provider import EdgeTTSProvider, TTSProvider, resolve_voice
from vmic import setup as vmic_setup, teardown as vmic_teardown


def _make_provider(name: str, proxy: str | None = None) -> TTSProvider:
    if name == "edge-tts":
        return EdgeTTSProvider(proxy=proxy)
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
        "--provider", choices=["edge-tts"], default="edge-tts", help="TTS provider"
    )
    p.add_argument("--proxy", type=str, help="Proxy URL (default: HTTPS_PROXY env)")
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
    p.add_argument("text", nargs="?", help="Text to speak")
    return p.parse_args()


async def list_voices(provider: TTSProvider, lang: str | None = None) -> None:
    voices = await provider.list_voices()
    for v in voices:
        if lang and not v.locale.startswith(lang):
            continue
        print(f"{v.name:50s} {v.gender:8s} {v.locale}")


async def run() -> None:
    args = parse_args()

    provider = _make_provider(args.provider, args.proxy)

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
        audio_suffix = ".mp3"
        voice = resolve_voice(args.lang, args.voice, args.voice_name)
        cache = TTSCache()
        cached = None if args.no_cache else cache.get(provider.name, voice, args.text)

        if cached is not None:
            audio = cached
        else:
            audio = await provider.synthesize(args.text, voice)
            if not args.no_cache:
                cache.set(provider.name, voice, args.text, audio)

    tasks = []
    if args.output:
        tasks.append(play_audio(audio, sink="", suffix=audio_suffix))
    if args.mic:
        tasks.append(play_audio(audio, sink="tts-vmic", suffix=audio_suffix))
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
