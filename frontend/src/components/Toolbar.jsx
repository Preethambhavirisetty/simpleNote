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
  Palette,
  Table,
  Download,
  Upload,
  Eraser,
  ChevronUp,
  ChevronDown
} from 'lucide-react';

export default function Toolbar({ 
  collapsed, 
  setCollapsed, 
  editorRef, 
  onFileUpload, 
  onAskAI, 
  showToast, 
  currentDoc, 
  isExporting, 
  isUploading 
}) {
  const [showColorPicker, setShowColorPicker] = useState(false);
  const [textColor, setTextColor] = useState('#000000');
  const fileInputRef = useRef(null);

  const execCommand = (command, value = null) => {
    document.execCommand(command, false, value);
    if (editorRef?.current) {
      editorRef.current.focus();
    }
  };

  const clearFormatting = () => {
    const selection = window.getSelection();
    if (!selection.rangeCount) return;
    
    const selectedText = selection.toString();
    if (selectedText) {
      document.execCommand('removeFormat', false, null);
      document.execCommand('unlink', false, null);
      if (showToast) {
        showToast('Formatting cleared', 'success');
      }
    } else {
      if (showToast) {
        showToast('Select text first to clear formatting', 'info');
      }
    }
  };

  const handleFileUploadClick = () => {
    fileInputRef.current?.click();
  };

  const handleFileChange = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;

    if (onFileUpload) {
      await onFileUpload(file);
    }

    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  const ToolButton = ({ icon: Icon, onClick, title, disabled = false }) => (
    <button
      onClick={onClick}
      disabled={disabled}
      className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
      title={title}
    >
      <Icon size={16} className="text-gray-700 dark:text-gray-300" />
    </button>
  );

  const Divider = () => (
    <div className="w-px h-6 bg-gray-300 dark:bg-gray-600"></div>
  );

  if (collapsed) {
    return (
      <div className="flex items-center justify-end px-4 py-2 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800">
        <button
          onClick={() => setCollapsed(false)}
          className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
          title="Show Toolbar"
        >
          <ChevronDown size={16} className="text-gray-700 dark:text-gray-300" />
        </button>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1 px-2 sm:px-4 py-2 border-b border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-800 overflow-x-auto">
      {/* Hidden file input */}
      <input
        ref={fileInputRef}
        type="file"
        accept=".txt,.docx"
        onChange={handleFileChange}
        className="hidden"
      />

      {/* Text Style */}
      <ToolButton icon={Bold} onClick={() => execCommand('bold')} title="Bold (Ctrl+B)" />
      <ToolButton icon={Italic} onClick={() => execCommand('italic')} title="Italic (Ctrl+I)" />
      <ToolButton icon={Underline} onClick={() => execCommand('underline')} title="Underline (Ctrl+U)" />
      <ToolButton icon={Eraser} onClick={clearFormatting} title="Clear Formatting" />

      <Divider />

      {/* Alignment */}
      <ToolButton icon={AlignLeft} onClick={() => execCommand('justifyLeft')} title="Align Left" />
      <ToolButton icon={AlignCenter} onClick={() => execCommand('justifyCenter')} title="Center" />
      <ToolButton icon={AlignRight} onClick={() => execCommand('justifyRight')} title="Align Right" />

      <Divider />

      {/* Lists */}
      <ToolButton icon={List} onClick={() => execCommand('insertUnorderedList')} title="Bullet List" />
      <ToolButton icon={ListOrdered} onClick={() => execCommand('insertOrderedList')} title="Numbered List" />

      <Divider />

      {/* Color Picker */}
      <div className="relative">
        <button
          onClick={() => setShowColorPicker(!showColorPicker)}
          className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
          title="Text Color"
        >
          <Palette size={16} className="text-gray-700 dark:text-gray-300" />
        </button>
        {showColorPicker && (
          <div className="absolute top-full left-0 mt-2 z-50 bg-white dark:bg-gray-800 border border-gray-300 dark:border-gray-600 rounded-lg p-3 shadow-xl">
            <div className="text-xs font-semibold text-gray-700 dark:text-gray-300 mb-2">
              Text Color
            </div>
            <input
              type="color"
              value={textColor}
              onChange={(e) => {
                setTextColor(e.target.value);
                execCommand('foreColor', e.target.value);
              }}
              className="w-24 h-24 cursor-pointer rounded border border-gray-300 dark:border-gray-600"
            />
            <div className="grid grid-cols-4 gap-2 mt-3">
              {['#000000', '#ffffff', '#ff0000', '#00ff00', '#0000ff', '#ffff00', '#ff00ff', '#00ffff'].map(color => (
                <button
                  key={color}
                  onClick={() => {
                    setTextColor(color);
                    execCommand('foreColor', color);
                    setShowColorPicker(false);
                  }}
                  style={{ backgroundColor: color }}
                  className="w-6 h-6 rounded border border-gray-300 dark:border-gray-600 hover:scale-110 transition-transform"
                />
              ))}
            </div>
            <button
              onClick={() => setShowColorPicker(false)}
              className="w-full mt-3 px-3 py-1 text-xs font-semibold bg-gray-100 dark:bg-gray-700 hover:bg-gray-200 dark:hover:bg-gray-600 rounded"
            >
              Close
            </button>
          </div>
        )}
      </div>

      <Divider />

      {/* File Operations */}
      <ToolButton 
        icon={Upload} 
        onClick={handleFileUploadClick} 
        title="Import File (.txt, .docx)" 
        disabled={isUploading}
      />

      {/* Spacer to push collapse button to the right */}
      <div className="flex-1"></div>

      {/* Collapse Button */}
      <button
        onClick={() => setCollapsed(true)}
        className="p-2 hover:bg-gray-100 dark:hover:bg-gray-700 rounded transition-colors"
        title="Hide Toolbar"
      >
        <ChevronUp size={16} className="text-gray-700 dark:text-gray-300" />
      </button>
    </div>
  );
}
