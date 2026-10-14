"""
A reader for JSON5, which also reads JSON and JSON with comments, for converting them to SOML. https://spec.json5.org

It keeps an int and a float apart, as `json.loads()` does: a number with a `.` or an exponent is a float, and every other number, including a hexadecimal one, is an int. It is stricter than JSON5 where SOML is, as `soml from-json` is: a duplicate key is an error, and so is a number that is too large or too small for a 64-bit float, rather than infinity or zero. `Infinity` and `NaN` are read, and the caller decides about them.
"""

import math
import re
import unicodedata


class JSON5DecodeError(ValueError):
	def __init__(self, message, text, position):
		line = 1
		column = position + 1
		for match in LINE_BREAK.finditer(text, 0, position):
			line += 1
			column = position - match.end() + 1

		super().__init__(f'{message}, at line {line}, column {column}')


# White space, as in ECMAScript, and comments.
SPACE = re.compile(r'(?:[\t\n\v\f\r    -     　﻿]+|//[^\n\r  ]*|/\*.*?\*/)*', re.DOTALL)
NUMBER = re.compile(r'([+-]?)(?:(Infinity)|(NaN)|0[xX]([0-9a-fA-F]+)|((?:0|[1-9][0-9]*)(\.[0-9]*)?|\.[0-9]+)([eE][+-]?[0-9]+)?)')
IDENTIFIER_START_CATEGORIES = {'Lu', 'Ll', 'Lt', 'Lm', 'Lo', 'Nl'}
IDENTIFIER_PART_CATEGORIES = IDENTIFIER_START_CATEGORIES | {'Mn', 'Mc', 'Nd', 'Pc'}
DIGITS = '0123456789'
ESCAPES = {'b': '\b', 'f': '\f', 'n': '\n', 'r': '\r', 't': '\t', 'v': '\v'}
LINE_TERMINATORS = '\n\r  '
LINE_BREAK = re.compile(r'\r\n|[\n\r\u2028\u2029]')


def is_identifier_start(character):
	return character in '$_' or unicodedata.category(character) in IDENTIFIER_START_CATEGORIES


def is_identifier_part(character):
	return character in '$_‌‍' or unicodedata.category(character) in IDENTIFIER_PART_CATEGORIES


def abbreviate(number):
	"""The text of a number for an error message, cut short when it is long."""
	return number if len(number) <= 20 else number[:20] + '…'


def parse_float(text):
	"""A float, which is an error when it is too large or too small for a 64-bit float, rather than infinity or zero. Also for TOML, with `tomllib.loads(text, parse_float=parse_float)`."""
	number = float(text)
	if math.isinf(number) and 'inf' not in text:
		raise ValueError(f'The number {abbreviate(text)} is too large for a 64-bit float')

	if number == 0 and re.search(r'[1-9]', text.lower().partition('e')[0]):
		raise ValueError(f'The number {abbreviate(text)} is too small to be told apart from zero')

	return number


def loads(text):
	"""Read a JSON5 text into Python values: `dict`, `list`, `str`, `int`, `float`, `bool`, and `None`."""
	reader = Reader(text)
	try:
		return reader.read()
	except RecursionError:
		raise reader.error('The document is nested too deeply') from None


