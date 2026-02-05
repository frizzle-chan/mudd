# Vulture whitelist for TYPE_CHECKING false positives
# MuddBot is imported under TYPE_CHECKING in sync.py to avoid circular imports
from main import MuddBot

_ = MuddBot  # Mark as used
