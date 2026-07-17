from __future__ import annotations

import argparse
import platform
import sys
import sysconfig
import time
from pathlib import Path
from time import perf_counter_ns

from pkgreuse import __version__
from pkgreuse.application.indexing import (
    IndexInitializationService,
    TargetIndexRefreshService,
)
from pkgreuse.application.indexing import (
    default_scan_roots as application_default_scan_roots,
)
from pkgreuse.application.installation import (
    InstallPreparationStatus,
    LocalInstallationService,
)
from pkgreuse.application.installers import InstallerService
from pkgreuse.application.queries import LocalQueryService
from pkgreuse.dependencies import analyze_dependencies
from pkgreuse.domain.errors import BackendError, PKGReuseError
from pkgreuse.index import (
    find_package_candidates,
    is_target_environment,
)
from pkgreuse.infrastructure.backends import backend_for
from pkgreuse.infrastructure.index_repository import JsonIndexRepository
from pkgreuse.inventory import scan_environment_packages
from pkgreuse.resolver import (
    build_installation_plan,
    select_candidate,
    target_installed_version,
    version_satisfies,
)
from pkgreuse.scanner import (
    DEFAULT_NEIGHBORHOOD_DEPTH,
    create_environment_index,
    environment_site_packages,
)
from pkgreuse.transfer import (
    choose_donor,
    create_transfer_plan,
    execute_installation_plan,
    execute_transfer_plan,
    format_size,
    validate_installed_distribution,
)


def is_virtual_environment() -> bool:
    """Return True when running inside a standard virtual environment."""
    return sys.prefix != sys.base_prefix


def require_virtual_environment() -> bool:
    """Print an error when pkgreuse is not running inside a venv."""
    if is_virtual_environment():
        return True

    print("Error: pkgreuse is not running inside a virtual environment.")
    print("Create and activate a virtual environment before using it.")
    return False


def show_status() -> int:
    """Display information about the currently active Python environment."""
    print(f"pkgreuse {__version__}")
    print()

    if not require_virtual_environment():
        return 1

    environment_path = Path(sys.prefix).resolve()
    python_path = Path(sys.executable).resolve()
    index_path = environment_path / ".pkgreuse" / "index.json"

    print("Active virtual environment detected")
    print(f"Environment:     {environment_path}")
    print(f"Python:          {python_path}")
    print(f"Base Python:     {Path(sys.base_prefix).resolve()}")
    print(f"Implementation:  {platform.python_implementation()}")
    print(f"Version:         {platform.python_version()}")
    print(f"Architecture:    {platform.architecture()[0]}")
    print(f"Platform:        {sys.platform}")
    print(f"Cache tag:       {sys.implementation.cache_tag}")
    print(f"SOABI:           {sysconfig.get_config_var('SOABI') or 'unknown'}")
    print(f"Local index:     {index_path}")
    print(f"Index exists:    {'yes' if index_path.is_file() else 'no'}")

    return 0


def default_scan_roots() -> tuple[Path, ...]:
    """Choose bounded project-neighbourhood roots for automatic discovery."""
    return application_default_scan_roots()


def default_scan_root() -> Path:
    """Return the first automatic scan root for compatibility."""
    return default_scan_roots()[0]


def index_initialization_service() -> IndexInitializationService:
    """Compose the target-local index initialization service."""
    target = Path(sys.prefix).resolve()
    repository = JsonIndexRepository(target / ".pkgreuse" / "index.json")
    return IndexInitializationService(
        repository,
        create_environment_index,
        target,
        automatic_builder=lambda roots, environment: create_environment_index(
            roots,
            environment,
            max_depth=DEFAULT_NEIGHBORHOOD_DEPTH,
        ),
    )


def target_refresh_service() -> TargetIndexRefreshService:
    """Compose the target-only index refresh service."""
    target = Path(sys.prefix).resolve()
    repository = JsonIndexRepository(target / ".pkgreuse" / "index.json")
    return TargetIndexRefreshService(
        repository,
        target,
        environment_site_packages,
        scan_environment_packages,
    )


def local_installation_service() -> LocalInstallationService:
    """Compose local installation orchestration from application ports."""
    return LocalInstallationService(
        initialization=index_initialization_service(),
        installed_version=target_installed_version,
        version_satisfies=version_satisfies,
        candidate_selector=select_candidate,
        plan_builder=build_installation_plan,
        plan_executor=execute_installation_plan,
    )


