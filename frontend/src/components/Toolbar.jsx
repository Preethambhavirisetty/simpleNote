import React, { useState } from 'react';
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
  Palette
} from 'lucide-react';

export default function Toolbar({ glassClass, hoverClass, updateDocContent, isCollapsed, onToggleCollapse }) {
  const [fontSize, setFontSize] = useState('16');
  const [textColor, setTextColor] = useState('#000000');
  const [isRecording, setIsRecording] = useState(false);
  const [showFontSize, setShowFontSize] = useState(false);
  const [recognition, setRecognition] = useState(null);
  const [transcript, setTranscript] = useState('');

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

  return (
    <div className={`${glassClass} rounded-lg border-l-2 border-[var(--color-accent-primary)] w-48 overflow-y-auto`}>
      <div className="p-3">
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
              <input
                type="color"
                value={textColor}
                onChange={(e) => {
                  setTextColor(e.target.value);
                  execCommand('foreColor', e.target.value);
                }}
                className="absolute inset-0 opacity-0 cursor-pointer"
                title="Text Color"
              />
              <button
                className={`w-full p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)] relative`}
                title="Color"
              >
                <Palette size={14} strokeWidth={2} className="mx-auto" />
              </button>
            </div>
          </div>
        </div>

        {/* Insert */}
        <div className="mb-4">
          <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
            Insert
          </div>
          <div className="grid grid-cols-3 gap-1.5">
            <button
              onClick={() => insertShape('square')}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Square"
            >
              <Square size={14} strokeWidth={2} className="mx-auto" />
            </button>
            <button
              onClick={() => insertShape('circle')}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Circle"
            >
              <Circle size={14} strokeWidth={2} className="mx-auto" />
            </button>
            <button
              onClick={() => insertShape('line')}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Line"
            >
              <Minus size={14} strokeWidth={2} className="mx-auto" />
            </button>
            <button
              onClick={() => {
                const url = prompt('Enter image URL:');
                if (url) execCommand('insertImage', url);
              }}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Image"
            >
              <Image size={14} strokeWidth={2} className="mx-auto" />
            </button>
            <button
              onClick={() => {
                const url = prompt('Enter link URL:');
                if (url) execCommand('createLink', url);
              }}
              className={`p-2 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`}
              title="Link"
            >
              <Link size={14} strokeWidth={2} className="mx-auto" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
