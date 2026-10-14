import contextlib
import datetime
import decimal
import difflib
import fractions
import itertools
import math
import os
import re
import tomllib

import sublime
import sublime_plugin

from . import json5, soml


def is_soml(view):
	return view.match_selector(0, 'source.soml')


def document_text(view):
	return view.substr(sublime.Region(0, view.size()))


@contextlib.contextmanager
def tabs_kept(view):
	"""Keep the tabs that are inserted in the `with` block as they are. With `translate_tabs_to_spaces` on, Sublime Text turns inserted tabs into spaces, which would change the value of a block string."""
	settings = view.settings()
	translates_tabs = settings.get('translate_tabs_to_spaces')
	settings.set('translate_tabs_to_spaces', False)
	try:
		yield
	finally:
		# Erased first, so that a view that inherits the setting goes on inheriting it. A value of the view that is the same as the inherited one is then inherited too, because the API does not tell them apart.
		settings.erase('translate_tabs_to_spaces')
		if settings.get('translate_tabs_to_spaces') != translates_tabs:
			settings.set('translate_tabs_to_spaces', translates_tabs)


def replace_text(view, edit, region, text):
	"""Replace the region with the text as it is."""
	with tabs_kept(view):
		view.replace(edit, region, text)


LAYOUT_OR_CONTENT = re.compile(r'''(?P<content>'[^']*'|"(?:\\.|[^"\\])*"|#[^\n]*)|[ \t,]+''')


def layout_key(line):
	"""A line without format-only layout, while keeping single-line strings and comments."""
	return LAYOUT_OR_CONTENT.sub(lambda match: match['content'] or '', line)


def common_ends(old, new):
	"""The lengths of the longest common start and end of two sequences, which do not overlap."""
	limit = min(len(old), len(new))
	start = 0
	while start < limit and old[start] == new[start]:
		start += 1

	end = 0
	while end < limit - start and old[-1 - end] == new[-1 - end]:
		end += 1

	return start, end


def text_changes(old, new):
	"""The parts of the old text to replace to get the new text, as `(start, end, replacement)` in order. Lines, and then characters within the lines that changed, so that a caret on a changed line keeps its place among the characters around it."""
	old_lines = old.splitlines(keepends=True)
	new_lines = new.splitlines(keepends=True)
	offsets = [0, *itertools.accumulate(len(line) for line in old_lines)]
	# Lines are matched without layout spaces, tabs, and commas, which Format Document changes, so a line keeps its place across such changes. Single-line strings and comments stay distinct. A match only pairs lines, whose characters are then compared.
	old_keys = [layout_key(line) for line in old_lines]
	new_keys = [layout_key(line) for line in new_lines]
	# Comparing lines takes time that grows much faster than their count. So the lines that stay at the start and the end are left out, blank lines do not anchor matches, a line that is common in a long text, such as `}`, does not match on its own (`autojunk`), and a long part that is left is one part.
	common_start, common_end = common_ends(old_keys, new_keys)
	old_count = len(old_lines) - common_start - common_end
	new_count = len(new_lines) - common_start - common_end
	operations = [('replace', 0, old_count, 0, new_count)] if old_count + new_count > 2000 else difflib.SequenceMatcher(lambda line: not line.strip(), old_keys[common_start:common_start + old_count], new_keys[common_start:common_start + new_count]).get_opcodes()
	operations = [('equal', 0, common_start, 0, common_start), *((tag, old_start + common_start, old_end + common_start, new_start + common_start, new_end + common_start) for tag, old_start, old_end, new_start, new_end in operations), ('equal', len(old_lines) - common_end, len(old_lines), len(new_lines) - common_end, len(new_lines))]

	# Line by line where the number of lines stays, and otherwise as one part.
	parts = []
	for _, old_start, old_end, new_start, new_end in operations:
		if old_end - old_start == new_end - new_start:
			parts += [(offsets[index], old_lines[index], new_lines[index - old_start + new_start]) for index in range(old_start, old_end) if old_lines[index] != new_lines[index - old_start + new_start]]
		else:
			parts.append((offsets[old_start], ''.join(old_lines[old_start:old_end]), ''.join(new_lines[new_start:new_end])))

	# Comparing characters takes time that grows much faster than their count too. So a part is compared without the characters that stay at its start and end, and what is left is compared only while it is short and the characters compared so far are few, and is otherwise replaced whole.
	budget = 10_000
	changes = []
	for start, old_part, new_part in parts:
		common_start, common_end = common_ends(old_part, new_part)
		old_part = old_part[common_start:len(old_part) - common_end]
		new_part = new_part[common_start:len(new_part) - common_end]
		start += common_start
		size = len(old_part) + len(new_part)
		if size > 200 or size > budget:
			changes.append((start, start + len(old_part), new_part))
			continue

		budget -= size
		changes += [(start + old_start, start + old_end, new_part[new_start:new_end]) for tag, old_start, old_end, new_start, new_end in difflib.SequenceMatcher(None, old_part, new_part, autojunk=False).get_opcodes() if tag != 'equal']

	return changes