def local_query_service() -> LocalQueryService:
    """Compose read-only package lookup and planning use cases."""
    target = Path(sys.prefix).resolve()
    repository = JsonIndexRepository(target / ".pkgreuse" / "index.json")
    return LocalQueryService(
        repository=repository,
        candidate_finder=find_package_candidates,
        donor_selector=choose_donor,
        candidate_selector=select_candidate,
        transfer_planner=create_transfer_plan,
        dependency_analyzer=analyze_dependencies,
        resolution_planner=build_installation_plan,
    )


def refresh_target_index() -> None:
    """Refresh target inventory without invalidating a successful install."""
    try:
        target_refresh_service().refresh()
    except (PKGReuseError, RuntimeError, OSError) as exc:
        print(f"Warning: package installed, but target index refresh failed: {exc}")


def initialize_index(root_arguments: list[str]) -> int:
    """Scan for matching environments and create the local index."""
    if not require_virtual_environment():
        return 1

    roots = [Path(root) for root in root_arguments] or list(default_scan_roots())

    target_environment = Path(sys.prefix).resolve()

    print("Initializing pkgreuse")
    print(f"Target environment: {target_environment}")
    print("Scan roots:")

    for root in roots:
        print(f"  - {root}")

    print()
    print("Scanning for Python virtual environments...")

    try:
        service = index_initialization_service()
        initialized = (
            service.initialize(roots)
            if root_arguments
            else service.initialize_default()
        )
    except PKGReuseError as exc:
        print(f"Error: {exc}")
        return 1

    index_path = initialized.path
    index_data = initialized.data

    scan = index_data["scan"]

    print()
    print("Local environment index created")
    print(f"Index:                   {index_path}")
    print(f"Scan time:               {scan['elapsed_seconds']:.4f} seconds")
    print(f"Directories checked:     {scan['directories_checked']:,}")
    print(f"Environments found:      {scan['environments_found']}")
    print(f"Compatible environments: {scan['compatible_environments']}")
    print(f"Skipped environments:    {scan['skipped_environments']}")
    print(f"Distributions indexed:   {scan['distributions_indexed']:,}")
    print(f"Unique package names:    {scan['unique_package_names']:,}")
    print(f"Metadata failures:       {scan['package_metadata_failures']:,}")

    if scan["compatible_environments"] == 0:
        print()
        print("No environments using the exact same Python interpreter were found.")

    return 0


