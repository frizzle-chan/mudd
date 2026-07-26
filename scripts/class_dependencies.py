#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Generate Mermaid diagram of dependency injection relationships in mudd/.

Discovers first-party classes and their constructor dependencies to visualize
the DI graph. Only shows relationships where one mudd class depends on another
mudd class via __init__ parameter type annotations.

Usage:
    uv run scripts/class_dependencies.py
    uv run scripts/class_dependencies.py > di_diagram.mmd
"""

import ast
import sys
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ClassInfo:
    """Information about a discovered class."""

    name: str
    module: str  # e.g., "mudd.services.entity"
    dependencies: list[str] = field(default_factory=list)  # Type names from __init__


@dataclass
class FileInfo:
    """Parsed information from a Python file."""

    classes: list[ClassInfo] = field(default_factory=list)
    imports: dict[str, str] = field(default_factory=dict)  # local_name -> full_module


def find_python_files(root: Path) -> list[Path]:
    """Find all Python files in the given directory."""
    return sorted(root.rglob("*.py"))


def module_from_path(path: Path, root: Path) -> str:
    """Convert file path to module name relative to project root."""
    rel = path.relative_to(root.parent)
    parts = rel.with_suffix("").parts
    return ".".join(parts)


def extract_type_name(annotation: ast.expr) -> str | None:
    """Extract the base type name from a type annotation AST node.

    Handles:
    - Simple names: EntityService -> "EntityService"
    - String annotations: "EntityService" -> "EntityService"
    - Subscripts: list[EntityService] -> None (not a DI dependency)
    - Union/Optional: EntityService | None -> "EntityService"
    - Attributes: module.Class -> "Class"
    """
    if isinstance(annotation, ast.Name):
        return annotation.id
    elif isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        # String annotation like "EntityService"
        return annotation.value
    elif isinstance(annotation, ast.Attribute):
        # module.Class -> just get the final attribute
        return annotation.attr
    elif isinstance(annotation, ast.BinOp) and isinstance(annotation.op, ast.BitOr):
        # Union type like EntityService | None
        # Try left side first, then right
        left = extract_type_name(annotation.left)
        if left and left != "None":
            return left
        return extract_type_name(annotation.right)
    elif (
        isinstance(annotation, ast.Subscript)
        and isinstance(annotation.value, ast.Name)
        and annotation.value.id == "Optional"
    ):
        # Handle Optional[EntityService]
        return extract_type_name(annotation.slice)
    return None


def parse_init_dependencies(func_def: ast.FunctionDef) -> list[str]:
    """Extract type annotation names from __init__ parameters."""
    dependencies: list[str] = []

    for arg in func_def.args.args:
        if arg.arg == "self":
            continue
        if arg.annotation:
            type_name = extract_type_name(arg.annotation)
            if type_name:
                dependencies.append(type_name)

    return dependencies


def parse_file(path: Path, root: Path) -> FileInfo:
    """Parse a Python file and extract class/import information."""
    info = FileInfo()
    module = module_from_path(path, root)

    try:
        source = path.read_text()
        tree = ast.parse(source)
    except (SyntaxError, UnicodeDecodeError):
        return info

    # Collect imports for name resolution
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".")[-1]
                info.imports[local_name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module:
            for alias in node.names:
                local_name = alias.asname or alias.name
                info.imports[local_name] = f"{node.module}.{alias.name}"

    # Find class definitions at module level
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            class_info = ClassInfo(name=node.name, module=module)

            # Find __init__ method
            for item in node.body:
                if isinstance(item, ast.FunctionDef) and item.name == "__init__":
                    class_info.dependencies = parse_init_dependencies(item)
                    break

            info.classes.append(class_info)

    return info


def build_class_registry(
    files: list[tuple[Path, FileInfo]],
) -> dict[str, ClassInfo]:
    """Build registry mapping class names to ClassInfo."""
    registry: dict[str, ClassInfo] = {}

    for _, file_info in files:
        for cls in file_info.classes:
            # Use simple name as key (handle duplicates by overwriting)
            registry[cls.name] = cls

    return registry


def resolve_di_dependencies(
    files: list[tuple[Path, FileInfo]],
    registry: dict[str, ClassInfo],
) -> list[tuple[str, str]]:
    """Resolve dependency names to first-party classes.

    Returns list of (from_class, to_class) edges.
    """
    edges: list[tuple[str, str]] = []
    first_party_names = set(registry.keys())

    for _, file_info in files:
        for cls in file_info.classes:
            for dep_name in cls.dependencies:
                # Check if dependency is a first-party class
                # Handle both direct names and Protocol suffixes
                if dep_name in first_party_names:
                    edges.append((cls.name, dep_name))
                elif dep_name.endswith("Protocol"):
                    # Try without Protocol suffix
                    base_name = dep_name[:-8]  # Remove "Protocol"
                    if base_name in first_party_names:
                        edges.append((cls.name, base_name))
                elif dep_name.endswith("Service"):
                    # Already in registry, was added above
                    pass
                else:
                    # Try to resolve via imports
                    if dep_name in file_info.imports:
                        full_path = file_info.imports[dep_name]
                        # Extract class name from full path
                        parts = full_path.split(".")
                        resolved_name = parts[-1]
                        if resolved_name in first_party_names:
                            edges.append((cls.name, resolved_name))

    return edges


def get_namespace(module: str) -> str:
    """Extract namespace from module path for grouping.

    mudd.services.entity -> services
    mudd.cogs.look -> cogs
    mudd.matching.entity_matcher -> matching
    """
    parts = module.split(".")
    if len(parts) >= 2:
        return parts[1]  # mudd.X.* -> X
    return "mudd"


def generate_mermaid(
    registry: dict[str, ClassInfo],
    edges: list[tuple[str, str]],
) -> str:
    """Generate Mermaid classDiagram from classes and edges."""
    lines = ["classDiagram"]

    # Group classes by namespace
    namespaces: dict[str, list[str]] = {}
    for name, info in registry.items():
        ns = get_namespace(info.module)
        if ns not in namespaces:
            namespaces[ns] = []
        namespaces[ns].append(name)

    # Filter to only classes that appear in edges
    classes_in_edges = set()
    for from_cls, to_cls in edges:
        classes_in_edges.add(from_cls)
        classes_in_edges.add(to_cls)

    # Output namespaces with their classes
    for ns in sorted(namespaces.keys()):
        classes = sorted(c for c in namespaces[ns] if c in classes_in_edges)
        if classes:
            lines.append(f"    namespace {ns} {{")
            for cls in classes:
                lines.append(f"        class {cls}")
            lines.append("    }")

    # Output edges (deduplicated)
    seen_edges: set[tuple[str, str]] = set()
    for from_cls, to_cls in sorted(edges):
        if (from_cls, to_cls) not in seen_edges:
            lines.append(f"    {from_cls} --> {to_cls} : injects")
            seen_edges.add((from_cls, to_cls))

    return "\n".join(lines)


def main() -> int:
    """Generate DI diagram for mudd/ package."""
    project_root = Path(__file__).parent.parent
    mudd_path = project_root / "mudd"

    if not mudd_path.exists():
        print(f"Error: {mudd_path} not found", file=sys.stderr)
        return 1

    # Find and parse all Python files
    python_files = find_python_files(mudd_path)
    parsed_files: list[tuple[Path, FileInfo]] = []

    for path in python_files:
        file_info = parse_file(path, mudd_path)
        parsed_files.append((path, file_info))

    # Build class registry
    registry = build_class_registry(parsed_files)

    # Resolve dependencies
    edges = resolve_di_dependencies(parsed_files, registry)

    # Generate and output Mermaid diagram
    diagram = generate_mermaid(registry, edges)
    print(diagram)

    return 0


if __name__ == "__main__":
    sys.exit(main())
