"""Import verified originals from the first local helper; never run its code."""
from pathlib import Path
import json
import re

from .core import PatchError, child_path, file_hash, load_profile, load_state, sha256, write_json


def import_legacy_restore(app_root: Path, state_dir: Path, helper_dir: Path, profile_name: str,
                          legacy_root: Path | None = None) -> dict:
    app_root, state_dir, helper_dir = app_root.resolve(), state_dir.resolve(), helper_dir.resolve()
    profile = load_profile(profile_name)
    native_path = (legacy_root.resolve() if legacy_root else helper_dir) / "native_manifest.json"
    if not native_path.is_file():
        raise PatchError("No restore manifest or legacy helper backup found. Keep the original state directory; "
                         "use -StateDir, -LegacyHelper or -LegacyRoot to select the installation being restored.")
    native = json.loads(native_path.read_text(encoding="utf-8-sig"))
    if (native["original_sha256"] != profile["native"]["sha256"] or
            Path(native["source"]).resolve() != child_path(app_root, profile["native"]["relative"])):
        raise PatchError("Legacy helper does not belong to the selected NVIDIA installation/profile")
    if state_dir.is_relative_to(app_root):
        raise PatchError("Local state must be outside the NVIDIA installation.")

    backup_root = Path(native["backup"]).resolve().parent
    startup = json.loads((backup_root / "helper-startup.json").read_text(encoding="utf-8-sig"))
    match = re.fullmatch(r'"[^"\r\n]+\.exe"\s+"([^"\r\n]+)"', startup.get("Installed", ""), re.IGNORECASE)
    if (startup.get("Name") != "NVIDIA Codec Split" or not match or
            Path(match[1]).resolve() != helper_dir / "watcher.py" or
            (startup.get("Previous") is not None and not isinstance(startup["Previous"], str))):
        raise PatchError("Legacy startup backup does not identify this helper")

    # The old helper stored the original codec in its API snapshot. Only this
    # field is imported; unrelated NVIDIA preferences are never replayed.
    codec = 2  # Original H.264/HEVC automatic mode if the snapshot is absent.
    snapshot = backup_root / "original_api_settings.json"
    if snapshot.is_file():
        original = json.loads(snapshot.read_text(encoding="utf-8-sig"))
        value = original.get("GetInstantReplaySettings", {}).get("payload", {}).get("codec")
        codecs = {"H264/HEVC": 2, "AV1": 3}
        if value not in codecs:
            raise PatchError("Unsupported original codec in legacy settings backup")
        codec = codecs[value]
    startup = {"Name": startup["Name"], "Previous": startup.get("Previous"),
               "Installed": startup["Installed"], "Codec": list(codec.to_bytes(4, "little")),
               "LegacyHelper": str(helper_dir)}

    files, originals = [], []
    for info in profile["frontend"]["files"]:
        source = child_path(backup_root / "osc", info["relative"].removeprefix("osc/"))
        if not source.is_file() or file_hash(source) != info["original_sha256"]:
            raise PatchError(f"Missing or changed legacy original backup: {info['relative']}")
        target = child_path(state_dir, "original/" + info["relative"])
        if target.exists() and file_hash(target) != info["original_sha256"]:
            raise PatchError(f"Existing original backup changed: {info['relative']}")
        files.append({key: info[key] for key in ("relative", "original_sha256", "patched_sha256")})
        files[-1]["legacy_patched_sha256"] = info.get("legacy_patched_sha256", [])
        originals.append((target, source.read_bytes()))
        if sha256(originals[-1][1]) != info["original_sha256"]:
            raise PatchError(f"Legacy backup changed while reading: {info['relative']}")
    manifest = {"schema": 1, "profile": profile["version"], "app_root": str(app_root), "files": files}
    if (state_dir / "manifest.json").exists() and load_state(state_dir) != manifest:
        raise PatchError("Existing state belongs to a different or modified installation")
    startup_path = state_dir / "startup.json"
    if startup_path.exists() and json.loads(startup_path.read_text(encoding="utf-8-sig")) != startup:
        raise PatchError("Existing startup backup belongs to another helper")

    # All originals and metadata are checked before creating any restore state.
    # No generated/patched vendor files are needed to uninstall.
    for target, data in originals:
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
    write_json(state_dir / "manifest.json", manifest)
    write_json(startup_path, startup)
    return {"imported_legacy_files": len(files), "helper_dir": str(helper_dir), "state_dir": str(state_dir)}
