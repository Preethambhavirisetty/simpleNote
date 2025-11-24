import React, { useState, useRef } from 'react';
import {
  Bold,
  Italic,
  Underline,
  AlignLeft,
  AlignCenter,
  AlignRight,
  List,
  ListOrdered,
  Type,
  Image,
  Link,
  Square,
  Circle,
  Minus,
  Mic,
  Palette,
  Table,
  FileText,
  Download,
  Upload,
  Video,
  LinkIcon,
  Eraser
} from 'lucide-react';
import html2pdf from 'html2pdf.js';
import mammoth from 'mammoth';

export default function Toolbar({ currentDoc, glassClass, hoverClass, updateDocContent, onFileUpload, showToast, isCollapsed, onToggleCollapse }) {
  const [fontSize, setFontSize] = useState('16');
  const [textColor, setTextColor] = useState('#000000');
  const [isRecording, setIsRecording] = useState(false);
  const [showFontSize, setShowFontSize] = useState(false);
  const [recognition, setRecognition] = useState(null);
  const [transcript, setTranscript] = useState('');
  const [showColorPicker, setShowColorPicker] = useState(false);
  const [showLinkDialog, setShowLinkDialog] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [isExporting, setIsExporting] = useState(false);
  const [showTableDialog, setShowTableDialog] = useState(false);
  
  const fileInputRef = useRef(null);
  const imageInputRef = useRef(null);
  const videoInputRef = useRef(null);

  // Initialize speech recognition on mount
  React.useEffect(() => {
    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
      const recognitionInstance = new SpeechRecognition();
      
      recognitionInstance.continuous = true;
      recognitionInstance.interimResults = true;
      recognitionInstance.lang = 'en-US';

      recognitionInstance.onresult = (event) => {
        let interimTranscript = '';
        let finalTranscript = '';

        for (let i = event.resultIndex; i < event.results.length; i++) {
          const transcript = event.results[i][0].transcript;
          if (event.results[i].isFinal) {
            finalTranscript += transcript + ' ';
          } else {
            interimTranscript += transcript;
          }
        }

        setTranscript(interimTranscript || finalTranscript);

        if (finalTranscript) {
          // Insert text at cursor position in editor
          const editor = document.querySelector('[contenteditable]');
          if (editor) {
            editor.focus();
            document.execCommand('insertText', false, finalTranscript);
            setTimeout(() => {
              const content = editor.innerHTML;
              if (content) updateDocContent(content);
            }, 0);
          }
        }
      };

      recognitionInstance.onerror = (event) => {
        console.error('Speech recognition error:', event.error);
        setIsRecording(false);
        setTranscript('');
      };

      recognitionInstance.onend = () => {
        setIsRecording(false);
        setTranscript('');
      };

      setRecognition(recognitionInstance);
    }
  }, [updateDocContent]);

  const execCommand = (command, value = null) => {
    document.execCommand(command, false, value);
    document.querySelector('[contenteditable]')?.focus();
    setTimeout(() => {
      const content = document.querySelector('[contenteditable]')?.innerHTML;
      if (content) updateDocContent(content);
    }, 0);
  };

  const insertShape = (shape) => {
    const shapeHTML = {
      square: '<span style="display:inline-block;width:50px;height:50px;border:2px solid #000;margin:5px;border-radius:2px;"></span>',
      circle: '<span style="display:inline-block;width:50px;height:50px;border:2px solid #000;border-radius:50%;margin:5px;"></span>',
      line: '<hr style="border:1px solid #000;margin:10px 0;">'
    };
    document.execCommand('insertHTML', false, shapeHTML[shape]);
    const content = document.querySelector('[contenteditable]')?.innerHTML;
    if (content) updateDocContent(content);
  };

  const handleVoiceRecording = () => {
    if (!recognition) {
      alert('Speech recognition is not supported in your browser. Please use Chrome, Edge, or Safari.');
      return;
    }

    if (isRecording) {
      recognition.stop();
      setIsRecording(false);
      setTranscript('');
    } else {
      recognition.start();
      setIsRecording(true);
    }
  };

  const insertTable = (rows, cols) => {
    const isDark = document.documentElement.classList.contains('dark');
    
    // Dark mode uses gray borders, light mode uses lighter borders
    const headerBorder = isDark ? '#6b7280' : '#e5e5e5';
    const cellBorder = isDark ? '#4b5563' : '#e5e5e5';
    const headerBg = isDark ? '#1f2937' : '#f5f5f5';
    const cellBg = isDark ? '#111827' : '#ffffff';
    const headerText = isDark ? '#e5e7eb' : '#111827';
    const cellText = isDark ? '#d1d5db' : '#000000';
    
    let tableHTML = `<table style="border-collapse: separate; border-spacing: 0; width: 100%; margin: 20px 0; box-shadow: 0 4px 12px rgba(0,0,0,${isDark ? '0.5' : '0.15'}); border-radius: 8px; overflow: hidden; table-layout: fixed;"><tbody>`;
    
    for (let i = 0; i < parseInt(rows); i++) {
      tableHTML += '<tr>';
      for (let j = 0; j < parseInt(cols); j++) {
        const isHeader = i === 0;
        const isFirstCol = j === 0;
        const isLastCol = j === parseInt(cols) - 1;
        const isLastRow = i === parseInt(rows) - 1;
        
        let extraStyle = '';
        if (isHeader && isFirstCol) extraStyle += 'border-top-left-radius: 8px;';
        if (isHeader && isLastCol) extraStyle += 'border-top-right-radius: 8px;';
        if (isLastRow && isFirstCol) extraStyle += 'border-bottom-left-radius: 8px;';
        if (isLastRow && isLastCol) extraStyle += 'border-bottom-right-radius: 8px;';
        
        const style = isHeader 
          ? `border: 2px solid ${headerBorder}; padding: 14px 16px; background: ${headerBg}; color: ${headerText}; font-weight: 700; text-align: left; font-size: 13px; letter-spacing: 0.5px; text-transform: uppercase; vertical-align: top; line-height: 1.5; ${extraStyle}`
          : `border: 1px solid ${cellBorder}; padding: 12px 16px; background: ${cellBg}; color: ${cellText}; min-width: 100px; vertical-align: top; line-height: 1.6; font-size: 14px; ${extraStyle}`;
        const tag = isHeader ? 'th' : 'td';
        tableHTML += `<${tag} style="${style}" contenteditable="true">${isHeader ? `Column ${j + 1}` : ''}</${tag}>`;
      }
      tableHTML += '</tr>';
    }
    tableHTML += '</tbody></table><p><br></p>';
    
    document.execCommand('insertHTML', false, tableHTML);
    const content = document.querySelector('[contenteditable]')?.innerHTML;
    if (content) updateDocContent(content);
    setShowTableDialog(false);
    
    if (showToast) {
      showToast(`Table with ${rows}×${cols} cells created!`, 'success');
    }
  };

  const handleFileUpload = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsUploading(true);
    
    try {
      let content = '';
      let title = file.name.replace(/\.(txt|docx)$/, '');

      if (file.name.endsWith('.txt')) {
        const text = await file.text();
        content = text.replace(/\n/g, '<br>');
      } else if (file.name.endsWith('.docx')) {
        const arrayBuffer = await file.arrayBuffer();
        const result = await mammoth.convertToHtml({ arrayBuffer });
        content = result.value;
      }

      // Create new document with file content
      if (onFileUpload) {
        await onFileUpload(title, content);
      }
    } catch (error) {
      console.error('File upload error:', error);
      if (showToast) {
        showToast('Failed to upload file. Please try again.', 'error');
      }
    } finally {
      setIsUploading(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = '';
      }
    }
  };

  const handleImageUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (showToast) {
      showToast('Uploading image...', 'loading', 0);
    }

    const reader = new FileReader();
    reader.onload = (event) => {
      const img = `<img src="${event.target.result}" style="max-width: 100%; height: auto; margin: 10px 0;" />`;
      document.execCommand('insertHTML', false, img);
      const content = document.querySelector('[contenteditable]')?.innerHTML;
      if (content) updateDocContent(content);
      
      if (showToast) {
        showToast('Image inserted successfully!', 'success');
      }
    };
    reader.onerror = () => {
      if (showToast) {
        showToast('Failed to upload image', 'error');
      }
    };
    reader.readAsDataURL(file);
    
    if (imageInputRef.current) {
      imageInputRef.current.value = '';
    }
  };

  const handleVideoUpload = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (showToast) {
      showToast('Uploading video...', 'loading', 0);
    }

    const reader = new FileReader();
    reader.onload = (event) => {
      const video = `<video controls style="max-width: 100%; margin: 10px 0;"><source src="${event.target.result}" type="${file.type}"></video>`;
      document.execCommand('insertHTML', false, video);
      const content = document.querySelector('[contenteditable]')?.innerHTML;
      if (content) updateDocContent(content);
      
      if (showToast) {
        showToast('Video inserted successfully!', 'success');
      }
    };
    reader.onerror = () => {
      if (showToast) {
        showToast('Failed to upload video', 'error');
      }
    };
    reader.readAsDataURL(file);
    
    if (videoInputRef.current) {
      videoInputRef.current.value = '';
    }
  };

  const exportToPDF = async () => {
    const editor = document.querySelector('[contenteditable]');
    if (!editor) return;

    setIsExporting(true);
    if (showToast) {
      showToast('Generating PDF...', 'loading', 0);
    }

    try {
      // Use document title for filename, sanitize it
      const docTitle = currentDoc?.title || 'document';
      const sanitizedTitle = docTitle
        .replace(/[^a-z0-9]/gi, '_')
        .toLowerCase()
        .replace(/_+/g, '_')
        .replace(/^_|_$/g, '');
      
      const opt = {
        margin: 0.2,  // Reduced from 0.4 to 0.2 inches
        filename: `${sanitizedTitle}.pdf`,
        image: { type: 'jpeg', quality: 0.98 },
        html2canvas: { scale: 2, useCORS: true },
        jsPDF: { unit: 'in', format: 'letter', orientation: 'portrait' }
      };

      await html2pdf().set(opt).from(editor).save();
      
      if (showToast) {
        showToast(`"${currentDoc?.title || 'Document'}" exported to PDF!`, 'success');
      }
    } catch (error) {
      console.error('PDF export error:', error);
      if (showToast) {
        showToast('Failed to export PDF. Please try again.', 'error');
      }
    } finally {
      setIsExporting(false);
    }
  };

  const clearFormatting = () => {
    const selection = window.getSelection();
    if (!selection.rangeCount) return;
    
    const selectedText = selection.toString();
    if (selectedText) {
      // Clear formatting from selected text
      document.execCommand('removeFormat', false, null);
      document.execCommand('unlink', false, null);
      const content = document.querySelector('[contenteditable]')?.innerHTML;
      if (content) updateDocContent(content);
      
      if (showToast) {
        showToast('Formatting cleared', 'success', 2000);
      }
    } else {
      if (showToast) {
        showToast('Select text first to clear formatting', 'info', 2000);
      }
    }
  };

  const handleLinkInsert = () => {
    const selection = window.getSelection();
    const selectedText = selection.toString().trim();
    
    if (selectedText) {
      // Selected text exists, show dialog to add URL
      setShowLinkDialog(true);
    } else {
      // No selection, prompt for both text and URL
      const displayText = prompt('Enter link text:');
      if (displayText) {
        const url = prompt('Enter URL:');
        if (url) {
          const link = `<a href="${url}" target="_blank" style="color: #0066cc; text-decoration: underline;">${displayText}</a>`;
          document.execCommand('insertHTML', false, link);
          const content = document.querySelector('[contenteditable]')?.innerHTML;
          if (content) updateDocContent(content);
          if (showToast) {
            showToast('Link inserted!', 'success', 2000);
          }
        }
      }
    }
  };

  const insertLink = (displayText, url) => {
    const link = `<a href="${url}" target="_blank" style="color: #0066cc; text-decoration: underline;">${displayText}</a>`;
    document.execCommand('insertHTML', false, link);
    const content = document.querySelector('[contenteditable]')?.innerHTML;
    if (content) updateDocContent(content);
    setShowLinkDialog(false);
    if (showToast) {
      showToast('Link created!', 'success', 2000);
    }
  };

  return (
    <>
      <div className={`${glassClass} rounded-lg border-l-2 border-[var(--color-accent-primary)] w-full md:w-48 overflow-y-auto md:max-h-full max-h-40`}>
        <div className="p-3">
        {/* Hidden file inputs */}
        <input
          ref={fileInputRef}
          type="file"
          accept=".txt,.docx"
          onChange={handleFileUpload}
          className="hidden"
        />
        <input
          ref={imageInputRef}
          type="file"
          accept="image/*"
          onChange={handleImageUpload}
          className="hidden"
        />
        <input
          ref={videoInputRef}
          type="file"
          accept="video/*"
          onChange={handleVideoUpload}
          className="hidden"
        />
        {/* Voice */}
        <div className="mb-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
            Voice
          </div>
          <button
            onClick={handleVoiceRecording}
            className={`w-full p-2 rounded transition-all border ${
              isRecording
                ? 'bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-[var(--color-bg-primary)] animate-pulse'
                : `${hoverClass} border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`
            }`}
            title={isRecording ? "Stop Recording" : "Start Voice Recording"}
          >
            <Mic size={14} strokeWidth={2} className="mx-auto" />
          </button>
          {isRecording && (
            <div className="mt-2 text-center">
              <div className="flex items-center justify-center gap-1 mb-1">
                <div className="w-1 h-1 bg-[var(--color-accent-primary)] rounded-full animate-pulse"></div>
                <div className="w-1 h-1 bg-[var(--color-accent-primary)] rounded-full animate-pulse" style={{animationDelay: '0.2s'}}></div>
                <div className="w-1 h-1 bg-[var(--color-accent-primary)] rounded-full animate-pulse" style={{animationDelay: '0.4s'}}></div>
              </div>
              <p className="text-[9px] font-bold uppercase tracking-wider text-[var(--color-accent-primary)]">
                Listening...
              </p>
              {transcript && (
                <p className="text-[8px] text-[var(--color-text-muted)] mt-1 line-clamp-2">
                  {transcript}
                </p>
              )}
            </div>
          )}
        </div>

        {/* Text Style */}
        <div className="mb-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
            Style
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            <button
              onClick={() => execCommand('bold')}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Bold"
            >
              <Bold size={14} strokeWidth={2} className="mx-auto" />
            </button>
            <button
              onClick={() => execCommand('italic')}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Italic"
            >
              <Italic size={14} strokeWidth={2} className="mx-auto" />
            </button>
            <button
              onClick={() => execCommand('underline')}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Underline"
            >
              <Underline size={14} strokeWidth={2} className="mx-auto" />
            </button>
            <button
              onClick={clearFormatting}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Clear Formatting"
            >
              <Eraser size={14} strokeWidth={2} className="mx-auto" />
            </button>
          </div>
        </div>

        {/* Alignment */}
        <div className="mb-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
            Align
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            <button
              onClick={() => execCommand('justifyLeft')}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Align Left"
            >
              <AlignLeft size={14} strokeWidth={2} className="mx-auto" />
            </button>
            <button
              onClick={() => execCommand('justifyCenter')}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Center"
            >
              <AlignCenter size={14} strokeWidth={2} className="mx-auto" />
            </button>
            <button
              onClick={() => execCommand('justifyRight')}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Align Right"
            >
              <AlignRight size={14} strokeWidth={2} className="mx-auto" />
            </button>
          </div>
        </div>

        {/* Lists */}
        <div className="mb-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
            Lists
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            <button
              onClick={() => execCommand('insertUnorderedList')}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Bullet List"
            >
              <List size={14} strokeWidth={2} className="mx-auto" />
            </button>
            <button
              onClick={() => execCommand('insertOrderedList')}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Numbered"
            >
              <ListOrdered size={14} strokeWidth={2} className="mx-auto" />
            </button>
          </div>
        </div>

        {/* Format */}
        <div className="mb-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
            Format
          </div>
          <div className="grid grid-cols-2 gap-1.5">
            {/* Font Size */}
            <div className="relative">
              <button
                onClick={() => setShowFontSize(!showFontSize)}
                className={`w-full p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
                title="Font Size"
              >
                <Type size={14} strokeWidth={2} className="mx-auto" />
              </button>
              {showFontSize && (
                <div className="absolute left-full ml-2 top-0 z-50 bg-[var(--color-bg-elevated)] border border-[var(--color-border-medium)] rounded p-1.5 shadow-xl min-w-[100px]">
                  {[12, 14, 16, 18, 20, 24, 28, 32].map(size => (
                    <button
                      key={size}
                      onClick={() => {
                        setFontSize(size.toString());
                        execCommand('fontSize', '7');
                        const fontElements = document.querySelectorAll('font[size="7"]');
                        fontElements.forEach(el => {
                          el.removeAttribute('size');
                          el.style.fontSize = size + 'px';
                        });
                        setShowFontSize(false);
                      }}
                      className={`w-full text-left px-2 py-1 rounded text-xs font-medium ${hoverClass}`}
                    >
                      {size}px
                    </button>
                  ))}
                </div>
              )}
            </div>

            {/* Text Color */}
            <div className="relative">
              <button
                onClick={() => setShowColorPicker(!showColorPicker)}
                className={`w-full p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
                title="Text Color"
              >
                <Palette size={14} strokeWidth={2} className="mx-auto" />
              </button>
              {showColorPicker && (
                <div className="fixed right-52 top-1/2 -translate-y-1/2 z-[999] bg-[var(--color-bg-elevated)] border-2 border-[var(--color-border-dark)] rounded-lg p-3 shadow-2xl"
                  style={{
                    backdropFilter: 'blur(10px)',
                    WebkitBackdropFilter: 'blur(10px)'
                  }}
                >
                  <div className="text-xs font-bold uppercase tracking-wider text-[var(--color-text-secondary)] mb-3">
                    Text Color
                  </div>
                  <input
                    type="color"
                    value={textColor}
                    onChange={(e) => {
                      setTextColor(e.target.value);
                      execCommand('foreColor', e.target.value);
                    }}
                    className="w-32 h-32 cursor-pointer rounded border-2 border-[var(--color-border-medium)]"
                  />
                  <div className="grid grid-cols-4 gap-2 mt-3">
                    {['#000000', '#ffffff', '#ff0000', '#00ff00', '#0000ff', '#ffff00', '#ff00ff', '#00ffff', '#ff6b6b', '#4ecdc4', '#45b7d1', '#f7b731'].map(color => (
                      <button
                        key={color}
                        onClick={() => {
                          setTextColor(color);
                          execCommand('foreColor', color);
                          setShowColorPicker(false);
                        }}
                        style={{ backgroundColor: color }}
                        className="w-8 h-8 rounded-md border-2 border-[var(--color-border-medium)] hover:scale-110 transition-transform shadow-md"
                      />
                    ))}
                  </div>
                  <button
                    onClick={() => setShowColorPicker(false)}
                    className={`w-full mt-3 px-3 py-2 rounded ${hoverClass} text-xs font-semibold border border-[var(--color-border-medium)]`}
                  >
                    Close
                  </button>
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Export & Import */}
        <div className="mb-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
            Files
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            <button
              onClick={() => fileInputRef.current?.click()}
              disabled={isUploading}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)] relative ${isUploading ? 'opacity-50 cursor-not-allowed' : ''}`}
              title="Import File"
            >
              {isUploading ? (
                <div className="w-3.5 h-3.5 border-2 border-[var(--color-accent-primary)] border-t-transparent rounded-full animate-spin mx-auto"></div>
              ) : (
                <Upload size={14} strokeWidth={2} className="mx-auto" />
              )}
            </button>
            <button
              onClick={exportToPDF}
              disabled={isExporting}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)] ${isExporting ? 'opacity-50 cursor-not-allowed' : ''}`}
              title="Export to PDF"
            >
              {isExporting ? (
                <div className="w-3.5 h-3.5 border-2 border-[var(--color-accent-primary)] border-t-transparent rounded-full animate-spin mx-auto"></div>
              ) : (
                <Download size={14} strokeWidth={2} className="mx-auto" />
              )}
            </button>
          </div>
        </div>

        {/* Insert */}
        <div className="mb-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
            Insert
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            <button
              onClick={() => setShowTableDialog(true)}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Table"
            >
              <Table size={14} strokeWidth={2} className="mx-auto" />
            </button>
            <button
              onClick={() => insertShape('line')}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Horizontal Line"
            >
              <Minus size={14} strokeWidth={2} className="mx-auto" />
            </button>
            <button
              onClick={handleLinkInsert}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Insert Link"
            >
              <LinkIcon size={14} strokeWidth={2} className="mx-auto" />
            </button>
            <button
              onClick={() => imageInputRef.current?.click()}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Upload Image"
            >
              <Image size={14} strokeWidth={2} className="mx-auto" />
            </button>
            <button
              onClick={() => videoInputRef.current?.click()}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Upload Video"
            >
              <Video size={14} strokeWidth={2} className="mx-auto" />
            </button>
          </div>
        </div>
      </div>
    </div>

    {/* Table Dialog */}
    {showTableDialog && (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[1000]" onClick={() => setShowTableDialog(false)}>
        <div 
          className={`${glassClass} rounded-lg p-6 min-w-[320px] border border-[var(--color-border-medium)] shadow-2xl`}
          onClick={(e) => e.stopPropagation()}
        >
          <h3 className="text-lg font-bold mb-4 text-[var(--color-text-primary)]">Insert Table</h3>
          
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-semibold mb-2 text-[var(--color-text-secondary)]">
                Rows
              </label>
              <input
                type="number"
                id="table-rows"
                min="1"
                max="50"
                defaultValue="5"
                className={`w-full px-3 py-2 rounded border border-[var(--color-border-medium)] bg-[var(--color-bg-elevated)] text-[var(--color-text-primary)] focus:outline-none focus:border-[var(--color-accent-primary)]`}
              />
              <p className="text-xs text-[var(--color-text-muted)] mt-1">Max: 50 rows</p>
            </div>
            
            <div>
              <label className="block text-sm font-semibold mb-2 text-[var(--color-text-secondary)]">
                Columns
              </label>
              <input
                type="number"
                id="table-cols"
                min="1"
                max="20"
                defaultValue="4"
                className={`w-full px-3 py-2 rounded border border-[var(--color-border-medium)] bg-[var(--color-bg-elevated)] text-[var(--color-text-primary)] focus:outline-none focus:border-[var(--color-accent-primary)]`}
              />
              <p className="text-xs text-[var(--color-text-muted)] mt-1">Max: 20 columns</p>
            </div>

            <div className="flex gap-2 pt-2">
              <button
                onClick={() => {
                  const rows = document.getElementById('table-rows').value;
                  const cols = document.getElementById('table-cols').value;
                  insertTable(rows, cols);
                }}
                className={`flex-1 px-4 py-2 rounded bg-[var(--color-accent-primary)] text-[var(--color-bg-primary)] font-semibold ${hoverClass} border border-[var(--color-accent-primary)]`}
              >
                Insert
              </button>
              <button
                onClick={() => setShowTableDialog(false)}
                className={`flex-1 px-4 py-2 rounded ${hoverClass} border border-[var(--color-border-medium)] font-semibold`}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      </div>
    )}

    {/* Link Dialog */}
    {showLinkDialog && (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-[1000]" onClick={() => setShowLinkDialog(false)}>
        <div 
          className={`${glassClass} rounded-lg p-6 min-w-[400px] border border-[var(--color-border-medium)] shadow-2xl`}
          onClick={(e) => e.stopPropagation()}
        >
          <h3 className="text-lg font-bold mb-4 text-[var(--color-text-primary)]">Insert Link</h3>
          
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-semibold mb-2 text-[var(--color-text-secondary)]">
                Display Text
              </label>
              <input
                type="text"
                id="link-text"
                defaultValue={window.getSelection().toString().trim()}
                placeholder="Link text"
                className={`w-full px-3 py-2 rounded border border-[var(--color-border-medium)] bg-[var(--color-bg-elevated)] text-[var(--color-text-primary)] focus:outline-none focus:border-[var(--color-accent-primary)]`}
              />
            </div>
            
            <div>
              <label className="block text-sm font-semibold mb-2 text-[var(--color-text-secondary)]">
                URL
              </label>
              <input
                type="url"
                id="link-url"
                placeholder="https://example.com"
                className={`w-full px-3 py-2 rounded border border-[var(--color-border-medium)] bg-[var(--color-bg-elevated)] text-[var(--color-text-primary)] focus:outline-none focus:border-[var(--color-accent-primary)]`}
              />
            </div>

            <div className="flex gap-2 pt-2">
              <button
                onClick={() => {
                  const text = document.getElementById('link-text').value;
                  const url = document.getElementById('link-url').value;
                  if (text && url) {
                    insertLink(text, url);
                  }
                }}
                className={`flex-1 px-4 py-2 rounded bg-[var(--color-accent-primary)] text-[var(--color-bg-primary)] font-semibold ${hoverClass} border border-[var(--color-accent-primary)]`}
              >
                Insert Link
              </button>
              <button
                onClick={() => setShowLinkDialog(false)}
                className={`flex-1 px-4 py-2 rounded ${hoverClass} border border-[var(--color-border-medium)] font-semibold`}
              >
                Cancel
              </button>
            </div>
          </div>
        </div>
      </div>
    )}
  </>
  );
}
