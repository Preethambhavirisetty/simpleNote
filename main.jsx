import React, { useState, useRef, useEffect } from 'react';
import { FileText, Plus, Trash2, Moon, Sun, Type, Bold, Italic, Underline, AlignLeft, AlignCenter, AlignRight, List, ListOrdered, Image, Link, Square, Circle, Minus, ChevronDown } from 'lucide-react';

export default function NotesApp() {
  const [theme, setTheme] = useState('light');
  const [documents, setDocuments] = useState([
    { id: 1, title: 'Welcome Note', content: '<h2>Welcome to Notes App!</h2><p>Start creating your notes here...</p>', createdAt: new Date().toISOString() }
  ]);
  const [activeDoc, setActiveDoc] = useState(1);
  const [fontSize, setFontSize] = useState('16');
  const [textColor, setTextColor] = useState('#000000');
  const [pageTemplate, setPageTemplate] = useState('blank');
  const [showTemplates, setShowTemplates] = useState(false);
  const editorRef = useRef(null);

  const templates = {
    blank: { name: 'Blank Page', content: '' },
    lined: { name: 'Lined Paper', content: '<p><br></p>'.repeat(20) },
    meeting: { name: 'Meeting Notes', content: '<h2>Meeting Notes</h2><p><strong>Date:</strong> </p><p><strong>Attendees:</strong> </p><p><strong>Agenda:</strong></p><ul><li></li></ul><p><strong>Action Items:</strong></p><ul><li></li></ul>' },
    todo: { name: 'To-Do List', content: '<h2>To-Do List</h2><ul><li>☐ Task 1</li><li>☐ Task 2</li><li>☐ Task 3</li></ul>' },
    journal: { name: 'Daily Journal', content: '<h2>Daily Journal</h2><p><strong>Date:</strong> </p><p><strong>Mood:</strong> </p><p><strong>Today I:</strong></p><p></p><p><strong>Grateful for:</strong></p><p></p>' }
  };

  const currentDoc = documents.find(doc => doc.id === activeDoc);

  const addNewDocument = () => {
    const newDoc = {
      id: Date.now(),
      title: `Untitled ${documents.length + 1}`,
      content: '',
      createdAt: new Date().toISOString()
    };
    setDocuments([...documents, newDoc]);
    setActiveDoc(newDoc.id);
  };

  const deleteDocument = (id) => {
    if (documents.length === 1) return;
    const filtered = documents.filter(doc => doc.id !== id);
    setDocuments(filtered);
    if (activeDoc === id) {
      setActiveDoc(filtered[0].id);
    }
  };

  const updateDocContent = () => {
    if (editorRef.current) {
      const content = editorRef.current.innerHTML;
      setDocuments(docs => docs.map(doc => 
        doc.id === activeDoc ? { ...doc, content } : doc
      ));
    }
  };

  const updateDocTitle = (id, newTitle) => {
    setDocuments(docs => docs.map(doc => 
      doc.id === id ? { ...doc, title: newTitle } : doc
    ));
  };

  const execCommand = (command, value = null) => {
    document.execCommand(command, false, value);
    editorRef.current?.focus();
    updateDocContent();
  };

  const applyTemplate = (templateKey) => {
    if (editorRef.current) {
      editorRef.current.innerHTML = templates[templateKey].content;
      setPageTemplate(templateKey);
      setShowTemplates(false);
      updateDocContent();
    }
  };

  const insertShape = (shape) => {
    const shapeHTML = {
      square: '<span style="display:inline-block;width:50px;height:50px;border:2px solid currentColor;margin:5px;"></span>',
      circle: '<span style="display:inline-block;width:50px;height:50px;border:2px solid currentColor;border-radius:50%;margin:5px;"></span>',
      line: '<hr style="border:1px solid currentColor;margin:10px 0;">'
    };
    document.execCommand('insertHTML', false, shapeHTML[shape]);
    updateDocContent();
  };

  useEffect(() => {
    if (editorRef.current && currentDoc) {
      editorRef.current.innerHTML = currentDoc.content;
    }
  }, [activeDoc]);

  const bgClass = theme === 'light' 
    ? 'bg-gradient-to-br from-gray-100 via-blue-50 to-purple-50' 
    : 'bg-gradient-to-br from-gray-900 via-gray-800 to-gray-900';
  
  const glassClass = theme === 'light'
    ? 'bg-white/40 backdrop-blur-lg border border-white/20 shadow-xl'
    : 'bg-gray-800/40 backdrop-blur-lg border border-gray-700/20 shadow-xl';

  const textClass = theme === 'light' ? 'text-gray-800' : 'text-gray-100';
  const secondaryTextClass = theme === 'light' ? 'text-gray-600' : 'text-gray-400';
  const hoverClass = theme === 'light' ? 'hover:bg-white/60' : 'hover:bg-gray-700/60';

  return (
    <div className={`min-h-screen ${bgClass} ${textClass} p-4`}>
      {/* Top Bar - Templates & Theme */}
      <div className={`${glassClass} rounded-2xl p-4 mb-4 flex justify-between items-center relative z-50`}>
        <div className="flex items-center gap-4">
          <h1 className="text-2xl font-bold bg-gradient-to-r from-blue-600 to-purple-600 bg-clip-text text-transparent">
            Notes App
          </h1>
          <div className="relative">
            <button
              onClick={() => setShowTemplates(!showTemplates)}
              className={`flex items-center gap-2 px-4 py-2 rounded-lg ${hoverClass} transition-all`}
            >
              <FileText size={18} />
              <span>Templates: {templates[pageTemplate].name}</span>
              <ChevronDown size={16} />
            </button>
            {showTemplates && (
              <div className={`absolute top-full mt-2 left-0 ${glassClass} rounded-lg p-2 min-w-[200px] z-[100]`}>
                {Object.entries(templates).map(([key, template]) => (
                  <button
                    key={key}
                    onClick={() => applyTemplate(key)}
                    className={`w-full text-left px-4 py-2 rounded-lg ${hoverClass} transition-all`}
                  >
                    {template.name}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>
        <button
          onClick={() => setTheme(theme === 'light' ? 'dark' : 'light')}
          className={`p-2 rounded-lg ${hoverClass} transition-all`}
        >
          {theme === 'light' ? <Moon size={20} /> : <Sun size={20} />}
        </button>
      </div>

      <div className="flex gap-4 h-[calc(100vh-120px)]">
        {/* Document List */}
        <div className={`${glassClass} rounded-2xl p-4 w-64 overflow-y-auto`}>
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold">Notes</h2>
            <button
              onClick={addNewDocument}
              className={`p-2 rounded-lg ${hoverClass} transition-all`}
              title="New Document"
            >
              <Plus size={20} />
            </button>
          </div>
          <div className="space-y-2">
            {documents.map(doc => (
              <div
                key={doc.id}
                className={`p-3 rounded-lg cursor-pointer transition-all ${
                  activeDoc === doc.id
                    ? 'bg-blue-500/20 border-2 border-blue-500'
                    : hoverClass
                }`}
              >
                <div className="flex items-start justify-between gap-2">
                  <div
                    onClick={() => setActiveDoc(doc.id)}
                    className="flex-1 min-w-0"
                  >
                    <input
                      type="text"
                      value={doc.title}
                      onChange={(e) => updateDocTitle(doc.id, e.target.value)}
                      className="bg-transparent border-none outline-none w-full font-medium text-black"
                      onClick={(e) => e.stopPropagation()}
                    />
                    <p className={`text-xs ${secondaryTextClass} mt-1`}>
                      {new Date(doc.createdAt).toLocaleDateString()}
                    </p>
                  </div>
                  {documents.length > 1 && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        deleteDocument(doc.id);
                      }}
                      className="text-red-500 hover:text-red-600 p-1"
                      title="Delete"
                    >
                      <Trash2 size={16} />
                    </button>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Editor Area */}
        <div className={`flex-1 ${glassClass} rounded-2xl p-8 overflow-y-auto`}>
          <div
            ref={editorRef}
            contentEditable
            className={`outline-none min-h-full ${textClass} prose prose-lg max-w-none`}
            onInput={updateDocContent}
            style={{
              fontSize: `${fontSize}px`,
              lineHeight: '1.6'
            }}
          />
        </div>

        {/* Right Toolbar - Formatting Tools */}
        <div className={`${glassClass} rounded-2xl p-4 w-16 flex flex-col gap-2 overflow-y-auto`}>
          <div className="flex flex-col gap-2">
            {/* Text Formatting */}
            <button
              onClick={() => execCommand('bold')}
              className={`p-3 rounded-lg ${hoverClass} transition-all`}
              title="Bold"
            >
              <Bold size={20} />
            </button>
            <button
              onClick={() => execCommand('italic')}
              className={`p-3 rounded-lg ${hoverClass} transition-all`}
              title="Italic"
            >
              <Italic size={20} />
            </button>
            <button
              onClick={() => execCommand('underline')}
              className={`p-3 rounded-lg ${hoverClass} transition-all`}
              title="Underline"
            >
              <Underline size={20} />
            </button>

            <div className="h-px bg-gray-300/50 my-2"></div>

            {/* Alignment */}
            <button
              onClick={() => execCommand('justifyLeft')}
              className={`p-3 rounded-lg ${hoverClass} transition-all`}
              title="Align Left"
            >
              <AlignLeft size={20} />
            </button>
            <button
              onClick={() => execCommand('justifyCenter')}
              className={`p-3 rounded-lg ${hoverClass} transition-all`}
              title="Align Center"
            >
              <AlignCenter size={20} />
            </button>
            <button
              onClick={() => execCommand('justifyRight')}
              className={`p-3 rounded-lg ${hoverClass} transition-all`}
              title="Align Right"
            >
              <AlignRight size={20} />
            </button>

            <div className="h-px bg-gray-300/50 my-2"></div>

            {/* Lists */}
            <button
              onClick={() => execCommand('insertUnorderedList')}
              className={`p-3 rounded-lg ${hoverClass} transition-all`}
              title="Bullet List"
            >
              <List size={20} />
            </button>
            <button
              onClick={() => execCommand('insertOrderedList')}
              className={`p-3 rounded-lg ${hoverClass} transition-all`}
              title="Numbered List"
            >
              <ListOrdered size={20} />
            </button>

            <div className="h-px bg-gray-300/50 my-2"></div>

            {/* Font Size */}
            <div className="relative group">
              <button className={`p-3 rounded-lg ${hoverClass} transition-all`} title="Font Size">
                <Type size={20} />
              </button>
              <select
                value={fontSize}
                onChange={(e) => {
                  setFontSize(e.target.value);
                  execCommand('fontSize', '7');
                  const fontElements = document.querySelectorAll('font[size="7"]');
                  fontElements.forEach(el => {
                    el.removeAttribute('size');
                    el.style.fontSize = e.target.value + 'px';
                  });
                }}
                className={`absolute left-full ml-2 top-0 opacity-0 group-hover:opacity-100 ${glassClass} rounded-lg p-2 transition-opacity`}
              >
                {[12, 14, 16, 18, 20, 24, 28, 32, 36, 48].map(size => (
                  <option key={size} value={size}>{size}px</option>
                ))}
              </select>
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
                className="w-12 h-12 rounded-lg cursor-pointer"
                title="Text Color"
              />
            </div>

            <div className="h-px bg-gray-300/50 my-2"></div>

            {/* Shapes */}
            <button
              onClick={() => insertShape('square')}
              className={`p-3 rounded-lg ${hoverClass} transition-all`}
              title="Insert Square"
            >
              <Square size={20} />
            </button>
            <button
              onClick={() => insertShape('circle')}
              className={`p-3 rounded-lg ${hoverClass} transition-all`}
              title="Insert Circle"
            >
              <Circle size={20} />
            </button>
            <button
              onClick={() => insertShape('line')}
              className={`p-3 rounded-lg ${hoverClass} transition-all`}
              title="Insert Line"
            >
              <Minus size={20} />
            </button>

            <div className="h-px bg-gray-300/50 my-2"></div>

            {/* Insert Image URL */}
            <button
              onClick={() => {
                const url = prompt('Enter image URL:');
                if (url) execCommand('insertImage', url);
              }}
              className={`p-3 rounded-lg ${hoverClass} transition-all`}
              title="Insert Image"
            >
              <Image size={20} />
            </button>

            {/* Insert Link */}
            <button
              onClick={() => {
                const url = prompt('Enter link URL:');
                if (url) execCommand('createLink', url);
              }}
              className={`p-3 rounded-lg ${hoverClass} transition-all`}
              title="Insert Link"
            >
              <Link size={20} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}