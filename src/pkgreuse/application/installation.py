"""Local installation planning and execution application service."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

from packaging.requirements import Requirement
from packaging.version import InvalidVersion, Version

from pkgreuse.application.indexing import IndexInitializationService
from pkgreuse.domain.names import normalize_package_name
from pkgreuse.domain.requirements import parse_requirement
from pkgreuse.ports import IndexData

Candidate = dict[str, Any]
InstallationPlanData = dict[str, Any]


class InstallPreparationStatus(str, Enum):
    """Possible outcomes before target mutation."""

    ALREADY_SATISFIED = "already-satisfied"
    PLAN_READY = "plan-ready"
    FALLBACK_REQUIRED = "fallback-required"


@dataclass(frozen=True, slots=True)
class InstallPreparation:
    """Validated result of local installation preparation."""

    status: InstallPreparationStatus
    package_name: str
    requested_version: str
    installed_version: str | None = None
    plan: InstallationPlanData | None = None
    reason: str | None = None
    auto_initialized: bool = False


class LocalInstallationService:
    """Prepare and execute one locally maximized package installation."""

    def __init__(
        self,
        initialization: IndexInitializationService,
        installed_version: Callable[[str], str | None],
        version_satisfies: Callable[[str, Requirement], bool],
        candidate_selector: Callable[
            [IndexData, Requirement, str | None],
            Candidate | None,
        ],
        plan_builder: Callable[
            [str, str, Candidate, IndexData],
            InstallationPlanData,
        ],
        plan_executor: Callable[..., dict[str, Any]],
    ) -> None:
        self.initialization = initialization
        self.installed_version = installed_version
        self.version_satisfies = version_satisfies
        self.candidate_selector = candidate_selector
        self.plan_builder = plan_builder
        self.plan_executor = plan_executor

    def prepare(
        self,
        package_query: str,
        on_index_missing: Callable[[], None] | None = None,
    ) -> InstallPreparation:
        """Build and fully inspect a local plan without target mutation."""
        requirement = parse_requirement(package_query)
        package_name = normalize_package_name(requirement.name)
        index_result = self.initialization.ensure(on_missing=on_index_missing)
        installed_version = self.installed_version(package_name)
        local_candidate = self.candidate_selector(
            index_result.data,
            requirement,
            None,
        )
        if (
            installed_version is not None
            and self.version_satisfies(installed_version, requirement)
            and (
                local_candidate is None
                or _version_at_least(installed_version, local_candidate["version"])
            )
        ):
            return InstallPreparation(
                status=InstallPreparationStatus.ALREADY_SATISFIED,
                package_name=package_name,
                requested_version=installed_version,
                installed_version=installed_version,
                auto_initialized=index_result.initialized,
            )
        if installed_version is not None:
            return InstallPreparation(
                status=InstallPreparationStatus.FALLBACK_REQUIRED,
                package_name=package_name,
                requested_version=(
                    local_candidate["version"]
                    if local_candidate is not None
                    else str(requirement.specifier) or "latest"
                ),
                installed_version=installed_version,
                reason=(
                    f"{package_name}=={installed_version} is installed and "
                    "PKGReuse does not overwrite target files."
                ),
                auto_initialized=index_result.initialized,
            )

        if local_candidate is None:
            return InstallPreparation(
                status=InstallPreparationStatus.FALLBACK_REQUIRED,
                package_name=package_name,
                requested_version=str(requirement.specifier) or "latest",
                reason=(f"no reusable local version satisfies {package_query}."),
                auto_initialized=index_result.initialized,
            )
        selected_version = local_candidate["version"]
        plan = self.plan_builder(
            package_name,
            selected_version,
            local_candidate,
            index_result.data,
        )
        blockers = installation_plan_blockers(plan)
        if blockers:
            return InstallPreparation(
                status=InstallPreparationStatus.FALLBACK_REQUIRED,
                package_name=package_name,
                requested_version=selected_version,
                plan=plan,
                reason=(
                    "the complete package dependency closure could not be "
                    "safely reused: " + "; ".join(blockers)
                ),
                auto_initialized=index_result.initialized,
            )
        return InstallPreparation(
            status=InstallPreparationStatus.PLAN_READY,
            package_name=package_name,
            requested_version=selected_version,
            plan=plan,
            auto_initialized=index_result.initialized,
        )

    def execute(
        self,
        preparation: InstallPreparation,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> dict[str, Any]:
        """Execute only a preparation containing a safe plan."""
        if (
            preparation.status is not InstallPreparationStatus.PLAN_READY
            or preparation.plan is None
        ):
            raise ValueError("A ready installation plan is required.")
        return self.plan_executor(
            installation_plan=preparation.plan,
            progress_callback=progress_callback,
        )


def _version_at_least(installed: str, candidate: str) -> bool:
    """Return whether the target version is at least the local maximum."""
    try:
        return Version(installed) >= Version(candidate)
    except InvalidVersion:
        return False


def installation_plan_blockers(plan: InstallationPlanData) -> tuple[str, ...]:
    """Return user-facing reasons an installation plan is unsafe."""
    blockers: list[str] = []
    if plan["missing"]:
        blockers.append(f"{len(plan['missing'])} missing dependencies")
    if plan["conflicts"]:
        blockers.append(f"{len(plan['conflicts'])} dependency conflicts")
    if plan["overlapping_files"]:
        blockers.append(f"{len(plan['overlapping_files'])} overlapping files")
    for package in plan["packages"]:
        transfer = package["transfer"]
        package_blockers: list[str] = []
        if transfer["conflicts"]:
            package_blockers.append(f"{len(transfer['conflicts'])} target conflicts")
        if transfer["missing_files"]:
            package_blockers.append(
                f"{len(transfer['missing_files'])} missing source files"
            )
        if transfer["unsafe_files"]:
            package_blockers.append(f"{len(transfer['unsafe_files'])} unsafe paths")
        if transfer["environment_files"]:
            package_blockers.append(
                f"{transfer['environment_files']} environment-level files"
            )
        if transfer.get("invalid_pth_files"):
            package_blockers.append(
                f"{len(transfer['invalid_pth_files'])} unsafe .pth files"
            )
        if package_blockers:
            blockers.append(
                f"{package['name']}=={package['version']}: "
                + ", ".join(package_blockers)
            )
    return tuple(blockers)
