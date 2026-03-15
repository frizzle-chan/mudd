"""Unit tests for dialog_loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from mudd.loaders.dialog_loader import (
    DialogNode,
    DialogOption,
    DialogTree,
    _registry,
    get_dialog,
    load_all_dialogs,
    load_dialog,
)

VALID_YAML = """\
id: test-dialog
root: greeting

nodes:
  greeting:
    text: "Hello, traveler."
    options:
      - label: Who are you?
        next: who_are_you
      - label: Goodbye.
        next: goodbye

  who_are_you:
    text: "I'm a test NPC."
    options:
      - label: Nice to meet you.
        next: goodbye

  goodbye:
    text: "Farewell!"
    end: true
"""


class TestLoadDialog:
    def test_loads_valid_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "test-dialog.yaml"
        path.write_text(VALID_YAML)

        tree = load_dialog(path)

        assert tree.id == "test-dialog"
        assert tree.root == "greeting"
        assert len(tree.nodes) == 3
        assert tree.nodes["greeting"].text == "Hello, traveler."
        assert tree.nodes["greeting"].options == (
            DialogOption(label="Who are you?", next="who_are_you"),
            DialogOption(label="Goodbye.", next="goodbye"),
        )
        assert tree.nodes["goodbye"].end is True
        assert tree.nodes["goodbye"].options == ()

    def test_option_with_condition_and_hint(self, tmp_path: Path) -> None:
        yaml_content = """\
id: cond-dialog
root: start

nodes:
  start:
    text: "Welcome."
    options:
      - label: Secret option
        next: secret
        condition: "{{ user.level >= 5 }}"
        hidden: false
        hint: Requires level 5
      - label: Leave
        next: end

  secret:
    text: "You found the secret!"
    options:
      - label: Leave
        next: end

  end:
    text: "Goodbye."
    end: true
"""
        path = tmp_path / "cond-dialog.yaml"
        path.write_text(yaml_content)

        tree = load_dialog(path)

        opt = tree.nodes["start"].options[0]
        assert opt.condition == "{{ user.level >= 5 }}"
        assert opt.hidden is False
        assert opt.hint == "Requires level 5"

    def test_returns_correct_types(self, tmp_path: Path) -> None:
        path = tmp_path / "test-dialog.yaml"
        path.write_text(VALID_YAML)

        tree = load_dialog(path)

        assert isinstance(tree, DialogTree)
        assert isinstance(tree.nodes["greeting"], DialogNode)
        assert isinstance(tree.nodes["greeting"].options, tuple)
        assert isinstance(tree.nodes["greeting"].options[0], DialogOption)


class TestValidation:
    def test_bad_root_reference(self, tmp_path: Path) -> None:
        yaml_content = """\
id: bad-root
root: nonexistent

nodes:
  greeting:
    text: "Hello."
    end: true
"""
        path = tmp_path / "bad-root.yaml"
        path.write_text(yaml_content)

        with pytest.raises(ValueError, match="root 'nonexistent' does not reference"):
            load_dialog(path)

    def test_bad_option_next_reference(self, tmp_path: Path) -> None:
        yaml_content = """\
id: bad-ref
root: greeting

nodes:
  greeting:
    text: "Hello."
    options:
      - label: Go nowhere
        next: does_not_exist
"""
        path = tmp_path / "bad-ref.yaml"
        path.write_text(yaml_content)

        with pytest.raises(
            ValueError, match="references unknown node 'does_not_exist'"
        ):
            load_dialog(path)

    def test_unreachable_node_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        yaml_content = """\
id: unreachable
root: greeting

nodes:
  greeting:
    text: "Hello."
    end: true

  orphan:
    text: "Nobody links here."
    end: true
"""
        path = tmp_path / "unreachable.yaml"
        path.write_text(yaml_content)

        with caplog.at_level("WARNING"):
            load_dialog(path)

        assert "node 'orphan' is unreachable" in caplog.text

    def test_end_node_with_options_warns(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        yaml_content = """\
id: end-opts
root: greeting

nodes:
  greeting:
    text: "Hello."
    options:
      - label: Leave
        next: goodbye

  goodbye:
    text: "Bye!"
    end: true
    options:
      - label: Wait
        next: greeting
"""
        path = tmp_path / "end-opts.yaml"
        path.write_text(yaml_content)

        with caplog.at_level("WARNING"):
            load_dialog(path)

        assert "node 'goodbye' is marked as end but also has options" in caplog.text


class TestGetDialog:
    def test_returns_none_for_unknown_id(self) -> None:
        assert get_dialog("nonexistent-dialog-id") is None


class TestLoadAllDialogs:
    def test_populates_registry(self, tmp_path: Path) -> None:
        (tmp_path / "test-dialog.yaml").write_text(VALID_YAML)

        second_yaml = """\
id: another-dialog
root: start

nodes:
  start:
    text: "Hi."
    end: true
"""
        (tmp_path / "another-dialog.yaml").write_text(second_yaml)

        result = load_all_dialogs(tmp_path)

        assert len(result) == 2
        assert "test-dialog" in result
        assert "another-dialog" in result

        # Registry is populated
        assert get_dialog("test-dialog") is not None
        assert get_dialog("another-dialog") is not None

    def test_clears_previous_registry(self, tmp_path: Path) -> None:
        _registry["stale-entry"] = DialogTree(id="stale-entry", root="x", nodes={})

        (tmp_path / "test-dialog.yaml").write_text(VALID_YAML)

        load_all_dialogs(tmp_path)

        assert get_dialog("stale-entry") is None
        assert get_dialog("test-dialog") is not None

    def test_missing_directory_returns_empty(self, tmp_path: Path) -> None:
        result = load_all_dialogs(tmp_path / "does-not-exist")

        assert result == {}

    def test_empty_directory_returns_empty(self, tmp_path: Path) -> None:
        result = load_all_dialogs(tmp_path)

        assert result == {}

    def test_bad_file_skipped_others_loaded(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        (tmp_path / "good.yaml").write_text(VALID_YAML)
        bad_yaml = "id: bad\nroot: missing\nnodes:\n  x:\n    text: hi\n    end: true\n"
        (tmp_path / "bad.yaml").write_text(bad_yaml)

        with caplog.at_level("WARNING"):
            result = load_all_dialogs(tmp_path)

        assert "test-dialog" in result
        assert "bad" not in result
        assert "Failed to load dialog from bad.yaml" in caplog.text
