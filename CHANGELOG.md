# Changelog

All notable changes to PKGReuse are documented here.

## 0.1.0

- Add explicit pip and uv wrapper commands with unchanged remote fallback.
- Automatically initialize the local environment index on first installation.
- Resolve the highest satisfying version strictly from compatible local donors.
- Resolve and transfer complete local dependency closures transactionally.
- Copy distribution metadata while allowing same-volume hard links for package
  content.
- Reject stale, editable, conflicting, unsafe, and unsupported donor content.
- Roll back files created by failed transfers or post-installation validation.
