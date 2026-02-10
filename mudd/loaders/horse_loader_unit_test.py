"""Unit tests for horse_loader parsing."""

from __future__ import annotations

from mudd.loaders.horse_loader import HorseData, _parse_horse_row


class TestParseHorseRow:
    def test_basic_parsing(self) -> None:
        row = {
            "Id": "flash",
            "Name": "Flash",
            "Speed": "90",
            "Stamina": "70",
            "Consistency": "75",
            "Luck": "55",
        }
        result = _parse_horse_row(row)
        assert result == HorseData(
            id="flash",
            name="Flash",
            speed=90,
            stamina=70,
            consistency=75,
            luck=55,
            active=True,
            description=None,
            lore=None,
            profile_image=None,
            race_image=None,
            victory_image=None,
        )

    def test_active_false(self) -> None:
        row = {
            "Id": "retired",
            "Name": "Old Timer",
            "Speed": "30",
            "Stamina": "40",
            "Consistency": "80",
            "Luck": "20",
            "Active": "false",
        }
        result = _parse_horse_row(row)
        assert result.active is False

    def test_active_absent_defaults_to_true(self) -> None:
        row = {
            "Id": "newbie",
            "Name": "Newbie",
            "Speed": "50",
            "Stamina": "50",
            "Consistency": "50",
            "Luck": "50",
        }
        result = _parse_horse_row(row)
        assert result.active is True

    def test_active_empty_string_defaults_to_true(self) -> None:
        row = {
            "Id": "blank",
            "Name": "Blank",
            "Speed": "60",
            "Stamina": "60",
            "Consistency": "60",
            "Luck": "60",
            "Active": "",
        }
        result = _parse_horse_row(row)
        assert result.active is True

    def test_images_are_none(self) -> None:
        """_parse_horse_row doesn't load images; they're attached later."""
        row = {
            "Id": "test",
            "Name": "Test Horse",
            "Speed": "50",
            "Stamina": "50",
            "Consistency": "50",
            "Luck": "50",
        }
        result = _parse_horse_row(row)
        assert result.profile_image is None
        assert result.race_image is None
        assert result.victory_image is None

    def test_description_and_lore_parsing(self) -> None:
        """Test that description and lore fields are parsed correctly."""
        row = {
            "Id": "story",
            "Name": "Story Horse",
            "Speed": "60",
            "Stamina": "65",
            "Consistency": "70",
            "Luck": "55",
            "Description": "A beautiful horse with a white mane.",
            "Lore": "Born in the mountains, this horse has traveled far.",
        }
        result = _parse_horse_row(row)
        assert result.description == "A beautiful horse with a white mane."
        assert result.lore == "Born in the mountains, this horse has traveled far."

    def test_description_and_lore_absent(self) -> None:
        """Test that missing description and lore default to None."""
        row = {
            "Id": "basic",
            "Name": "Basic Horse",
            "Speed": "50",
            "Stamina": "50",
            "Consistency": "50",
            "Luck": "50",
        }
        result = _parse_horse_row(row)
        assert result.description is None
        assert result.lore is None
