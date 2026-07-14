import os
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class Voice:
    name: str
    gender: str
    locale: str


GENDER_VOICE_MAP: dict[tuple[str, str], str] = {
    ("en", "male"): "en-US-GuyNeural",
    ("en", "female"): "en-US-JennyNeural",
    ("ru", "male"): "ru-RU-DmitryNeural",
    ("ru", "female"): "ru-RU-SvetlanaNeural",
}


class TTSProvider(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def list_voices(self) -> list[Voice]: ...

    @abstractmethod
    async def synthesize(self, text: str, voice: str) -> bytes: ...


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

    async def synthesize(self, text: str, voice: str) -> bytes:
        import edge_tts

        communicate = edge_tts.Communicate(text, voice, proxy=self._proxy)
        chunks: list[bytes] = []
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                d = chunk.get("data")
                if d is not None:
                    chunks.append(d)
        return b"".join(chunks)


def resolve_voice(lang: str, gender: str, voice_name: str | None = None) -> str:
    if voice_name:
        return voice_name
    return GENDER_VOICE_MAP.get((lang, gender), "en-US-GuyNeural")
