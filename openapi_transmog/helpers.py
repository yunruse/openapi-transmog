"""
Project-agnostic helper functions.
"""


from typing import Callable, TypeVar

T = TypeVar('T')


def split_by_predicate(
    data: list[T],
    pred: Callable[[T], bool] = bool
):
    yes: list[T] = []
    no: list[T] = []
    for x in data:
        (yes if pred(x) else no).append(x)
    return yes, no


def walk_dict(d: dict):
    """
    Walk a dict, yielding it and any dicts contained within it.
    """
    if not isinstance(d, dict):
        return
    yield d
    for v in d.values():
        yield from walk_dict(v)
        if isinstance(v, (list, tuple)):
            for v2 in v:
                yield from walk_dict(v)