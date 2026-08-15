"""AST-based static source inspection.

Inspects Python source files to locate functions, extract their
source bodies, and identify structural characteristics relevant
to security and correctness analysis.

Safety contract:
  - Does NOT execute any source code.
  - Only reads files and parses their AST.
  - Returns None/empty safely when inspection fails.
"""

from __future__ import annotations

import ast
import textwrap
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class SourceInspectionResult:
    """Result of inspecting a single function or code location."""

    available: bool = False

    source_file: str = ""          # relative path as provided to inspect_source
    function_name: Optional[str] = None
    class_name: Optional[str] = None

    start_line: Optional[int] = None   # 1-based
    end_line: Optional[int] = None     # 1-based, inclusive
    source_excerpt: Optional[str] = None

    # Structural findings from AST walk
    has_ownership_check: bool = False     # any comparison of user_id against stored value
    has_conditional_raise: bool = False   # any raise inside an if/conditional block
    assigned_fields: list[str] = field(default_factory=list)   # names assigned in func
    called_functions: list[str] = field(default_factory=list)  # names called in func

    # How the location was found: "line_number", "function_name", "none"
    location_method: str = "none"

    parse_error: Optional[str] = None


@dataclass
class ClassFieldInspectionResult:
    """Result of inspecting a single class attribute / Pydantic field."""

    available: bool = False

    source_file: str = ""
    class_name: Optional[str] = None     # e.g. "TaskCreate"
    field_name: Optional[str] = None     # e.g. "title"

    source_line: Optional[int] = None    # 1-based line of the annotation
    source_excerpt: Optional[str] = None  # the raw source line(s) for that field

    # Parsed Field() keyword constraints, e.g. {"max_length": 256, "min_length": 1}
    field_constraints: dict[str, object] = field(default_factory=dict)

    parse_error: Optional[str] = None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def inspect_source(
    repo_path: Path,
    source_file: str,
    line_number: Optional[int] = None,
    function_name: Optional[str] = None,
) -> SourceInspectionResult:
    """Inspect a source file and return structural evidence.

    Provide either ``line_number`` (to find which function contains that line)
    or ``function_name`` (to find a function by name).  Both may be provided;
    ``line_number`` takes priority for location, ``function_name`` as fallback.

    The ``source_file`` path is resolved relative to ``repo_path``.
    """
    result = SourceInspectionResult(source_file=source_file)

    # Resolve file path
    abs_path = _resolve_path(repo_path, source_file)
    if abs_path is None or not abs_path.is_file():
        result.parse_error = f"File not found: {source_file}"
        return result

    # Read source
    try:
        source_text = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        result.parse_error = f"Could not read file: {exc}"
        return result

    # Parse AST
    try:
        tree = ast.parse(source_text, filename=str(abs_path))
    except SyntaxError as exc:
        result.parse_error = f"Syntax error: {exc}"
        return result

    source_lines = source_text.splitlines()

    # Find the target function
    func_node = _find_function(tree, line_number=line_number, function_name=function_name)
    if func_node is None:
        result.parse_error = "Function not found in source"
        return result

    # Populate result
    result.available = True
    result.function_name = func_node.name
    result.start_line = func_node.lineno
    result.end_line = func_node.end_lineno
    result.location_method = "line_number" if line_number is not None else "function_name"

    # Find enclosing class name if any
    result.class_name = _find_enclosing_class(tree, func_node)

    # Extract source excerpt (at most 30 lines)
    result.source_excerpt = _extract_lines(
        source_lines, func_node.lineno, func_node.end_lineno, max_lines=30
    )

    # Walk AST for structural characteristics
    _analyze_function_ast(func_node, result)

    return result


def inspect_function_by_name(
    repo_path: Path,
    source_file: str,
    function_name: str,
) -> SourceInspectionResult:
    """Convenience wrapper: inspect by function name only."""
    return inspect_source(repo_path, source_file, function_name=function_name)


def inspect_line(
    repo_path: Path,
    source_file: str,
    line_number: int,
) -> SourceInspectionResult:
    """Convenience wrapper: find the function containing the given line."""
    return inspect_source(repo_path, source_file, line_number=line_number)


