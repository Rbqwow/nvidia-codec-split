# Changelog

## 0.1.1

- Fix `Restore.cmd` for the original local installation: import verified originals and startup metadata even when the public state manifest is absent.
- Find a sibling `nvidia_codec_patch` project when the installed legacy helper was removed; support an explicit `-LegacyRoot` for other locations.
- Validate restore sources before stopping helpers or requesting UAC. Generated patch files are no longer required to restore originals.
- Stop the legacy watcher without terminating its memory-writing children; wait for those transactions and reject reused watcher PIDs.
- Restore the login entry after the administrator step succeeds, and preserve `Restore.cmd`'s failure exit code across `pause`.
- Check the native SHA-256 through .NET so Windows PowerShell restoration does not depend on `Get-FileHash` availability.
- Add legacy migration, missing-backup, Windows entry point and helper shutdown regression tests.

## 0.1.0

- Publish an exact-build profile for NVIDIA App 11.0.9.251.
- Expose separate H.264, HEVC and AV1 overlay settings.
- Keep the signed native DLL on disk and patch the loaded recording module.
- Replace machine-specific paths with configurable install/state directories.
- Generate private local backups; refuse unsupported builds and unexpected bytes.
- Add graceful helper shutdown, process creation-time tracking, and memory write rollback.
- Preserve vendor JavaScript line endings instead of duplicating CRLF when preparing resources.
- Restore only known managed resources, leaving newer vendor files intact.
- Add English/Chinese documentation and synthetic compatibility/rollback tests.
