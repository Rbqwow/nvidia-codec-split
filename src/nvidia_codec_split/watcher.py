"""Single-instance user-session watcher with a graceful stop event."""
from pathlib import Path
import ctypes as c
from ctypes import wintypes as w
import hashlib
import time

from .core import PatchError, load_profile, load_state, verify_native
from .memory import ProcessMemory, WindowsAPI, patch_regions


def instance_name(state_dir: Path) -> str:
    identity = hashlib.sha256(str(state_dir.resolve()).casefold().encode("utf-8")).hexdigest()[:20]
    return "Local\\NVIDIACodecSplit-" + identity


def stop(state_dir: Path) -> bool:
    api = WindowsAPI()
    api.k.OpenEventW.argtypes, api.k.OpenEventW.restype = [w.DWORD, w.BOOL, w.LPCWSTR], w.HANDLE
    api.k.SetEvent.argtypes = [w.HANDLE]
    handle = api.k.OpenEventW(2, False, instance_name(state_dir) + "-Stop")
    if not handle:
        return False
    try:
        if not api.k.SetEvent(handle):
            raise c.WinError(c.get_last_error())
    finally:
        api.k.CloseHandle(handle)
    return True


def run(state_dir: Path) -> int:
    state = load_state(state_dir)
    profile = load_profile(state["profile"])
    root = Path(state["app_root"])
    source = verify_native(root, profile)
    api = WindowsAPI()
    k = api.k
    k.CreateMutexW.argtypes, k.CreateMutexW.restype = [c.c_void_p, w.BOOL, w.LPCWSTR], w.HANDLE
    k.CreateEventW.argtypes, k.CreateEventW.restype = [c.c_void_p, w.BOOL, w.BOOL, w.LPCWSTR], w.HANDLE
    k.WaitForSingleObject.argtypes = [w.HANDLE, w.DWORD]
    mutex = k.CreateMutexW(None, False, instance_name(state_dir))
    if not mutex:
        raise c.WinError(c.get_last_error())
    if c.get_last_error() == 183:
        k.CloseHandle(mutex)
        return 0
    event = k.CreateEventW(None, True, False, instance_name(state_dir) + "-Stop")
    if not event:
        k.CloseHandle(mutex)
        raise c.WinError(c.get_last_error())
    log_file = state_dir / "watcher.log"

    def log(message):
        with log_file.open("a", encoding="utf-8") as stream:
            stream.write(time.strftime("%Y-%m-%d %H:%M:%S ") + message + "\n")

    processed = set()
    rejected = set()
    try:
        log(f"Started profile {profile['version']}; native DLL remains original on disk")
        while k.WaitForSingleObject(event, 0) != 0:
            # Also detect on-disk upgrades while a previously processed PID stays alive.
            verify_native(root, profile)
            recorders = api.recorders(source)
            active = {(item.pid, item.created) for item in recorders}
            processed.intersection_update(active)
            rejected.intersection_update(active)
            for recorder in recorders:
                identity = recorder.pid, recorder.created
                if identity in processed or identity in rejected:
                    continue
                try:
                    with ProcessMemory(api, recorder, source) as process:
                        count = patch_regions(process, profile["native"]["changes"], recorder.base)
                    processed.add(identity)
                    log(f"Verified {len(profile['native']['changes'])} regions in PID {recorder.pid}; wrote {count}")
                except (OSError, PatchError) as error:
                    rejected.add(identity)
                    log(f"Refused PID {recorder.pid}: {error}")
            if k.WaitForSingleObject(event, 2000) == 0:
                break
        log("Stopped gracefully")
        return 0
    except (OSError, PatchError) as error:
        log(f"Stopped: {error}")
        return 1
    finally:
        k.CloseHandle(event)
        k.CloseHandle(mutex)
