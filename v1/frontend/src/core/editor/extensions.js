import StarterKit from '@tiptap/starter-kit';
import TextAlign from '@tiptap/extension-text-align';
import Underline from '@tiptap/extension-underline';
import { Color } from '@tiptap/extension-color';
import { TextStyle } from '@tiptap/extension-text-style';
import FontFamily from '@tiptap/extension-font-family';
import Link from '@tiptap/extension-link';
import { Table } from '@tiptap/extension-table';
import { TableRow } from '@tiptap/extension-table-row';
import { TableCell } from '@tiptap/extension-table-cell';
import { TableHeader } from '@tiptap/extension-table-header';
import { Extension } from '@tiptap/core';
import { ResizableImage } from 'tiptap-extension-resizable-image';
import CodeBlockLowlight from '@tiptap/extension-code-block-lowlight';
import { ReactNodeViewRenderer } from '@tiptap/react';
import { common, createLowlight } from 'lowlight';
import CodeBlockView from '../../components/CodeBlockView';

// Create lowlight instance with common languages (includes js, python, bash, cpp, etc.)
const lowlight = createLowlight(common);

// Custom CodeBlock extension with React NodeView for header with language selector and copy button
const CustomCodeBlock = CodeBlockLowlight.extend({
  addNodeView() {
    return ReactNodeViewRenderer(CodeBlockView);
  },
});

// Custom FontSize extension - extends TextStyle like FontFamily does
export const FontSize = Extension.create({
  name: 'fontSize',

  addOptions() {
    return {
      types: ['textStyle'],
    };
  },

  addGlobalAttributes() {
    return [
      {
        types: this.options.types,
        attributes: {
          fontSize: {
            default: null,
            parseHTML: (element) => element.style.fontSize?.replace(/['"]+/g, ''),
            renderHTML: (attributes) => {
              if (!attributes.fontSize) {
                return {};
              }
              return {
                style: `font-size: ${attributes.fontSize}`,
              };
            },
          },
        },
      },
    ];
  },

  addCommands() {
    return {
      setFontSize:
        (fontSize) =>
        ({ chain }) => {
          return chain().setMark('textStyle', { fontSize }).run();
        },
      unsetFontSize:
        () =>
        ({ chain }) => {
          return chain()
            .setMark('textStyle', { fontSize: null })
            .removeEmptyTextStyle()
            .run();
        },
    };
  },
});

// Custom Tab Handler Extension
export const TabHandler = Extension.create({
  name: 'tabHandler',

  addKeyboardShortcuts() {
    return {
      Tab: () => {
        this.editor.commands.insertContent('\t');
        return true;
      },
    };
  },
});

// Get all editor extensions with configuration
export function getEditorExtensions() {
  return [
    StarterKit.configure({
      heading: {
        levels: [1, 2, 3, 4, 5, 6],
      },
      history: {
        depth: 100,
      },
      // Disable default code block - we'll use CodeBlockLowlight instead
      codeBlock: false,
    }),
    // Code block with syntax highlighting and custom NodeView
    CustomCodeBlock.configure({
      lowlight,
      defaultLanguage: 'plaintext',
    }),
    TextAlign.configure({
      types: ['heading', 'paragraph'],
    }),
    Underline.configure({
      HTMLAttributes: {
        class: 'underline',
      },
    }),
    Color,
    TextStyle.configure({
      HTMLAttributes: {},
    }),
    FontFamily.configure({
      types: ['textStyle'],
    }),
    FontSize,
    Link.configure({
      openOnClick: false,
      HTMLAttributes: {
        class: 'text-[var(--color-accent-primary)] underline cursor-pointer',
      },
    }),
    ResizableImage.configure({
      allowBase64: true,
      allowResize: true,
      inline: true,
      HTMLAttributes: {
        class: 'rounded cursor-pointer',
      },
    }),
    Table.configure({
      resizable: true,
    }),
    TableRow,
    TableHeader,
    TableCell,
    TabHandler,
  ];
}

// Handle image paste in editor
export function handleImagePaste(view, event) {
  const items = event.clipboardData?.items;
  if (items) {
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.indexOf('image') !== -1) {
        event.preventDefault();
        const blob = items[i].getAsFile();
        if (blob) {
          const reader = new FileReader();
          reader.onload = (e) => {
            const base64 = e.target.result;
            const { schema } = view.state;
            const nodeType = schema.nodes.resizableImage || schema.nodes.image;
            const node = nodeType.create({ src: base64 });
            const transaction = view.state.tr.replaceSelectionWith(node);
            view.dispatch(transaction);
          };
          reader.readAsDataURL(blob);
        }
        return true;
      }
    }
  }
  return false;
}
