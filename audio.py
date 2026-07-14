import asyncio
import os
import tempfile


def _parse_sink_name(name: str) -> str:
    if name == "default":
        return ""
    return name


async def play_audio(audio_data: bytes, sink: str = "", suffix: str = ".mp3") -> int:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.write(fd, audio_data)
    os.close(fd)
    try:
        cmd = ["paplay"]
        if sink:
            cmd.extend(["--device", sink])
        cmd.append(path)
        proc = await asyncio.create_subprocess_exec(*cmd)
        return await proc.wait()
    finally:
        os.unlink(path)
