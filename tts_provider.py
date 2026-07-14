from __future__ import annotations

import asyncio
import io
import json
import os
import re
import wave
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.error import HTTPError
from urllib.request import urlretrieve

from platformdirs import user_cache_dir

if TYPE_CHECKING:
    from piper.voice import PiperVoice


@dataclass(frozen=True)
class Voice:
    name: str
    gender: str
    locale: str


GENDER_VOICE_MAP: dict[str, dict[tuple[str, str], str | tuple[str, str]]] = {
    "edge-tts": {
        ("en", "male"): "en-US-GuyNeural",
        ("en", "female"): "en-US-JennyNeural",
        ("ru", "male"): "ru-RU-DmitryNeural",
        ("ru", "female"): "ru-RU-SvetlanaNeural",
    },
    "piper-tts": {
        ("en", "male"): ("en_US", "lessac"),
        ("en", "female"): ("en_US", "amy"),
        ("ru", "male"): ("ru_RU", "dmitri"),
        ("ru", "female"): ("ru_RU", "irina"),
    },
    "supertonic": {
        ("en", "male"): "M1",
        ("en", "female"): "F1",
    },
}


class TTSProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def list_voices(self) -> list[Voice]: ...

    @abstractmethod
    async def synthesize(
        self, text: str, voice: str, *, speed: float = 1.0
    ) -> bytes: ...


class EdgeTTSProvider(TTSProvider):
    def __init__(self, proxy: str | None = None):
        raw = proxy or os.environ.get("HTTPS_PROXY") or os.environ.get("http_proxy")
        if raw and not raw.startswith("http://") and not raw.startswith("https://"):
            raw = f"http://{raw}"
        self._proxy = raw

    @property
    def name(self) -> str:
        return "edge-tts"

    async def list_voices(self) -> list[Voice]:
        import edge_tts

        raw = await edge_tts.list_voices(proxy=self._proxy)
        return [
            Voice(
                name=v["ShortName"],
                gender=v.get("Gender", ""),
                locale=v["Locale"],
            )
            for v in raw
        ]

    async def synthesize(self, text: str, voice: str, *, speed: float = 1.0) -> bytes:
        import edge_tts

        rate = _speed_to_edge_rate(speed)
        if rate:
            communicate = edge_tts.Communicate(
                text, voice, proxy=self._proxy, rate=rate
            )
        else:
            communicate = edge_tts.Communicate(text, voice, proxy=self._proxy)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                d = chunk.get("data")
                if d is not None:
                    chunks.append(d)
        return b"".join(chunks)


_PIPER_VOICE_PATTERN = re.compile(r"^([a-z]{2,3}_[A-Z]{2})-([^-]+)-(.+)$")


def _speed_to_edge_rate(speed: float) -> str | None:
    if speed == 1.0:
        return None
    pct = int(round((speed - 1.0) * 100))
    return f"+{pct}%" if pct >= 0 else f"{pct}%"


