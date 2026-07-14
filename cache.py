import hashlib
from pathlib import Path
from platformdirs import user_cache_dir


class TTSCache:
    def __init__(self, cache_dir: str | None = None):
        self.cache_dir = Path(cache_dir or user_cache_dir("ttsspeaker"))
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _key(self, provider: str, voice: str, text: str) -> str:
        raw = f"{provider}\0{voice}\0{text}".encode()
        return hashlib.sha256(raw).hexdigest()

    def get(self, provider: str, voice: str, text: str) -> bytes | None:
        path = self.cache_dir / self._key(provider, voice, text)
        return path.read_bytes() if path.exists() else None

    def set(self, provider: str, voice: str, text: str, data: bytes) -> None:
        path = self.cache_dir / self._key(provider, voice, text)
        path.write_bytes(data)

    def clear(self) -> None:
        import shutil

        shutil.rmtree(self.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def has(self, provider: str, voice: str, text: str) -> bool:
        return (self.cache_dir / self._key(provider, voice, text)).exists()
