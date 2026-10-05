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

Publishing preparation did not replace the active local installation with the refactored installer or run a second helper. The full refactored UAC installation/login/uninstall sequence therefore remains a separate integration-validation task. CI uses synthetic data and cannot validate NVIDIA hardware capture or live injection.

The repository includes extracted stream facts and an overlay screenshot, not original recordings, complete NVIDIA resources, or machine-specific logs.