class PiperTTSProvider(TTSProvider):
    def __init__(
        self,
        download_dir: str | Path | None = None,
        gpu: bool = False,
        gpu_provider: str | None = None,
    ):
        if download_dir is None:
            download_dir = Path(user_cache_dir("ttsspeaker")) / "piper" / "voices"
        self._download_dir = Path(download_dir)
        self._gpu = gpu
        self._gpu_provider = gpu_provider
        self._voice_cache: dict[str, PiperVoice] = {}

    @property
    def name(self) -> str:
        return "piper-tts"

    async def list_voices(self) -> list[Voice]:
        return [
            Voice(name="en_US-lessac-low", gender="Male", locale="en-US"),
            Voice(name="en_US-lessac-medium", gender="Male", locale="en-US"),
            Voice(name="en_US-lessac-high", gender="Male", locale="en-US"),
            Voice(name="en_US-amy-low", gender="Female", locale="en-US"),
            Voice(name="en_US-amy-medium", gender="Female", locale="en-US"),
            Voice(name="en_US-joe-medium", gender="Male", locale="en-US"),
            Voice(name="en_US-kristin-medium", gender="Female", locale="en-US"),
            Voice(name="en_US-bryce-medium", gender="Male", locale="en-US"),
            Voice(name="en_US-danny-low", gender="Male", locale="en-US"),
            Voice(name="en_GB-alan-low", gender="Male", locale="en-GB"),
            Voice(name="en_GB-alan-medium", gender="Male", locale="en-GB"),
            Voice(
                name="en_GB-southern_english_female-low",
                gender="Female",
                locale="en-GB",
            ),
            Voice(
                name="en_GB-northern_english_male-medium", gender="Male", locale="en-GB"
            ),
            Voice(name="ru_RU-dmitri-medium", gender="Male", locale="ru-RU"),
            Voice(name="ru_RU-irina-medium", gender="Female", locale="ru-RU"),
            Voice(name="ru_RU-denis-medium", gender="Male", locale="ru-RU"),
            Voice(name="ru_RU-ruslan-medium", gender="Male", locale="ru-RU"),
        ]

    async def synthesize(self, text: str, voice: str, *, speed: float = 1.0) -> bytes:
        piper_voice = await self._load_voice(voice)
        loop = asyncio.get_running_loop()

        from piper import SynthesisConfig

        syn_config = SynthesisConfig(length_scale=1.0 / max(speed, 0.1))

        audio_chunks: list[bytes] = []
        sample_rate = 0

        def _run():
            nonlocal sample_rate
            for chunk in piper_voice.synthesize(text, syn_config=syn_config):
                if sample_rate == 0:
                    sample_rate = chunk.sample_rate
                audio_chunks.append(chunk.audio_int16_bytes)

        await loop.run_in_executor(None, _run)

        buf = io.BytesIO()
        with wave.open(buf, "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(sample_rate)
            wav.writeframes(b"".join(audio_chunks))
        return buf.getvalue()

    def _model_path(self, voice: str) -> Path:
        return self._download_dir / f"{voice}.onnx"

    def _config_path(self, voice: str) -> Path:
        return self._download_dir / f"{voice}.onnx.json"

    def _providers(self) -> list[str]:
        if self._gpu_provider:
            return [self._gpu_provider]
        if self._gpu:
            return ["CUDAExecutionProvider"]
        return ["CPUExecutionProvider"]

    async def _ensure_model(self, voice: str) -> None:
        model_path = self._model_path(voice)
        config_path = self._config_path(voice)

        if model_path.exists() and config_path.exists():
            return

        self._download_dir.mkdir(parents=True, exist_ok=True)

        m = _PIPER_VOICE_PATTERN.match(voice)
        if not m:
            raise ValueError(
                f"invalid piper voice name '{voice}' — expected <lang>-<name>-<quality>"
            )

        lang_family = m.group(1).split("_")[0]
        lang_code = m.group(1)
        voice_name = m.group(2)
        quality = m.group(3)

        base_url = (
            f"https://huggingface.co/rhasspy/piper-voices/resolve/main/"
            f"{lang_family}/{lang_code}/{voice_name}/{quality}/"
            f"{lang_code}-{voice_name}-{quality}"
        )

        loop = asyncio.get_running_loop()

        for ext, dest in [(".onnx", model_path), (".onnx.json", config_path)]:
            if dest.exists():
                continue
            url = base_url + ext + "?download=true"
            try:
                await loop.run_in_executor(None, urlretrieve, url, str(dest))
            except HTTPError as e:
                if e.code == 404 and quality != "medium":
                    fallback = f"{lang_code}-{voice_name}-medium"
                    print(
                        f"warning: '{voice}' not found, falling back to '{fallback}'",
                        file=__import__("sys").stderr,
                    )
                    await self._ensure_model(fallback)
                    import shutil

                    for ext, dest in [
                        (".onnx", model_path),
                        (".onnx.json", config_path),
                    ]:
                        src = (
                            self._model_path(fallback)
                            if ext == ".onnx"
                            else self._config_path(fallback)
                        )
                        shutil.copy2(src, dest)
                    return
                raise RuntimeError(
                    f"voice '{voice}' not found at {url} ({e.code}). "
                    f"check available voices with --list-voices --provider piper-tts"
                )

    async def _load_voice(self, voice: str) -> "PiperVoice":
        if voice in self._voice_cache:
            return self._voice_cache[voice]

        await self._ensure_model(voice)

        import onnxruntime
        from piper import PiperConfig
        from piper.voice import PiperVoice as _PiperVoice

        model_path = self._model_path(voice)
        config_path = self._config_path(voice)

        loop = asyncio.get_running_loop()

        def _load():
            config_dict = json.loads(config_path.read_text())
            config = PiperConfig.from_dict(config_dict)
            sess_opts = onnxruntime.SessionOptions()
            session = onnxruntime.InferenceSession(
                str(model_path), sess_options=sess_opts, providers=self._providers()
            )
            return _PiperVoice(
                session=session,
                config=config,
                download_dir=self._download_dir,
            )

        piper_voice = await loop.run_in_executor(None, _load)
        self._voice_cache[voice] = piper_voice
        return piper_voice


class SupertonicTTSProvider(TTSProvider):
    _QUALITY_STEPS = {"low": 5, "medium": 8, "high": 12}

    def __init__(self, quality: str = "medium", lang: str = "en"):
        self._quality = quality
        self._lang = lang or "na"
        self._tts = None

    @property
    def name(self) -> str:
        return "supertonic"

    async def list_voices(self) -> list[Voice]:
        return [
            Voice(name="M1", gender="Male", locale=""),
            Voice(name="M2", gender="Male", locale=""),
            Voice(name="M3", gender="Male", locale=""),
            Voice(name="M4", gender="Male", locale=""),
            Voice(name="M5", gender="Male", locale=""),
            Voice(name="F1", gender="Female", locale=""),
            Voice(name="F2", gender="Female", locale=""),
            Voice(name="F3", gender="Female", locale=""),
            Voice(name="F4", gender="Female", locale=""),
            Voice(name="F5", gender="Female", locale=""),
        ]

    async def synthesize(self, text: str, voice: str, *, speed: float = 1.0) -> bytes:
        import soundfile as sf
        from supertonic import TTS

        loop = asyncio.get_running_loop()

        if self._tts is None:
            self._tts = await loop.run_in_executor(
                None, lambda: TTS(auto_download=True)
            )

        def _run() -> bytes:
            style = self._tts.get_voice_style(voice_name=voice)
            total_steps = self._QUALITY_STEPS.get(self._quality, 8)
            wav, _ = self._tts.synthesize(
                text=text,
                voice_style=style,
                lang=self._lang,
                speed=max(0.7, min(speed, 2.0)),
                total_steps=total_steps,
            )
            buf = io.BytesIO()
            sf.write(buf, wav.squeeze(), 44100, format="WAV")
            return buf.getvalue()

        return await loop.run_in_executor(None, _run)


def resolve_voice(
    lang: str,
    gender: str,
    provider: str = "edge-tts",
    voice_name: str | None = None,
    quality: str = "medium",
) -> str:
    if voice_name:
        return voice_name

    provider_map = GENDER_VOICE_MAP.get(provider, {})
    entry = provider_map.get((lang, gender))
    if entry is None:
        entry = provider_map.get(("en", gender))
    if entry is None:
        entry = GENDER_VOICE_MAP["edge-tts"][("en", "male")]

    if isinstance(entry, tuple):
        lang_code, base_name = entry
        return f"{lang_code}-{base_name}-{quality}"

    return entry
