[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $projectRoot ".venv\Scripts\python.exe"
$dist = Join-Path $projectRoot "dist"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Development interpreter not found: $python"
}

Push-Location $projectRoot
try {
    & $python -m ruff check .
    if ($LASTEXITCODE -ne 0) { throw "Ruff lint failed." }

    & $python -m ruff format --check .
    if ($LASTEXITCODE -ne 0) { throw "Ruff format check failed." }

    & $python -m mypy
    if ($LASTEXITCODE -ne 0) { throw "MyPy failed." }

    & $python -m pytest --cov=pkgreuse
    if ($LASTEXITCODE -ne 0) { throw "pytest failed." }

    if (Test-Path -LiteralPath $dist) {
        $resolvedDist = (Resolve-Path -LiteralPath $dist).Path
        $resolvedRoot = (Resolve-Path -LiteralPath $projectRoot).Path
        if ((Split-Path -Parent $resolvedDist) -ne $resolvedRoot) {
            throw "Refusing to clean unexpected distribution path: $resolvedDist"
        }
        Remove-Item -LiteralPath $resolvedDist -Recurse -Force
    }

    & $python -m build
    if ($LASTEXITCODE -ne 0) { throw "Distribution build failed." }

    & $python -m twine check dist\*
    if ($LASTEXITCODE -ne 0) { throw "Distribution metadata check failed." }

    & $python scripts\smoke-release.py
    if ($LASTEXITCODE -ne 0) { throw "Fresh-environment smoke test failed." }
}
finally {
    Pop-Location
}
