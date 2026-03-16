import React, { useState, useRef, useEffect } from 'react';
import jsPDF from 'jspdf';
import html2canvas from 'html2canvas';
import { Document, Packer, Paragraph, TextRun, HeadingLevel } from 'docx';
import { saveAs } from 'file-saver';
import DesktopToolbar from './toolbar/DesktopToolbar';
import MobileToolbar from './toolbar/MobileToolbar';
import {
  ColorPickerModal,
  FontFamilyModal,
  FontSizeModal,
  LinkDialog,
} from './toolbar/modals';

export default function Toolbar({
  editor,
  currentDoc,
  glassClass,
  hoverClass,
  onFileUpload,
  showToast,
  isCollapsed,
  onToggleCollapse,
  mobileOnly = false,
}) {
  const [showColorPicker, setShowColorPicker] = useState(false);
  const [showFontFamilyDialog, setShowFontFamilyDialog] = useState(false);
  const [showFontSizeDialog, setShowFontSizeDialog] = useState(false);
  const [showLinkDialog, setShowLinkDialog] = useState(false);
  const [isRecording, setIsRecording] = useState(false);
  const recognitionRef = useRef(null);

  // Initialize voice recognition for mobile
  useEffect(() => {
    if (!editor) return;

    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      const SpeechRecognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;

      if (!recognitionRef.current) {
        const recognitionInstance = new SpeechRecognition();
        recognitionInstance.continuous = true;
        recognitionInstance.interimResults = true;
        recognitionInstance.lang = 'en-US';

        recognitionInstance.onresult = (event) => {
          let finalTranscript = '';
          for (let i = event.resultIndex; i < event.results.length; i++) {
            if (event.results[i].isFinal) {
              finalTranscript += event.results[i][0].transcript + ' ';
            }
          }
          if (finalTranscript) {
            editor.chain().focus().insertContent(finalTranscript).run();
          }
        };

        recognitionInstance.onerror = () => {
          recognitionRef.current.shouldContinue = false;
          setIsRecording(false);
        };

        recognitionInstance.onend = () => {
          if (recognitionRef.current?.shouldContinue) {
            try {
              recognitionInstance.start();
            } catch (err) {
              console.error('Error restarting:', err);
            }
          } else {
            setIsRecording(false);
          }
        };

        recognitionRef.current = recognitionInstance;
        recognitionRef.current.shouldContinue = false;
      }
    }
  }, [editor]);

  // If no editor, show loading state
  if (!editor) {
    return (
      <div
        className={`${glassClass} rounded-lg border border-[var(--color-border-light)] p-4 text-center text-[var(--color-text-muted)]`}
      >
        <p className="text-sm">Loading toolbar...</p>
      </div>
    );
  }

  // Show link dialog (only if text is selected)
  const handleShowLinkDialog = () => {
    const { from, to } = editor.state.selection;
    const selectedText = editor.state.doc.textBetween(from, to, ' ');

    if (!selectedText.trim()) {
      showToast?.('Please select text first', 'info', 2000);
      return;
    }

    setShowLinkDialog(true);
  };

  // Handle media upload
  const handleMediaUpload = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      const base64 = e.target.result;

      if (file.type.startsWith('image/')) {
        const imgHtml = `<img src="${base64}" alt="${file.name}" class="resizable-image" />`;
        editor.chain().focus().insertContent(imgHtml).run();
        showToast?.('Image uploaded', 'success', 1500);
      } else if (file.type.startsWith('video/')) {
        const videoHtml = `<video controls src="${base64}" style="max-width: 100%; border-radius: 5px;"></video>`;
        editor.chain().focus().insertContent(videoHtml).run();
        showToast?.('Video uploaded', 'success', 1500);
      } else {
        const fileLink = `<a href="${base64}" download="${file.name}">${file.name}</a>`;
        editor.chain().focus().insertContent(fileLink).run();
        showToast?.('File uploaded', 'success', 1500);
      }
    };

    reader.onerror = () => {
      showToast?.('Failed to read file', 'error', 2000);
    };

    reader.readAsDataURL(file);
    event.target.value = '';
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

  // Export as PDF with proper multi-page support
  const handleExportPDF = async () => {
    if (!currentDoc) return;

    try {
      showToast?.('Generating PDF...', 'loading', 0);

      const editorElement = document.querySelector('.tiptap-editor .ProseMirror');
      if (!editorElement) throw new Error('Editor not found');

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

  // Export as DOCX with comprehensive content handling
  const handleExportDocx = async () => {
    if (!currentDoc) return;

    try {
      showToast?.('Generating DOCX...', 'loading', 0);

      const editorElement = document.querySelector('.tiptap-editor .ProseMirror');
      if (!editorElement) throw new Error('Editor not found');

      const children = [];

      // Get text runs with formatting
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
              }));
            }
            return;
          }

          if (node.nodeType !== Node.ELEMENT_NODE) return;

          const tagName = node.tagName?.toLowerCase();
          const styles = { ...inheritedStyles };

          if (tagName === 'strong' || tagName === 'b') styles.bold = true;
          if (tagName === 'em' || tagName === 'i') styles.italics = true;
          if (tagName === 'u') styles.underline = true;
          if (tagName === 's' || tagName === 'del') styles.strike = true;

          for (const child of node.childNodes) {
            processNode(child, styles);
          }
        };

        for (const child of element.childNodes) {
          processNode(child, {});
        }

        return runs.length > 0 ? runs : [new TextRun('')];
      };

      // Process all direct children
      for (const node of editorElement.childNodes) {
        if (node.nodeType !== Node.ELEMENT_NODE) continue;

        const tagName = node.tagName?.toLowerCase();

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
          children.push(new Paragraph({
            children: getTextRuns(node),
            heading: headingLevels[level],
            spacing: { before: 240, after: 120 },
          }));
        } else if (tagName === 'p') {
          children.push(new Paragraph({
            children: getTextRuns(node),
            spacing: { after: 120 },
          }));
        } else if (tagName === 'ul') {
          for (const li of node.querySelectorAll(':scope > li')) {
            children.push(new Paragraph({
              children: getTextRuns(li),
              bullet: { level: 0 },
              spacing: { after: 60 },
            }));
          }
        } else if (tagName === 'ol') {
          let num = 1;
          for (const li of node.querySelectorAll(':scope > li')) {
            children.push(new Paragraph({
              children: [new TextRun({ text: `${num}. ` }), ...getTextRuns(li)],
              spacing: { after: 60 },
            }));
            num++;
          }
        } else if (tagName === 'pre') {
          const codeContent = node.textContent || '';
          for (const line of codeContent.split('\n')) {
            children.push(new Paragraph({
              children: [new TextRun({ text: line || ' ', font: 'Courier New', size: 20 })],
              spacing: { after: 0 },
            }));
          }
        } else if (tagName === 'blockquote') {
          children.push(new Paragraph({
            children: getTextRuns(node),
            indent: { left: 720 },
            spacing: { before: 120, after: 120 },
          }));
        }
      }

      if (children.length === 0) {
        children.push(new Paragraph({ children: [new TextRun('')] }));
      }

      const doc = new Document({
        sections: [{
          properties: { page: { margin: { top: 1440, right: 1440, bottom: 1440, left: 1440 } } },
          children,
        }],
      });

      const blob = await Packer.toBlob(doc);
      saveAs(blob, `${currentDoc.title}.docx`);
      showToast?.('DOCX exported successfully', 'success', 2000);
    } catch (error) {
      console.error('DOCX export error:', error);
      showToast?.('Failed to export DOCX', 'error', 2000);
    }
  };

  // Voice recording toggle for mobile
  const handleVoiceRecording = () => {
    const recognition = recognitionRef.current;

    if (!recognition) {
      showToast?.('Speech recognition not supported', 'error', 3000);
      return;
    }

    if (isRecording) {
      recognition.shouldContinue = false;
      recognition.abort();
      setIsRecording(false);
      showToast?.('Voice stopped', 'success', 1000);
        } else {
      recognition.shouldContinue = true;
      recognition.start();
      setIsRecording(true);
      showToast?.('Listening... Speak now', 'info', 2000);
    }
  };

  // Insert table
  const handleInsertTable = () => {
    editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run();
    showToast?.('Table inserted', 'success', 1500);
  };

  return (
    <>
      {/* Desktop Toolbar - hidden when mobileOnly */}
      {!mobileOnly && (
        <DesktopToolbar
          editor={editor}
          currentDoc={currentDoc}
          glassClass={glassClass}
          hoverClass={hoverClass}
          isCollapsed={isCollapsed}
          onToggleCollapse={onToggleCollapse}
          onShowColorPicker={() => setShowColorPicker(true)}
          onShowFontFamilyDialog={() => setShowFontFamilyDialog(true)}
          onShowFontSizeDialog={() => setShowFontSizeDialog(true)}
          onShowLinkDialog={handleShowLinkDialog}
          onMediaUpload={handleMediaUpload}
          onFileUpload={onFileUpload}
          showToast={showToast}
        />
      )}

      {/* Mobile Toolbar - shown when mobileOnly or on mobile screens */}
      {mobileOnly && (
        <MobileToolbar
          editor={editor}
          glassClass={glassClass}
          hoverClass={hoverClass}
          currentDoc={currentDoc}
          isRecording={isRecording}
          onVoiceRecording={handleVoiceRecording}
          onShowColorPicker={() => setShowColorPicker(true)}
          onShowFontFamilyDialog={() => setShowFontFamilyDialog(true)}
          onShowFontSizeDialog={() => setShowFontSizeDialog(true)}
          onShowLinkDialog={handleShowLinkDialog}
          onMediaUpload={handleMediaUpload}
          onImport={handleImport}
          onExportPDF={handleExportPDF}
          onExportDocx={handleExportDocx}
          onInsertTable={handleInsertTable}
        />
      )}

      {/* Modals */}
      <ColorPickerModal
        isOpen={showColorPicker}
        onClose={() => setShowColorPicker(false)}
        editor={editor}
        glassClass={glassClass}
        hoverClass={hoverClass}
        showToast={showToast}
      />

      <FontFamilyModal
        isOpen={showFontFamilyDialog}
        onClose={() => setShowFontFamilyDialog(false)}
        editor={editor}
        glassClass={glassClass}
        hoverClass={hoverClass}
        showToast={showToast}
      />

      <FontSizeModal
        isOpen={showFontSizeDialog}
        onClose={() => setShowFontSizeDialog(false)}
        editor={editor}
        glassClass={glassClass}
        hoverClass={hoverClass}
        showToast={showToast}
      />

      <LinkDialog
        isOpen={showLinkDialog}
        onClose={() => setShowLinkDialog(false)}
        editor={editor}
        glassClass={glassClass}
        hoverClass={hoverClass}
        showToast={showToast}
      />
    </>
  );
}
