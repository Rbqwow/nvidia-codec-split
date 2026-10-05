from pathlib import Path
import argparse
import json
import os
import sys

from .core import PatchError, apply_ui, child_path, default_app_root, default_state_dir, file_hash, load_profile, load_state, prepare, verify_native, verify_prepared


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Version-checked NVIDIA App recording codec split")
    parser.add_argument("command", choices=["prepare", "check", "apply-ui", "restore-ui", "patch-memory", "restore-memory", "status", "watch", "stop-watch"])
    parser.add_argument("--app-root", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument("--profile", default="11.0.9.251")
    parser.add_argument("--original-frontend", type=Path, help="Original osc directory for migrating an already-patched installation")
    args = parser.parse_args(argv)
    try:
        state_dir = (args.state_dir or default_state_dir()).resolve()
        if args.command == "prepare":
            result = prepare(args.app_root or default_app_root(), state_dir, load_profile(args.profile), args.original_frontend)
            print(json.dumps({"profile": result["profile"], "files": len(result["files"]), "state_dir": str(state_dir)}, indent=2))
            return 0
        if args.command == "stop-watch":
            from .watcher import stop
            print(json.dumps({"stop_signaled": stop(state_dir)}))
            return 0
        state = load_state(state_dir)
        root = Path(state["app_root"])
        profile = load_profile(state["profile"])
        if args.app_root and args.app_root.resolve() != root.resolve():
            raise PatchError("App root differs from the prepared installation")
        if args.command == "check":
            verify_native(root, profile)
            verify_prepared(state_dir, state)
            for info in state["files"]:
                digest = file_hash(child_path(root, info["relative"]))
                if digest not in {info["original_sha256"], info["patched_sha256"], *info.get("legacy_patched_sha256", [])}:
                    raise PatchError(f"Installed file changed: {info['relative']}")
            result = {"status": "verified", "files": len(state["files"]), "native_disk_modified": False}
        elif args.command in {"apply-ui", "restore-ui"}:
            result = apply_ui(state_dir, args.command == "restore-ui")
        elif args.command in {"patch-memory", "restore-memory"}:
            from .memory import patch_recorders
            result = patch_recorders(root, profile, args.command == "restore-memory")
        elif args.command == "watch":
            from .watcher import run
            return run(state_dir)
        else:
            result = {"profile": profile["version"], "app_root": str(root), "state_dir": str(state_dir),
                      "native_original": child_path(root, profile["native"]["relative"]).is_file() and
                      file_hash(child_path(root, profile["native"]["relative"])) == profile["native"]["sha256"]}
            if os.name == "nt" and result["native_original"]:
                from .memory import ProcessMemory, WindowsAPI, memory_states
                source = verify_native(root, profile)
                api = WindowsAPI()
                result["recorders"] = []
                for recorder in api.recorders(source):
                    with ProcessMemory(api, recorder, source, write=False) as process:
                        counts = memory_states(process, profile["native"]["changes"], recorder.base)
                    result["recorders"].append({"pid": recorder.pid, "regions": counts})
        print(json.dumps(result, indent=2))
        return 0
    except (PatchError, OSError, KeyError, ValueError) as error:
        message = f"nvidia-codec-split: {error}"
        if sys.stderr:
            print(message, file=sys.stderr)
        else:
            try:
                state_dir.mkdir(parents=True, exist_ok=True)
                with (state_dir / "watcher.log").open("a", encoding="utf-8") as log:
                    log.write(message + "\n")
            except Exception:
                pass
        return 1
