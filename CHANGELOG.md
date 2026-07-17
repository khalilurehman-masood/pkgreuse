# Changelog

All notable changes to PKGReuse are documented here.

## 0.1.2

- Replace automatic full-filesystem discovery with fast Conda, uv, and pip
  hints plus a two-level project-neighbourhood scan.
- Keep explicit `pkgreuse init <root>` discovery recursive for intentional
  wider scans.

## 0.1.1

- Skip malformed or incompatible donor Python executables during discovery.
- Prune pytest caches and the Windows per-user temporary directory from scans.

## 0.1.0

- Add explicit pip and uv wrapper commands with unchanged remote fallback.
- Automatically initialize the local environment index on first installation.
- Resolve the highest satisfying version strictly from compatible local donors.
- Resolve and transfer complete local dependency closures transactionally.
- Copy distribution metadata while allowing same-volume hard links for package
  content.
- Reject stale, editable, conflicting, unsafe, and unsupported donor content.
- Roll back files created by failed transfers or post-installation validation.