def moved_point(point, changes):
	"""Where a point goes when the changes from `text_changes()` are made: before a change that starts at it, and after one that ends at it."""
	delta = 0
	for start, end, replacement in changes:
		if point <= start:
			break

		if point < end:
			return start + delta + min(point - start, len(replacement))

		delta += len(replacement) - (end - start)

	return point + delta


def update_text(view, edit, region, text):
	"""Replace the region with the text, changing only the parts that differ, so that the selection keeps its place among the characters that stay."""
	changes = [(region.begin() + start, region.begin() + end, replacement) for start, end, replacement in text_changes(view.substr(region), text)]
	# Moved here, because Sublime Text moves a caret at the edge of a replaced part as it sees fit.
	selection = [sublime.Region(moved_point(selected.a, changes), moved_point(selected.b, changes)) for selected in view.sel()]

	# From the end, so the offsets before each change stay valid. The setting is changed once, because each change of it takes time.
	with tabs_kept(view):
		for start, end, replacement in reversed(changes):
			view.replace(edit, sublime.Region(start, end), replacement)

	view.sel().clear()
	view.sel().add_all(selection)


def replace_selections(view, edit, replacements):
	"""Make the replacements, `(region, text)` for each selection in order, or `None` to leave one as it is, and put a caret after each text, as after typing."""
	selection = []
	made = []
	delta = 0
	for selected, replacement in zip(view.sel(), replacements):
		if replacement is None:
			selection.append(sublime.Region(selected.a + delta, selected.b + delta))
			continue

		region, text = replacement
		# Once for carets that replace the same region, such as two carets in one `{}` for Paste JSON as SOML.
		if made and made[-1][0] == region:
			selection.append(caret)
			continue

		made.append(replacement)
		caret = sublime.Region(region.begin() + delta + len(text))
		selection.append(caret)
		delta += len(text) - region.size()

	# From the end, so the offsets before each replacement stay valid.
	for replacement in reversed(made):
		replace_text(view, edit, *replacement)

	view.sel().clear()
	view.sel().add_all(selection)


def indentation_unit(view):
	settings = view.settings()
	return ' ' * settings.get('tab_size', 4) if settings.get('translate_tabs_to_spaces') else '\t'


###[ STRINGS AND KEYS ]########################################################


def leading_whitespace(text):
	return text[:len(text) - len(text.lstrip(' \t'))]


def indent_lines(text, indentation, unit):
	"""Indent every line but the first of text that soml writes, except empty lines, and write the tabs that indent its lines as the unit of indentation of the view. soml writes no block string, whose lines are its value."""
	def indented(line):
		depth = len(line) - len(line.lstrip('\t'))
		return indentation + unit * depth + line[depth:]

	first, *rest = text.split('\n')
	return '\n'.join([first, *(indented(line) if line else line for line in rest)])


def is_block_string(token):
	return token.startswith(("'''", '"""'))


def written_value(value):
	"""The value as canonical form writes the value of a member: a string as a literal string `'...'` when it can be one, and otherwise as an escaped string, and an object or an array over several lines. A literal string may hold a tab, but canonical form writes it as `\\t`, and Sublime Text turns a tab that is inserted into spaces when `translate_tabs_to_spaces` is on."""
	return soml.dumps({'_': value}).removeprefix('_: ').removesuffix('\n')


def escape(value, *, escapes_line_breaks=True):
	"""The value with the escapes of an escaped string, as canonical form writes them."""
	def replacement(match):
		character = match.group()
		return {'\\': '\\\\', '"': '\\"', '\n': '\\n', '\t': '\\t'}.get(character) or f'\\u{{{ord(character):x}}}'

	pattern = r'[\\"\x00-\x1f\x7f]' if escapes_line_breaks else r'[\\\x00-\x09\x0b-\x1f\x7f]'
	return re.sub(pattern, replacement, value)


def format_key(key):
	"""The key as canonical form writes it, quoted when it is not a bare key."""
	return soml.dumps({key: None}).removesuffix(': null\n')


def format_path(path):
	"""The path as soml-cli writes a key path, such as `servers[0].host` or `'the name'.port`."""
	text = ''
	for segment in path:
		text += f'[{segment}]' if isinstance(segment, int) else f'{"." if text else ""}{format_key(segment)}'

	return text


def decode_string(token):
	"""The value of a string token, such as `'a'` or a block string."""
	return soml.loads(f'a: {token}')['a']


class SomlCommand:
	"""A command for SOML documents. A mixin, because Sublime Text makes a command of every `TextCommand` subclass in the plugin."""

	def is_enabled(self):
		return is_soml(self.view)


###[ FORMAT ]##################################################################