def find_package(package_query: str) -> int:
    """Search the local JSON index for a package."""
    if not require_virtual_environment():
        return 1

    started_at = perf_counter_ns()

    try:
        lookup = local_query_service().lookup(package_query)
    except (PKGReuseError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1

    normalized_name = lookup.package_name
    versions = lookup.versions

    elapsed_ms = (perf_counter_ns() - started_at) / 1_000_000

    if not versions:
        print(f"Package not found in the local index: {package_query}")
        print(f"Lookup completed in {elapsed_ms:.3f} ms")
        return 1

    donor_count = 0
    target_count = 0

    print(f"Package found: {normalized_name}")
    print()

    for version, candidates in versions.items():
        donor_candidates = []
        target_candidates = []

        for candidate in candidates:
            if is_target_environment(candidate["environment"]):
                target_candidates.append(candidate)
            else:
                donor_candidates.append(candidate)

        if not donor_candidates and not target_candidates:
            continue

        print(f"Version {version}")

        if target_candidates:
            target_count += len(target_candidates)
            print("  Already installed in target environment")

        for candidate in donor_candidates:
            donor_count += 1

            editable_label = (
                " [editable—not reusable]" if candidate.get("editable") else ""
            )

            record_label = "" if candidate.get("record") else " [RECORD missing]"

            print(f"  Donor: {candidate['environment']}{editable_label}{record_label}")

        print()

    print(f"Reusable donor candidates: {donor_count}")
    print(f"Target installations:      {target_count}")
    print(f"Lookup completed in:        {elapsed_ms:.3f} ms")

    return 0 if donor_count or target_count else 1


def plan_package_transfer(package_query: str) -> int:
    """Build and display a dry-run package transfer plan."""
    if not require_virtual_environment():
        return 1

    started_at = perf_counter_ns()

    try:
        planning = local_query_service().transfer_plan(package_query)
        plan = planning.plan
    except (PKGReuseError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1

    elapsed_ms = (perf_counter_ns() - started_at) / 1_000_000

    print("Package transfer plan")
    print()
    print(f"Package:             {plan['package']}")
    print(f"Version:             {plan['version']}")
    print(f"Donor:               {plan['donor']}")
    print(f"Target:              {plan['target_environment']}")
    print(f"Same drive:          {'yes' if plan['same_drive'] else 'no'}")
    print(f"Files owned:         {plan['file_count']:,}")
    print(f"site-packages files: {plan['site_packages_files']:,}")
    print(f"Environment files:   {plan['environment_files']:,}")
    print(f"Skipped bytecode:    {plan['skipped_bytecode_files']:,}")
    print(f"Skipped launchers:   {len(plan['skipped_launcher_files']):,}")
    print(f"Transfer size:       {format_size(plan['total_size_bytes'])}")
    print(f"Existing conflicts:  {len(plan['conflicts']):,}")
    print(f"Missing source files:{len(plan['missing_files']):>4,}")
    print(f"Unsafe paths:        {len(plan['unsafe_files']):,}")
    print(f"Planning time:       {elapsed_ms:.3f} ms")
    if plan["environment_file_paths"]:
        print()
        print("Environment-level files:")

        for file_entry in plan["environment_file_paths"]:
            print(f"  RECORD: {file_entry['record_path']}")
            print(f"  Source: {file_entry['source']}")
            print(f"  Target: {file_entry['destination']}")
    if plan["skipped_launcher_files"]:
        print()
        print("Skipped donor-specific launchers:")

        for launcher in plan["skipped_launcher_files"]:
            print(f"  {launcher}")

        print(
            "  These commands will not be available until launcher "
            "regeneration is implemented."
        )

    if plan["conflicts"]:
        print()
        print("Target conflicts:")

        for conflict in plan["conflicts"][:10]:
            print(f"  {conflict}")

        remaining = len(plan["conflicts"]) - 10

        if remaining > 0:
            print(f"  ...and {remaining} more")

    if plan["missing_files"]:
        print()
        print("Missing donor files:")

        for missing_file in plan["missing_files"][:10]:
            print(f"  {missing_file}")

        remaining = len(plan["missing_files"]) - 10

        if remaining > 0:
            print(f"  ...and {remaining} more")

    if plan["unsafe_files"]:
        print()
        print("Unsafe RECORD paths:")

        for unsafe_file in plan["unsafe_files"][:10]:
            print(f"  {unsafe_file}")

        remaining = len(plan["unsafe_files"]) - 10

        if remaining > 0:
            print(f"  ...and {remaining} more")

    print()
    print("Dry run only. No files were changed.")

    return 0


def reuse_package(package_query: str) -> int:
    """Transfer one exact package version from an indexed environment."""
    if not require_virtual_environment():
        return 1

    try:
        planning = local_query_service().transfer_plan(
            package_query,
            require_exact=True,
        )
        normalized_name = planning.package_name
        requested_version = planning.version
        plan = planning.plan
    except (PKGReuseError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1

    print("Package reuse plan")
    print()
    print(f"Package:          {normalized_name}")
    print(f"Version:          {requested_version}")
    print(f"Donor:            {plan['donor']}")
    print(f"Files:            {plan['file_count']:,}")
    print(f"Size:             {format_size(plan['total_size_bytes'])}")
    print(
        f"Transfer method:  "
        f"{'hard link with copy fallback' if plan['same_drive'] else 'copy'}"
    )

    safety_errors: list[str] = []

    if plan["conflicts"]:
        safety_errors.append(f"{len(plan['conflicts'])} target conflicts")

    if plan["missing_files"]:
        safety_errors.append(f"{len(plan['missing_files'])} missing donor files")

    if plan["unsafe_files"]:
        safety_errors.append(f"{len(plan['unsafe_files'])} unsafe paths")

    if plan["environment_files"]:
        safety_errors.append(f"{plan['environment_files']} environment-level files")

    if safety_errors:
        print()
        print("Transfer refused:")

        for error in safety_errors:
            print(f"  - {error}")

        print()
        print("Run the plan command for details:")
        print(f"  pkgreuse plan {normalized_name}=={requested_version}")

        return 1

    print()
    print("Reusing installed package...")

    last_progress_update = 0.0

    def show_progress(completed: int, total: int) -> None:
        nonlocal last_progress_update

        now = time.perf_counter()

        if completed != total and now - last_progress_update < 0.08:
            return

        last_progress_update = now

        bar_width = 24
        filled = int(bar_width * completed / total)

        bar = "█" * filled + "-" * (bar_width - filled)

        print(
            f"\r[{bar}] {completed:,}/{total:,} files",
            end="",
            flush=True,
        )

    try:
        result = execute_transfer_plan(
            plan=plan,
            progress_callback=show_progress,
        )

        print()

        validate_installed_distribution(
            package_name=normalized_name,
            expected_version=requested_version,
        )

    except Exception as exc:
        print()
        print(f"Error: {exc}")
        return 1

    print()
    print("Package reused successfully")
    print(f"Package:          {result['package']}")
    print(f"Version:          {result['version']}")
    print(f"Files transferred:{result['files_transferred']:>7,}")
    print(f"Hard linked:      {result['hardlinked_files']:>7,}")
    print(f"Physically copied:{result['copied_files']:>7,}")
    print(f"Package size:     {format_size(result['bytes_transferred'])}")
    print(f"Transfer time:    {result['elapsed_seconds']:.4f} seconds")
    print("Metadata validation: passed")

    return 0


def show_package_dependencies(package_query: str) -> int:
    """Show dependency availability for one exact indexed package."""
    if not require_virtual_environment():
        return 1

    started_at = perf_counter_ns()

    try:
        analysis = local_query_service().dependencies(package_query)
        normalized_name = analysis.package_name
        requested_version = analysis.version
        donor = analysis.donor
        dependencies = analysis.dependencies
    except (PKGReuseError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1

    elapsed_ms = (perf_counter_ns() - started_at) / 1_000_000

    print("Package dependency analysis")
    print()
    print(f"Package: {normalized_name}")
    print(f"Version: {requested_version}")
    print(f"Donor:   {donor['environment']}")
    print()

    required_count = 0
    installed_count = 0
    reusable_count = 0
    missing_count = 0
    optional_count = 0

    if not dependencies:
        print("No declared dependencies.")
        print()
        print(f"Analysis time: {elapsed_ms:.3f} ms")
        return 0

    for dependency in dependencies:
        status = dependency["status"]

        if status == "optional":
            optional_count += 1
            label = "OPTIONAL"

        elif status == "installed":
            required_count += 1
            installed_count += 1
            label = f"INSTALLED {dependency['target_version']}"

        elif status == "reusable":
            required_count += 1
            reusable_count += 1
            versions_text = ", ".join(dependency["available_versions"])
            label = f"REUSABLE: {versions_text}"

        elif status == "missing":
            required_count += 1
            missing_count += 1
            label = "MISSING LOCALLY"

        else:
            required_count += 1
            missing_count += 1
            label = "UNPARSED"

        print(f"[{label}]")
        print(f"  {dependency['requirement']}")

    print()
    print(f"Required dependencies: {required_count}")
    print(f"Already installed:     {installed_count}")
    print(f"Reusable locally:      {reusable_count}")
    print(f"Missing locally:       {missing_count}")
    print(f"Optional extras:       {optional_count}")
    print(f"Analysis time:         {elapsed_ms:.3f} ms")

    return 0


def plan_complete_installation(
    package_query: str,
) -> int:
    """Build a local-only recursive installation plan."""
    if not require_virtual_environment():
        return 1

    started_at = perf_counter_ns()

    try:
        resolution = local_query_service().resolution_plan(package_query)
        normalized_name = resolution.package_name
        requested_version = resolution.version
        plan = resolution.plan
    except (PKGReuseError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}")
        return 1

    elapsed_ms = (perf_counter_ns() - started_at) / 1_000_000

    print("Complete local installation plan")
    print()
    print(f"Root package: {normalized_name}=={requested_version}")
    print()

    for package in plan["packages"]:
        transfer = package["transfer"]

        source_label = (
            "root"
            if package["required_by"] is None
            else f"required by {package['required_by']}"
        )

        print(f"{package['name']}=={package['version']}")
        print(f"  Source: {source_label}")
        print(f"  Donor:  {package['donor']}")
        print(f"  Files:  {transfer['file_count']:,}")
        print(f"  Size:   {format_size(transfer['total_size_bytes'])}")

        blockers: list[str] = []

        if transfer["conflicts"]:
            blockers.append(f"{len(transfer['conflicts'])} target conflicts")

        if transfer["missing_files"]:
            blockers.append(f"{len(transfer['missing_files'])} missing files")

        if transfer["unsafe_files"]:
            blockers.append(f"{len(transfer['unsafe_files'])} unsafe paths")

        if transfer["environment_files"]:
            blockers.append(f"{transfer['environment_files']} environment-level files")

        if transfer.get("invalid_pth_files"):
            blockers.append(f"{len(transfer['invalid_pth_files'])} unsafe .pth files")

        if blockers:
            print(f"  Status: BLOCKED — {', '.join(blockers)}")
        else:
            print("  Status: reusable")

        print()

    if plan["already_installed"]:
        print(f"Already satisfied in target: {len(plan['already_installed'])}")

    if plan["missing"]:
        print()
        print("Missing locally:")

        for item in plan["missing"]:
            print(f"  {item['requirement']} (required by {item['required_by']})")

    if plan["conflicts"]:
        print()
        print("Dependency conflicts:")

        for item in plan["conflicts"]:
            print(
                f"  {item['package']}: selected "
                f"{item['selected']}, requested "
                f"{item['requested']} by "
                f"{item['required_by']}"
            )

    if plan["overlapping_files"]:
        print()
        print(f"Inter-package file overlaps: {len(plan['overlapping_files'])}")

    print()
    print(f"Packages to reuse: {len(plan['packages'])}")
    print(f"Total files:       {plan['total_files']:,}")
    print(f"Total size:        {format_size(plan['total_size_bytes'])}")
    print(f"Missing packages:  {len(plan['missing'])}")
    print(f"Dependency conflicts: {len(plan['conflicts'])}")
    print(f"Planning time:     {elapsed_ms:.3f} ms")
    print()
    print("Dry run only. No files were changed.")

    return 0


def install_complete_local_package(
    package_query: str,
    fallback_backend: str | None = None,
) -> int:
    """
    Reuse a package and its complete locally available dependency
    closure as one transaction.
    """
    if not require_virtual_environment():
        return 1

    def fallback(reason: str) -> int:
        """Use pip or uv when local reuse cannot complete."""
        if fallback_backend is None:
            print(f"Error: {reason}")
            return 1

        print(f"Local reuse unavailable: {reason}")
        print("No local files were changed.")

        return run_backend_install(
            backend=fallback_backend,
            package_query=package_query,
        )

    planning_started_at = perf_counter_ns()
    service = local_installation_service()

    def show_automatic_initialization() -> None:
        print("No local PKGReuse index was found.")
        print("Scanning for compatible virtual environments...")

    try:
        preparation = service.prepare(
            package_query,
            on_index_missing=show_automatic_initialization,
        )
        normalized_name = preparation.package_name
        requested_version = preparation.requested_version

        if preparation.status is InstallPreparationStatus.ALREADY_SATISFIED:
            print("Requirement already satisfied")
            print()
            print(f"  {normalized_name}=={preparation.installed_version}")
            print()
            print(f"Location: {Path(sys.prefix).resolve()}")
            print("No files were changed.")
            return 0

        if preparation.status is InstallPreparationStatus.FALLBACK_REQUIRED:
            return fallback(preparation.reason or "local reuse is unavailable.")

        if preparation.plan is None:
            return fallback(preparation.reason or "local reuse is unavailable.")

        installation_plan = preparation.plan

    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    except (PKGReuseError, RuntimeError) as exc:
        return fallback(str(exc))

    planning_ms = (perf_counter_ns() - planning_started_at) / 1_000_000

    blocked_packages: list[str] = []

    for package in installation_plan["packages"]:
        transfer = package["transfer"]
        blockers: list[str] = []

        if transfer["conflicts"]:
            blockers.append(f"{len(transfer['conflicts'])} conflicts")

        if transfer["missing_files"]:
            blockers.append(f"{len(transfer['missing_files'])} missing files")

        if transfer["unsafe_files"]:
            blockers.append(f"{len(transfer['unsafe_files'])} unsafe paths")

        if transfer["environment_files"]:
            blockers.append(f"{transfer['environment_files']} environment-level files")

        if blockers:
            blocked_packages.append(
                f"{package['name']}=={package['version']}: {', '.join(blockers)}"
            )

    print("Local package installation")
    print()
    print(f"Root package:       {normalized_name}=={requested_version}")
    print(f"Packages to reuse:  {len(installation_plan['packages'])}")
    print(f"Files to transfer:  {installation_plan['total_files']:,}")
    print(f"Total package size: {format_size(installation_plan['total_size_bytes'])}")
    print(f"Planning time:      {planning_ms:.3f} ms")

    safety_failures = False

    if installation_plan["missing"]:
        safety_failures = True
        print()
        print("Missing local dependencies:")

        for item in installation_plan["missing"]:
            print(f"  {item['requirement']} (required by {item['required_by']})")

    if installation_plan["conflicts"]:
        safety_failures = True
        print()
        print("Dependency conflicts:")

        for item in installation_plan["conflicts"]:
            print(
                f"  {item['package']}: "
                f"{item['selected']} conflicts with "
                f"{item['requested']}"
            )

    if installation_plan["overlapping_files"]:
        safety_failures = True
        print()
        print("Installation contains overlapping distribution files.")

    if blocked_packages:
        safety_failures = True
        print()
        print("Blocked package transfers:")

        for blocker in blocked_packages:
            print(f"  {blocker}")

    if safety_failures:
        print()

        return fallback(
            "the complete package dependency closure could not be safely reused."
        )

    print()
    print("Installing from existing environments...")

    last_progress_update = 0.0
    current_package = ""

    def show_installation_progress(
        package_name: str,
        completed: int,
        total: int,
    ) -> None:
        nonlocal last_progress_update
        nonlocal current_package

        now = time.perf_counter()

        package_changed = package_name != current_package

        if (
            not package_changed
            and completed != total
            and now - last_progress_update < 0.08
        ):
            return

        current_package = package_name
        last_progress_update = now

        bar_width = 24
        filled = int(bar_width * completed / total)

        bar = "█" * filled + "-" * (bar_width - filled)

        package_label = package_name[:20].ljust(20)

        print(
            f"\r{package_label} [{bar}] {completed:,}/{total:,}",
            end="",
            flush=True,
        )

    try:
        result = service.execute(
            preparation,
            progress_callback=show_installation_progress,
        )
    except Exception as exc:
        print()
        print()
        print(f"Local installation failed: {exc}")
        print("All files created by the local installation were rolled back.")

        return fallback("the local package transfer or validation failed.")

    refresh_target_index()

    print()
    print()
    print("Local installation completed")
    print()

    for package_name, version in result["package_versions"].items():
        print(f"  {package_name}=={version}")

    print()
    print(f"Packages installed: {result['packages_installed']}")
    print(f"Files transferred:  {result['files_transferred']:,}")
    print(f"Hard linked:        {result['hardlinked_files']:,}")
    print(f"Physically copied:  {result['copied_files']:,}")
    print(f"Package size:       {format_size(result['bytes_transferred'])}")
    print(f"Installation time:  {result['elapsed_seconds']:.4f} seconds")
    print("Metadata validation: passed")
    print("Dependency validation: passed")

    return 0


def run_backend_install(
    backend: str,
    package_query: str,
) -> int:
    """Install a requirement using the requested real installer."""
    try:
        installer = backend_for(backend)
        service = InstallerService(installer)
        arguments = ["install", package_query]
        command = installer.command(Path(sys.executable), arguments)
    except BackendError as exc:
        print(f"Error: {exc}")
        return 1

    print()
    print("Delegating to the original installer:")
    print(f"  {' '.join(command)}")
    print()

    try:
        execution = service.install(
            Path(sys.executable),
            arguments,
        )
    except (BackendError, OSError) as exc:
        print(f"Error: could not start {backend}: {exc}")
        return 1

    if execution.return_code != 0:
        print()
        print(f"{backend} installation failed with exit code {execution.return_code}.")
    else:
        refresh_target_index()

    return execution.return_code


def handle_prefixed_installer(
    backend: str,
    installer_arguments: list[str],
) -> int:
    """
    Handle explicit pip or uv-prefixed installation commands.

    Supported initially:
        pkgreuse pip install package==version
        pkgreuse uv pip install package==version
    """
    if backend == "pip":
        expected_prefix = ["install"]

    elif backend == "uv":
        expected_prefix = ["pip", "install"]

    else:
        print(f"Error: unsupported installer backend: {backend}")
        return 1

    prefix_length = len(expected_prefix)

    if installer_arguments[:prefix_length] != expected_prefix:
        if backend == "pip":
            print("Error: currently supported syntax is:")
            print("  pkgreuse pip install package==version")
        else:
            print("Error: currently supported syntax is:")
            print("  pkgreuse uv pip install package==version")

        return 1

    remaining_arguments = installer_arguments[prefix_length:]

    if len(remaining_arguments) != 1:
        print("Error: the wrapper supports exactly one package requirement.")
        print("Exact pins and standard version bounds are supported:")
        print("  package==version")
        print("  package>=minimum,<maximum")
        return 1

    package_query = remaining_arguments[0]

    print(f"Backend requested: {backend}")
    print("Local reuse mode: enabled because the command was prefixed with pkgreuse")
    print()

    return install_complete_local_package(
        package_query=package_query,
        fallback_backend=backend,
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the command-line parser."""
    parser = argparse.ArgumentParser(
        prog="pkgreuse",
        description=(
            "Reuse installed Python packages from existing virtual environments."
        ),
    )

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    commands = parser.add_subparsers(
        dest="command",
        required=True,
    )

    commands.add_parser(
        "status",
        help="Show the active virtual environment and Python identity.",
    )

    init_parser = commands.add_parser(
        "init",
        help="Scan for environments and create the local JSON index.",
    )

    init_parser.add_argument(
        "roots",
        nargs="*",
        help=(
            "Directories to scan recursively. Without roots, use fast manager "
            "hints and a two-level project-neighbourhood scan."
        ),
    )
    find_parser = commands.add_parser(
        "find",
        help="Find an installed package in compatible environments.",
    )

    find_parser.add_argument(
        "package",
        help="Package name, optionally followed by an exact ==version.",
    )
    plan_parser = commands.add_parser(
        "plan",
        help="Create a dry-run package transfer plan.",
    )

    plan_parser.add_argument(
        "package",
        help="Package name with an exact version: package==version.",
    )

    reuse_parser = commands.add_parser(
        "reuse",
        help="Reuse one exact installed package version.",
    )

    reuse_parser.add_argument(
        "package",
        help="Exact package requirement: package==version.",
    )
    deps_parser = commands.add_parser(
        "deps",
        help="Analyze dependencies for an indexed package.",
    )

    deps_parser.add_argument(
        "package",
        help="Exact package requirement: package==version.",
    )

    resolve_parser = commands.add_parser(
        "resolve",
        help="Plan a package and its complete local dependency closure.",
    )

    resolve_parser.add_argument(
        "package",
        help="Exact package requirement: package==version.",
    )

    install_parser = commands.add_parser(
        "install",
        help=("Reuse a package and its locally available dependencies."),
    )

    install_parser.add_argument(
        "package",
        help="Exact package requirement: package==version.",
    )

    pip_parser = commands.add_parser(
        "pip",
        help="Run a pip-style installation through pkgreuse.",
    )

    pip_parser.add_argument(
        "installer_arguments",
        nargs=argparse.REMAINDER,
        help="Arguments that normally follow pip.",
    )

    uv_parser = commands.add_parser(
        "uv",
        help="Run a uv pip installation through pkgreuse.",
    )

    uv_parser.add_argument(
        "installer_arguments",
        nargs=argparse.REMAINDER,
        help="Arguments that normally follow uv.",
    )

    return parser


def main() -> int:
    """Run the pkgreuse command-line interface."""
    parser = build_parser()
    arguments = parser.parse_args()

    if arguments.command == "status":
        return show_status()

    if arguments.command == "init":
        return initialize_index(arguments.roots)

    if arguments.command == "find":
        return find_package(arguments.package)

    if arguments.command == "plan":
        return plan_package_transfer(arguments.package)
    if arguments.command == "reuse":
        return reuse_package(arguments.package)
    if arguments.command == "deps":
        return show_package_dependencies(arguments.package)
    if arguments.command == "resolve":
        return plan_complete_installation(arguments.package)
    if arguments.command == "install":
        return install_complete_local_package(arguments.package)

    if arguments.command == "pip":
        return handle_prefixed_installer(
            backend="pip",
            installer_arguments=arguments.installer_arguments,
        )

    if arguments.command == "uv":
        return handle_prefixed_installer(
            backend="uv",
            installer_arguments=arguments.installer_arguments,
        )

    parser.error(f"Unsupported command: {arguments.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
