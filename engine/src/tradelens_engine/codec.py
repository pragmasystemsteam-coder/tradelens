"""JSON codec for the engine's frozen dataclasses (DD 3.2: state saved after every close).

Only ints, strings, bools, None, UTC datetimes (ISO-8601 text), tuples and nested dataclasses
are allowed, so a round trip through ``json`` is exact. Decoding follows the type hints and
rejects values of the wrong type, so corrupt state fails loudly instead of drifting.
"""

from __future__ import annotations

import functools
import types
from dataclasses import fields, is_dataclass
from datetime import datetime
from typing import Any, Literal, Union, get_args, get_origin, get_type_hints

from tradelens_engine.timefmt import iso, parse_iso

TUPLE_OF_ANY_LEN = 2  # tuple[X, ...] has two type arguments: X and Ellipsis


def encode(value: Any) -> Any:  # noqa: ANN401 - any engine value
    """Plain JSON form of an engine value (dataclass -> dict, tuple -> list, time -> text).

    Raises:
        TypeError: For floats, lists, dicts or other types the engine never stores.
    """
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, datetime):
        return iso(value)
    if is_dataclass(value) and not isinstance(value, type):
        return {f.name: encode(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, tuple):
        return [encode(v) for v in value]
    raise TypeError(f"cannot encode {type(value).__name__}")


@functools.cache
def _hints(cls: type) -> dict[str, Any]:
    return get_type_hints(cls)


def decode(tp: Any, data: Any) -> Any:  # noqa: ANN401 - any engine type
    """Inverse of :func:`encode` for type ``tp``.

    Raises:
        ValueError: If ``data`` does not match ``tp``.
        TypeError: If ``tp`` is not a supported type.
    """
    origin = get_origin(tp)
    if origin is Literal:
        if data not in get_args(tp):
            raise ValueError(f"{data!r} is not one of {get_args(tp)}")
        return data
    if origin in (Union, types.UnionType):
        args = get_args(tp)
        if data is None:
            if type(None) in args:
                return None
            raise ValueError(f"null not allowed for {tp}")
        rest = [a for a in args if a is not type(None)]
        if len(rest) != 1:
            raise TypeError(f"ambiguous union {tp}")
        return decode(rest[0], data)
    if origin is tuple:
        if not isinstance(data, list):
            raise ValueError(f"expected a list for {tp}, got {type(data).__name__}")
        args = get_args(tp)
        if len(args) == TUPLE_OF_ANY_LEN and args[1] is Ellipsis:
            return tuple(decode(args[0], v) for v in data)
        return tuple(decode(a, v) for a, v in zip(args, data, strict=True))
    if tp is datetime:
        return parse_iso(data)
    if tp in (int, str, bool):
        if type(data) is not tp:
            raise ValueError(f"expected {tp.__name__}, got {type(data).__name__}")
        return data
    if isinstance(tp, type) and is_dataclass(tp):
        if not isinstance(data, dict):
            raise ValueError(f"expected an object for {tp.__name__}")
        hints = _hints(tp)
        names = [f.name for f in fields(tp)]
        missing = [n for n in names if n not in data]
        if missing:
            raise ValueError(f"{tp.__name__}: missing field(s) {missing}")
        return tp(**{n: decode(hints[n], data[n]) for n in names})
    raise TypeError(f"unsupported type {tp!r}")
