from __future__ import annotations


class OpenKNetError(Exception):
    """Base for all OpenKNet errors."""


class ProjectNotFoundError(OpenKNetError):
    """Raised when a project does not exist in the store."""


class ProjectNotInitializedError(OpenKNetError):
    """Raised when a method requires initialization but the client is not yet initialized."""


class IngestError(OpenKNetError):
    """Raised when ingestion fails for one or more documents."""


class BuildError(OpenKNetError):
    """Raised when the build step fails."""


class SchemaError(OpenKNetError):
    """Raised when the schema YAML is invalid or incompatible."""
