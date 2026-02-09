# Vulture whitelist for TYPE_CHECKING false positives
# MuddBot is imported under TYPE_CHECKING in sync.py to avoid circular imports
from main import MuddBot

# RoomChannelCache: TYPE_CHECKING import in skills_reconciler.py,
# skills_announcements.py
from mudd.observers.discord import RoomChannelCache

_ = MuddBot  # Mark as used
_ = RoomChannelCache
