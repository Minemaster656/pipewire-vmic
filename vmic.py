import asyncio

VMIC_SINK = "tts-vmic"
VMIC_SOURCE = "tts-vmic-source"


async def _get_default_source() -> str:
    out = await _pactun("info")
    for line in out.splitlines():
        line = line.strip()
        if line.startswith("Default Source:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError("could not find default source")


async def _pactun(*args: str) -> str:
    proc = await asyncio.create_subprocess_exec(
        "pactl",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f"pactl {' '.join(args)} failed: {stderr.decode()}")
    return stdout.decode()


async def setup() -> None:
    out = await _pactun("list", "modules", "short")
    if VMIC_SOURCE in out:
        print(f"virtual mic '{VMIC_SOURCE}' already exists")
        return

    real_mic = await _get_default_source()

    out = await _pactun(
        "load-module",
        "module-null-sink",
        f"sink_name={VMIC_SINK}",
        "sink_properties=device.description=TTS-Virtual-Mic",
    )
    null_id = out.strip()
    print(f"null-sink loaded as module #{null_id}")

    out = await _pactun(
        "load-module",
        "module-loopback",
        f"source={real_mic}",
        f"sink={VMIC_SINK}",
    )
    loop_id = out.strip()
    print(f"loopback (real mic → vmic) loaded as module #{loop_id}")

    out = await _pactun(
        "load-module",
        "module-virtual-source",
        f"source_name={VMIC_SOURCE}",
        f"master={VMIC_SINK}.monitor",
        "source_properties=device.description=TTS-Virtual-Mic",
    )
    vsrc_id = out.strip()
    print(f"virtual source loaded as module #{vsrc_id}")
    print(f"\nSelect '{VMIC_SOURCE}' as your microphone in apps")


async def teardown() -> None:
    out = await _pactun("list", "modules", "short")
    for line in out.strip().split("\n"):
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        mod_id = parts[0]
        mod_desc = " ".join(parts[1:])
        if VMIC_SINK in mod_desc or VMIC_SOURCE in mod_desc:
            await _pactun("unload-module", mod_id)
            print(f"unloaded module #{mod_id}: {mod_desc[:60]}")
