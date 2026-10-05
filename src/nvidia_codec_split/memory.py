"""Windows process access and guarded, reversible native code changes."""
from ctypes import wintypes as w
from dataclasses import dataclass
from pathlib import Path
import ctypes as c
import os

from .core import PatchError, verify_native


@dataclass(frozen=True)
class Recorder:
    pid: int
    created: int
    base: int


def patch_regions(adapter, changes: list[dict], base: int, restore: bool = False) -> int:
    """Validate all regions, write while suspended, and roll back a failed write."""
    completed = []
    with adapter.suspended():
        operations = []
        for change in changes:
            old = bytes.fromhex(change["patched" if restore else "original"])
            new = bytes.fromhex(change["original" if restore else "patched"])
            address = base + change["rva"]
            actual = adapter.read(address, len(old))
            if actual == new:
                continue
            if actual != old:
                raise PatchError(f"Unexpected memory at {change['name']}; no patch applied")
            operations.append((address, actual, new))
        try:
            for address, old, new in operations:
                # Include the current write in rollback in case it only partly succeeds.
                completed.append((address, old))
                adapter.write(address, new)
                if adapter.read(address, len(new)) != new:
                    raise PatchError("Memory write verification failed")
        except Exception as failure:
            errors = []
            for address, old in reversed(completed):
                try:
                    adapter.write(address, old)
                except Exception as error:
                    errors.append(str(error))
            if errors:
                raise PatchError(f"Memory patch failed and rollback failed: {errors}; reload recording service") from failure
            raise PatchError(f"Memory patch failed; original bytes restored: {failure}") from failure
    return len(completed)


