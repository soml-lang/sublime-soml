"""
The writer, and the conversions to exact builtin types that the writer and the syntax tree share.
"""

import math
import re
from collections import UserString
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from operator import itemgetter

from ._parser import DURATION_UNITS, INT64_MAX, INT64_MIN, MAX_DEPTH, MAX_INSTANT, MIN_INSTANT, NANOSECONDS_PER_SECOND, UNIX_EPOCH, UNIX_EPOCH_ORDINAL, abbreviate, is_bare_key

# Not imported at runtime, so that importing the package stays fast. Annotations are evaluated only when something asks for them.
TYPE_CHECKING = False

if TYPE_CHECKING:
	from collections.abc import Iterable, Iterator
	from typing import NoReturn, TypeIs

type Serializable = str | int | float | bool | datetime | timedelta | Sequence[Serializable] | Mapping[str, Serializable] | None
"""
A value that `dumps()` accepts. This is wider than what `loads()` returns, so that a `dict[str, int]` or a `tuple` can be written as it is.
"""

# A single quote, a control character, or a lone surrogate, which all need more than `'...'`.
NEEDS_ATTENTION = re.compile("[\x00-\x1f'\x7f\ud800-\udfff]")
LONE_SURROGATE = re.compile('[\ud800-\udfff]')

ESCAPES = str.maketrans(
	{
		**{chr(code): f'\\u{{{code:x}}}' for code in (*range(32), 127)},
		'\\': '\\\\',
		'"': '\\"',
		'\n': '\\n',
		'\t': '\\t',
	}
)

MICROSECOND = timedelta(microseconds=1)
RADIX_FORMATS = {16: ('0x', 'X'), 8: ('0o', 'o'), 2: ('0b', 'b')}


def dumps(value: Mapping[str, Serializable] | Sequence[Serializable], /, *, canonical: bool = False) -> str:
	"""
	Serialize a `dict` or a `list` to SOML.

	The output follows every rule of canonical form except member order: members keep the order of the input, because a person reads the file, and sorted keys put `description` before `name`. Comments and block strings are never written. The text ends with one line feed.

	With `canonical=True`, members are sorted by key, and the output is canonical form. Canonical form is unique for a value: equal values give the same text, so the output can be hashed, signed, or compared.

	An `int` is written as an int and a `float` as a float, so `{'port': 8080}` gives `port: 8080` and `{'ratio': 1.0}` gives `ratio: 1.0`. A `datetime` must have a time zone, and it is written in UTC.

	Raises `TypeError` for a value of a type that cannot be written, or when `canonical` is not a `bool`, and `ValueError` for a value of the right type that cannot be written, such as NaN, an int outside the 64-bit range, a string with a carriage return, a `datetime` without a time zone, a circular reference, or nesting more than 100 levels deep.
	"""
	# A runtime check too, for callers that are not type-checked, because a string such as `'false'` is truthy.
	if not isinstance(canonical, bool):  # pyright: ignore[reportUnnecessaryIsInstance]
		raise TypeError(f'The `canonical` option must be a bool, not {type(canonical).__name__!r}')

	return Writer(canonical=canonical).write_document(value)


class Writer:
	"""
	Appends to one list of parts that is joined once at the end, so the time is linear in the output whatever the nesting.
	"""

	__slots__ = ('ancestors', 'canonical', 'parts')

	def __init__(self, *, canonical: bool) -> None:
		self.canonical = canonical
		self.parts: list[str] = []
		# The ids of the containers being written, to find a circular reference.
		self.ancestors: set[int] = set()

	def write_document(self, value: object) -> str:
		check_document_type(value)

		if is_object(value):
			enter_container(value, 1, self.ancestors)
			members = self.members(value)

			for key, member in members:
				self.write_item(f'{format_key(key)}: ', member, 2, '', '\n')

			# A brace-less object needs at least one entry, so the empty object keeps its braces.
			return ''.join(self.parts) if self.parts else '{}\n'

		self.write_item('', value, 1, '', '\n')
		return ''.join(self.parts)

	def write_item(self, prefix: str, value: object, depth: int, indent: str, suffix: str) -> None:
		"""Writes `prefix`, the value, and `suffix`. A container's own depth is `depth`, and its lines are indented by `indent`."""
		scalar = format_scalar(value)

		if scalar is not None:
			self.parts.append(f'{prefix}{scalar}{suffix}')
			return

		enter_container(value, depth, self.ancestors)
		inner_indent = f'{indent}\t'

		if is_object(value):
			self.write_children(value, f'{prefix}{{', '}', depth, indent, inner_indent=inner_indent, suffix=suffix)
		elif is_array(value):
			self.write_children(value, f'{prefix}[', ']', depth, indent, inner_indent=inner_indent, suffix=suffix)

		# Only the containers being written are ancestors, so a container that two places share is written in both, and only a container inside itself is circular.
		self.ancestors.remove(id(value))

	def write_children(self, value: Mapping[object, object] | Sequence[object], opening: str, closing: str, depth: int, indent: str, *, inner_indent: str, suffix: str) -> None:
		"""Writes the members or items of a container, each with its own prefix, one per line. An empty container is written on one line."""
		if not len(value):
			self.parts.append(f'{opening}{closing}{suffix}')
			return

		self.parts.append(f'{opening}\n')

		if is_object(value):
			for key, member in self.members(value):
				self.write_item(f'{inner_indent}{format_key(key)}: ', member, depth + 1, inner_indent, '\n')
		else:
			for child in value:
				self.write_item(inner_indent, child, depth + 1, inner_indent, '\n')

		self.parts.append(f'{indent}{closing}{suffix}')

	def members(self, mapping: Mapping[object, object]) -> Iterable[tuple[str, object]]:
		"""The members to write, in the order of the mapping, or sorted by key for canonical form. `str` comparison is by code point, which is the canonical order."""
		members = checked_members(mapping)

		if self.canonical:
			return sorted(members, key=itemgetter(0))

		return members


