"""Tests for zone loader.

Tests:
1. load_zones_from_rec parses zones from mansion.rec
2. load_rooms_from_rec parses rooms from mansion.rec with Zone and HasVoice fields
3. sync_zones_and_rooms_to_db loads zones and rooms to database
4. Rooms reference valid zones (FK constraint)
5. Has_voice field is correctly parsed
6. Re-sync removes zones/rooms not in files
"""

import asyncpg
import pytest
import pytest_asyncio

from mudd.services.zone_loader import (
    Room,
    get_default_room,
    load_rooms_from_rec,
    load_zones_from_rec,
    sync_zones_and_rooms_to_db,
)


class TestLoadZonesFromRec:
    """Test parsing zones from rec files."""

    def test_loads_zones(self):
        """Zones are parsed from mansion.rec."""
        zones = load_zones_from_rec()
        assert len(zones) > 0

    def test_zone_has_required_fields(self):
        """Each zone has id and name."""
        zones = load_zones_from_rec()
        for zone in zones:
            assert zone.id, "Zone must have id"
            assert zone.name, "Zone must have name"

    def test_floor_1_zone_exists(self):
        """The floor-1 zone from mansion.rec is loaded."""
        zones = load_zones_from_rec()
        zone_ids = {z.id for z in zones}
        assert "floor-1" in zone_ids

    def test_zone_description_optional(self):
        """Zone description is optional."""
        zones = load_zones_from_rec()
        # At least one zone should exist
        assert len(zones) > 0
        # Description can be None or a string
        for zone in zones:
            assert zone.description is None or isinstance(zone.description, str)


class TestLoadRoomsFromRec:
    """Test parsing rooms from rec files."""

    def test_loads_rooms(self):
        """Rooms are parsed from mansion.rec."""
        rooms = load_rooms_from_rec()
        assert len(rooms) > 0

    def test_room_has_required_fields(self):
        """Each room has id, name, description, and zone_id."""
        rooms = load_rooms_from_rec()
        for room in rooms:
            assert room.id, f"Room must have id: {room}"
            assert room.name, f"Room must have name: {room}"
            assert room.description, f"Room must have description: {room}"
            assert room.zone_id, f"Room must have zone_id: {room}"

    def test_foyer_room_exists(self):
        """The foyer room from mansion.rec is loaded."""
        rooms = load_rooms_from_rec()
        room_ids = {r.id for r in rooms}
        assert "foyer" in room_ids

    def test_room_references_valid_zone(self):
        """All rooms reference zones that exist."""
        zones = load_zones_from_rec()
        rooms = load_rooms_from_rec()

        zone_ids = {z.id for z in zones}
        for room in rooms:
            assert room.zone_id in zone_ids, (
                f"Room {room.id} references unknown zone {room.zone_id}"
            )

    def test_has_voice_defaults_to_false(self):
        """has_voice defaults to False when not specified."""
        rooms = load_rooms_from_rec()
        # Find a room without HasVoice specified (foyer doesn't have it)
        foyer = next((r for r in rooms if r.id == "foyer"), None)
        assert foyer is not None
        assert foyer.has_voice is False

    def test_has_voice_parsed_correctly(self):
        """has_voice is True when specified as 'yes'."""
        rooms = load_rooms_from_rec()
        # office, screening-room, and lounge have HasVoice: yes
        office = next((r for r in rooms if r.id == "office"), None)
        assert office is not None
        assert office.has_voice is True

    def test_is_default_defaults_to_false(self):
        """is_default defaults to False when not specified."""
        rooms = load_rooms_from_rec()
        # office doesn't have IsDefault specified
        office = next((r for r in rooms if r.id == "office"), None)
        assert office is not None
        assert office.is_default is False

    def test_is_default_parsed_correctly(self):
        """is_default is True when specified as 'yes'."""
        rooms = load_rooms_from_rec()
        # foyer has IsDefault: yes
        foyer = next((r for r in rooms if r.id == "foyer"), None)
        assert foyer is not None
        assert foyer.is_default is True

    def test_all_expected_rooms_present(self):
        """All rooms from mansion.rec are loaded."""
        rooms = load_rooms_from_rec()
        room_ids = {r.id for r in rooms}

        expected_rooms = {
            "foyer",
            "sitting-room",
            "hallway",
            "office",
            "gallery",
            "library",
            "screening-room",
            "banquet-hall",
            "kitchen",
            "freezer",
            "store-room",
            "lounge",
        }

        missing = expected_rooms - room_ids
        assert expected_rooms.issubset(room_ids), f"Missing rooms: {missing}"


