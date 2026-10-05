# Changelog

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
