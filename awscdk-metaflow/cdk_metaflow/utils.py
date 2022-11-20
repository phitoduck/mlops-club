from typing import Callable

TNamerFn = Callable[[str], str]

def make_namer_fn(prefix) -> TNamerFn:
    """Return a naming function that can be used to concisely ensure that construct IDs are unique."""
    return lambda s: f"{prefix}-{s}"