def make_file_valid(view):
	"""Sublime Text hides line endings and the encoding from the text, so they are fixed on the view. Returns what was changed."""
	changes = []

	# A carriage return is an error in SOML.
	if view.line_endings() != 'Unix':
		view.set_line_endings('Unix')
		changes.append('the line endings to LF')

	# A SOML file is UTF-8 with no BOM. A file with only ASCII characters has the encoding “Undefined”.
	if view.encoding() not in ('UTF-8', 'Undefined'):
		view.set_encoding('UTF-8')
		changes.append('the encoding to UTF-8')

	return changes


class SomlFormatCommand(SomlCommand, sublime_plugin.TextCommand):
	"""Format the document as the SOML specification describes: normalize the layout and keep comments, member order, and the spelling of every value."""

	def run(self, edit):
		text = document_text(self.view)

		try:
			formatted = soml.format(text)
		except soml.SOMLDecodeError as error:
			sublime.status_message(f'SOML: {error}')
			return

		# Only what changed, so the selection and the scroll position stay where they are.
		update_text(self.view, edit, sublime.Region(0, self.view.size()), formatted)

		if changes := make_file_valid(self.view):
			sublime.status_message(f'SOML: Changed {" and ".join(changes)}')


###[ SAVE ]####################################################################


class SomlTrimTrailingWhitespaceCommand(SomlCommand, sublime_plugin.TextCommand):
	"""Remove the spaces and tabs at the end of every line, except in a block string, where they are part of the value."""

	def run(self, edit):
		for region in reversed(self.view.find_all(r'[ \t]+$')):
			# Text after the opening delimiter of a block string is an error, not content.
			if not self.view.match_selector(region.begin(), 'string - invalid'):
				self.view.erase(edit, region)


class SomlSaveListener(sublime_plugin.EventListener):
	def on_pre_save(self, view):
		if not is_soml(view):
			return

		if view.settings().get('soml_trim_trailing_white_space_on_save'):
			view.run_command('soml_trim_trailing_whitespace')

		if view.settings().get('soml_format_on_save'):
			view.run_command('soml_format')


###[ JSON AND TOML ]###########################################################


def unsupported_value(value, path=()):
	"""Why a value from JSON or TOML cannot be SOML, with its key path, or `None` when it can be."""
	where = format_path(path) or 'the top level'
	match value:
		case dict():
			return next((reason for key, item in value.items() if (reason := unsupported_value(item, (*path, key))) is not None), None)
		case list():
			return next((reason for index, item in enumerate(value) if (reason := unsupported_value(item, (*path, index))) is not None), None)
		case float() if math.isnan(value):
			return f'SOML has no NaN, at {where}'
		case datetime.datetime() if value.tzinfo is None:
			return f'SOML has no local date-time, only an instant with an offset, at {where}'
		case datetime.date() if not isinstance(value, datetime.datetime):
			return f'SOML has no date without a time, at {where}'
		case datetime.time():
			return f'SOML has no time without a date, at {where}'

	return None


def read(text, *, is_toml=False):
	"""The value of a JSON, JSONC, JSON5, or TOML text. Raises `ValueError` for one that SOML cannot hold."""
	value = tomllib.loads(text, parse_float=json5.parse_float) if is_toml else json5.loads(text)
	if (reason := unsupported_value(value)) is not None:
		raise ValueError(reason)

	return value


def is_in_array(view, point):
	"""Whether the innermost container at the point is an array rather than an object."""
	containers = [scope for scope in view.scope_name(point).split() if scope in ('meta.sequence.soml', 'meta.mapping.soml')]
	return containers[-1:] == ['meta.sequence.soml']


def is_after_key(view, point):
	"""Whether the point is where the value of a member goes: after its `:`, and whitespace and comments, which may span lines."""
	while point > 0:
		if view.substr(point - 1) in ' \t\n':
			point -= 1
		elif view.match_selector(point - 1, 'comment'):
			point = view.expand_to_scope(point - 1, 'comment').begin()
		else:
			return view.match_selector(point - 1, 'punctuation.separator.key-value')

	return False


class SomlPasteJsonCommand(SomlCommand, sublime_plugin.TextCommand):
	"""Paste the JSON, JSONC, or JSON5 on the clipboard as SOML. At the start of a line where a member can begin, an object becomes members, and elsewhere, as after a key, it becomes a value in braces."""

	def run(self, edit):
		try:
			value = read(sublime.get_clipboard())
			# Written as the value of a member, so an object keeps its braces, and a string or a number can be pasted too.
			value_text = written_value(value)
			members_text = soml.dumps(value) if isinstance(value, dict) else None
		except (ValueError, TypeError, RecursionError) as error:
			sublime.status_message(f'SOML: The clipboard does not have JSON that SOML can hold. {error}')
			return

		replacements = []
		for region in self.view.sel():
			line = self.view.line(region.begin())
			before = self.view.substr(sublime.Region(line.begin(), region.begin()))
			after = self.view.substr(sublime.Region(region.end(), self.view.line(region.end()).end()))
			# An object pasted in an empty `{}` on one line takes its place as a value, because only members can go between braces.
			is_in_braces = members_text is not None and before.rstrip(' \t').endswith('{') and after.lstrip(' \t').startswith('}')
			if is_in_braces:
				before = before.rstrip(' \t')[:-1]
				after = after.lstrip(' \t')[1:]
				region = sublime.Region(line.begin() + len(before), self.view.line(region.end()).end() - len(after))

			indentation = leading_whitespace(before)
			# A value may begin on the line after its key, so a line that is empty before the caret takes members only where a member can begin.
			is_members = members_text is not None and not is_in_braces and before.strip() == '' and not is_in_array(self.view, region.begin()) and not is_after_key(self.view, region.begin())
			if is_members and value == {}:
				sublime.status_message('SOML: The object on the clipboard is empty, so it has no members to paste')
				replacements.append(None)
				continue

			text = indent_lines(members_text.removesuffix('\n') if is_members else value_text, indentation, indentation_unit(self.view))
			# Members end their line, so text after them goes to the next line.
			if is_members and after.strip() != '':
				text += '\n' + indentation

			replacements.append((region, text))

		replace_selections(self.view, edit, replacements)


