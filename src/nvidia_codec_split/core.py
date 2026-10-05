"""Profiles and local UI preparation. No Windows processes are changed here."""
from pathlib import Path
import hashlib
import json
import os
import tempfile


class PatchError(RuntimeError):
    pass


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_hash(path: Path) -> str:
    return sha256(path.read_bytes())


def default_app_root() -> Path:
    return Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "NVIDIA Corporation" / "NVIDIA App"


def default_state_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA")
    if not base:
        raise PatchError("LOCALAPPDATA is unavailable. Supply --state-dir explicitly.")
    return Path(base) / "NVIDIA Codec Split"


def child_path(root: Path, relative: str) -> Path:
    """Reject absolute names, traversals, and symlinks outside the specified root."""
    name = Path(relative)
    if name.is_absolute() or ".." in name.parts or "\\" in relative or ":" in relative:
        raise PatchError(f"Invalid relative path: {relative}")
    resolved = (root / name).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise PatchError(f"Path escapes its root: {relative}")
    return resolved


def load_profile(name: str = "11.0.9.251") -> dict:
    if not name or any(char not in "0123456789." for char in name):
        raise PatchError("Profile names must be numeric NVIDIA App versions.")
    path = Path(__file__).with_name("profiles") / f"{name}.json"
    if not path.is_file():
        raise PatchError(f"No supported profile for {name}. See docs/ADAPTATION.zh-CN.md.")
    profile = json.loads(path.read_text(encoding="utf-8"))
    validate_profile(profile)
    return profile


def validate_profile(profile: dict) -> None:
    if profile.get("schema") != 1:
        raise PatchError("Unsupported profile schema")
    spans = []
    for change in profile["native"]["changes"]:
        original, patched = bytes.fromhex(change["original"]), bytes.fromhex(change["patched"])
        if not original or len(original) != len(patched) or change["rva"] < 0:
            raise PatchError(f"Invalid patch region: {change['name']}")
        spans.append((change["rva"], change["rva"] + len(original)))
    spans.sort()
    if any(right[0] < left[1] for left, right in zip(spans, spans[1:])):
        raise PatchError("Overlapping native patch regions")
    for digest in [profile["native"]["sha256"], *[f["original_sha256"] for f in profile["frontend"]["files"]]]:
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            raise PatchError("Invalid profile SHA-256")


def transform_main(data: bytes, profile: dict) -> bytes:
    text = data.decode("utf-8")
    for edit in profile["frontend"]["edits"]:
        count = text.count(edit["old"])
        if count != edit.get("count", 1):
            raise PatchError(f"Frontend match count changed for {edit['name']}: {count}")
        text = text.replace(edit["old"], edit["new"])
    # Preserve the vendor file's existing line endings; never double CRLF.
    return text.encode("utf-8")


