"""YAML dialog tree loader with validation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DialogOption:
    """A player choice within a dialog node."""

    label: str
    next: str
    condition: str | None = None
    hidden: bool = True
    hint: str | None = None


@dataclass(frozen=True, slots=True)
class DialogNode:
    """A single node in a dialog tree (one NPC message + player choices)."""

    text: str
    options: tuple[DialogOption, ...] = ()
    end: bool = False


@dataclass(frozen=True, slots=True)
class DialogTree:
    """A complete dialog tree loaded from YAML."""

    id: str
    root: str
    nodes: dict[str, DialogNode]


_registry: dict[str, DialogTree] = {}


def load_dialog(path: Path) -> DialogTree:
    """Parse and validate a single YAML dialog file.

    Args:
        path: Path to the YAML file.

    Returns:
        Validated DialogTree instance.

    Raises:
        ValueError: If the dialog fails validation.
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    dialog_id = data["id"]
    root = data["root"]
    raw_nodes: dict[str, dict] = data["nodes"]

    # Build nodes
    nodes: dict[str, DialogNode] = {}
    for node_id, node_data in raw_nodes.items():
        options: list[DialogOption] = []
        for opt_data in node_data.get("options") or []:
            options.append(
                DialogOption(
                    label=opt_data["label"],
                    next=opt_data["next"],
                    condition=opt_data.get("condition"),
                    hidden=opt_data.get("hidden", True),
                    hint=opt_data.get("hint"),
                )
            )
        nodes[node_id] = DialogNode(
            text=node_data["text"],
            options=tuple(options),
            end=node_data.get("end", False),
        )

    node_keys = set(nodes.keys())

    # Validate: root must reference a valid node
    if root not in node_keys:
        msg = f"{path.name}: root '{root}' does not reference a valid node"
        raise ValueError(msg)

    # Validate: every option.next must reference a valid node
    for node_id, node in nodes.items():
        for option in node.options:
            if option.next not in node_keys:
                msg = (
                    f"{path.name}: node '{node_id}' option '{option.label}' "
                    f"references unknown node '{option.next}'"
                )
                raise ValueError(msg)

    # Warn about end nodes that also have options
    for node_id, node in nodes.items():
        if node.end and node.options:
            logger.warning(
                "%s: node '%s' is marked as end but also has options",
                path.name,
                node_id,
            )

    # Warn about unreachable nodes
    referenced: set[str] = {root}
    for node in nodes.values():
        for option in node.options:
            referenced.add(option.next)
    unreachable = node_keys - referenced
    for node_id in sorted(unreachable):
        logger.warning("%s: node '%s' is unreachable", path.name, node_id)

    return DialogTree(id=dialog_id, root=root, nodes=nodes)


def load_all_dialogs(directory: Path) -> dict[str, DialogTree]:
    """Load all YAML dialog files from a directory into the registry.

    Args:
        directory: Path to the directory containing YAML files.

    Returns:
        Dict mapping dialog IDs to DialogTree instances.
    """
    _registry.clear()
    if not directory.is_dir():
        logger.warning("Dialogs directory not found: %s", directory)
        return _registry

    for path in sorted(directory.glob("*.yaml")):
        try:
            tree = load_dialog(path)
        except Exception:
            logger.exception("Failed to load dialog from %s", path.name)
            continue
        _registry[tree.id] = tree

    logger.info("Loaded %d dialog(s) from %s", len(_registry), directory)
    return _registry


def get_dialog(dialog_id: str) -> DialogTree | None:
    """Look up a dialog tree by ID from the module-level registry.

    Args:
        dialog_id: The dialog tree identifier.

    Returns:
        The DialogTree if found, otherwise None.
    """
    return _registry.get(dialog_id)
