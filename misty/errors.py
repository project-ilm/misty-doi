"""Typed errors so automation callers can branch on failure class.

Every exception carries a stable ``code`` attribute that maps 1:1 to a process
exit code (see ``misty.cli.EXIT``). This lets shell/CI wrappers distinguish a
bad metadata file (caller's fault, exit 2) from a Zenodo outage (transient,
exit 4) without parsing log text.
"""


class MistyError(Exception):
    """Base class for all Misty errors."""

    code = 1


class MetadataError(MistyError):
    """Canonical metadata is missing required fields or malformed."""

    code = 2


class ConfigError(MistyError):
    """Environment/credentials/configuration problem (e.g. no token)."""

    code = 3


class ZenodoError(MistyError):
    """Zenodo API returned an error or was unreachable."""

    code = 4


class OTSError(MistyError):
    """OpenTimestamps client missing or stamping/verification failed."""

    code = 5
