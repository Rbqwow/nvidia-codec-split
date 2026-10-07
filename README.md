# NVIDIA Codec Split

[中文说明](README.zh-CN.md) · [Version adaptation](docs/ADAPTATION.zh-CN.md) · [Validation](docs/VALIDATION.md)

Select **H.264**, **HEVC (H.265)** or **AV1** independently in NVIDIA App's recording overlay. HEVC can record **1440p SDR** without selecting 4K or enabling HDR. The settings apply to manual recording, Instant Replay and the shared video capture configuration.

This is an experimental, unofficial Windows utility. The supported build is **NVIDIA App 11.0.9.251**, identified by exact file hashes. Other builds are refused until an adapted profile is reviewed. Tested hardware: RTX 4060 Laptop GPU, driver 616.92.

![Independent HEVC setting in NVIDIA Overlay](docs/images/codec-settings.png)

## Install

Requirements: Windows x64, a GPU supporting NVIDIA HEVC recording, **64-bit Python 3.11+** with `python.exe` on PATH, and the supported NVIDIA App build. `pythonw.exe` must be available beside the Python executable. No Python dependencies are needed at runtime.

1. Clone or download this repository.
2. Save any active recording and turn off Instant Replay while installing.
3. Run **`Apply.cmd`** from your ordinary user session. Windows UAC grants the installation-directory write step.
4. Open NVIDIA Overlay → Settings → Video capture → Codec, and select **HEVC (H.265)**.

The patch is prepared from your own installed files. Original resources, generated files, logs and startup metadata stay in `%LOCALAPPDATA%\NVIDIA Codec Split`; NVIDIA binaries and complete application resources are not distributed with the repository.

For a non-default installation or state directory:

```powershell
powershell.exe -NoProfile -File .\Install.ps1 -Action Apply `
  -AppRoot 'C:\Program Files\NVIDIA Corporation\NVIDIA App' `
  -StateDir "$env:LOCALAPPDATA\NVIDIA Codec Split"
```

If the original local codec helper already owns the login entry, run `Restore.cmd` first; it can import that installation's verified backups. An already-patched UI also needs its verified original `osc` directory through `-OriginalFrontend` if this project's local backups are not available.

## What it changes

- The overlay JavaScript and translations expose separate choices and preserve HEVC when settings are read back. HEVC appears only when hardware support and the patched backend capability query both succeed.
- The original signed recording DLL remains unchanged **on disk**. A user-session `pythonw.exe` helper applies six reviewed code changes **in memory** after NVIDIA loads it.
- The helper checks the original DLL hash every poll, validates all code regions before writing, tracks process creation time to handle PID reuse, and stops on an unsupported on-disk build.
- Memory writes occur while the recording process is briefly suspended. A failed write attempts to restore all affected regions before resuming the process.
- H.264 respects the explicit selection for supported SDR modes, including the tested 1440p/240 FPS case. Existing HDR, 8K and hardware-required fallback behavior is preserved; select HEVC or AV1 for HDR/8K.

The login entry is named `NVIDIA Codec Split`. Logs are in the local state directory's `watcher.log`. The helper uses only the Python standard library and does not download or send data.

## Verify and restore

```powershell
python .\run.py status
```

`native_original: true` confirms the recording DLL matches the supported original. For the running recorder, all six regions should report `patched` and zero `unexpected` regions. `Check.cmd` checks the installed resources and local backups without modifying NVIDIA files.

To uninstall, save active recordings and run **`Restore.cmd`**. It validates all original backups before stopping the helper, restores the UI, restarts the NVIDIA recording service, and restores the login entry after that step succeeds. The public helper stops gracefully; the original helper's memory-writing children are allowed to finish before the service restarts. Files replaced by a newer NVIDIA update are skipped rather than overwritten with old backups. Keep the local state directory until restoration is complete; generated files under `prepared` are not needed to uninstall.

If this project's `manifest.json` is absent, restoration can import originals and startup metadata using the old helper's `native_manifest.json`. If that helper directory was removed, a sibling `nvidia_codec_patch` project is also detected. For a different location or a custom state directory:

```powershell
.\Restore.cmd -LegacyRoot 'C:\Backups\nvidia_codec_patch'
.\Restore.cmd -StateDir 'C:\Backups\NVIDIA Codec Split'
```

Use `-LegacyHelper` as well if the old runtime helper was installed at a custom path. Missing or changed originals cause an error before UAC; the command returns a nonzero exit code. After a successful restore on the supported build, `python .\run.py status` reports six `original` regions and zero `patched` regions. `python .\run.py check-restore` checks the restore sources without requiring generated patch files.

NVIDIA App updates can replace the UI or native code. A new version requires a new profile; changing only the hash or bypassing region checks is insufficient. See the [adaptation workflow](docs/ADAPTATION.zh-CN.md).

## Validation and development

The original local implementation recorded HEVC Main at **2560×1440, 120 FPS, 8-bit SDR** using both manual capture and saved Instant Replay. Explicit H.264 recording at **2560×1440, 240 FPS** remained H.264 High. See [validation details](docs/VALIDATION.md) for the distinction between original live recording tests and public-package checks.

```powershell
python -m unittest discover -s tests -v
python -O -m unittest discover -s tests -v
```

CI checks Windows and Linux with Python 3.11 and 3.14 using synthetic files and fake process memory. It does not require an NVIDIA GPU or perform live injection. Maintainer inspection tools can additionally use `pefile` and `capstone` through `pip install -e ".[adaptation]"`.

Contributions for additional builds should include hashes, reviewed code locations and actual recorded-video validation. See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Project code and documentation are licensed under [MIT](LICENSE). NVIDIA software is not included and is not covered by this project's license. NVIDIA trademarks and the illustrated application UI belong to their respective owners. This project is not affiliated with NVIDIA.
