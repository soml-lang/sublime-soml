import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {parseTree, visitorKeys} from 'soml-lang';

const conformanceDirectory = path.join(import.meta.dirname, '../soml/conformance');

const validFiles = fs.readdirSync(path.join(conformanceDirectory, 'valid'), {recursive: true})
	.filter(file => file.endsWith('.soml'))
	.map(file => path.join(conformanceDirectory, 'valid', file));

// Only the invalid values, because some other invalid documents are not UTF-8 or hold a carriage return, which Sublime Text changes when it reads a file.
const invalidValueFiles = ['number', 'duration', 'instant', 'keyword'].flatMap(directory => fs.readdirSync(path.join(conformanceDirectory, 'invalid', directory))
	.filter(file => file.endsWith('.soml'))
	.map(file => path.join(conformanceDirectory, 'invalid', directory, file)));

// Tokenize every document in one Sublime Text instance, because each launch takes a few seconds.
function tokenizeAll(files) {
	const temporaryDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'sublime-soml-'));
	const outputPath = path.join(temporaryDirectory, 'tokens.json');

	try {
		execFileSync('scripts/st-run', ['dump', 'SOML.sublime-syntax', ...files, '--package', '.', '--name', 'SOML', '--merge', '--output', outputPath], {stdio: 'inherit'});
		return JSON.parse(fs.readFileSync(outputPath, 'utf8'));
	} finally {
		fs.rmSync(temporaryDirectory, {recursive: true, force: true});
	}
}

const tokensByFile = tokenizeAll([...validFiles, ...invalidValueFiles]);

// Sublime Text gives offsets in code points, and the parser in UTF-16 code units.
function codePointOffsets(text) {
	const offsets = [];
	let index = 0;
	let codePoint = 0;
	for (const character of text) {
		// The middle of a surrogate pair is never the start or end of a token.
		offsets[index] = codePoint;
		offsets[index + 1] = codePoint;
		index += character.length;
		codePoint++;
	}

	offsets[index] = codePoint;
	return offsets;
}

// The tokens of a document as `{start, end, scope}`, with code point offsets.
function tokenize(file) {
	return tokensByFile[file].map(([start, end, scope]) => ({start, end, scope}));
}

const expectedScopes = {
	BareKey: 'meta.mapping.key.soml',
	String: 'string.quoted.',
	Float: 'meta.number.float.',
	Instant: 'constant.other.datetime.soml',
	Duration: 'meta.number.duration.soml',
	Line: 'comment.line.number-sign.soml',
	Block: 'comment.block.soml',
};

const integerScopes = {
	'0x': 'meta.number.integer.hexadecimal.soml',
	'0o': 'meta.number.integer.octal.soml',
	'0b': 'meta.number.integer.binary.soml',
};

const keywordScopes = {
	true: 'constant.language.boolean.true.soml',
	false: 'constant.language.boolean.false.soml',
	null: 'constant.language.null.soml',
};

function expectedScope(token) {
	switch (token.type) {
		case 'Punctuator': {
			return punctuationScopes[token.value];
		}

		case 'Integer': {
			return integerScopes[token.value.slice(0, 2)] ?? 'meta.number.integer.decimal.soml';
		}

		case 'Keyword': {
			return keywordScopes[token.value];
		}

		default: {
			return expectedScopes[token.type];
		}
	}
}

const punctuationScopes = {
	'{': 'punctuation.section.mapping.begin.soml',
	'}': 'punctuation.section.mapping.end.soml',
	'[': 'punctuation.section.sequence.begin.soml',
	']': 'punctuation.section.sequence.end.soml',
	',': 'punctuation.separator.sequence.soml',
	':': 'punctuation.separator.key-value.soml',
};

function keyRangesOf(node) {
	return node.type === 'Key'
		? [node.range]
		: visitorKeys[node.type].flatMap(key => [node[key]].flat().flatMap(child => keyRangesOf(child)));
}

const hasScope = (token, scope) => ` ${token.scope}`.includes(` ${scope}`);
const hasOnlyMetaScopes = token => token.scope.split(' ').every(scope => scope.startsWith('meta.') || scope === 'source.soml');

// The number of objects in braces around the deepest value.
function bracedObjectDepth(node) {
	const childDepth = Math.max(0, ...visitorKeys[node.type].flatMap(key => [node[key]].flat().map(child => bracedObjectDepth(child))));
	return childDepth + (node.type === 'Object' && node.braced ? 1 : 0);
}

