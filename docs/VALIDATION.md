# Validation

## Live recording evidence from the original local implementation

NVIDIA App **11.0.9.251**, RTX 4060 Laptop GPU, driver **616.92**, SDR desktop capture. Saved video streams were inspected with `ffprobe`.

| Capture | Codec/profile | Resolution | Frame rate | Pixel format / transfer |
| --- | --- | --- | --- | --- |
| Manual recording | HEVC Main | 2560×1440 | 120/1 | yuv420p / bt709 |
| Saved Instant Replay | HEVC Main | 2560×1440 | 120/1 | yuv420p / bt709 |
| Explicit H.264, high frame rate | H.264 High | 2560×1440 | 240/1 | yuv420p / bt709 |

The independent UI choices returned `H264/HEVC`, `H265`, and `AV1` respectively through the recording API. AV1 was checked at the UI/API level; an independent AV1 validation clip was not saved. HDR/8K fallback paths were retained, but live HDR/8K clips were not tested.

## Public package validation

The public refactor uses the same six reviewed native byte changes. On the supported local installation:

- All 33 UI resources were prepared and their generated hashes verified in an ignored local state directory.
- Node.js accepted the prepared main bundle syntax.
- The Python and Windows PowerShell `Check` entry points accepted the supported files/backups.
- Read-only runtime inspection found all six native regions already patched by the original local helper, with no unexpected bytes.
- Unit tests cover refusal of unknown builds, refusal before backup creation, idempotent preparation/install, updated-file preservation, path containment, tampered manifests, file rollback, memory preflight checks, partial memory write rollback, and reverse patching.
- The same tests pass with Python optimization enabled; production checks do not rely on `assert`.

Publishing preparation did not replace the active local installation with the refactored installer or run a second helper. CI uses synthetic data and cannot validate NVIDIA hardware capture or live injection.

## Restore regression validation (0.1.1)

The failed original `Restore.cmd` attempted `restore-ui` without a public `manifest.json`. The active installation had been created by the earlier local scripts, whose originals and startup backup used a different location. Version 0.1.1 imports those verified originals before any helper shutdown or UAC step. The subsequent local run also exposed an unavailable `Get-FileHash` in Windows PowerShell; the native hash check now uses .NET SHA-256 directly.

- All 24 Python tests passed normally and with optimization enabled. They include restoration without generated files, damaged-original refusal before writes, legacy state migration, missing-helper recovery from the old project, updated-file preservation, and the actual Windows batch failure exit code.
- Windows PowerShell tests verify public helper shutdown, legacy watcher termination, completion of quoted and unquoted memory-writing children, child timeout refusal, watcher PID reuse refusal, and SHA-256 without `Get-FileHash`.
- Copies of all 33 real, hash-matched legacy UI files were restored to their originals in an ignored staging directory. The recording DLL copy remained original.
- The user manually ran the old restore command before live verification completed. At the final public `Restore.cmd` run, the installed UI and native regions were already original, and the old runtime helper directory had been removed. The public command recovered state from the sibling old project, completed the UAC service restart, and returned exit code 0. It did not need to replace installed UI files or terminate a live legacy helper in that run.

This verifies the restore entry point on an already-restored machine and file restoration in staging. A full public Apply/login/Restore cycle and live termination of an active legacy helper remain separate integration-validation tasks.

The repository includes extracted stream facts and an overlay screenshot, not original recordings, complete NVIDIA resources, or machine-specific logs.