def inspect_class_field(
    repo_path: Path,
    source_file: str,
    class_name: str,
    field_name: str,
) -> "ClassFieldInspectionResult":
    """Inspect a class attribute (e.g. a Pydantic field) and return its constraints.

    Locates ``class_name.field_name`` in ``source_file``, extracts the source
    line, and parses any keyword arguments passed to ``Field(...)`` so callers
    can read constraints such as ``max_length`` directly.

    The ``source_file`` path is resolved relative to ``repo_path``.
    """
    result = ClassFieldInspectionResult(
        source_file=source_file,
        class_name=class_name,
        field_name=field_name,
    )

    abs_path = _resolve_path(repo_path, source_file)
    if abs_path is None or not abs_path.is_file():
        result.parse_error = f"File not found: {source_file}"
        return result

    try:
        source_text = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        result.parse_error = f"Could not read file: {exc}"
        return result

    try:
        tree = ast.parse(source_text, filename=str(abs_path))
    except SyntaxError as exc:
        result.parse_error = f"Syntax error: {exc}"
        return result

    source_lines = source_text.splitlines()

    node = _find_class_field(tree, class_name, field_name)
    if node is None:
        result.parse_error = f"Field '{class_name}.{field_name}' not found"
        return result

    result.available = True
    result.source_line = node.lineno

    # Extract the raw source line(s) for this annotation
    result.source_excerpt = _extract_lines(source_lines, node.lineno, node.end_lineno, max_lines=5)

    # Parse Field() keyword arguments if the default value is a Call
    result.field_constraints = _parse_field_call(node)

    return result


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _find_function(
    tree: ast.AST,
    line_number: Optional[int] = None,
    function_name: Optional[str] = None,
) -> Optional[ast.FunctionDef]:
    """Return the best-matching FunctionDef node."""
    all_funcs: list[ast.FunctionDef] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            all_funcs.append(node)  # type: ignore[arg-type]

    if not all_funcs:
        return None

    # Priority 1: find by line number — smallest function that contains the line
    if line_number is not None:
        containing = [
            f for f in all_funcs
            if f.lineno <= line_number <= (f.end_lineno or f.lineno)
        ]
        if containing:
            # Prefer the innermost (smallest range)
            return min(containing, key=lambda f: (f.end_lineno or f.lineno) - f.lineno)

    # Priority 2: find by function name
    if function_name is not None:
        named = [f for f in all_funcs if f.name == function_name]
        if named:
            return named[0]

    return None