class Reader:
	def __init__(self, text):
		self.text = text
		self.position = 0

	def error(self, message, position=None):
		return JSON5DecodeError(message, self.text, self.position if position is None else position)

	def skip_space(self):
		self.position = SPACE.match(self.text, self.position).end()
		if self.text.startswith('/*', self.position):
			raise self.error('A block comment is not closed')

	def peek(self):
		return self.text[self.position:self.position + 1]

	def expect(self, character):
		if self.peek() != character:
			raise self.error(f'Expected {character!r}')

		self.position += 1

	def read(self):
		self.skip_space()
		value = self.value()
		self.skip_space()
		if self.position < len(self.text):
			raise self.error('Unexpected text after the value')

		return value

	def value(self):
		character = self.peek()
		if character == '{':
			return self.object()

		if character == '[':
			return self.array()

		if character in ('"', "'"):
			return self.string()

		for word, value in (('true', True), ('false', False), ('null', None)):
			if self.text.startswith(word, self.position) and not self.continues_identifier(self.position + len(word)):
				self.position += len(word)
				return value

		return self.number()

	def continues_identifier(self, position):
		return position < len(self.text) and is_identifier_part(self.text[position])

	def object(self):
		self.position += 1
		result = {}
		self.skip_space()
		while self.peek() != '}':
			start = self.position
			key = self.string() if self.peek() in ('"', "'") else self.identifier()
			if key in result:
				raise self.error(f'Duplicate key {key}, which SOML does not allow', start)

			self.skip_space()
			self.expect(':')
			self.skip_space()
			result[key] = self.value()
			if not self.separator('}'):
				break

		self.expect('}')
		return result

	def array(self):
		self.position += 1
		result = []
		self.skip_space()
		while self.peek() != ']':
			result.append(self.value())
			if not self.separator(']'):
				break

		self.expect(']')
		return result

	def separator(self, closing):
		"""Read a comma, which may also come after the last member or item. Returns whether another member or item can follow."""
		self.skip_space()
		if self.peek() != ',':
			if self.peek() != closing:
				raise self.error(f'Expected , or {closing}')

			return False

		self.position += 1
		self.skip_space()
		return True

	def identifier(self):
		start = self.position
		name = ''
		while self.position < len(self.text):
			character = self.text[self.position]
			if character == '\\':
				if not self.text.startswith('\\u', self.position):
					raise self.error('Expected a \\u escape in a key')

				self.position += 1
				character = self.unicode_escape()
			elif (is_identifier_part(character) if name else is_identifier_start(character)):
				self.position += 1
			else:
				break

			if not (is_identifier_part(character) if name else is_identifier_start(character)):
				raise self.error('The escape is not a character that a key can have', start)

			name += character

		if not name:
			raise self.error('Expected a key')

		return name

	def unicode_escape(self):
		"""Read the `u` and four hexadecimal digits of a `\\u` escape."""
		digits = self.text[self.position + 1:self.position + 5]
		if not re.fullmatch(r'[0-9a-fA-F]{4}', digits):
			raise self.error('Expected four hexadecimal digits after \\u')

		self.position += 5
		return chr(int(digits, 16))

	def string(self):
		quote = self.text[self.position]
		self.position += 1
		parts = []
		while True:
			if self.position >= len(self.text):
				raise self.error('A string is not closed')

			character = self.text[self.position]
			if character == quote:
				self.position += 1
				break

			if character in '\n\r':
				raise self.error('A line break in a string must be escaped')

			if character != '\\':
				parts.append(character)
				self.position += 1
				continue

			self.position += 1
			escaped = self.peek()
			if escaped == '':
				raise self.error('A string is not closed')

			if escaped == 'u':
				parts.append(self.unicode_escape())
				continue

			self.position += 1
			if escaped in ESCAPES:
				parts.append(ESCAPES[escaped])
			elif escaped == '0':
				# Not at the end of the text, where `peek()` is `''`, which `in` finds in any string.
				if self.peek() and self.peek() in DIGITS:
					raise self.error('A \\0 escape cannot be followed by a digit')

				parts.append('\0')
			elif escaped == 'x':
				digits = self.text[self.position:self.position + 2]
				if not re.fullmatch(r'[0-9a-fA-F]{2}', digits):
					raise self.error('Expected two hexadecimal digits after \\x')

				parts.append(chr(int(digits, 16)))
				self.position += 2
			elif escaped in LINE_TERMINATORS:
				# A line continuation. CRLF is one line break.
				if escaped == '\r' and self.peek() == '\n':
					self.position += 1
			elif escaped in '123456789':
				raise self.error('A digit cannot be escaped')
			else:
				parts.append(escaped)

		# A surrogate pair written as two escapes is one character.
		return ''.join(parts).encode('utf-16', 'surrogatepass').decode('utf-16', 'surrogatepass')

	def number(self):
		match = NUMBER.match(self.text, self.position)
		if match is None or match.end() == self.position or self.continues_number(match.end()):
			raise self.error('Unexpected character' if self.position < len(self.text) else 'Expected a value')

		self.position = match.end()
		sign, infinity, nan, hexadecimal, decimal, fraction, exponent = match.groups()
		negative = sign == '-'
		if infinity:
			return -math.inf if negative else math.inf

		if nan:
			return math.nan

		if hexadecimal:
			return int(hexadecimal, 16) * (-1 if negative else 1)

		if fraction is None and exponent is None and not decimal.startswith('.'):
			try:
				return int(match.group(0))
			except ValueError:
				# Python reads at most 4300 digits, and SOML holds at most 19.
				raise self.error(f'The number {abbreviate(match.group(0))} is too large', match.start()) from None

		try:
			return parse_float(match.group(0))
		except ValueError as error:
			raise self.error(str(error), match.start()) from None

	def continues_number(self, position):
		return position < len(self.text) and (self.text[position] in DIGITS or is_identifier_part(self.text[position]))
