"""Shared XP <-> level math, so database.py and cogs/engagement.py always agree on the same curve."""


def level_from_xp(xp: int) -> int:
    return int((xp / 100) ** 0.5)


def xp_threshold(level: int) -> int:
    """Total XP required to reach the given level."""
    return 100 * level * level
