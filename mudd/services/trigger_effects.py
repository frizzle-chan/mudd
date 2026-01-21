"""Side effects collected during template rendering."""

from dataclasses import dataclass, field


@dataclass
class TriggerEffects:
    """Collects side effects during template rendering.

    Templates can call methods on this object to queue side effects
    that will be executed after the template renders:

    - `broadcast(message)`: Queue a message to send publicly to the channel

    Example template:
        {{ effects.broadcast("**" ~ user.name ~ "** put on music.") }}
        You slide the record onto the turntable. Music fills the room.

    Result:
        - Ephemeral to user: "You slide the record onto the turntable..."
        - Public to channel: "**Frizzle** put on music."
    """

    broadcasts: list[str] = field(default_factory=list)

    def broadcast(self, message: str) -> str:
        """Queue a message to broadcast publicly to the channel.

        Args:
            message: Message to send to the channel (empty/None ignored)

        Returns:
            Empty string (allows inline use in templates without output)
        """
        if message:
            self.broadcasts.append(message)
        return ""
