import asyncio
import os
import shutil
import tempfile

DRAIN_SLEEP = 0.5


def _player_cmd(sink: str, path: str) -> list[str]:
    for prog, sink_flag in (("pw-play", "--target"), ("paplay", "--device")):
        if shutil.which(prog):
            cmd = [prog]
            if sink:
                cmd.extend([sink_flag, sink])
            cmd.append(path)
            return cmd
    raise RuntimeError("neither pw-play nor paplay found")


async def play_audio(audio_data: bytes, sink: str = "", suffix: str = ".mp3") -> int:
    fd, path = tempfile.mkstemp(suffix=suffix)
    os.write(fd, audio_data)
    os.close(fd)
    try:
        cmd = _player_cmd(sink, path)
        proc = await asyncio.create_subprocess_exec(*cmd)
        ret = await proc.wait()
        await asyncio.sleep(DRAIN_SLEEP)
        return ret
    finally:
        os.unlink(path)