class SomlConvertToSomlCommand(sublime_plugin.TextCommand):
	"""Open a JSON, JSONC, JSON5, or TOML document as SOML in a new tab, in the folder of the file."""

	def extension(self):
		return os.path.splitext(self.view.file_name() or '')[1].lower()

	def is_toml(self):
		return self.view.match_selector(0, 'source.toml') or self.extension() == '.toml'

	def is_enabled(self):
		# By the file extension too, for a JSON5 file without a JSON5 syntax, which is plain text.
		return self.view.window() is not None and (self.view.match_selector(0, 'source.json, source.json5, source.toml') or self.extension() in ('.json', '.jsonc', '.json5', '.toml'))

	def is_visible(self):
		return self.is_enabled()

	def run(self, edit):
		try:
			soml_text = soml.dumps(read(document_text(self.view), is_toml=self.is_toml()))
		except (ValueError, TypeError, RecursionError) as error:
			sublime.status_message(f'SOML: {error}')
			return

		view = self.view.window().new_file(syntax='Packages/SOML/SOML.sublime-syntax')
		if name := self.view.file_name():
			view.set_name(os.path.splitext(os.path.basename(name))[0] + '.soml')
			view.settings().set('default_dir', os.path.dirname(name))

		view.run_command('append', {'characters': soml_text})


###[ KEY PATHS ]###############################################################


# The last tree, with the ID of its view and the change count it was parsed at, so that moving the caret does not parse the document again. `None` for a document that is not valid.
cached_tree = (None, None, None)


def document_tree(view):
	"""The syntax tree of the document, or `None` when the document is not valid. A document with an instant or a duration finer than a microsecond has no tree, because soml-python holds microseconds."""
	global cached_tree
	key = (view.id(), view.change_count())
	if cached_tree[:2] == key:
		return cached_tree[2]

	try:
		tree = soml.tree.parse(document_text(view))
	except ValueError:
		tree = None

	cached_tree = (*key, tree)
	return tree


def contains(node, point):
	return node.range[0] <= point <= node.range[1]


def path_at(tree, point):
	"""The path of the member or array item at the point, or `None` when it is not in one."""
	path = []
	node = tree.body
	while True:
		if isinstance(node, soml.tree.ObjectNode):
			member = next((member for member in node.members if contains(member, point)), None)
			if member is None:
				break

			path.append(member.key.value)
			node = member.value
		elif isinstance(node, soml.tree.ArrayNode):
			index = next((index for index, element in enumerate(node.elements) if contains(element, point)), None)
			if index is None:
				break

			path.append(index)
			node = node.elements[index]
		else:
			break

	return path or None


def members(node, path=()):
	"""Every member inside the node, at any depth, with its path."""
	if isinstance(node, soml.tree.ObjectNode):
		for member in node.members:
			member_path = (*path, member.key.value)
			yield member_path, member
			yield from members(member.value, member_path)
	elif isinstance(node, soml.tree.ArrayNode):
		for index, element in enumerate(node.elements):
			yield from members(element, (*path, index))


def preview(node, source):
	"""A short text for the value of a member."""
	if isinstance(node, soml.tree.ObjectNode):
		return '{…}'

	if isinstance(node, soml.tree.ArrayNode):
		return '[…]'

	text = source[node.range[0]:node.range[1]].split('\n', 1)[0]
	return text if len(text) <= 40 else text[:39] + '…'


