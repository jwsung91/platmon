# Changelog

Versions use MAJOR.MINOR.PATCH. The application version is defined once in
`frontends/cli.py`; Debian packaging revisions use a separate `-N` suffix.
API schema versions are independent of release versions.

## 0.1.0 — Unreleased

- First versioned distribution of the existing platform monitor.
- Debian package with a systemd service, standalone CLI and preserved INI configuration.
- Server and CLI `--version`, source archive, build manifest and SHA-256 checksums.
- Source installer stages updates and restores previous code/unit on startup failure.
- Package and release validation workflows; an explicit version tag creates a draft release.
