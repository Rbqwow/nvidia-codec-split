# Contributing

New NVIDIA App builds need a reviewed profile, not a wildcard version or a replaced SHA-256 alone.

For a new build:

1. Confirm whether its stock UI/backend already supports independent HEVC.
2. Work from verified original installation files and keep backups outside the repository.
3. Locate the recording property setter, bitrate query, settings getter and SDR codec-selection branch. Recheck every RVA, field offset, branch target and available padding region.
4. Add a profile under `src/nvidia_codec_split/profiles/`, with the exact original DLL/UI hashes, equal-length byte changes, and frontend match counts.
5. Run the tests, prepare resources locally, and inspect the generated JavaScript syntax.
6. Verify actual manual and Instant Replay clips with `ffprobe`; check H.264 high-framerate behavior, AV1 compatibility, and helper behavior after a service restart.
7. Document tested hardware/builds and any untested behavior. Attach only redacted logs and extracted validation results.

Do not commit complete NVIDIA files, backups, generated UI bundles, recordings, account data or machine state. Profiles contain hashes and small patch/matching fragments needed to transform a user's installed copy.

```powershell
python -m unittest discover -s tests -v
python -O -m unittest discover -s tests -v
```

The implementation must preserve the signed native file on disk, reject unknown memory bytes before any writes, preserve existing HDR/8K checks, and avoid overwriting updated vendor files during restoration. Keep runtime dependencies within the standard library when practical.
