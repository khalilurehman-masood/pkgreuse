"""Typed PKGReuse exception hierarchy."""


class PKGReuseError(Exception):
    """Base class for controlled PKGReuse failures."""


class ConfigurationError(PKGReuseError):
    """Configuration is invalid."""


class EnvironmentError(PKGReuseError):
    """An environment is invalid or incompatible."""


class NotInVirtualEnvironmentError(EnvironmentError):
    """PKGReuse was invoked outside a virtual environment."""


class InvalidEnvironmentError(EnvironmentError):
    """A virtual environment has an invalid layout."""


class PythonIdentityMismatchError(EnvironmentError):
    """A donor interpreter does not match the target."""


class IndexError(PKGReuseError):
    """The local index could not be used."""


class IndexNotFoundError(IndexError):
    """The local index does not exist."""


class IndexCorruptError(IndexError):
    """The local index contains invalid data."""


class UnsupportedIndexVersionError(IndexError):
    """The local index schema is unsupported."""


class IndexLockTimeoutError(IndexError):
    """The local index lock could not be acquired."""


class MetadataError(PKGReuseError):
    """Installed distribution metadata is invalid."""


class ResolutionError(PKGReuseError):
    """Local dependency resolution failed."""


class DistributionNotFoundError(ResolutionError):
    """A requested distribution was not found."""


class MissingDependencyError(ResolutionError):
    """A dependency is unavailable locally."""


class DependencyConflictError(ResolutionError):
    """Selected dependency versions conflict."""


class PlanningError(PKGReuseError):
    """A transfer plan is unsafe."""


class UnsafeRecordPathError(PlanningError):
    """A RECORD path escapes an allowed root."""


class MissingSourceFileError(PlanningError):
    """A RECORD-owned donor file is missing."""


class DestinationConflictError(PlanningError):
    """A target path already exists."""


class UnsupportedInstalledFileError(PlanningError):
    """A distribution owns an unsupported installed file."""


class TransferError(PKGReuseError):
    """File transfer failed."""


class ValidationError(PKGReuseError):
    """Post-transfer validation failed."""


class BackendError(PKGReuseError):
    """An installer backend could not be executed."""
