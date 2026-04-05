"""Error handling and retry strategies.

Design principle: errors are data, not exceptions.
Transient failures retry automatically. Permanent failures
return structured error info for the caller to handle.
"""

from __future__ import annotations

import time
import random
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

T = TypeVar("T")


@dataclass
class NodeError:
    """Structured error from a pipeline node.

    Instead of raising, nodes return this in their state updates.
    Downstream nodes can check and adapt.
    """
    node: str
    error_type: str
    message: str
    recoverable: bool = True


def retry(
    fn: Callable[..., T],
    *args: Any,
    max_attempts: int = 3,
    backoff_base: float = 1.0,
    backoff_max: float = 30.0,
    retry_on: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> T:
    """Retry a function with exponential backoff + jitter.

    Returns:
        Function result on success.

    Raises:
        The last exception if all attempts fail.
    """
    last_exception: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return fn(*args, **kwargs)
        except retry_on as e:
            last_exception = e
            if attempt < max_attempts - 1:
                delay = min(backoff_base * (2 ** attempt), backoff_max)
                delay *= 0.5 + random.random()  # jitter
                time.sleep(delay)

    raise last_exception  # type: ignore[misc]


def with_fallback(
    primary: Callable[..., T],
    fallback: Callable[..., T],
    *args: Any,
    catch: tuple[type[Exception], ...] = (Exception,),
    **kwargs: Any,
) -> T:
    """Try primary function, fall back on failure."""
    try:
        return primary(*args, **kwargs)
    except catch:
        return fallback(*args, **kwargs)
