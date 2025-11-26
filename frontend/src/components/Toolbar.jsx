import React, { useState, useEffect, useRef } from "react";
import jsPDF from "jspdf";
import html2canvas from "html2canvas";
import { Document, Packer, Paragraph, TextRun, HeadingLevel } from "docx";
import { saveAs } from "file-saver";
import {
  Bold,
  Italic,
  Strikethrough,
  Underline as UnderlineIcon,
  List,
  ListOrdered,
  Heading1,
  Heading2,
  Heading3,
  Link as LinkIcon,
  Image as ImageIcon,
  Code,
  Quote,
  AlignLeft,
  AlignCenter,
  AlignRight,
  Eraser,
  Palette,
  Type,
  ChevronLeft,
  ChevronRight,
  Minus,
  Upload,
  Download,
  Table as TableIcon,
  Indent,
  Outdent,
  Mic,
  Sigma,
} from "lucide-react";

export default function Toolbar({
  editor,
  currentDoc,
  glassClass,
  hoverClass,
  onFileUpload,
  showToast,
  isCollapsed,
  onToggleCollapse,
  fontFamily,
  onFontChange,
  fontSize,
  onFontSizeChange,
}) {
  const [showColorPicker, setShowColorPicker] = useState(false);
  const [textColor, setTextColor] = useState("#000000");
  const [showFontFamilyDialog, setShowFontFamilyDialog] = useState(false);
  const [showFontSizeDialog, setShowFontSizeDialog] = useState(false);
  const [showLinkDialog, setShowLinkDialog] = useState(false);
  const [linkUrl, setLinkUrl] = useState("");
  const [linkText, setLinkText] = useState("");
  const [isRecording, setIsRecording] = useState(false);
  const recognitionRef = useRef(null); // Use ref instead of state
  const [transcript, setTranscript] = useState("");

  // Common colors
  const colors = [
    "#000000",
    "#FF0000",
    "#00FF00",
    "#0000FF",
    "#FFFF00",
    "#FF00FF",
    "#00FFFF",
    "#FFA500",
    "#800080",
    "#FFC0CB",
    "#A52A2A",
    "#808080",
    "#FFFFFF",
  ];

  // Font families
  const fontFamilies = [
    { name: "System Default", value: "system-ui, -apple-system, sans-serif" },
    { name: "Arial", value: "Arial, sans-serif" },
    { name: "Helvetica", value: "Helvetica, sans-serif" },
    { name: "Georgia", value: "Georgia, serif" },
    { name: "Times New Roman", value: "Times New Roman, serif" },
    { name: "Courier New", value: "Courier New, monospace" },
    { name: "Verdana", value: "Verdana, sans-serif" },
    { name: "Comic Sans", value: "Comic Sans MS, cursive" },
  ];

  // Font sizes
  const fontSizes = [12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 64];

  useEffect(() => {
    if (!editor) return;

    if ("webkitSpeechRecognition" in window || "SpeechRecognition" in window) {
      const SpeechRecognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;

      // Only create one instance
      if (!recognitionRef.current) {
        const recognitionInstance = new SpeechRecognition();
        recognitionInstance.continuous = true;
        recognitionInstance.interimResults = true;
        recognitionInstance.lang = "en-US";
        recognitionInstance.maxAlternatives = 1;

        recognitionInstance.onresult = (event) => {
          let interimTranscript = "";
          let finalTranscript = "";

          for (let i = event.resultIndex; i < event.results.length; i++) {
            const transcript = event.results[i][0].transcript;
            if (event.results[i].isFinal) {
              finalTranscript += transcript + " ";
            } else {
              interimTranscript += transcript;
            }
          }

          setTranscript(interimTranscript || finalTranscript);

          if (finalTranscript) {
            editor.chain().focus().insertContent(finalTranscript).run();
          }
        };

        recognitionInstance.onerror = (event) => {
          console.error("Speech recognition error:", event.error);
          recognitionRef.current.shouldContinue = false;
          setIsRecording(false);
          setTranscript("");

          if (showToast) {
            showToast(`Speech error: ${event.error}`, "error", 3000);
          }
        };

        recognitionInstance.onend = () => {

          if (recognitionRef.current.shouldContinue) {
            try {
              recognitionInstance.start(); // Restart only if allowed
            } catch (err) {
              console.error("❌ Error restarting:", err);
            }
          } else {
            setIsRecording(false);
            setTranscript("");
          }
        };

        recognitionRef.current = recognitionInstance;
        recognitionRef.current.shouldContinue = false;
      }
    }
  }, [editor, showToast]);

  // Start listening
  const startListening = () => {
    if (recognitionRef.current && !isRecording) {
      recognitionRef.current.shouldContinue = true;
      recognitionRef.current.start();
      setIsRecording(true);
    }
  };

  // Stop listening immediately
  const stopListening = () => {
    if (recognitionRef.current && isRecording) {
      recognitionRef.current.shouldContinue = false; // Prevent auto-restart
      recognitionRef.current.onend = () => {
        // Override onend to prevent restart when stopping manually
        setIsRecording(false);
        setTranscript("");
      };
      recognitionRef.current.stop(); // Immediately stop recognition
    }
  };

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

  const handleVoiceRecording = () => {
    const recognition = recognitionRef.current;

    if (!recognition) {
      if (showToast) {
        showToast(
          "Speech recognition not supported. Use Chrome, Edge, or Safari.",
          "error",
          3000
        );
      }
      return;
    }

    if (isRecording) {
      // STOP IMMEDIATELY
      try {

        // 1. Set flag to FALSE first (prevents onend from restarting)
        if (recognitionRef.current) {
          recognitionRef.current.shouldContinue = false;
        }

        // 2. Abort immediately (doesn't wait for results)
        recognition.abort();

        // 3. Update UI immediately
        setIsRecording(false);
        setTranscript("");

        if (showToast) {
          showToast("Voice stopped", "success", 1000);
        }
      } catch (error) {
        console.error("❌ Error stopping recognition:", error);

        // Force cleanup
        setIsRecording(false);
        setTranscript("");
        if (recognitionRef.current) {
          recognitionRef.current.shouldContinue = false;
        }
      }
    } else {
      // START LISTENING
      try {

        // 1. Set flag to TRUE (enables auto-restart in onend)
        if (recognitionRef.current) {
          recognitionRef.current.shouldContinue = true;
        }

        // 2. Start recognition
        recognition.start();
        setIsRecording(true);

        if (showToast) {
          showToast("Listening... Speak now", "info", 2000);
        }
      } catch (error) {
        console.error("❌ Error starting recognition:", error);
        setIsRecording(false);

        if (recognitionRef.current) {
          recognitionRef.current.shouldContinue = false;
        }

        if (showToast) {
          showToast("Failed to start voice recording", "error", 2000);
        }
      }
    }
  };

  // Export document as PDF
  const handleExport = async () => {
    if (!currentDoc) return;

    try {
      if (showToast) {
        showToast("Generating PDF...", "loading", 0);
      }

      // Get the editor content
      const editorElement = document.querySelector(
        ".tiptap-editor .ProseMirror"
      );
      if (!editorElement) {
        throw new Error("Editor not found");
      }

      // Create canvas from HTML
      const canvas = await html2canvas(editorElement, {
        padding: 16,
        scale: 2,
        useCORS: true,
        logging: false,
        backgroundColor: "#ffffff",
      });

      // Calculate PDF dimensions with margins
      const pdf = new jsPDF("p", "mm", "a4");
      const pageWidth = 210; // A4 width in mm
      const pageHeight = 297; // A4 height in mm
      const margin = 15; // 15mm margins on all sides
      const contentWidth = pageWidth - 2 * margin;
      const contentHeight = pageHeight - 2 * margin;

      // Calculate image dimensions to fit within margins
      const imgWidth = contentWidth;
      const imgHeight = (canvas.height * contentWidth) / canvas.width;

      let heightLeft = imgHeight;
      let position = margin;

      // Add image to PDF with margins
      const imgData = canvas.toDataURL("image/png");
      pdf.addImage(imgData, "PNG", margin, position, imgWidth, imgHeight);
      heightLeft -= contentHeight;

      // Add extra pages if needed
      while (heightLeft > 0) {
        position = -(imgHeight - heightLeft) + margin;
        pdf.addPage();
        pdf.addImage(imgData, "PNG", margin, position, imgWidth, imgHeight);
        heightLeft -= contentHeight;
      }

      // Save with document name
      pdf.save(`${currentDoc.title}.pdf`);

      if (showToast) {
        showToast("PDF exported successfully", "success", 2000);
      }
    } catch (error) {
      console.error("PDF export error:", error);
      if (showToast) {
        showToast("Failed to export PDF", "error", 2000);
      }
    }
  };

  // Export document as DOCX
  const handleExportDocx = async () => {
    if (!currentDoc) return;

    try {
      if (showToast) {
        showToast("Generating DOCX...", "loading", 0);
      }

      // Get the editor content as HTML
      const editorElement = document.querySelector(
        ".tiptap-editor .ProseMirror"
      );
      if (!editorElement) {
        throw new Error("Editor not found");
      }

      // Convert HTML to plain text and create document structure
      const htmlContent = editorElement.innerHTML;
      const tempDiv = document.createElement("div");
      tempDiv.innerHTML = htmlContent;

      // Parse HTML and convert to docx elements
      const paragraphs = [];

      // Helper function to process nodes
      const processNode = (node) => {
        if (node.nodeType === Node.TEXT_NODE) {
          const text = node.textContent.trim();
          if (text) {
            return new TextRun({
              text: text,
              bold:
                node.parentElement?.tagName === "STRONG" ||
                node.parentElement?.tagName === "B",
              italics:
                node.parentElement?.tagName === "EM" ||
                node.parentElement?.tagName === "I",
              underline: node.parentElement?.tagName === "U" ? {} : undefined,
              strike:
                node.parentElement?.style?.textDecoration === "line-through",
            });
          }
        }
        return null;
      };

      // Process all nodes
      const allNodes = tempDiv.querySelectorAll(
        "p, h1, h2, h3, h4, h5, h6, li"
      );
      allNodes.forEach((element) => {
        const textRuns = [];

        // Get all text nodes
        const walker = document.createTreeWalker(
          element,
          NodeFilter.SHOW_TEXT,
          null
        );

        let node;
        while ((node = walker.nextNode())) {
          const textRun = processNode(node);
          if (textRun) textRuns.push(textRun);
        }

        // If no text runs, add the direct text content
        if (textRuns.length === 0 && element.textContent.trim()) {
          textRuns.push(
            new TextRun({
              text: element.textContent.trim(),
              bold: element.querySelector("strong, b") !== null,
              italics: element.querySelector("em, i") !== null,
              underline: element.querySelector("u") !== null ? {} : undefined,
            })
          );
        }

        // Determine heading level
        let heading = undefined;
        if (element.tagName === "H1") heading = HeadingLevel.HEADING_1;
        else if (element.tagName === "H2") heading = HeadingLevel.HEADING_2;
        else if (element.tagName === "H3") heading = HeadingLevel.HEADING_3;
        else if (element.tagName === "H4") heading = HeadingLevel.HEADING_4;
        else if (element.tagName === "H5") heading = HeadingLevel.HEADING_5;
        else if (element.tagName === "H6") heading = HeadingLevel.HEADING_6;

        paragraphs.push(
          new Paragraph({
            children:
              textRuns.length > 0 ? textRuns : [new TextRun({ text: " " })],
            heading: heading,
            spacing: {
              after: 200,
            },
          })
        );
      });

      // Create document
      const doc = new Document({
        sections: [
          {
            properties: {
              page: {
                margin: {
                  top: 1440, // 1 inch in twips (1440 twips = 1 inch)
                  right: 1440,
                  bottom: 1440,
                  left: 1440,
                },
              },
            },
            children: paragraphs,
          },
        ],
      });

      // Generate and save
      const blob = await Packer.toBlob(doc);
      saveAs(blob, `${currentDoc.title}.docx`);

      if (showToast) {
        showToast("DOCX exported successfully", "success", 2000);
      }
    } catch (error) {
      console.error("DOCX export error:", error);
      if (showToast) {
        showToast("Failed to export DOCX", "error", 2000);
      }
    }
  };

  // Show link dialog (only if text is selected)
  const showLinkInput = () => {
    const { from, to } = editor.state.selection;
    const selectedText = editor.state.doc.textBetween(from, to, " ");

    if (!selectedText.trim()) {
      if (showToast) {
        showToast("Please select text first", "info", 2000);
      }
      return;
    }

    setShowLinkDialog(true);
  };

  // Insert link
  const insertLink = () => {
    if (!linkUrl) {
      if (showToast) {
        showToast("Please enter a URL", "info", 2000);
      }
      return;
    }

    editor.chain().focus().setLink({ href: linkUrl }).run();
    setShowLinkDialog(false);
    setLinkUrl("");

    if (showToast) {
      showToast("Link added", "success", 1500);
    }
  };

  // Handle file import - creates new document
  const handleImport = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const content = e.target.result;
        let proseMirrorContent;

        // Get filename without extension as title
        const fileName = file.name.replace(/\.(json|txt|md)$/, "");

        // Try to parse as JSON (ProseMirror format)
        if (file.name.endsWith(".json")) {
          proseMirrorContent = JSON.parse(content);
        } else {
          // Plain text or markdown - convert to ProseMirror format
          proseMirrorContent = {
            type: "doc",
            content: [
              {
                type: "paragraph",
                content: content ? [{ type: "text", text: content }] : [],
              },
            ],
          };
        }

        // Call onFileUpload to create a new document with this content
        if (onFileUpload) {
          onFileUpload(fileName, proseMirrorContent);
        }
      } catch (error) {
        console.error("Import error:", error);
        if (showToast) {
          showToast("Failed to import file", "error", 2000);
        }
      }
    };
    reader.readAsText(file);

    // Reset input
    event.target.value = "";
  };

  // Handle image/video/file upload
  const handleMediaUpload = (event) => {
    const file = event.target.files?.[0];
    if (!file) return;

    if (!editor) {
      if (showToast) showToast("Editor not ready", "error", 2000);
      return;
    }

    const reader = new FileReader();
    reader.onload = (e) => {
      const base64 = e.target.result;

      if (file.type.startsWith("image/")) {
        // Insert image using insertContent with img tag
        const imgHtml = `<img src="${base64}" alt="${file.name}" class="resizable-image" />`;
        editor.chain().focus().insertContent(imgHtml).run();
        if (showToast) {
          showToast("Image uploaded", "success", 1500);
        }
      } else if (file.type.startsWith("video/")) {
        // Insert video as HTML
        const videoHtml = `<video controls src="${base64}" style="max-width: 100%; border-radius: 5px;"></video>`;
        editor.chain().focus().insertContent(videoHtml).run();
        if (showToast) {
          showToast("Video uploaded", "success", 1500);
        }
      } else {
        // Insert file as link
        const fileLink = `<a href="${base64}" download="${file.name}">${file.name}</a>`;
        editor.chain().focus().insertContent(fileLink).run();
        if (showToast) {
          showToast("File uploaded", "success", 1500);
        }
      }
    };

    reader.onerror = () => {
      if (showToast) showToast("Failed to read file", "error", 2000);
    };

    reader.readAsDataURL(file);

    // Reset input
    event.target.value = "";
  };

  // Insert table
  const insertTable = () => {
    editor
      .chain()
      .focus()
      .insertTable({ rows: 3, cols: 3, withHeaderRow: true })
      .run();
    if (showToast) {
      showToast("Table inserted", "success", 1500);
    }
  };

  return (
    <>
      {/* Desktop Toolbar - Right Side */}
      <div
        className={`scroll-container hidden md:block ${glassClass} rounded-lg border border-[var(--color-border-light)] overflow-hidden transition-all duration-300 ${
          isCollapsed ? "w-14" : "w-72"
        }`}
      >
        {/* Header with Toggle */}
        <div className="flex items-center justify-between p-3 border-b border-[var(--color-border-light)] bg-[var(--color-bg-secondary)]">
          {!isCollapsed && (
            <h2 className="text-sm font-bold tracking-tight">Formatting</h2>
          )}
          <button
            onClick={onToggleCollapse}
            className={`p-1.5 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)]`}
            title={isCollapsed ? "Expand Toolbar" : "Collapse Toolbar"}
          >
            {isCollapsed ? (
              <ChevronLeft size={14} />
            ) : (
              <ChevronRight size={14} />
            )}
          </button>
        </div>

        {/* Toolbar Content */}
        {!isCollapsed && (
          <div className="p-4 space-y-4 overflow-y-auto max-h-[calc(100vh-200px)]">
            {/* Voice */}

            <div className="mb-4">
              <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
                Voice
              </div>

              <button
                onClick={() => {
                  if (isRecording) {
                    stopListening(); // Stop immediately
                  } else {
                    startListening(); // Start voice recording
                  }
                }}
                className={`w-full p-2 rounded transition-all border ${
                  isRecording
                    ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-[var(--color-bg-primary)] animate-pulse"
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
                    <div
                      className="w-1 h-1 bg-[var(--color-accent-primary)] rounded-full animate-pulse"
                      style={{ animationDelay: "0.2s" }}
                    ></div>
                    <div
                      className="w-1 h-1 bg-[var(--color-accent-primary)] rounded-full animate-pulse"
                      style={{ animationDelay: "0.4s" }}
                    ></div>
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
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
                Style
              </div>
              <div className="grid grid-cols-3 gap-1.5">
                <button
                  onClick={() => editor.chain().focus().toggleBold().run()}
                  className={`p-2 rounded transition-all border ${
                    editor.isActive("bold")
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  title="Bold"
                >
                  <Bold size={14} strokeWidth={2} className="mx-auto" />
                </button>
                <button
                  onClick={() => editor.chain().focus().toggleItalic().run()}
                  className={`p-2 rounded transition-all border ${
                    editor.isActive("italic")
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  title="Italic"
                >
                  <Italic size={14} strokeWidth={2} className="mx-auto" />
                </button>
                <button
                  onClick={() => editor.chain().focus().toggleStrike().run()}
                  className={`p-2 rounded transition-all border ${
                    editor.isActive("strike")
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  title="Strikethrough"
                >
                  <Strikethrough
                    size={14}
                    strokeWidth={2}
                    className="mx-auto"
                  />
                </button>
                <button
                  onClick={() => editor.chain().focus().toggleUnderline().run()}
                  className={`p-2 rounded transition-all border ${
                    editor.isActive("underline")
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  title="Underline"
                >
                  <UnderlineIcon
                    size={14}
                    strokeWidth={2}
                    className="mx-auto"
                  />
                </button>
                <button
                  onClick={() => editor.chain().focus().toggleCode().run()}
                  className={`p-2 rounded transition-all border ${
                    editor.isActive("code")
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  title="Inline Code"
                >
                  <Code size={14} strokeWidth={2} className="mx-auto" />
                </button>
                <button
                  onClick={() => editor.chain().focus().unsetAllMarks().run()}
                  className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
                  title="Clear Formatting"
                >
                  <Eraser size={14} strokeWidth={2} className="mx-auto" />
                </button>
                <button
                  onClick={() => setShowColorPicker(!showColorPicker)}
                  className={`w-full p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)] flex items-center justify-center gap-2`}
                  title="Text Color"
                >
                  <Palette size={14} strokeWidth={2} />
                </button>
                <button
                  onClick={() => setShowFontFamilyDialog(!showFontFamilyDialog)}
                  className={`w-full p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)] flex items-center justify-center gap-2 text-xs truncate`}
                  title="Font Family"
                  style={{ fontFamily }}
                >
                  <Type size={14} strokeWidth={2} />
                  <span className="truncate">
                    {fontFamilies.find((f) => f.value === fontFamily)?.name ||
                      "System Default"}
                  </span>
                </button>
                <button
                  onClick={() => setShowFontSizeDialog(!showFontSizeDialog)}
                  className={`w-full p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)] flex items-center justify-center gap-2 text-xs`}
                  title="Font Size"
                >
                  {/* <Sigma size={14} strokeWidth={2} /> */}
                  <span className="text-xs font-medium">Aa</span>
                  <span>{fontSize}px</span>
                </button>
              </div>
            </div>

            {/* Headings */}
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
                Headings
              </div>
              <div className="grid grid-cols-3 gap-1.5">
                <button
                  onClick={() =>
                    editor.chain().focus().toggleHeading({ level: 1 }).run()
                  }
                  className={`p-2 rounded transition-all border ${
                    editor.isActive("heading", { level: 1 })
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  title="Heading 1"
                >
                  <Heading1 size={14} strokeWidth={2} className="mx-auto" />
                </button>
                <button
                  onClick={() =>
                    editor.chain().focus().toggleHeading({ level: 2 }).run()
                  }
                  className={`p-2 rounded transition-all border ${
                    editor.isActive("heading", { level: 2 })
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  title="Heading 2"
                >
                  <Heading2 size={14} strokeWidth={2} className="mx-auto" />
                </button>
                <button
                  onClick={() =>
                    editor.chain().focus().toggleHeading({ level: 3 }).run()
                  }
                  className={`p-2 rounded transition-all border ${
                    editor.isActive("heading", { level: 3 })
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  title="Heading 3"
                >
                  <Heading3 size={14} strokeWidth={2} className="mx-auto" />
                </button>
              </div>
            </div>

            {/* Alignment */}
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
                Align
              </div>
              <div className="grid grid-cols-3 gap-1.5">
                <button
                  onClick={() =>
                    editor.chain().focus().setTextAlign("left").run()
                  }
                  className={`p-2 rounded transition-all border ${
                    editor.isActive({ textAlign: "left" })
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  title="Align Left"
                >
                  <AlignLeft size={14} strokeWidth={2} className="mx-auto" />
                </button>
                <button
                  onClick={() =>
                    editor.chain().focus().setTextAlign("center").run()
                  }
                  className={`p-2 rounded transition-all border ${
                    editor.isActive({ textAlign: "center" })
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  title="Center"
                >
                  <AlignCenter size={14} strokeWidth={2} className="mx-auto" />
                </button>
                <button
                  onClick={() =>
                    editor.chain().focus().setTextAlign("right").run()
                  }
                  className={`p-2 rounded transition-all border ${
                    editor.isActive({ textAlign: "right" })
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  title="Align Right"
                >
                  <AlignRight size={14} strokeWidth={2} className="mx-auto" />
                </button>
              </div>
            </div>

            {/* Lists */}
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
                Lists
              </div>
              <div className="grid grid-cols-4 gap-1.5">
                <button
                  onClick={() =>
                    editor.chain().focus().toggleBulletList().run()
                  }
                  className={`p-2 rounded transition-all border ${
                    editor.isActive("bulletList")
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  title="Bullet List"
                >
                  <List size={14} strokeWidth={2} className="mx-auto" />
                </button>
                <button
                  onClick={() =>
                    editor.chain().focus().toggleOrderedList().run()
                  }
                  className={`p-2 rounded transition-all border ${
                    editor.isActive("orderedList")
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  title="Numbered List"
                >
                  <ListOrdered size={14} strokeWidth={2} className="mx-auto" />
                </button>
                <button
                  onClick={() =>
                    editor.chain().focus().sinkListItem("listItem").run()
                  }
                  disabled={!editor.can().sinkListItem("listItem")}
                  className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)] disabled:opacity-50`}
                  title="Indent"
                >
                  <Indent size={14} strokeWidth={2} className="mx-auto" />
                </button>
                <button
                  onClick={() =>
                    editor.chain().focus().liftListItem("listItem").run()
                  }
                  disabled={!editor.can().liftListItem("listItem")}
                  className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)] disabled:opacity-50`}
                  title="Outdent"
                >
                  <Outdent size={14} strokeWidth={2} className="mx-auto" />
                </button>
              </div>
            </div>

            {/* Insert */}
            <div>
              <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-[var(--color-border-light)]">
                Insert
              </div>
              <div className="grid grid-cols-3 gap-1.5">
                <button
                  onClick={showLinkInput}
                  className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
                  title="Insert Link (Select text first)"
                >
                  <LinkIcon size={14} strokeWidth={2} className="mx-auto" />
                </button>
                <label
                  className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)] cursor-pointer flex items-center justify-center`}
                  title="Upload Image/Video/File"
                >
                  <ImageIcon size={14} strokeWidth={2} className="mx-auto" />
                  <input
                    type="file"
                    accept="image/*,video/*,*"
                    onChange={handleMediaUpload}
                    className="hidden"
                  />
                </label>
                <button
                  onClick={insertTable}
                  className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
                  title="Insert Table"
                >
                  <TableIcon size={14} strokeWidth={2} className="mx-auto" />
                </button>
                <button
                  onClick={() => editor.chain().focus().toggleCodeBlock().run()}
                  className={`p-2 rounded transition-all border ${
                    editor.isActive("codeBlock")
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  title="Code Block"
                >
                  <Code size={14} strokeWidth={2} className="mx-auto" />
                </button>
                <button
                  onClick={() =>
                    editor.chain().focus().toggleBlockquote().run()
                  }
                  className={`p-2 rounded transition-all border ${
                    editor.isActive("blockquote")
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  title="Blockquote"
                >
                  <Quote size={14} strokeWidth={2} className="mx-auto" />
                </button>
                <button
                  onClick={() =>
                    editor.chain().focus().setHorizontalRule().run()
                  }
                  className={`p-2 rounded transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
                  title="Horizontal Line"
                >
                  <Minus size={14} strokeWidth={2} className="mx-auto" />
                </button>
              </div>
            </div>

            {/* File Operations */}
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
                  onClick={handleExport}
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
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Mobile Toolbar - Bottom Horizontal Scroll */}
      <div
        className={`md:hidden ${glassClass} border-t border-[var(--color-border-light)] bg-[var(--color-bg-secondary)]/95 backdrop-blur-lg rounded-lg overflow-hidden`}
      >
        <div className="flex items-center gap-1 p-2 overflow-x-auto scrollbar-thin scrollbar-thumb-[var(--color-border-medium)] scrollbar-track-transparent">
          {/* Voice */}
          <button
            onClick={handleVoiceRecording}
            className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)] ${
              isRecording ? "animate-pulse bg-red-500/20" : ""
            }`}
            title="Voice Input"
          >
            <Mic size={16} strokeWidth={2} />
          </button>

          {/* Basic Formatting */}
          <button
            onClick={() => editor?.chain().focus().toggleBold().run()}
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive("bold")
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            disabled={!editor?.can().chain().focus().toggleBold().run()}
            title="Bold"
          >
            <Bold size={16} strokeWidth={2} />
          </button>

          <button
            onClick={() => editor?.chain().focus().toggleItalic().run()}
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive("italic")
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            disabled={!editor?.can().chain().focus().toggleItalic().run()}
            title="Italic"
          >
            <Italic size={16} strokeWidth={2} />
          </button>

          <button
            onClick={() => editor?.chain().focus().toggleUnderline().run()}
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive("underline")
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            disabled={!editor?.can().chain().focus().toggleUnderline().run()}
            title="Underline"
          >
            <UnderlineIcon size={16} strokeWidth={2} />
          </button>

          <button
            onClick={() => editor?.chain().focus().toggleStrike().run()}
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive("strike")
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            disabled={!editor?.can().chain().focus().toggleStrike().run()}
            title="Strikethrough"
          >
            <Strikethrough size={16} strokeWidth={2} />
          </button>

          {/* Divider */}
          <div className="w-px h-6 bg-[var(--color-border-medium)] flex-shrink-0"></div>

          {/* Headings */}
          <button
            onClick={() =>
              editor?.chain().focus().toggleHeading({ level: 1 }).run()
            }
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive("heading", { level: 1 })
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            title="Heading 1"
          >
            <Heading1 size={16} strokeWidth={2} />
          </button>

          <button
            onClick={() =>
              editor?.chain().focus().toggleHeading({ level: 2 }).run()
            }
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive("heading", { level: 2 })
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            title="Heading 2"
          >
            <Heading2 size={16} strokeWidth={2} />
          </button>

          <button
            onClick={() =>
              editor?.chain().focus().toggleHeading({ level: 3 }).run()
            }
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive("heading", { level: 3 })
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            title="Heading 3"
          >
            <Heading3 size={16} strokeWidth={2} />
          </button>

          {/* Divider */}
          <div className="w-px h-6 bg-[var(--color-border-medium)] flex-shrink-0"></div>

          {/* Lists */}
          <button
            onClick={() => editor?.chain().focus().toggleBulletList().run()}
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive("bulletList")
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            title="Bullet List"
          >
            <List size={16} strokeWidth={2} />
          </button>

          <button
            onClick={() => editor?.chain().focus().toggleOrderedList().run()}
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive("orderedList")
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            title="Numbered List"
          >
            <ListOrdered size={16} strokeWidth={2} />
          </button>

          {/* Divider */}
          <div className="w-px h-6 bg-[var(--color-border-medium)] flex-shrink-0"></div>

          {/* Alignment */}
          <button
            onClick={() => editor?.chain().focus().setTextAlign("left").run()}
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive({ textAlign: "left" })
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            title="Align Left"
          >
            <AlignLeft size={16} strokeWidth={2} />
          </button>

          <button
            onClick={() => editor?.chain().focus().setTextAlign("center").run()}
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive({ textAlign: "center" })
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            title="Align Center"
          >
            <AlignCenter size={16} strokeWidth={2} />
          </button>

          <button
            onClick={() => editor?.chain().focus().setTextAlign("right").run()}
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive({ textAlign: "right" })
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            title="Align Right"
          >
            <AlignRight size={16} strokeWidth={2} />
          </button>

          {/* Divider */}
          <div className="w-px h-6 bg-[var(--color-border-medium)] flex-shrink-0"></div>

          {/* Color */}
          <button
            onClick={() => setShowColorPicker(true)}
            className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
            title="Text Color"
          >
            <Palette size={16} strokeWidth={2} />
          </button>

          {/* Font Family */}
          <button
            onClick={() => setShowFontFamilyDialog(true)}
            className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
            title="Font Family"
          >
            <Type size={16} strokeWidth={2} />
          </button>

          {/* Font Size */}
          <button
            onClick={() => setShowFontSizeDialog(true)}
            className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
            title="Font Size"
          >
            <span className="text-xs font-bold">Aa</span>
          </button>

          {/* Divider */}
          <div className="w-px h-6 bg-[var(--color-border-medium)] flex-shrink-0"></div>

          {/* Link */}
          <button
            onClick={insertLink}
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive("link")
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            title="Link"
          >
            <LinkIcon size={16} strokeWidth={2} />
          </button>

          {/* Media Upload */}
          <label
            className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)] cursor-pointer flex items-center justify-center`}
            title="Upload Media"
          >
            <ImageIcon size={16} strokeWidth={2} />
            <input
              type="file"
              accept="image/*,video/*,*"
              onChange={handleMediaUpload}
              className="hidden"
            />
          </label>

          {/* Divider */}
          <div className="w-px h-6 bg-[var(--color-border-medium)] flex-shrink-0"></div>

          {/* Code */}
          <button
            onClick={() => editor?.chain().focus().toggleCode().run()}
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive("code")
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            disabled={!editor?.can().chain().focus().toggleCode().run()}
            title="Code"
          >
            <Code size={16} strokeWidth={2} />
          </button>

          <button
            onClick={() => editor?.chain().focus().toggleCodeBlock().run()}
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive("codeBlock")
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            title="Code Block"
          >
            <Code size={16} strokeWidth={2} />
          </button>

          <button
            onClick={() => editor?.chain().focus().toggleBlockquote().run()}
            className={`p-2 rounded flex-shrink-0 transition-all border ${
              editor?.isActive("blockquote")
                ? "bg-[var(--color-accent-primary)] text-white dark:text-black"
                : `${hoverClass} border-[var(--color-border-medium)]`
            }`}
            title="Blockquote"
          >
            <Quote size={16} strokeWidth={2} />
          </button>

          {/* Divider */}
          <div className="w-px h-6 bg-[var(--color-border-medium)] flex-shrink-0"></div>

          {/* Table */}
          <button
            onClick={insertTable}
            className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)]`}
            title="Insert Table"
          >
            <TableIcon size={16} strokeWidth={2} />
          </button>

          {/* Divider */}
          <div className="w-px h-6 bg-[var(--color-border-medium)] flex-shrink-0"></div>

          {/* File Actions */}
          <label
            className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)] cursor-pointer flex items-center justify-center gap-1.5`}
            title="Import"
          >
            <Upload size={16} strokeWidth={2} />
            <input
              type="file"
              accept=".txt,.md,.json"
              onChange={handleImport}
              className="hidden"
            />
          </label>

          <button
            onClick={handleExport}
            className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)] flex items-center justify-center gap-1.5`}
            title="Export to PDF"
            disabled={!currentDoc}
          >
            <Download size={16} strokeWidth={2} />
          </button>

          <button
            onClick={handleExportDocx}
            className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)] flex items-center justify-center`}
            title="Export to DOCX"
            disabled={!currentDoc}
          >
            <Download size={16} strokeWidth={2} />
          </button>
        </div>
      </div>

      {/* Color Picker Modal */}
      {showColorPicker && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-[1000]"
          onClick={() => setShowColorPicker(false)}
        >
          <div
            className={`${glassClass} rounded-lg p-6 min-w-[320px] border border-[var(--color-border-medium)] shadow-2xl`}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-sm font-bold mb-4">Text Color</h3>
            <div className="grid grid-cols-5 gap-2 mb-4">
              {colors.map((color) => (
                <button
                  key={color}
                  onClick={() => {
                    editor.chain().focus().setColor(color).run();
                    setTextColor(color);
                    setShowColorPicker(false);
                    if (showToast) showToast("Color applied", "success", 1500);
                  }}
                  className="w-10 h-10 rounded border-2 border-[var(--color-border-medium)] hover:scale-110 transition-transform"
                  style={{ backgroundColor: color }}
                  title={color}
                />
              ))}
            </div>
            <div className="flex gap-2">
              <input
                type="color"
                value={textColor}
                onChange={(e) => setTextColor(e.target.value)}
                className="flex-1 h-10 rounded border border-[var(--color-border-medium)]"
              />
              <button
                onClick={() => {
                  editor.chain().focus().setColor(textColor).run();
                  setShowColorPicker(false);
                  if (showToast) showToast("Color applied", "success", 1500);
                }}
                className={`px-4 py-2 rounded bg-[var(--color-accent-primary)] text-[var(--color-bg-primary)] font-semibold ${hoverClass}`}
              >
                Apply
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Font Family Dialog */}
      {showFontFamilyDialog && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-[1000]"
          onClick={() => setShowFontFamilyDialog(false)}
        >
          <div
            className={`${glassClass} rounded-lg p-6 min-w-[320px] max-w-md border border-[var(--color-border-medium)] shadow-2xl`}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-sm font-bold mb-4">Font Family</h3>
            <div className="space-y-2 max-h-[400px] overflow-y-auto">
              {fontFamilies.map((font) => (
                <button
                  key={font.value}
                  onClick={() => {
                    onFontChange(font.value);
                    setShowFontFamilyDialog(false);
                    if (showToast)
                      showToast(
                        `Font changed to ${font.name}`,
                        "success",
                        1500
                      );
                  }}
                  className={`w-full p-3 rounded border text-left transition-all ${
                    fontFamily === font.value
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                  style={{ fontFamily: font.value }}
                >
                  {font.name}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Font Size Dialog */}
      {showFontSizeDialog && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-[1000]"
          onClick={() => setShowFontSizeDialog(false)}
        >
          <div
            className={`${glassClass} rounded-lg p-6 min-w-[320px] border border-[var(--color-border-medium)] shadow-2xl`}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-sm font-bold mb-4">Font Size</h3>
            <div className="grid grid-cols-4 gap-2">
              {fontSizes.map((size) => (
                <button
                  key={size}
                  onClick={() => {
                    onFontSizeChange(size);
                    setShowFontSizeDialog(false);
                    if (showToast)
                      showToast(`Font size: ${size}px`, "success", 1500);
                  }}
                  className={`p-3 rounded border font-semibold transition-all ${
                    fontSize === size
                      ? "bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-white dark:text-black"
                      : `${hoverClass} border-[var(--color-border-medium)]`
                  }`}
                >
                  {size}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Link Dialog */}
      {showLinkDialog && (
        <div
          className="fixed inset-0 bg-black/50 flex items-center justify-center z-[1000]"
          onClick={() => setShowLinkDialog(false)}
        >
          <div
            className={`${glassClass} rounded-lg p-6 min-w-[320px] border border-[var(--color-border-medium)] shadow-2xl`}
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-sm font-bold mb-4">Insert Link</h3>
            <div className="space-y-3">
              <input
                type="url"
                placeholder="https://example.com"
                value={linkUrl}
                onChange={(e) => setLinkUrl(e.target.value)}
                className="w-full px-3 py-2 rounded border border-[var(--color-border-medium)] bg-[var(--color-bg-primary)] focus:outline-none focus:border-[var(--color-accent-primary)]"
                autoFocus
              />
              <div className="flex gap-2">
                <button
                  onClick={insertLink}
                  className={`flex-1 px-4 py-2 rounded bg-[var(--color-accent-primary)] text-[var(--color-bg-primary)] font-semibold ${hoverClass}`}
                >
                  Insert
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
