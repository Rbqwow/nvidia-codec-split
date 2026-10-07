from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nvidia_codec_split.core import PatchError, apply_ui, check_restore, sha256
from nvidia_codec_split.legacy import import_legacy_restore


class LegacyRestore(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.app, self.state, self.helper = root / "app", root / "state", root / "helper"
        self.backup = root / "old project/backup"
        self.helper.mkdir()
        self.profile = {"schema": 1, "version": "11.0.9.251",
                        "native": {"relative": "ShadowPlay/record.dll", "sha256": sha256(b"signed original"), "changes": []},
                        "frontend": {"files": []}}
        for relative in ["osc/main.js", "osc/assets/i18n/zh_CN.json"]:
            original, current = (relative + " original").encode(), (relative + " legacy patch").encode()
            info = {"relative": relative, "original_sha256": sha256(original),
                    "patched_sha256": sha256(b"public patch"), "legacy_patched_sha256": [sha256(current)]}
            self.profile["frontend"]["files"].append(info)
            for path, data in [(self.app / relative, current), (self.backup / relative, original)]:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
        self.native_file = self.app / self.profile["native"]["relative"]
        self.native_file.parent.mkdir()
        self.native_file.write_bytes(b"signed original")
        self.native = {"source": str(self.native_file), "original_sha256": self.profile["native"]["sha256"],
                       "backup": str(self.backup / "record.dll")}
        self.write_native()
        # A backup command is parsed, never executed or dot-sourced.
        self.startup = {"Name": "NVIDIA Codec Split", "Previous": None,
                        "Installed": f'"C:/Python/pythonw.exe" "{self.helper / "watcher.py"}"'}
        self.write_startup()
        for name in ["nvidia_codec_split.core.load_profile", "nvidia_codec_split.legacy.load_profile"]:
            mock = patch(name, return_value=self.profile)
            mock.start()
            self.addCleanup(mock.stop)

    def write_native(self):
        (self.helper / "native_manifest.json").write_text(json.dumps(self.native), encoding="utf-8")

    def write_startup(self):
        # Windows PowerShell 5.1's Set-Content -Encoding utf8 produces a BOM.
        (self.backup / "helper-startup.json").write_text(json.dumps(self.startup), encoding="utf-8-sig")

    def import_restore(self):
        return import_legacy_restore(self.app, self.state, self.helper, "11.0.9.251")

    def test_legacy_import_restores_known_files_without_generated_resources(self):
        self.assertEqual(self.import_restore()["imported_legacy_files"], 2)
        self.assertFalse((self.state / "prepared").exists())
        self.assertEqual(check_restore(self.state)["pending_ui_files"], 2)
        self.assertEqual(apply_ui(self.state, restore=True)["changed"], 2)
        self.assertEqual(check_restore(self.state)["pending_ui_files"], 0)
        self.assertEqual(self.native_file.read_bytes(), b"signed original")
        self.import_restore()
        self.assertEqual(apply_ui(self.state, restore=True)["changed"], 0)
        startup = json.loads((self.state / "startup.json").read_text())
        self.assertEqual(startup["Codec"], [2, 0, 0, 0])
        self.assertEqual(startup["LegacyHelper"], str(self.helper.resolve()))

    def test_missing_last_backup_refused_before_state_or_installed_writes(self):
        (self.backup / "osc/assets/i18n/zh_CN.json").unlink()
        with self.assertRaisesRegex(PatchError, "legacy original backup"):
            self.import_restore()
        self.assertFalse(self.state.exists())
        self.assertIn(b"legacy patch", (self.app / "osc/main.js").read_bytes())

    def test_other_installation_refused(self):
        self.native["source"] = str(self.app / "other.dll")
        self.write_native()
        with self.assertRaisesRegex(PatchError, "selected NVIDIA installation"):
            self.import_restore()
        self.assertFalse(self.state.exists())

    def test_other_helper_startup_refused(self):
        self.startup["Installed"] = '"C:/Python/pythonw.exe" "unrelated/watcher.py"'
        self.write_startup()
        with self.assertRaisesRegex(PatchError, "identify this helper"):
            self.import_restore()
        self.assertFalse(self.state.exists())

    def test_conflicting_existing_startup_backup_is_preserved(self):
        self.state.mkdir()
        path = self.state / "startup.json"
        path.write_text('{"Installed":"another helper"}')
        with self.assertRaisesRegex(PatchError, "another helper"):
            self.import_restore()
        self.assertFalse((self.state / "manifest.json").exists())
        self.assertEqual(path.read_text(), '{"Installed":"another helper"}')

    def test_nvidia_update_can_be_uninstalled_without_downgrade(self):
        self.native_file.write_bytes(b"new vendor native build")
        target = self.app / "osc/main.js"
        target.write_bytes(b"new vendor frontend")
        self.import_restore()
        result = apply_ui(self.state, restore=True)
        self.assertEqual(result["changed"], 1)
        self.assertEqual(result["skipped_updated_files"], ["osc/main.js"])
        self.assertEqual(target.read_bytes(), b"new vendor frontend")
        self.assertEqual(self.native_file.read_bytes(), b"new vendor native build")

    def test_original_av1_preference_is_imported(self):
        (self.backup / "original_api_settings.json").write_text(json.dumps({
            "GetInstantReplaySettings": {"payload": {"codec": "AV1"}}}))
        self.import_restore()
        startup = json.loads((self.state / "startup.json").read_text())
        self.assertEqual(startup["Codec"], [3, 0, 0, 0])

    def test_removed_helper_can_be_restored_from_original_project_directory(self):
        legacy_root = self.backup.parent
        (legacy_root / "native_manifest.json").write_text(json.dumps(self.native), encoding="utf-8")
        (self.helper / "native_manifest.json").unlink()
        self.helper.rmdir()
        import_legacy_restore(self.app, self.state, self.helper, "11.0.9.251", legacy_root)
        self.assertEqual(apply_ui(self.state, restore=True)["changed"], 2)


if __name__ == "__main__":
    unittest.main()
