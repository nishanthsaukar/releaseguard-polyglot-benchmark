"""Static source inspection for ReleaseGuard."""

from .inspector import (
    ClassFieldInspectionResult,
    SourceInspectionResult,
    inspect_class_field,
    inspect_source,
)

__all__ = [
    "ClassFieldInspectionResult",
    "inspect_class_field",
    "inspect_source",
    "SourceInspectionResult",
]
