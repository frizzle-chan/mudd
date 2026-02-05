# Vulture whitelist for TYPE_CHECKING false positives
from typing import Any

from discord import Interaction

from main import MuddBot

# Mark as used for vulture
_ = (MuddBot, Any, Interaction)