def _find_enclosing_class(tree: ast.AST, func_node: ast.FunctionDef) -> Optional[str]:
    """Return the name of the class that directly contains func_node, or None."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for child in ast.walk(node):
                if child is func_node:
                    return node.name
    return None


def _extract_lines(
    lines: list[str],
    start: int,
    end: Optional[int],
    max_lines: int = 30,
) -> str:
    """Return source lines start..end (1-based, inclusive), capped at max_lines."""
    end = end or start
    # Cap the range
    actual_end = min(end, start + max_lines - 1)
    # Python list is 0-based
    excerpt = lines[start - 1 : actual_end]
    # Dedent to remove common leading whitespace
    return textwrap.dedent("\n".join(excerpt))


def _analyze_function_ast(
    func_node: ast.FunctionDef,
    result: SourceInspectionResult,
) -> None:
    """Walk the function AST and populate structural findings on result."""

    for node in ast.walk(func_node):
        # Track all names assigned within the function
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            if node.id not in result.assigned_fields:
                result.assigned_fields.append(node.id)

        # Track all function/method calls
        if isinstance(node, ast.Call):
            call_name = _get_call_name(node)
            if call_name and call_name not in result.called_functions:
                result.called_functions.append(call_name)

        # Detect conditional raises (guard patterns)
        if isinstance(node, ast.If):
            for child in ast.walk(node):
                if isinstance(child, ast.Raise):
                    result.has_conditional_raise = True
                    break

        # Detect ownership / identity comparisons
        # Look for comparisons involving names that suggest user/owner matching
        if isinstance(node, ast.Compare):
            if _looks_like_ownership_check(node):
                result.has_ownership_check = True


def _get_call_name(node: ast.Call) -> Optional[str]:
    """Extract a simple name from a Call node."""
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _looks_like_ownership_check(node: ast.Compare) -> bool:
    """Return True if a comparison looks like an ownership/identity check.

    Heuristic: any comparison whose operands reference names containing
    'user', 'owner', 'id', or 'auth' on both sides.
    """
    ownership_terms = ("user", "owner", "uid", "auth", "identity")

    def _names_in(expr: ast.expr) -> list[str]:
        names = []
        for n in ast.walk(expr):
            if isinstance(n, ast.Name):
                names.append(n.id.lower())
            elif isinstance(n, ast.Attribute):
                names.append(n.attr.lower())
        return names

    lhs_names = _names_in(node.left)
    rhs_names = []
    for comp in node.comparators:
        rhs_names.extend(_names_in(comp))

    all_names = lhs_names + rhs_names
    return any(term in name for term in ownership_terms for name in all_names)


def _find_class_field(
    tree: ast.AST,
    class_name: str,
    field_name: str,
) -> Optional[ast.AnnAssign]:
    """Return the AnnAssign node for ``class_name.field_name``, or None."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.AnnAssign)
                    and isinstance(stmt.target, ast.Name)
                    and stmt.target.id == field_name
                ):
                    return stmt
    return None


def _parse_field_call(node: ast.AnnAssign) -> dict[str, object]:
    """Extract keyword arguments from a ``Field(...)`` call in an AnnAssign default.

    Returns a dict mapping keyword names to their literal values (int, str, bool).
    Non-literal values are omitted.  Returns an empty dict when no Field call is found.
    """
    if node.value is None or not isinstance(node.value, ast.Call):
        return {}

    # Accept Field(...) or pydantic.Field(...)
    call = node.value
    func = call.func
    is_field_call = (
        (isinstance(func, ast.Name) and func.id == "Field")
        or (isinstance(func, ast.Attribute) and func.attr == "Field")
    )
    if not is_field_call:
        return {}

    constraints: dict[str, object] = {}
    for kw in call.keywords:
        if kw.arg is None:
            continue  # **kwargs spread — skip
        val = _eval_literal(kw.value)
        if val is not None:
            constraints[kw.arg] = val

    return constraints


def _eval_literal(node: ast.expr) -> Optional[object]:
    """Return the Python literal value of a simple AST node, or None."""
    if isinstance(node, ast.Constant):
        return node.value
    # Negative numbers: UnaryOp(USub, Constant(...))
    if (
        isinstance(node, ast.UnaryOp)
        and isinstance(node.op, ast.USub)
        and isinstance(node.operand, ast.Constant)
    ):
        return -node.operand.value
    return None


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _resolve_path(repo_path: Path, source_file: str) -> Optional[Path]:
    """Resolve a potentially relative source_file path against repo_path.

    Handles both forward-slash and backslash separators, absolute paths,
    and paths that may include a repo-root prefix.
    """
    normalized = source_file.replace("\\", "/")
    candidate = Path(normalized)

    # If it's already absolute and exists, use it
    if candidate.is_absolute() and candidate.is_file():
        return candidate

    # Try as relative to repo_path
    relative_try = repo_path / normalized
    if relative_try.is_file():
        return relative_try

    # The path might include the repo_path itself as a prefix; try stripping it
    try:
        rel = candidate.relative_to(repo_path)
        full = repo_path / rel
        if full.is_file():
            return full
    except ValueError:
        pass

    # Search under repo_path for a matching suffix
    # e.g. "app/main.py" matches "python-app/app/main.py"
    for depth in range(1, 5):
        parts = Path(normalized).parts
        if len(parts) >= depth:
            suffix = Path(*parts[-depth:])
            found = list(repo_path.rglob(str(suffix)))
            if found:
                return found[0]

    return None