class SomlKeyPathListener(sublime_plugin.ViewEventListener):
	"""Show the key path of the caret in the status bar."""

	@classmethod
	def is_applicable(cls, settings):
		return settings.get('syntax', '').endswith('/SOML.sublime-syntax')

	pending = 0

	# Also when the listener is made, such as when a file is opened or its syntax is set, because the caret has not moved yet.
	def __init__(self, view):
		super().__init__(view)
		# Sublime Text drops the listener when the syntax of the view changes to another one, without telling it, so the key path is removed here.
		self.shows_key_path = view.settings().get('soml_show_key_path')
		view.settings().add_on_change('soml_key_path', self.on_settings_change)
		self.update_soon()

	def on_settings_change(self):
		settings = self.view.settings()
		if not self.is_applicable(settings):
			settings.clear_on_change('soml_key_path')
			self.view.erase_status('soml_key_path')
		elif settings.get('soml_show_key_path') != self.shows_key_path:
			self.shows_key_path = settings.get('soml_show_key_path')
			self.update_soon()

	def on_selection_modified_async(self):
		self.update_soon()

	def on_activated_async(self):
		self.update_soon()

	def update_soon(self):
		# Only the last of quick changes, such as typing, parses the document.
		self.pending += 1
		pending = self.pending
		sublime.set_timeout_async(lambda: self.update() if pending == self.pending else None, 100)

	def update(self):
		if not self.view.is_valid():
			return

		# Not after the syntax changed to another one while the update was pending.
		settings = self.view.settings()
		tree = document_tree(self.view) if settings.get('soml_show_key_path') and self.is_applicable(settings) else None
		path = path_at(tree, self.view.sel()[0].b) if tree is not None and len(self.view.sel()) > 0 else None
		if path is None:
			self.view.erase_status('soml_key_path')
		else:
			self.view.set_status('soml_key_path', format_path(path))


class SomlCopyKeyPathCommand(SomlCommand, sublime_plugin.TextCommand):
	"""Copy the key path of each caret, as soml-cli writes it, such as `servers[0].host`, each on a line of its own, as the built-in Copy copies several selections."""

	def run(self, edit):
		if (tree := document_tree(self.view)) is None:
			sublime.status_message('SOML: The document is not valid')
			return

		paths = [format_path(path) for selected in self.view.sel() if (path := path_at(tree, selected.b)) is not None]
		if not paths:
			sublime.status_message('SOML: The caret is not in a member or an array item')
			return

		sublime.set_clipboard('\n'.join(paths))
		sublime.status_message(f'SOML: Copied {", ".join(paths)}')


class SomlGotoKeyCommand(SomlCommand, sublime_plugin.TextCommand):
	"""Go to a key at any depth, by its key path."""

	def is_enabled(self):
		return super().is_enabled() and self.view.window() is not None

	def run(self, edit):
		if (tree := document_tree(self.view)) is None:
			sublime.status_message('SOML: The document is not valid')
			return

		entries = list(members(tree.body))
		if not entries:
			sublime.status_message('SOML: The document has no keys')
			return

		view = self.view
		selection = list(view.sel())
		viewport = view.viewport_position()
		caret_path = path_at(tree, selection[0].b) if selection else None
		items = [sublime.QuickPanelItem(format_path(path), annotation=preview(member.value, tree.source)) for path, member in entries]
		regions = [sublime.Region(*member.key.range) for _, member in entries]
		# The deepest key that the caret is in.
		selected = max((index for index, (path, _) in enumerate(entries) if caret_path and caret_path[:len(path)] == list(path)), default=0)

		def show(index):
			view.sel().clear()
			view.sel().add(regions[index])
			view.show_at_center(regions[index], animate=False)

		def done(index):
			if index == -1:
				view.sel().clear()
				view.sel().add_all(selection)
				view.set_viewport_position(viewport, animate=False)
			else:
				show(index)

		view.window().show_quick_panel(items, done, selected_index=selected, on_highlight=show, placeholder='Key path')


###[ HOVER ]###################################################################

INSTANT = re.compile(r'(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.(\d+))?(?:Z|([+-])(\d{2}):(\d{2}))')
DURATION_PART = re.compile(r'(\d[\d_]*(?:\.\d[\d_]*)?)(h|ms|m|s|us|ns)')
NANOSECONDS = {'h': 3_600_000_000_000, 'm': 60_000_000_000, 's': 1_000_000_000, 'ms': 1_000_000, 'us': 1000, 'ns': 1}
DURATION_UNITS = [('day', 86_400_000_000_000), ('hour', 3_600_000_000_000), ('minute', 60_000_000_000), ('second', 1_000_000_000), ('millisecond', 1_000_000), ('microsecond', 1000), ('nanosecond', 1)]
RELATIVE_UNITS = [('week', 7 * 86_400),('day', 86_400), ('hour', 3600), ('minute', 60), ('second', 1)]


def plural(count, unit):
	return f'{count:,} {unit}{"" if count == 1 else "s"}'


def plural_decimal(count, unit):
	return f'{count.normalize():,f} {unit}{"" if count == 1 else "s"}'


def offset_name(offset):
	total = int(offset.total_seconds())
	if total == 0:
		return 'UTC'

	# From the magnitude, because flooring a negative offset rounds it away from zero. A local mean time, which time zones have before about 1900, has seconds.
	minutes, seconds = divmod(abs(total), 60)
	hours, minutes = divmod(minutes, 60)
	rest = f':{minutes:02}:{seconds:02}' if seconds else f':{minutes:02}' if minutes else ''
	return f'UTC{"+" if total > 0 else "-"}{hours}{rest}'