def enter_container(value: object, depth: int, ancestors: set[int]) -> None:
	"""Check the shared serialization limits before descending into a container."""
	if depth > MAX_DEPTH:
		raise ValueError(f'Cannot serialize a value nested more than {MAX_DEPTH} levels deep')

	identity = id(value)
	if identity in ancestors:
		raise ValueError('Cannot serialize a circular structure')

	ancestors.add(identity)


def check_document_type(value: object) -> None:
	"""Raises `TypeError` for a document that is not an object or an array, for `dumps()` and `DocumentNode.from_value()`."""
	if not is_object(value) and not is_array(value):
		raise TypeError(f'The top-level value must be a dict or a list, because a document is a collection, not {type(value).__name__!r}')


def is_object(value: object) -> TypeIs[Mapping[object, object]]:
	# The exact type first, which is the common case, because `isinstance` against an abstract class goes through its `__instancecheck__`.
	if type(value) is dict:
		return True

	if type(value) is list or type(value) is tuple:
		return False

	return isinstance(value, Mapping)


def is_array(value: object) -> TypeIs[Sequence[object]]:
	# Bytes are a sequence of ints in Python, but they are not an array a user would mean to write. Text is not either, and a `UserString` is a sequence of `UserString`s, so it would never end.
	if type(value) is list or type(value) is tuple:
		return True

	if type(value) is dict:
		return False

	return isinstance(value, Sequence) and not isinstance(value, str | UserString | bytes | bytearray | memoryview)


def checked_members(mapping: Mapping[object, object]) -> Iterator[tuple[str, object]]:
	"""The members of a mapping, in its order, with each key as an exact `str`. Raises `TypeError` for a key that is not a `str`, and `ValueError` for two keys that are the same string, which a `str` subclass with its own `__eq__`, or a mapping that is not a `dict`, can hold."""
	# Exact string keys in a dict are already unique. Only custom mappings and subclass keys need a second set of their normalized keys.
	mapping_type = type(mapping)

	if mapping_type is dict and all(type(key) is str for key in mapping):
		yield from mapping.items()  # type: ignore[misc] # All keys were checked to be exact strings.
		return

	keys: set[str] = set()

	for key, value in mapping.items():
		# The exact type first, so that the common key skips the call of `exact_str()`.
		if type(key) is str:
			key_text = key
		else:
			if not isinstance(key, str):
				raise TypeError(f'Object keys must be str, not {type(key).__name__!r}')

			key_text = exact_str(key)

		if key_text in keys:
			raise ValueError(f'Cannot serialize two keys that are the same string: {abbreviate(key_text)!r}')

		keys.add(key_text)
		yield key_text, value


