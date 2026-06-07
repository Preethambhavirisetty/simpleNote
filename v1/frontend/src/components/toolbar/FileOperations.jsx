import React from 'react';
import { Upload, Download } from 'lucide-react';
import jsPDF from 'jspdf';
import html2canvas from 'html2canvas';
import {
  Document,
  Packer,
  Paragraph,
  TextRun,
  HeadingLevel,
  AlignmentType,
  BorderStyle,
  Table,
  TableRow,
  TableCell,
  WidthType,
} from 'docx';
import { saveAs } from 'file-saver';

export default function FileOperations({
  currentDoc,
  hoverClass,
  onFileUpload,
  showToast,
}) {
  // Export document as PDF with proper page handling
  const handleExportPDF = async () => {
    if (!currentDoc) return;

    try {
      showToast?.('Generating PDF...', 'loading', 0);

      const editorElement = document.querySelector('.tiptap-editor .ProseMirror');
      if (!editorElement) {
        throw new Error('Editor not found');
      }

      // Clone the element for rendering
      const clone = editorElement.cloneNode(true);
      clone.style.width = '800px';
      clone.style.padding = '40px';
      clone.style.background = '#ffffff';
      clone.style.color = '#000000';
      
      // Temporarily append to body for rendering
      const container = document.createElement('div');
      container.style.position = 'absolute';
      container.style.left = '-9999px';
      container.style.top = '0';
      container.appendChild(clone);
      document.body.appendChild(container);

      const canvas = await html2canvas(clone, {
        scale: 2,
        useCORS: true,
        logging: false,
        backgroundColor: '#ffffff',
        windowWidth: 800,
      });

      // Clean up
      document.body.removeChild(container);

      const pdf = new jsPDF('p', 'mm', 'a4');
      const pageWidth = 210;
      const pageHeight = 297;
      const margin = 15;
      const contentWidth = pageWidth - 2 * margin;
      const contentHeight = pageHeight - 2 * margin;

      // Calculate dimensions
      const imgWidth = contentWidth;
      const imgHeight = (canvas.height * contentWidth) / canvas.width;
      
      // Calculate how many pages we need
      const totalPages = Math.ceil(imgHeight / contentHeight);
      
      // Calculate the height of each page slice in canvas pixels
      const pageSliceHeight = (canvas.height / imgHeight) * contentHeight;

      for (let page = 0; page < totalPages; page++) {
        if (page > 0) {
          pdf.addPage();
        }

        // Create a canvas for this page slice
        const pageCanvas = document.createElement('canvas');
        pageCanvas.width = canvas.width;
        
        // Calculate the slice height (last page might be shorter)
        const sliceStart = page * pageSliceHeight;
        const sliceHeight = Math.min(pageSliceHeight, canvas.height - sliceStart);
        pageCanvas.height = sliceHeight;

        // Draw the slice from the original canvas
        const ctx = pageCanvas.getContext('2d');
        ctx.drawImage(
          canvas,
          0, sliceStart,           // Source x, y
          canvas.width, sliceHeight, // Source width, height
          0, 0,                     // Destination x, y
          canvas.width, sliceHeight  // Destination width, height
        );

        // Calculate the actual height in mm for this slice
        const sliceHeightMM = (sliceHeight / canvas.height) * imgHeight;

        // Add this slice to the PDF
        const sliceImgData = pageCanvas.toDataURL('image/png');
        pdf.addImage(
          sliceImgData,
          'PNG',
          margin,
          margin,
          imgWidth,
          sliceHeightMM
        );
      }

      pdf.save(`${currentDoc.title}.pdf`);
      showToast?.('PDF exported successfully', 'success', 2000);
    } catch (error) {
      console.error('PDF export error:', error);
      showToast?.('Failed to export PDF', 'error', 2000);
    }
  };

  // Export document as DOCX with comprehensive content handling
  const handleExportDocx = async () => {
    if (!currentDoc) return;

    try {
      showToast?.('Generating DOCX...', 'loading', 0);

      const editorElement = document.querySelector('.tiptap-editor .ProseMirror');
      if (!editorElement) {
        throw new Error('Editor not found');
      }

      const children = [];
      
      // Process all direct children of the editor
      const processChildren = (parent) => {
        for (const node of parent.childNodes) {
          const element = processElement(node);
          if (element) {
            if (Array.isArray(element)) {
              children.push(...element);
            } else {
              children.push(element);
            }
          }
        }
      };

      // Process a single element
      const processElement = (node) => {
        if (node.nodeType === Node.TEXT_NODE) {
          return null; // Text nodes are handled by their parent
        }

        if (node.nodeType !== Node.ELEMENT_NODE) {
          return null;
        }

        const tagName = node.tagName?.toLowerCase();

        // Headings
        if (['h1', 'h2', 'h3', 'h4', 'h5', 'h6'].includes(tagName)) {
          const level = parseInt(tagName.charAt(1));
          const headingLevels = {
            1: HeadingLevel.HEADING_1,
            2: HeadingLevel.HEADING_2,
            3: HeadingLevel.HEADING_3,
            4: HeadingLevel.HEADING_4,
            5: HeadingLevel.HEADING_5,
            6: HeadingLevel.HEADING_6,
          };
          return new Paragraph({
            children: getTextRuns(node),
            heading: headingLevels[level],
            spacing: { before: 240, after: 120 },
          });
        }

        // Paragraphs
        if (tagName === 'p') {
          const textRuns = getTextRuns(node);
          if (textRuns.length === 0) {
            return new Paragraph({ children: [new TextRun('')] });
          }
          
          // Check for alignment
          const style = node.getAttribute('style') || '';
          let alignment = AlignmentType.LEFT;
          if (style.includes('text-align: center')) alignment = AlignmentType.CENTER;
          if (style.includes('text-align: right')) alignment = AlignmentType.RIGHT;
          if (style.includes('text-align: justify')) alignment = AlignmentType.JUSTIFIED;

          return new Paragraph({
            children: textRuns,
            alignment,
            spacing: { after: 120 },
          });
        }

        // Bullet lists
        if (tagName === 'ul') {
          const items = [];
          for (const li of node.querySelectorAll(':scope > li')) {
            items.push(new Paragraph({
              children: getTextRuns(li),
              bullet: { level: 0 },
              spacing: { after: 60 },
            }));
          }
          return items;
        }

        // Numbered lists
        if (tagName === 'ol') {
          const items = [];
          let num = 1;
          for (const li of node.querySelectorAll(':scope > li')) {
            items.push(new Paragraph({
              children: [
                new TextRun({ text: `${num}. ` }),
                ...getTextRuns(li),
              ],
              spacing: { after: 60 },
            }));
            num++;
          }
          return items;
        }

        // Code blocks
        if (tagName === 'pre') {
          const codeContent = node.textContent || '';
          const lines = codeContent.split('\n');
          const codeParas = [];
          
          // Add a visual separator before code
          codeParas.push(new Paragraph({
            children: [new TextRun({ text: '─'.repeat(40), color: '999999' })],
            spacing: { before: 120 },
          }));
          
          for (const line of lines) {
            codeParas.push(new Paragraph({
              children: [
                new TextRun({
                  text: line || ' ',
                  font: 'Courier New',
                  size: 20, // 10pt
                  color: '2d2d2d',
                }),
              ],
              shading: { fill: 'f5f5f5' },
              spacing: { after: 0 },
            }));
          }
          
          // Add a visual separator after code
          codeParas.push(new Paragraph({
            children: [new TextRun({ text: '─'.repeat(40), color: '999999' })],
            spacing: { after: 120 },
          }));
          
          return codeParas;
        }

        // Blockquotes
        if (tagName === 'blockquote') {
          return new Paragraph({
            children: getTextRuns(node),
            indent: { left: 720 }, // 0.5 inch
            border: {
              left: { style: BorderStyle.SINGLE, size: 24, color: '999999' },
            },
            spacing: { before: 120, after: 120 },
          });
        }

        // Horizontal rule
        if (tagName === 'hr') {
          return new Paragraph({
            children: [new TextRun({ text: '─'.repeat(50), color: 'cccccc' })],
            alignment: AlignmentType.CENTER,
            spacing: { before: 120, after: 120 },
          });
        }

        // Tables
        if (tagName === 'table') {
          const rows = [];
          for (const tr of node.querySelectorAll('tr')) {
            const cells = [];
            for (const td of tr.querySelectorAll('td, th')) {
              cells.push(
                new TableCell({
                  children: [new Paragraph({ children: getTextRuns(td) })],
                  shading: td.tagName === 'TH' ? { fill: 'f0f0f0' } : undefined,
                })
              );
            }
            if (cells.length > 0) {
              rows.push(new TableRow({ children: cells }));
            }
          }
          if (rows.length > 0) {
            return new Table({
              rows,
              width: { size: 100, type: WidthType.PERCENTAGE },
            });
          }
          return null;
        }

        // Images - add placeholder
        if (tagName === 'img') {
          return new Paragraph({
            children: [new TextRun({ text: '[Image]', italics: true, color: '666666' })],
            spacing: { before: 120, after: 120 },
          });
        }

        // Generic div or other containers - process children
        if (['div', 'section', 'article', 'span'].includes(tagName)) {
          const results = [];
          for (const child of node.childNodes) {
            const processed = processElement(child);
            if (processed) {
              if (Array.isArray(processed)) {
                results.push(...processed);
              } else {
                results.push(processed);
              }
            }
          }
          return results.length > 0 ? results : null;
        }

        return null;
      };

      // Get text runs with formatting from an element
      const getTextRuns = (element) => {
        const runs = [];
        
        const processNode = (node, inheritedStyles = {}) => {
          if (node.nodeType === Node.TEXT_NODE) {
            const text = node.textContent;
            if (text) {
              runs.push(new TextRun({
                text,
                bold: inheritedStyles.bold,
                italics: inheritedStyles.italics,
                underline: inheritedStyles.underline ? {} : undefined,
                strike: inheritedStyles.strike,
                color: inheritedStyles.color,
                font: inheritedStyles.font,
                size: inheritedStyles.size,
              }));
            }
            return;
          }

          if (node.nodeType !== Node.ELEMENT_NODE) return;

          const tagName = node.tagName?.toLowerCase();
          const styles = { ...inheritedStyles };

          // Detect formatting
          if (tagName === 'strong' || tagName === 'b') styles.bold = true;
          if (tagName === 'em' || tagName === 'i') styles.italics = true;
          if (tagName === 'u') styles.underline = true;
          if (tagName === 's' || tagName === 'strike' || tagName === 'del') styles.strike = true;
          if (tagName === 'code') {
            styles.font = 'Courier New';
            styles.size = 20;
          }

          // Check inline styles
          const style = node.getAttribute('style') || '';
          if (style.includes('font-weight: bold') || style.includes('font-weight: 700')) {
            styles.bold = true;
          }
          if (style.includes('font-style: italic')) {
            styles.italics = true;
          }
          if (style.includes('text-decoration') && style.includes('underline')) {
            styles.underline = true;
          }
          if (style.includes('text-decoration') && style.includes('line-through')) {
            styles.strike = true;
          }

          // Check for color
          const colorMatch = style.match(/color:\s*([^;]+)/);
          if (colorMatch) {
            const color = colorMatch[1].trim();
            if (color.startsWith('#')) {
              styles.color = color.replace('#', '');
            }
          }

          // Process children
          for (const child of node.childNodes) {
            processNode(child, styles);
          }
        };

        for (const child of element.childNodes) {
          processNode(child, {});
        }

        return runs.length > 0 ? runs : [new TextRun('')];
      };

      // Process the editor content
      processChildren(editorElement);

      // If no content, add empty paragraph
      if (children.length === 0) {
        children.push(new Paragraph({ children: [new TextRun('')] }));
      }

      const doc = new Document({
        sections: [
          {
            properties: {
              page: {
                margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 },
              },
            },
            children,
          },
        ],
      });

      const blob = await Packer.toBlob(doc);
      saveAs(blob, `${currentDoc.title}.docx`);
      showToast?.('DOCX exported successfully', 'success', 2000);
    } catch (error) {
      console.error('DOCX export error:', error);
      showToast?.('Failed to export DOCX', 'error', 2000);
    }
  };

  // Handle file import
  const handleImport = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const content = e.target.result;
        let proseMirrorContent;

        const fileName = file.name.replace(/\.(json|txt|md)$/, '');

        if (file.name.endsWith('.json')) {
          proseMirrorContent = JSON.parse(content);
        } else {
          proseMirrorContent = {
            type: 'doc',
            content: [
              {
                type: 'paragraph',
                content: content ? [{ type: 'text', text: content }] : [],
              },
            ],
          };
        }

        onFileUpload?.(fileName, proseMirrorContent);
      } catch (error) {
        console.error('Import error:', error);
        showToast?.('Failed to import file', 'error', 2000);
      }
    };
    reader.readAsText(file);
    event.target.value = '';
  };

  // Export document as JSON (preserves all formatting)
  const handleExportJSON = () => {
    if (!currentDoc) return;

    try {
      const editorElement = document.querySelector('.tiptap-editor .ProseMirror');
      if (!editorElement) {
        throw new Error('Editor not found');
      }

      // Get the current document content (already stored as JSON)
      const content = currentDoc.content;
      const jsonContent = typeof content === 'string' ? content : JSON.stringify(content, null, 2);
      
      const blob = new Blob([jsonContent], { type: 'application/json' });
      saveAs(blob, `${currentDoc.title}.json`);
      showToast?.('JSON exported successfully', 'success', 2000);
    } catch (error) {
      console.error('JSON export error:', error);
      showToast?.('Failed to export JSON', 'error', 2000);
    }
  };

  // Export as plain text
  const handleExportTxt = () => {
    if (!currentDoc) return;

    try {
      const editorElement = document.querySelector('.tiptap-editor .ProseMirror');
      if (!editorElement) {
        throw new Error('Editor not found');
      }

      const textContent = editorElement.innerText;
      const blob = new Blob([textContent], { type: 'text/plain' });
      saveAs(blob, `${currentDoc.title}.txt`);
      showToast?.('Text exported successfully', 'success', 2000);
    } catch (error) {
      console.error('Text export error:', error);
      showToast?.('Failed to export text', 'error', 2000);
    }
  };

  return (
    <div>
      <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
        File
      </div>
      <div className="grid grid-cols-2 gap-1.5">
        <label
          className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)] cursor-pointer flex items-center justify-center gap-1.5`}
          title="Import File (Creates new document)"
        >
          <Upload size={14} strokeWidth={2} />
          <span className="text-xs">Import</span>
          <input
            type="file"
            accept=".json,.txt,.md"
            onChange={handleImport}
            className="hidden"
          />
        </label>
        <button
          onClick={handleExportPDF}
          className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)] flex items-center justify-center gap-1.5`}
          title="Export to PDF"
          disabled={!currentDoc}
        >
          <Download size={14} strokeWidth={2} />
          <span className="text-xs">PDF</span>
        </button>
        <button
          onClick={handleExportDocx}
          className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)] flex items-center justify-center gap-1.5`}
          title="Export to DOCX"
          disabled={!currentDoc}
        >
          <Download size={14} strokeWidth={2} />
          <span className="text-xs">DOCX</span>
        </button>
        <button
          onClick={handleExportJSON}
          className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)] flex items-center justify-center gap-1.5`}
          title="Export to JSON (preserves all formatting)"
          disabled={!currentDoc}
        >
          <Download size={14} strokeWidth={2} />
          <span className="text-xs">JSON</span>
        </button>
        <button
          onClick={handleExportTxt}
          className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)] flex items-center justify-center gap-1.5 col-span-2`}
          title="Export as Plain Text"
          disabled={!currentDoc}
        >
          <Download size={14} strokeWidth={2} />
          <span className="text-xs">Plain Text</span>
        </button>
      </div>
    </div>
  );
}