class TestGetDefaultRoom:
    """Test get_default_room function."""

    def test_returns_default_room_id(self):
        """get_default_room returns the ID of the room marked as default."""
        rooms = load_rooms_from_rec()
        default_room = get_default_room(rooms)
        assert default_room == "foyer"

    def test_raises_if_no_default(self):
        """get_default_room raises ValueError if no room is marked as default."""
        rooms = [
            Room(id="room1", name="Room 1", description="A room", zone_id="zone1"),
            Room(id="room2", name="Room 2", description="A room", zone_id="zone1"),
        ]
        with pytest.raises(ValueError, match="No default room found"):
            get_default_room(rooms)

    def test_raises_if_multiple_defaults(self):
        """get_default_room raises ValueError if multiple rooms marked as default."""
        rooms = [
            Room(
                id="room1",
                name="Room 1",
                description="A room",
                zone_id="zone1",
                is_default=True,
            ),
            Room(
                id="room2",
                name="Room 2",
                description="A room",
                zone_id="zone1",
                is_default=True,
            ),
        ]
        with pytest.raises(ValueError, match="Multiple default rooms found"):
            get_default_room(rooms)


@pytest.mark.asyncio(loop_scope="module")
class TestSyncZonesAndRooms:
    """Test syncing zones and rooms to database using sync_zones_and_rooms_to_db."""

    @pytest_asyncio.fixture(scope="class", loop_scope="module")
    async def synced_db(self, test_db):
        """Sync zones and rooms to test database using the actual sync function."""
        zones = load_zones_from_rec()
        rooms = load_rooms_from_rec()

        # Use the actual sync function (DB-only, no Discord)
        await sync_zones_and_rooms_to_db(test_db, zones, rooms, default_room="foyer")

        yield test_db

    async def test_zones_loaded_to_database(self, synced_db):
        """Zones are inserted into the zones table."""
        async with synced_db.acquire() as conn:
            db_zones = await conn.fetch("SELECT * FROM zones")
            db_zone_ids = {z["id"] for z in db_zones}

            assert "floor-1" in db_zone_ids

    async def test_rooms_loaded_to_database(self, synced_db):
        """Rooms are inserted into the rooms table with zone reference."""
        async with synced_db.acquire() as conn:
            db_rooms = await conn.fetch("SELECT * FROM rooms")
            db_room_ids = {r["id"] for r in db_rooms}

            assert "foyer" in db_room_ids
            assert "office" in db_room_ids

    async def test_room_zone_fk_constraint(self, synced_db):
        """Room zone_id references zones.id (FK constraint)."""
        async with synced_db.acquire() as conn:
            # Try to insert a room with invalid zone_id - should fail
            with pytest.raises(asyncpg.ForeignKeyViolationError):
                await conn.execute(
                    """INSERT INTO rooms (id, name, description, zone_id, has_voice)
                       VALUES ($1, $2, $3, $4, $5)""",
                    "test-room",
                    "Test Room",
                    "A test room",
                    "nonexistent-zone",
                    False,
                )

    async def test_has_voice_stored_correctly(self, synced_db):
        """has_voice field is stored correctly in database."""
        async with synced_db.acquire() as conn:
            office = await conn.fetchrow("SELECT * FROM rooms WHERE id = $1", "office")
            assert office is not None
            assert office["has_voice"] is True

            foyer = await conn.fetchrow("SELECT * FROM rooms WHERE id = $1", "foyer")
            assert foyer is not None
            assert foyer["has_voice"] is False

    async def test_rooms_in_correct_zone(self, synced_db):
        """All rooms reference floor-1 zone."""
        async with synced_db.acquire() as conn:
            rooms = await conn.fetch("SELECT * FROM rooms")

            for room in rooms:
                assert room["zone_id"] == "floor-1", (
                    f"Room {room['id']} should be in floor-1"
                )

    async def test_sync_returns_stats(self, test_db):
        """sync_zones_and_rooms_to_db returns correct stats."""
        zones = load_zones_from_rec()
        rooms = load_rooms_from_rec()

        stats = await sync_zones_and_rooms_to_db(
            test_db, zones, rooms, default_room="foyer"
        )

        assert stats["zones"] == len(zones)
        assert stats["rooms"] == len(rooms)