// Sublime Text keeps at most about 256 contexts on its stack, and each object in braces takes three. See `object-body` in the syntax.
const maximumBracedObjectDepth = 86;

test('every token of every valid conformance document gets the scope of its type', () => {
	assert.ok(validFiles.length > 1000);

	for (const file of validFiles) {
		const name = path.relative(conformanceDirectory, file);
		const text = fs.readFileSync(file, 'utf8');
		const offsets = codePointOffsets(text);
		const characters = [...text];
		const tree = parseTree(text);
		if (bracedObjectDepth(tree) > maximumBracedObjectDepth) {
			continue;
		}

		const keyRanges = keyRangesOf(tree).map(([start, end]) => [offsets[start], offsets[end]]);
		const tokens = tokenize(file);

		const invalid = tokens.find(token => hasScope(token, 'invalid.'));
		assert.equal(invalid, undefined, `${name}: ${JSON.stringify(characters.slice(invalid?.start, invalid?.end).join(''))} is marked invalid`);

		const parserTokens = [...tree.tokens, ...tree.comments].map(token => {
			// A line comment includes its line break, as in the built-in syntaxes.
			const lineBreak = token.type === 'Line' && text[token.range[1]] === '\n' ? 1 : 0;
			return {...token, start: offsets[token.range[0]], end: offsets[token.range[1]] + lineBreak};
		});

		// Whitespace between the parser's tokens and comments gets only the scopes of the members and items around it.
		const stray = tokens.find(token => !hasOnlyMetaScopes(token) && parserTokens.every(({start, end}) => token.start < start || token.end > end));
		assert.equal(stray, undefined, `${name}: ${JSON.stringify(characters.slice(stray?.start, stray?.end).join(''))} is outside every token but is ${stray?.scope}`);

		for (const token of parserTokens) {
			const isKey = keyRanges.some(([keyStart, keyEnd]) => token.start >= keyStart && token.end <= keyEnd);
			const expected = expectedScope(token);
			const expectedScopesOfToken = isKey && token.type !== 'Punctuator' ? [expected, 'meta.mapping.key.soml'] : [expected];

			const mismatch = tokens.find(grammarToken => grammarToken.end > token.start && grammarToken.start < token.end && expectedScopesOfToken.some(scope => !hasScope(grammarToken, scope)));
			assert.equal(mismatch, undefined, `${name}: ${token.type} ${JSON.stringify(token.value)} should be ${expectedScopesOfToken.join(' and ')}, but is ${mismatch?.scope}`);
		}
	}
});

// The parser's reasons for rejecting what the syntax does not check. The readme documents these limits.
const needsArithmetic = /outside the 64-bit range|too large to be a finite|too small to be told apart|whole number of nanoseconds|in UTC it falls/v;

function parseErrorReason(text) {
	try {
		parseTree(text);
	} catch (error) {
		return error.reason;
	}

	throw new Error(`Expected ${JSON.stringify(text)} to be invalid`);
}

test('an invalid value in the conformance suite is marked invalid, unless rejecting it needs arithmetic', () => {
	let checkedCount = 0;

	for (const file of invalidValueFiles) {
		const name = path.relative(conformanceDirectory, file);
		const text = fs.readFileSync(file, 'utf8');
		const value = /^a: (?<value>.+)\n$/v.exec(text)?.groups.value;
		if (value === undefined || needsArithmetic.test(parseErrorReason(text))) {
			continue;
		}

		checkedCount++;
		const start = 'a: '.length;
		const end = start + [...value].length;
		const valueTokens = tokenize(file).filter(token => token.end > start && token.start < end);
		// A value with a separator in it, such as `1,000`, begins with a valid value.
		if (!/[ #,\]\}]|\/\*/v.test(value)) {
			const valueScope = valueTokens.find(token => /meta\.number|constant\.|string\./v.test(token.scope));
			assert.equal(valueScope, undefined, `${name}: ${value} is ${valueScope?.scope}`);
		}

		assert.ok(valueTokens.some(token => hasScope(token, 'invalid.illegal.')), `${name}: ${value} is not marked invalid`);
	}

	assert.ok(checkedCount > 150);
});
