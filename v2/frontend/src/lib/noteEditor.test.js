import test from 'node:test'
import assert from 'node:assert/strict'
import { parseNoteContent, textFromNoteContent } from './noteEditor.js'

test('preserves valid TipTap documents', () => {
  const document = { type: 'doc', content: [{ type: 'paragraph' }] }
  assert.equal(parseNoteContent(document), document)
})

test('converts multiline plain text without dropping empty lines', () => {
  assert.deepEqual(parseNoteContent('first\n\nthird'), {
    type: 'doc',
    content: [
      { type: 'paragraph', content: [{ type: 'text', text: 'first' }] },
      { type: 'paragraph', content: [] },
      { type: 'paragraph', content: [{ type: 'text', text: 'third' }] },
    ],
  })
})

test('reads serialized TipTap JSON and extracts nested text', () => {
  const document = {
    type: 'doc',
    content: [
      { type: 'heading', content: [{ type: 'text', text: 'Title' }] },
      { type: 'paragraph', content: [{ type: 'text', text: 'Body' }] },
    ],
  }
  assert.deepEqual(parseNoteContent(JSON.stringify(document)), document)
  assert.equal(textFromNoteContent(document), 'Title Body')
})

test('provides a safe empty document for missing content', () => {
  assert.deepEqual(parseNoteContent(null), {
    type: 'doc',
    content: [{ type: 'paragraph' }],
  })
})
