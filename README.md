# PKGReuse

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

PKGReuse is an explicit Windows and Linux command-line wrapper that reuses
compatible Python distributions already installed in other virtual
environments. It can avoid downloading and unpacking a package when a safe
local donor is available.

PKGReuse does not replace or intercept ordinary `pip` and `uv` commands. Local
reuse is enabled only when you invoke the `pkgreuse` command.

> PKGReuse 0.1 is alpha software. Use it in disposable virtual environments
> until its behavior has been validated for your workflow.

## How resolution works

For a requirement such as `filelock>=3,<4`, PKGReuse scans its local environment
index, filters locally installed versions against the requirement, and selects
the highest satisfying local version. It delegates the original requirement to
pip or uv only when the complete dependency closure cannot be reused locally.
It does not query PyPI to maximize a locally satisfiable requirement.

## Installation

```powershell
py -m pip install pkgreuse
```

Run PKGReuse from an active standard Python virtual environment.

## Usage

Use pip as the fallback installer:

```powershell
pkgreuse pip install "requests>=2.31,<3"
```

Or use uv as the fallback installer:

```powershell
pkgreuse uv pip install "requests>=2.31,<3"
```

On the first prefixed installation, PKGReuse automatically creates its local
environment index. It first uses Conda, uv, and pip discovery hints, then
performs a two-level scan around the active project and working directory.
Every candidate is independently validated before it can become a donor.

To discover environments outside that nearby area, explicitly provide one or
more roots. Explicit roots are scanned recursively, so they remain suitable
for a deliberate wider inventory without a default full-disk crawl:

```powershell
pkgreuse init C:\Users\you\Desktop
```

```bash
pkgreuse init "$HOME/projects" /opt
```

Useful diagnostic and planning commands include:

```powershell
pkgreuse status
pkgreuse find requests
pkgreuse resolve "requests>=2.31,<3"
```

## Safety model

PKGReuse validates the complete local dependency plan before changing the
target. Package content may be hard-linked on the same volume, while
distribution metadata is copied. It rejects stale donors, target conflicts,
unsafe RECORD traversal, executable or donor-specific `.pth` files, and
editable installations. Donor launchers are not copied. If transfer or final
validation fails, files created by the transaction are rolled back.

## Development

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\scripts\check-release.ps1
```

On Linux, run the equivalent checks directly:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
.venv/bin/python -m pytest --cov=pkgreuse
```

The native NumPy check is opt-in because it requires a prepared compatible
donor environment:

```powershell
$env:PKGREUSE_NUMPY_REQUIREMENT = "numpy==2.3.3"
.\.venv\Scripts\python.exe -m pytest -m extended tests\extended\test_numpy_manual.py
```

See [the resolution notes](docs/local_maximized_resolution.md) for the solver's
local-maximization semantics.