def format_scalar(value: object) -> str | None:
	"""Formats a scalar, or returns `None` for a container. The exact types come first, because they are the common case."""
	value_type = type(value)

	if value_type is str:
		return format_string(value, 'string')  # type: ignore[arg-type] # The exact type was checked.

	if value_type is int:
		return format_integer(value)  # type: ignore[arg-type] # The exact type was checked.

	if value_type is float:
		return format_float(value)  # type: ignore[arg-type] # The exact type was checked.

	if value is None:
		return 'null'

	# `bool` is a subclass of `int`, so it is checked before it.
	if value_type is bool:
		return 'true' if value else 'false'

	if value_type is dict or value_type is list or value_type is tuple:
		return None

	if value_type is datetime:
		return format_instant(instant_nanoseconds(value))  # type: ignore[arg-type] # The exact type was checked.

	if value_type is timedelta:
		return format_duration(value)  # type: ignore[arg-type] # The exact type was checked.

	if is_object(value) or is_array(value):
		return None

	# Subclasses, such as `StrEnum` and `IntEnum`, are written as their value, not as their `str()`, which an enum may override.
	if isinstance(value, str):
		return format_string(exact_str(value), 'string')

	if isinstance(value, int):
		return format_integer(exact_int(value))

	if isinstance(value, float):
		return format_float(exact_float(value))

	if isinstance(value, datetime):
		return format_instant(instant_nanoseconds(value))

	if isinstance(value, timedelta):
		return format_duration(value)

	raise_unsupported_type(value)


def raise_unsupported_type(value: object) -> NoReturn:
	"""The same actionable type errors for plain values and syntax-tree construction."""
	if isinstance(value, date):
		raise TypeError("Object of type 'date' is not SOML serializable. A date is not an instant, so write it as a string, or as a datetime with a time zone")

	raise TypeError(f'Object of type {type(value).__name__!r} is not SOML serializable')


def exact_str(value: str) -> str:
	"""The value as an exact `str`. The base method, because a subclass, such as an enum that mixes in `str`, may override `__str__` or `__format__`."""
	if type(value) is str:
		return value

	return str.__str__(value)


def exact_int(value: int) -> int:
	"""The value as an exact `int`. The base method, because a subclass, such as an `IntEnum`, may override `__int__`, `__index__`, or `__format__`."""
	if type(value) is int:
		return value

	return int.__int__(value)


def exact_float(value: int | float) -> float:  # noqa: PYI041 # Written out, because the `int` case has its own branch.
	"""The value as an exact `float`. The base method, because a subclass may override `__float__`. A type checker accepts an `int` for a `float`, so an `int` is converted too."""
	if type(value) is float:
		return value

	if isinstance(value, float):
		return float.__float__(value)

	try:
		return float(exact_int(value))
	except OverflowError:
		raise ValueError('The integer is too large to be a finite float') from None


def format_key(key: str) -> str:
	return key if is_bare_key(key) else format_string(key, 'key')


def format_string(string: str, kind: str) -> str:
	# One search settles the common case: no quote, no control character, and no lone surrogate.
	if NEEDS_ATTENTION.search(string) is None:
		return f"'{string}'"

	return f'"{escaped_string_body(string, kind)}"'


def format_escaped_string(string: str, kind: str) -> str:
	"""A string in the `"..."` form, even when `'...'` would do."""
	return f'"{escaped_string_body(string, kind)}"'


def escaped_string_body(string: str, kind: str) -> str:
	"""The body of a `"..."` string, with the checks that a `'...'` string skips: no lone surrogate and no carriage return."""
	check_string(string, kind)
	return string.translate(ESCAPES)


def check_string(string: str, kind: str) -> None:
	"""Validate a string or key without rendering escaped text that a tree does not need."""
	if LONE_SURROGATE.search(string) is not None:
		raise ValueError(f'Cannot serialize a {kind} containing a lone surrogate, which is not a Unicode scalar value')

	if '\r' in string:
		raise ValueError(f'Cannot serialize a {kind} containing a carriage return (U+000D), which is not representable')


def format_integer(value: int) -> str:
	check_integer(value)
	return int.__repr__(value)


def check_integer(value: int) -> None:
	"""Check the integer range without rendering decimal text that a tree does not need."""
	if not INT64_MIN <= value <= INT64_MAX:
		# Without the value, which can be too long to convert to text.
		raise ValueError('Cannot serialize an integer outside the 64-bit range (-9223372036854775808 to 9223372036854775807)')


