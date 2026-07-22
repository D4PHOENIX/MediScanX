"""Utility functions for vector transformations in the agent service."""

from typing import Any, List, Optional

def _vec_to_list(vec: Any) -> Optional[List[float]]:
    """Convert a PostgreSQL vector/array to a plain Python list of floats.

    Handles native Python lists, pgvector string representations, and
    ``None`` values gracefully.

    Args:
        vec (Any): Raw vector value from asyncpg (list, str, or None).

    Returns:
        Optional[List[float]]: A list of floats, or ``None`` if conversion is not possible.
    """
    if vec is None:
        return None
    if isinstance(vec, list):
        return [float(v) for v in vec]
    # In case it's a string representation (pgvector 0.x)
    try:
        return [float(x) for x in vec.strip("[]").split(",")]
    except Exception:
        return None
