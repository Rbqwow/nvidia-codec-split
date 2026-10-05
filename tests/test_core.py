from pathlib import Path
from tempfile import TemporaryDirectory
import copy
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nvidia_codec_split.core import PatchError, apply_ui, child_path, load_profile, prepare, sha256, transform_locale, validate_profile


class LocalUI(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "app"
        self.state = Path(self.temp.name) / "private-state"
        native = b"synthetic native module, not NVIDIA software"
        main = b"codec = AUTO;\r\nkeep = true;\n"
        locale = b'{"capture":{"CodecHelp1HEVC":"old"},"unrelated":"keep"}'
        self.profile = {"schema": 1, "version": "11.0.9.251", "native": {"relative": "ShadowPlay/record.dll", "sha256": sha256(native), "changes": []},
                        "frontend": {"edits": [{"name": "split", "old": "codec = AUTO", "new": "codec = HEVC", "count": 1}], "files": []}}
        for relative, kind, original, new in [("osc/main.js", "main", main, main.replace(b"AUTO", b"HEVC")),
                                               ("osc/assets/i18n/zh_CN.json", "locale", locale, transform_locale(locale, "zh_CN"))]:
            self.profile["frontend"]["files"].append({"relative": relative, "kind": kind,
                "original_sha256": sha256(original), "patched_sha256": sha256(new)})
            target = self.root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(original)
        target = self.root / "ShadowPlay/record.dll"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(native)
        self.approved = patch("nvidia_codec_split.core.load_profile", return_value=self.profile)
        self.approved.start()
        self.addCleanup(self.approved.stop)

    def test_prepare_apply_restore_keeps_native_untouched_and_preserves_newlines(self):
        native = (self.root / "ShadowPlay/record.dll").read_bytes()
        prepare(self.root, self.state, self.profile)
        self.assertEqual(apply_ui(self.state)["changed"], 2)
        self.assertEqual((self.root / "osc/main.js").read_bytes(), b"codec = HEVC;\r\nkeep = true;\n")
        self.assertEqual(apply_ui(self.state)["changed"], 0)
        self.assertEqual(apply_ui(self.state, restore=True)["changed"], 2)
        self.assertEqual((self.root / "osc/main.js").read_bytes(), b"codec = AUTO;\r\nkeep = true;\n")
        self.assertEqual((self.root / "ShadowPlay/record.dll").read_bytes(), native)

    def test_unknown_native_build_refused_before_writing_state(self):
        (self.root / "ShadowPlay/record.dll").write_bytes(b"updated version")
        with self.assertRaises(PatchError):
            prepare(self.root, self.state, self.profile)
        self.assertFalse(self.state.exists())

    def test_changed_later_resource_refused_before_backup_creation(self):
        (self.root / "osc/assets/i18n/zh_CN.json").write_bytes(b"customized")
        with self.assertRaises(PatchError):
            prepare(self.root, self.state, self.profile)
        self.assertFalse(self.state.exists())

    def test_reprepare_uses_existing_original_backup(self):
        prepare(self.root, self.state, self.profile)
        apply_ui(self.state)
        prepare(self.root, self.state, self.profile)
        self.assertEqual((self.state / "original/osc/main.js").read_bytes(), b"codec = AUTO;\r\nkeep = true;\n")

    def test_updated_resource_is_not_overwritten_during_restore(self):
        prepare(self.root, self.state, self.profile)
        apply_ui(self.state)
        target = self.root / "osc/main.js"
        target.write_bytes(b"new vendor release")
        result = apply_ui(self.state, restore=True)
        self.assertEqual(target.read_bytes(), b"new vendor release")
        self.assertEqual(result["skipped_updated_files"], ["osc/main.js"])

    def test_failed_second_replace_rolls_back_first(self):
        prepare(self.root, self.state, self.profile)
        before = (self.root / "osc/main.js").read_bytes()
        calls = 0
        def replacement(target, data):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("simulated permission failure")
            target.write_bytes(data)
        with self.assertRaisesRegex(PatchError, "rolled back"):
            apply_ui(self.state, replace=replacement)
        self.assertEqual((self.root / "osc/main.js").read_bytes(), before)

    def test_tampered_state_hash_cannot_approve_arbitrary_payload(self):
        prepare(self.root, self.state, self.profile)
        manifest = json.loads((self.state / "manifest.json").read_text())
        manifest["files"][0]["patched_sha256"] = sha256(b"unexpected code")
        (self.state / "manifest.json").write_text(json.dumps(manifest))
        (self.state / "prepared/osc/main.js").write_bytes(b"unexpected code")
        with self.assertRaisesRegex(PatchError, "reviewed profile"):
            apply_ui(self.state)
        self.assertIn(b"AUTO", (self.root / "osc/main.js").read_bytes())

    def test_path_traversal_rejected(self):
        for relative in ["../outside", "osc/../../outside", "C:/Windows/file", "osc\\file"]:
            with self.subTest(relative=relative), self.assertRaises(PatchError):
                child_path(self.root, relative)


class PublicProfile(unittest.TestCase):
    def test_supported_profile_has_six_nonoverlapping_regions_and_33_ui_files(self):
        profile = load_profile()
        self.assertEqual(len(profile["native"]["changes"]), 6)
        self.assertEqual(len(profile["frontend"]["files"]), 33)
        validate_profile(profile)

    def test_overlapping_regions_are_rejected(self):
        profile = copy.deepcopy(load_profile())
        profile["native"]["changes"][1]["rva"] = profile["native"]["changes"][0]["rva"]
        with self.assertRaisesRegex(PatchError, "Overlapping"):
            validate_profile(profile)


if __name__ == "__main__":
    unittest.main()
