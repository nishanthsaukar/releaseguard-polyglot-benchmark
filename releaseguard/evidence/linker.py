"""Evidence linker — connects test failures to source-code locations."""

from .linker_impl import link_failures_to_source, LinkedFailure

__all__ = ["link_failures_to_source", "LinkedFailure"]