class WindowsAPI:
    def __init__(self):
        if os.name != "nt" or c.sizeof(c.c_void_p) != 8:
            raise PatchError("Runtime patching requires 64-bit Python on Windows.")
        self.k = c.WinDLL("kernel32", use_last_error=True)
        self.p = c.WinDLL("psapi", use_last_error=True)
        self.n = c.WinDLL("ntdll")
        k, p, n = self.k, self.p, self.n
        k.OpenProcess.argtypes, k.OpenProcess.restype = [w.DWORD, w.BOOL, w.DWORD], w.HANDLE
        k.CloseHandle.argtypes = [w.HANDLE]
        k.ReadProcessMemory.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
        k.WriteProcessMemory.argtypes = k.ReadProcessMemory.argtypes
        k.VirtualProtectEx.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t, w.DWORD, c.POINTER(w.DWORD)]
        k.FlushInstructionCache.argtypes = [w.HANDLE, c.c_void_p, c.c_size_t]
        k.GetProcessTimes.argtypes = [w.HANDLE, c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p]
        p.EnumProcessModulesEx.argtypes = [w.HANDLE, c.c_void_p, w.DWORD, c.POINTER(w.DWORD), w.DWORD]
        p.GetModuleFileNameExW.argtypes = [w.HANDLE, w.HMODULE, w.LPWSTR, w.DWORD]
        k.CreateToolhelp32Snapshot.argtypes, k.CreateToolhelp32Snapshot.restype = [w.DWORD, w.DWORD], w.HANDLE
        n.NtSuspendProcess.argtypes = n.NtResumeProcess.argtypes = [w.HANDLE]
        n.NtSuspendProcess.restype = n.NtResumeProcess.restype = c.c_long

    def module_base(self, handle, source: Path) -> int | None:
        modules = (w.HMODULE * 1024)()
        needed = w.DWORD()
        if not self.p.EnumProcessModulesEx(handle, modules, c.sizeof(modules), c.byref(needed), 3):
            return None
        for module in modules[:min(len(modules), needed.value // c.sizeof(w.HMODULE))]:
            filename = c.create_unicode_buffer(32768)
            if self.p.GetModuleFileNameExW(handle, module, filename, len(filename)):
                if Path(filename.value).resolve() == source.resolve():
                    return module
        return None

    def created_time(self, handle) -> int:
        values = [c.c_ulonglong() for _ in range(4)]
        if not self.k.GetProcessTimes(handle, *[c.byref(value) for value in values]):
            raise c.WinError(c.get_last_error())
        return values[0].value

    def recorders(self, source: Path) -> list[Recorder]:
        class Process(c.Structure):
            _fields_ = [("size", w.DWORD), ("usage", w.DWORD), ("pid", w.DWORD),
                        ("heap", c.c_size_t), ("module", w.DWORD), ("threads", w.DWORD),
                        ("parent", w.DWORD), ("priority", w.LONG), ("flags", w.DWORD),
                        ("exe", w.WCHAR * 260)]
        self.k.Process32FirstW.argtypes = self.k.Process32NextW.argtypes = [w.HANDLE, c.POINTER(Process)]
        snapshot = self.k.CreateToolhelp32Snapshot(2, 0)
        if snapshot == c.c_void_p(-1).value:
            raise c.WinError(c.get_last_error())
        entry = Process()
        entry.size = c.sizeof(entry)
        result = []
        try:
            available = self.k.Process32FirstW(snapshot, c.byref(entry))
            while available:
                if entry.exe.lower() == "nvcontainer.exe":
                    handle = self.k.OpenProcess(0x410, False, entry.pid)
                    if handle:
                        try:
                            base = self.module_base(handle, source)
                            if base is not None:
                                result.append(Recorder(entry.pid, self.created_time(handle), base))
                        except OSError:
                            pass
                        finally:
                            self.k.CloseHandle(handle)
                available = self.k.Process32NextW(snapshot, c.byref(entry))
        finally:
            self.k.CloseHandle(snapshot)
        return result


class ProcessMemory:
    def __init__(self, api: WindowsAPI, recorder: Recorder, source: Path, write: bool = True):
        self.api = api
        self.handle = api.k.OpenProcess(0x0c38 if write else 0x410, False, recorder.pid)
        if not self.handle:
            raise c.WinError(c.get_last_error())
        if api.created_time(self.handle) != recorder.created or api.module_base(self.handle, source) != recorder.base:
            self.close()
            raise PatchError("Recording process changed between discovery and access")

    def close(self):
        if self.handle:
            self.api.k.CloseHandle(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *ignored):
        self.close()

    def read(self, address: int, size: int) -> bytes:
        buffer = c.create_string_buffer(size)
        count = c.c_size_t()
        if not self.api.k.ReadProcessMemory(self.handle, address, buffer, size, c.byref(count)):
            raise c.WinError(c.get_last_error())
        if count.value != size:
            raise PatchError("Incomplete memory read")
        return buffer.raw

    def write(self, address: int, data: bytes):
        old = w.DWORD()
        if not self.api.k.VirtualProtectEx(self.handle, address, len(data), 0x40, c.byref(old)):
            raise c.WinError(c.get_last_error())
        try:
            count = c.c_size_t()
            if not self.api.k.WriteProcessMemory(self.handle, address, data, len(data), c.byref(count)):
                raise c.WinError(c.get_last_error())
            if count.value != len(data):
                raise PatchError("Incomplete memory write")
        finally:
            discarded = w.DWORD()
            if not self.api.k.VirtualProtectEx(self.handle, address, len(data), old.value, c.byref(discarded)):
                raise c.WinError(c.get_last_error())
        if not self.api.k.FlushInstructionCache(self.handle, address, len(data)):
            raise c.WinError(c.get_last_error())

    def suspended(self):
        from contextlib import contextmanager

        @contextmanager
        def scope():
            status = self.api.n.NtSuspendProcess(self.handle)
            if status != 0:
                raise PatchError(f"Unable to suspend recording process: {status}")
            try:
                yield
            finally:
                status = self.api.n.NtResumeProcess(self.handle)
                if status != 0:
                    raise PatchError(f"Unable to resume recording process: {status}")
        return scope()


def memory_states(adapter, changes: list[dict], base: int) -> dict:
    counts = {"original": 0, "patched": 0, "unexpected": 0}
    for change in changes:
        data = adapter.read(base + change["rva"], len(bytes.fromhex(change["original"])))
        key = "patched" if data == bytes.fromhex(change["patched"]) else "original" if data == bytes.fromhex(change["original"]) else "unexpected"
        counts[key] += 1
    return counts


def patch_recorders(app_root: Path, profile: dict, restore: bool = False) -> list[dict]:
    source = verify_native(app_root, profile)
    api = WindowsAPI()
    results = []
    for recorder in api.recorders(source):
        with ProcessMemory(api, recorder, source) as process:
            changed = patch_regions(process, profile["native"]["changes"], recorder.base, restore)
        results.append({"pid": recorder.pid, "changed_regions": changed})
    return results