def describe_time(instant, fraction):
	return f'{instant:%A, %B} {instant.day}, {instant.year}, {instant:%H:%M:%S}{fraction} {offset_name(instant.utcoffset())}'


def calendar_months(earlier, later):
	"""The whole calendar months from one instant to a later one, in the same time zone."""
	months = (later.year - earlier.year) * 12 + later.month - earlier.month
	# A month is complete when its day and time come round again.
	if (later.day, later.time()) < (earlier.day, earlier.time()):
		months -= 1

	return months


def describe_relative(instant, now):
	# Years and months are counted on the calendar, because they have no fixed length.
	months = calendar_months(*sorted((instant, now)))
	if months >= 12:
		text = plural(months // 12, 'year')
	elif months >= 1:
		text = plural(months, 'month')
	else:
		seconds = abs((instant - now).total_seconds())
		text = next((plural(int(seconds // length), unit) for unit, length in RELATIVE_UNITS if seconds >= length), None)
		if text is None:
			return 'Now'

	return f'In {text}' if instant > now else f'{text} ago'


def describe_instant(text):
	match = INSTANT.fullmatch(text)
	year, month, day, hour, minute, second = (int(group) for group in match.groups()[:6])
	fraction, sign, offset_hours, offset_minutes = match.groups()[6:]
	offset = datetime.timedelta(0) if sign is None else (1 if sign == '+' else -1) * datetime.timedelta(hours=int(offset_hours), minutes=int(offset_minutes))
	# `datetime` holds microseconds, so the fraction is shown as it is written.
	microsecond = int((fraction or '0')[:6].ljust(6, '0'))
	written = datetime.datetime(year, month, day, hour, minute, second, microsecond, tzinfo=datetime.timezone(offset))
	fraction_text = f'.{fraction}' if fraction else ''

	lines = []
	try:
		local = written.astimezone()
		lines.append(f'<b>{describe_time(local, fraction_text)}</b> in your time zone')
	except (OverflowError, ValueError):
		local = None

	utc = written.astimezone(datetime.UTC)
	if local is None or local.utcoffset() != datetime.timedelta(0):
		lines.append(describe_time(utc, fraction_text))

	lines.append(describe_relative(utc, datetime.datetime.now(datetime.UTC)))
	return lines


def describe_duration(text):
	"""The duration in days of 24 hours, hours, and smaller units, and in seconds when that says more."""
	# Exact, because a duration is a whole number of nanoseconds and `timedelta` holds microseconds.
	nanoseconds = int(sum(fractions.Fraction(number.replace('_', '')) * NANOSECONDS[unit] for number, unit in DURATION_PART.findall(text)))
	sign = '-' if text.startswith('-') else ''
	if nanoseconds == 0:
		return ['<b>0 seconds</b>']

	remaining = nanoseconds
	parts = []
	for unit, length in DURATION_UNITS:
		count, remaining = divmod(remaining, length)
		if count:
			parts.append(plural(count, unit))

	lines = [f'<b>{sign}{" ".join(parts)}</b>']
	seconds = plural_decimal(decimal.Decimal(nanoseconds) / 1_000_000_000, 'second')
	if parts != [seconds]:
		lines.append(sign + seconds)

	return lines


def describe_permissions(value):
	return ''.join(flag if value & (1 << (8 - index)) else '-' for index, flag in enumerate('rwxrwxrwx'))


def describe_integer(text, base):
	value = int(text.replace('_', ''), base)
	lines = [f'<b>{value:,}</b>']
	if base != 16:
		lines.append(f'0x{value:X}')

	if base == 8 and value <= 0o777:
		lines.append(describe_permissions(value))

	return lines


def describe_decimal(text):
	"""A long decimal int, such as `86400000`, with its digits grouped."""
	return [f'<b>{int(text):,}</b>'] if len(text.lstrip('-')) >= 5 and '_' not in text else None


def describe_value(view, point):
	"""The lines of the hover for the value at the point, or `None` when it has nothing to explain."""
	for selector, describe in [
		('constant.other.datetime.soml', describe_instant),
		('meta.number.duration.soml', describe_duration),
		('meta.number.integer.hexadecimal.soml', lambda text: describe_integer(text[2:], 16)),
		('meta.number.integer.octal.soml', lambda text: describe_integer(text[2:], 8)),
		('meta.number.integer.binary.soml', lambda text: describe_integer(text[2:], 2)),
		('meta.number.integer.decimal.soml', describe_decimal),
	]:
		if view.match_selector(point, selector):
			text = view.substr(view.expand_to_scope(point, selector))
			# The syntax does not mark what needs arithmetic, such as an int outside int64, a duration that is not a whole number of nanoseconds, or an instant that is outside the range after it is moved to UTC, such as `0001-01-01T00:00:00+00:01`.
			try:
				soml.format(f'a: {text}')
			except ValueError:
				return None

			return describe(text)

	return None


class SomlHoverListener(sublime_plugin.EventListener):
	"""Explain an instant, a duration, or an int in another radix when hovering over it."""

	def on_hover(self, view, point, hover_zone):
		if hover_zone != sublime.HoverZone.TEXT or not is_soml(view) or not view.settings().get('soml_show_value_on_hover'):
			return

		if (lines := describe_value(view, point)) is None:
			return

		content = '<br>'.join(lines)
		view.show_popup(f'<body id="soml-hover"><div style="padding: 0.25rem 0.5rem">{content}</div></body>', sublime.PopupFlags.HIDE_ON_MOUSE_MOVE_AWAY, point, max_width=800)


###[ STRING CONVERSIONS ]######################################################


def string_region(view, point):
	"""The string or quoted key at the point, also when the caret is just after it."""
	for candidate in (point, point - 1):
		# At the end of the document, the point has the scope of the character before it, but no region.
		if candidate >= 0 and view.match_selector(candidate, 'meta.string.soml - string.unquoted') and (region := view.expand_to_scope(candidate, 'meta.string.soml')) is not None:
			return region

	return None


def strings_at_carets(view):
	"""The strings and quoted keys at the carets, each once, from the end of the document, so that changing one keeps the others in place."""
	regions = [string_region(view, selection.b) for selection in view.sel()]
	if None in regions:
		sublime.status_message('SOML: The caret is not in a string')

	return [sublime.Region(*region) for region in reversed(dict.fromkeys((region.a, region.b) for region in regions if region is not None))]


class SomlToggleQuotesCommand(SomlCommand, sublime_plugin.TextCommand):
	"""Switch the string or quoted key at the caret between `'...'` and `"..."`."""

	def run(self, edit):
		for region in strings_at_carets(self.view):
			token = self.view.substr(region)
			if is_block_string(token):
				sublime.status_message('SOML: The caret is not in a single-line string')
				continue

			try:
				value = decode_string(token)
			except ValueError as error:
				sublime.status_message(f'SOML: {error}')
				continue

			if token.startswith("'"):
				replace_text(self.view, edit, region, f'"{escape(value)}"')
			elif (literal := written_value(value)).startswith("'"):
				replace_text(self.view, edit, region, literal)
			else:
				sublime.status_message('SOML: A literal string cannot hold a \', a line break, or a control character')


def block_candidates(value, indentation):
	"""Block strings that may hold the value, literal first. The caller checks which one holds it."""
	lines = value.split('\n')

	# The closing delimiter is a run of exactly as many quotes at the start of a line, so a longer one is chosen than any run that starts a line.
	def delimiter(quote, content_lines):
		runs = [len(line.lstrip(' \t')) - len(line.lstrip(' \t').lstrip(quote)) for line in content_lines]
		return quote * max(3, max(runs, default=0) + 1)

	def block(quote, content_lines):
		run = delimiter(quote, content_lines)
		body = ''.join(f'{indentation}{line}\n' if line else '\n' for line in content_lines)
		return f'{run}\n{body}{indentation}{run}'

	# A tab is written as `\t`, as in a single-line string.
	if '\t' not in value:
		yield block("'", lines)

	# An escaped block string can write what a literal one cannot: a control character, a tab, a line of only spaces and tabs, and a line break at the start or the end, whose blank line would otherwise be dropped.
	escaped = [escape(line, escapes_line_breaks=False) for line in lines]
	escaped = [re.sub(r'^([ \t])(?=[ \t]*$)', lambda match: '\\t' if match.group(1) == '\t' else '\\u{20}', line) for line in escaped]
	while len(escaped) > 1 and escaped[0] == '':
		escaped = ['\\n' + escaped[1], *escaped[2:]]

	while len(escaped) > 1 and escaped[-1] == '':
		escaped = [*escaped[:-2], escaped[-2] + '\\n']

	yield block('"', escaped)


class SomlToggleBlockStringCommand(SomlCommand, sublime_plugin.TextCommand):
	"""Switch the string at the caret between a single-line string and a block string."""

	def run(self, edit):
		for region in strings_at_carets(self.view):
			if self.view.match_selector(region.begin(), 'meta.mapping.key'):
				sublime.status_message('SOML: A key cannot be a block string')
				continue

			token = self.view.substr(region)
			try:
				value = decode_string(token)
			except ValueError as error:
				sublime.status_message(f'SOML: {error}')
				continue

			if is_block_string(token):
				self.to_single_line(edit, region, value)
			else:
				self.to_block(edit, region, value)

	def to_single_line(self, edit, region, value):
		text = written_value(value)
		# A block string on the line after its key goes back to the line of its key, but not after a comment, which also may end with a `:`.
		before = self.view.substr(sublime.Region(0, region.begin())).rstrip(' \t\n')
		if before.endswith(':') and self.view.match_selector(len(before) - 1, 'punctuation.separator.key-value') and '\n' in self.view.substr(sublime.Region(len(before), region.begin())):
			update_text(self.view, edit, sublime.Region(len(before), region.end()), f' {text}')
		else:
			update_text(self.view, edit, region, text)

	def to_block(self, edit, region, value):
		line = self.view.line(region.begin())
		before = self.view.substr(sublime.Region(line.begin(), region.begin()))
		is_member_value = before.rstrip().endswith(':')
		indentation = leading_whitespace(before) + ('' if before.strip() == '' else indentation_unit(self.view))

		for candidate in block_candidates(value, indentation):
			try:
				if decode_string(candidate) != value:
					continue
			except ValueError:
				continue

			# As the formatter writes it, a block string begins on the line after its key.
			if is_member_value:
				start = line.begin() + len(before.rstrip())
				update_text(self.view, edit, sublime.Region(start, region.end()), f'\n{indentation}{candidate}')
			else:
				update_text(self.view, edit, region, candidate)

			return

		sublime.status_message('SOML: A block string cannot hold this string')


###[ INSERT CURRENT INSTANT ]##################################################


class SomlInsertInstantCommand(SomlCommand, sublime_plugin.TextCommand):
	"""Insert the current instant, in UTC or with the offset of your time zone."""

	def run(self, edit, local=False):
		now = datetime.datetime.now(datetime.UTC).replace(microsecond=0)
		text = now.astimezone().isoformat() if local else now.strftime('%Y-%m-%dT%H:%M:%SZ')
		replace_selections(self.view, edit, [(region, text) for region in self.view.sel()])


###[ STRUCTURE ]###############################################################


def replace_keeping_value(view, edit, region, text):
	"""Replace the region with the text when the document keeps its value, and show why not otherwise."""
	old = document_text(view)
	new = old[:region.begin()] + text + old[region.end():]
	try:
		keeps_value = soml.loads(new) == soml.loads(old)
	except ValueError:
		keeps_value = False

	if keeps_value:
		update_text(view, edit, region, text)
	else:
		sublime.status_message('SOML: This would change the document, so it was not done')


def has_comment_or_block_string(tree, start, end):
	return any(start <= comment.range[0] < end for comment in tree.comments) or any(start <= token.range[0] < end and is_block_string(token.value) for token in tree.tokens)


def join_tokens(tokens):
	"""The tokens of an object or an array on one line, as the formatter writes one: a comma and a space between its members or items, and no comma after the last one."""
	text = ''
	for previous, token in itertools.pairwise([None, *tokens]):
		if previous is not None and previous.value == ',' and token.value in ('}', ']'):
			text = text.removesuffix(',')
		elif previous is None or previous.value in ('{', '[') or token.value in ('}', ']', ',', ':'):
			pass
		elif previous.value in (':', ','):
			text += ' '
		else:
			# Two members or items on separate lines, which a line break separated.
			text += ', '

		text += token.value

	return text


def container_at(tree, point):
	"""The innermost object in braces or array that holds the point."""
	container = None
	node = tree.body
	while node is not None and contains(node, point):
		if isinstance(node, soml.tree.ObjectNode):
			if node.braced:
				container = node

			node = next((member.value for member in node.members if contains(member, point)), None)
		elif isinstance(node, soml.tree.ArrayNode):
			container = node
			node = next((element for element in node.elements if contains(element, point)), None)
		else:
			break

	return container


class SomlToggleOneLineCommand(SomlCommand, sublime_plugin.TextCommand):
	"""Put the object or array at each caret on one line, or give each of its members or items a line of its own."""

	def run(self, edit):
		if (tree := document_tree(self.view)) is None:
			sublime.status_message('SOML: The document is not valid')
			return

		containers = list({container.range: container for selected in self.view.sel() if (container := container_at(tree, selected.b)) is not None}.values())
		if not containers:
			sublime.status_message('SOML: The caret is not in an object in braces or an array')
			return

		# Not a container inside another one, whose text toggling the other one changes. From the end, so the offsets in the tree before each change stay valid.
		for container in reversed(containers):
			if not any(other is not container and contains(other, container.range[0]) and contains(other, container.range[1]) for other in containers):
				self.toggle(edit, tree, container)

	def toggle(self, edit, tree, container):
		start, end = container.range
		region = sublime.Region(start, end)
		if '\n' in tree.source[start:end]:
			if has_comment_or_block_string(tree, start, end):
				sublime.status_message('SOML: A comment or a block string cannot be on one line')
				return

			text = join_tokens([token for token in tree.tokens if start <= token.range[0] < end])
		else:
			# A line break inside a container makes the formatter give each member or item a line of its own.
			split = f'a: {tree.source[start]}\n{tree.source[start + 1:end]}'
			try:
				formatted = soml.format(split)
			except ValueError as error:
				# Such as a container at the nesting limit, which the member around it takes past the limit.
				sublime.status_message(f'SOML: {error}')
				return

			text = indent_lines(formatted.removeprefix('a: ').rstrip('\n'), leading_whitespace(self.view.substr(self.view.line(start))), indentation_unit(self.view))

		replace_keeping_value(self.view, edit, region, text)