def format_float(value: float) -> str:
	"""
	The shortest decimal that reads back as the same float, laid out as ECMAScript `Number::toString` does, which is also RFC 8785's choice, with `.0` added when there is neither a fraction nor an exponent, so that a float never reads back as an int.

	`repr()` gives the digits, but not the layout: it switches to an exponent at other magnitudes, and it writes `e+21` and `e-07`.
	"""
	# Covers -0.0 too, since zero has one value whatever its sign.
	if value == 0:
		return '0.0'

	if not math.isfinite(value):
		check_float(value)
		return 'infinity' if value > 0 else '-infinity'

	text = float.__repr__(value)

	if 'e' not in text:
		return text

	sign = '-' if value < 0 else ''
	mantissa, _, exponent_text = text.removeprefix('-').partition('e')
	integer_part, _, fraction_part = mantissa.partition('.')
	all_digits = integer_part + fraction_part
	# The value is 0.{digits} times 10 to the power of n.
	n = int(exponent_text) + len(integer_part)
	digits = all_digits.rstrip('0')
	k = len(digits)

	if k <= n <= 21:
		return f'{sign}{digits}{"0" * (n - k)}.0'

	if 0 < n <= 21:
		return f'{sign}{digits[:n]}.{digits[n:]}'

	if -6 < n <= 0:
		return f'{sign}0.{"0" * -n}{digits}'

	fraction = f'.{digits[1:]}' if k > 1 else ''
	return f'{sign}{digits[0]}{fraction}e{n - 1}'


def check_float(value: float) -> None:
	"""Reject NaN without computing a canonical spelling."""
	if math.isnan(value):
		raise ValueError('Cannot serialize NaN, which is not representable. Use None for a missing value')


def instant_nanoseconds(value: datetime) -> int:
	"""The instant as nanoseconds since the Unix epoch. The base methods, as in `exact_int()`, because a subclass may override them."""
	if datetime.utcoffset(value) is None:
		raise ValueError(f'Cannot serialize the datetime {datetime.isoformat(value)}, because it has no time zone. An instant needs one, such as datetime.UTC')

	# Subtraction rather than `astimezone()`, which raises `OverflowError` when the offset moves the time out of its year range.
	nanoseconds = timedelta.__floordiv__(datetime.__sub__(value, UNIX_EPOCH), MICROSECOND) * 1000

	if not MIN_INSTANT <= nanoseconds <= MAX_INSTANT:
		raise ValueError('Cannot serialize the instant, because in UTC it falls outside the years 0001 to 9999')

	return nanoseconds


def exact_instant(value: datetime) -> datetime:
	"""The value as an exact `datetime` in UTC, which is what `loads()` returns for an instant."""
	return UNIX_EPOCH + timedelta(microseconds=instant_nanoseconds(value) // 1000)


def duration_nanoseconds(value: timedelta) -> int:
	"""The duration as nanoseconds. The base methods, as in `exact_int()`, because a subclass may override them."""
	nanoseconds = timedelta.__floordiv__(value, MICROSECOND) * 1000

	if not INT64_MIN <= nanoseconds <= INT64_MAX:
		raise ValueError(f'Cannot serialize the duration {timedelta.__str__(value)}, because it is outside the 64-bit range of nanoseconds, about 292 years either way')

	return nanoseconds


def exact_duration(value: timedelta) -> timedelta:
	"""The value as an exact `timedelta`, which is what `loads()` returns for a duration."""
	return timedelta(microseconds=duration_nanoseconds(value) // 1000)


def format_instant(nanoseconds: int) -> str:
	"""An instant in canonical form, from `instant_nanoseconds()`, which checks its range."""
	days, nanoseconds_of_day = divmod(nanoseconds, 86_400 * NANOSECONDS_PER_SECOND)
	day = date.fromordinal(days + UNIX_EPOCH_ORDINAL)
	seconds_of_day, fraction = divmod(nanoseconds_of_day, NANOSECONDS_PER_SECOND)
	hours, rest = divmod(seconds_of_day, 3600)
	minutes, seconds = divmod(rest, 60)
	return f'{day.year:04}-{day.month:02}-{day.day:02}T{hours:02}:{minutes:02}:{seconds:02}{format_fraction(fraction)}Z'


def format_duration(value: timedelta) -> str:
	nanoseconds = duration_nanoseconds(value)

	if nanoseconds == 0:
		return '0s'

	hours, rest = divmod(abs(nanoseconds), DURATION_UNITS['h'])
	minutes, rest = divmod(rest, DURATION_UNITS['m'])
	seconds, fraction = divmod(rest, DURATION_UNITS['s'])
	parts = ['-' if nanoseconds < 0 else '']

	if hours:
		parts.append(f'{hours}h')

	if minutes:
		parts.append(f'{minutes}m')

	if seconds or fraction:
		parts.append(f'{seconds}{format_fraction(fraction)}s')

	return ''.join(parts)


def format_fraction(nanoseconds: int) -> str:
	"""The fraction of a second, as an instant and a duration write it: nothing for zero, and otherwise a `.` and nine digits without the trailing zeros."""
	return f'.{nanoseconds:09}'.rstrip('0') if nanoseconds else ''