def transform_locale(data: bytes, language: str) -> bytes:
    parsed = json.loads(data.decode("utf-8-sig"))
    capture = parsed.get("capture")
    if not isinstance(capture, dict):
        raise PatchError(f"Missing capture translations in {language}")
    capture.update({
        "CodecH264": "H.264", "CodecHEVC": "HEVC (H.265)",
        "CodecHelp1HEVC": "HEVC records in H.265 at every resolution, including SDR.",
        "CodecHelp2HEVC": "HDR and 8K recording require HEVC or AV1.",
    })
    if language == "zh_CN":
        capture.update(CodecHelp1HEVC="选择 HEVC 可在所有分辨率下使用 H.265，包括 SDR。",
                       CodecHelp2HEVC="录制 HDR 或 8K 内容请使用 HEVC 或 AV1。")
    elif language == "zh_TW":
        capture.update(CodecHelp1HEVC="選擇 HEVC 可在所有解析度下使用 H.265，包括 SDR。",
                       CodecHelp2HEVC="錄製 HDR 或 8K 內容請使用 HEVC 或 AV1。")
    return json.dumps(parsed, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def load_state(state_dir: Path) -> dict:
    path = state_dir / "manifest.json"
    if not path.is_file():
        raise PatchError("No prepared state. Run prepare or Apply.cmd first.")
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != 1:
        raise PatchError("Unsupported state manifest schema")
    return manifest


def verify_native(app_root: Path, profile: dict) -> Path:
    path = child_path(app_root, profile["native"]["relative"])
    if not path.is_file() or file_hash(path) != profile["native"]["sha256"]:
        raise PatchError("Recording DLL does not match the supported signed build; no changes made.")
    return path


def prepare(app_root: Path, state_dir: Path, profile: dict, original_frontend: Path | None = None) -> dict:
    app_root, state_dir = app_root.resolve(), state_dir.resolve()
    verify_native(app_root, profile)
    if state_dir.is_relative_to(app_root):
        raise PatchError("Local state must be outside the NVIDIA installation.")
    if (state_dir / "manifest.json").exists():
        previous = load_state(state_dir)
        if previous["profile"] != profile["version"] or Path(previous["app_root"]).resolve() != app_root:
            raise PatchError("Use a separate state directory for each NVIDIA build/installation.")
    planned = []
    for info in profile["frontend"]["files"]:
        target = child_path(app_root, info["relative"])
        if not target.is_file():
            raise PatchError(f"Missing NVIDIA resource: {info['relative']}")
        current = target.read_bytes()
        current_hash = sha256(current)
        backup = child_path(state_dir, "original/" + info["relative"])
        original = None
        if current_hash == info["original_sha256"]:
            original = current
        elif current_hash in {info["patched_sha256"], *info.get("legacy_patched_sha256", [])}:
            candidates = [backup]
            if original_frontend:
                candidates.append(child_path(original_frontend, info["relative"].removeprefix("osc/")))
            for candidate in candidates:
                if candidate.is_file() and file_hash(candidate) == info["original_sha256"]:
                    original = candidate.read_bytes()
                    break
            if original is None:
                raise PatchError(f"Already patched resource needs its original backup: {info['relative']}")
        else:
            raise PatchError(f"Unsupported or externally modified NVIDIA resource: {info['relative']}")
        if backup.exists() and file_hash(backup) != info["original_sha256"]:
            raise PatchError(f"Existing original backup changed: {info['relative']}")
        patched = transform_main(original, profile) if info["kind"] == "main" else transform_locale(original, Path(info["relative"]).stem)
        if sha256(patched) != info["patched_sha256"]:
            raise PatchError(f"Generated resource does not match the reviewed patch: {info['relative']}")
        planned.append((info, original, patched))
    # All compatibility checks pass before any backups/prepared files are written.
    for info, original, patched in planned:
        backup = child_path(state_dir, "original/" + info["relative"])
        staged = child_path(state_dir, "prepared/" + info["relative"])
        backup.parent.mkdir(parents=True, exist_ok=True)
        staged.parent.mkdir(parents=True, exist_ok=True)
        if not backup.exists():
            backup.write_bytes(original)
        staged.write_bytes(patched)
    manifest = {"schema": 1, "profile": profile["version"], "app_root": str(app_root),
                "files": [{"relative": info["relative"], "original_sha256": info["original_sha256"],
                           "patched_sha256": info["patched_sha256"],
                           "legacy_patched_sha256": info.get("legacy_patched_sha256", [])} for info, _, _ in planned]}
    write_json(state_dir / "manifest.json", manifest)
    return manifest


def verify_prepared(state_dir: Path, manifest: dict) -> None:
    for info in manifest["files"]:
        for folder, digest in [("original", info["original_sha256"]), ("prepared", info["patched_sha256"])]:
            file = child_path(state_dir, folder + "/" + info["relative"])
            if not file.is_file() or file_hash(file) != digest:
                raise PatchError(f"Local {folder} file changed: {info['relative']}")


def replace_file(path: Path, data: bytes) -> None:
    """Stage on the same volume, then replace; no shell-built file operations."""
    fd, name = tempfile.mkstemp(prefix=".codec-split-", suffix=".tmp", dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def apply_ui(state_dir: Path, restore: bool = False, replace=replace_file) -> dict:
    manifest = load_state(state_dir)
    profile = load_profile(manifest["profile"])
    root = Path(manifest["app_root"])
    allowed = {info["relative"] for info in profile["frontend"]["files"]}
    if {info["relative"] for info in manifest["files"]} != allowed:
        raise PatchError("Managed resources differ from the supported profile")
    expected = {info["relative"]: info for info in profile["frontend"]["files"]}
    for info in manifest["files"]:
        approved = expected[info["relative"]]
        for key in ("original_sha256", "patched_sha256"):
            if info[key] != approved[key]:
                raise PatchError("State file hashes differ from the reviewed profile")
        if info.get("legacy_patched_sha256", []) != approved.get("legacy_patched_sha256", []):
            raise PatchError("State compatibility hashes differ from the reviewed profile")
    verify_prepared(state_dir, manifest)
    if not restore:
        verify_native(root, profile)
    operations, skipped = [], []
    for info in manifest["files"]:
        target = child_path(root, info["relative"])
        if not target.is_file():
            if restore:
                skipped.append(info["relative"])
                continue
            raise PatchError(f"Missing installed file: {info['relative']}")
        current = target.read_bytes()
        digest = sha256(current)
        known = {info["original_sha256"], info["patched_sha256"], *info.get("legacy_patched_sha256", [])}
        if digest not in known:
            if restore:
                skipped.append(info["relative"])
                continue
            raise PatchError(f"Installed file changed; refusing overwrite: {info['relative']}")
        desired_hash = info["original_sha256" if restore else "patched_sha256"]
        if digest != desired_hash:
            folder = "original" if restore else "prepared"
            operations.append((target, current, child_path(state_dir, folder + "/" + info["relative"]).read_bytes()))
    completed = []
    try:
        for target, old, new in operations:
            replace(target, new)
            completed.append((target, old))
            if target.read_bytes() != new:
                raise PatchError(f"Replacement verification failed: {target.name}")
    except Exception as failure:
        failures = []
        for target, old in reversed(completed):
            try:
                replace(target, old)
            except Exception as rollback_error:
                failures.append(str(rollback_error))
        if failures:
            raise PatchError(f"Install failed; rollback also failed: {failures}") from failure
        raise PatchError(f"Install failed; completed replacements rolled back: {failure}") from failure
    return {"changed": len(completed), "skipped_updated_files": skipped, "native_disk_modified": False}