@pytest.mark.asyncio(loop_scope="module")
class TestSyncRemovesStaleData:
    """Test that sync removes zones/rooms not in files."""

    async def test_removes_stale_rooms(self, test_db):
        """Rooms not in rec files are removed on sync."""
        zones = load_zones_from_rec()
        rooms = load_rooms_from_rec()

        async with test_db.acquire() as conn:
            # Ensure zones exist first
            for zone in zones:
                await conn.execute(
                    """INSERT INTO zones (id, name, description)
                       VALUES ($1, $2, $3)
                       ON CONFLICT (id) DO UPDATE SET name = $2, description = $3""",
                    zone.id,
                    zone.name,
                    zone.description,
                )

            # Insert a fake room that should be deleted
            await conn.execute(
                """INSERT INTO rooms (id, name, description, zone_id, has_voice)
                   VALUES ($1, $2, $3, $4, $5)
                   ON CONFLICT (id) DO NOTHING""",
                "fake-room",
                "Fake Room",
                "This room should be deleted",
                "floor-1",
                False,
            )

            # Verify fake room exists
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM rooms WHERE id = $1", "fake-room"
            )
            assert count == 1

        # Run the sync function - it should delete the fake room
        await sync_zones_and_rooms_to_db(test_db, zones, rooms, default_room="foyer")

        async with test_db.acquire() as conn:
            # Verify fake room is gone
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM rooms WHERE id = $1", "fake-room"
            )
            assert count == 0

    async def test_removes_stale_zones(self, test_db):
        """Zones not in rec files are removed on sync."""
        zones = load_zones_from_rec()
        rooms = load_rooms_from_rec()

        async with test_db.acquire() as conn:
            # First clean up any existing data
            await conn.execute("DELETE FROM rooms")
            await conn.execute("DELETE FROM zones")

            # Insert a fake zone that should be deleted
            await conn.execute(
                """INSERT INTO zones (id, name, description)
                   VALUES ($1, $2, $3)""",
                "fake-zone",
                "Fake Zone",
                "This zone should be deleted",
            )

            # Verify fake zone exists
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM zones WHERE id = $1", "fake-zone"
            )
            assert count == 1

        # Run the sync function - it should delete the fake zone
        await sync_zones_and_rooms_to_db(test_db, zones, rooms, default_room="foyer")

        async with test_db.acquire() as conn:
            # Verify fake zone is gone
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM zones WHERE id = $1", "fake-zone"
            )
            assert count == 0

    async def test_validates_default_room(self, test_db):
        """sync_zones_and_rooms_to_db raises if default_room doesn't exist."""
        zones = load_zones_from_rec()
        rooms = load_rooms_from_rec()

        with pytest.raises(ValueError, match="Default room 'nonexistent' not found"):
            await sync_zones_and_rooms_to_db(
                test_db, zones, rooms, default_room="nonexistent"
            )
