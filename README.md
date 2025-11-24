# SimpleNote - Advanced Text Editor

A modern, feature-rich text editor with AI integration capabilities, built with React and Flask.

## ✨ Features

### Core Features
- 📝 Multi-document support with real-time auto-save
- 🎨 Black and white minimalist design with dark mode
- 📱 Collapsible sidebars for focused writing
- 🔄 Auto-focus and cursor positioning
- 🗂️ Recently edited documents move to top
- 🔗 Hash-based routing for direct document access

### Editing Tools
- **Text Formatting**: Bold, Italic, Underline
- **Alignment**: Left, Center, Right
- **Lists**: Bullet points and numbered lists
- **Font Control**: Size and color customization with color picker
- **Insert Options**: Tables, horizontal lines, images, videos, links

### Advanced Features
- 🎙️ **Speech-to-Text**: Real-time voice recording with visual feedback
- 📄 **File Import**: Import .txt and .docx files as new documents with formatting preserved
- 📥 **PDF Export**: Convert documents to PDF with loading indicator
- 🔤 **Markdown**: Toggle markdown mode for easy formatting
- 📎 **Attachments**: Upload images and videos directly into documents
- 📊 **Enhanced Tables**: Beautiful dialog for creating tables with customizable rows/columns

### AI Integration (Coming Soon)
- Text summarization
- Content rewriting
- Smart suggestions

## 🚀 Quick Start

### Prerequisites
- Node.js (v16 or higher)
- Python 3.8+
- npm or yarn

### Installation

1. **Clone the repository**
```bash
git clone <your-repo-url>
cd simpleNote
```

2. **Install Frontend Dependencies**
```bash
cd frontend
npm install
```

3. **Install Backend Dependencies**
```bash
cd ../backend_flask
pip install -r requirements.txt
```

4. **Start the Application**

**Option 1: Using the startup script**
```bash
chmod +x start-flask.sh
./start-flask.sh
```

**Option 2: Manual start**

Terminal 1 (Backend):
```bash
cd backend_flask
python app.py
```

Terminal 2 (Frontend):
```bash
cd frontend
npm run dev
```

5. **Access the App**
Open your browser and navigate to:
```
http://localhost:5173
```

## 🎯 Usage Guide

### Voice Recording
1. Click the microphone icon in the toolbar
2. Allow microphone permissions when prompted
3. Start speaking - text will appear in real-time
4. Click again to stop recording

### File Import
- Click the upload icon in the toolbar
- Select .txt or .docx files
- A new document will be created with the file's content and title
- Original formatting is preserved for .docx files
- Loading spinner shows progress during upload

### PDF Export
- Click the download icon in the toolbar
- Loading spinner indicates export in progress
- Document will be saved as PDF with all formatting, images, and styles preserved
- Professional page layout with proper margins

### Markdown Mode
- Click the code icon to toggle markdown
- Edit text with markdown syntax
- Toggle off to render as HTML

### Tables
- Click the table icon in the toolbar
- A dialog appears to set rows and columns
- First row is automatically styled as header
- Tables include professional styling with borders and backgrounds
- Click Insert to add the table to your document

### Document Management
- Create new documents with the + button
- Documents auto-sort by last edited
- Click any document to switch
- Use trash icon to delete (requires >1 document)
- URL automatically updates with document ID for easy sharing

### Color Picker
- Click the palette icon in the toolbar
- Use the full color picker for custom colors
- Or choose from 8 preset colors
- Click to apply color to selected text
- Color picker closes automatically after selection

## 🛠️ Tech Stack

### Frontend
- React 18
- Tailwind CSS
- Lucide Icons
- Marked (Markdown parser)
- html2pdf.js (PDF export)
- Mammoth (DOCX parser)
- Web Speech API

### Backend
- Python Flask
- SQLite
- CORS support

## 📁 Project Structure

```
simpleNote/
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Editor.jsx
│   │   │   ├── Sidebar.jsx
│   │   │   ├── Toolbar.jsx
│   │   │   └── AIPanel.jsx
│   │   ├── services/
│   │   │   └── api.js
│   │   ├── App.jsx
│   │   ├── index.css
│   │   └── main.jsx
│   ├── package.json
│   └── ...
├── backend_flask/
│   ├── app.py
│   ├── requirements.txt
│   └── database.db
├── start-flask.sh
└── README.md
```

## 🎨 Customization

### Theme Colors
Edit `/frontend/src/index.css` to customize the black and white theme:
- Light mode: CSS variables define all colors
- Dark mode: Automatically removes borders for cleaner look
- Customize accent colors, backgrounds, and borders as needed

## 🐛 Troubleshooting

### Voice Recording Not Working
- Use Chrome, Edge, or Safari (Firefox has limited support)
- Ensure microphone permissions are granted
- Check browser console for errors

### PDF Export Issues
- Large documents may take longer to export
- Check browser console for errors
- Ensure pop-up blocker is disabled

### File Upload Not Working
- Check file format (.txt or .docx only)
- Verify file size (<10MB recommended)
- Ensure browser has file access permissions
- Watch for loading spinner - upload may take a few seconds
- New document will appear at the top of the sidebar when complete

### Dark Mode Border Issues
- Borders are automatically hidden in dark mode
- If you see borders, check that dark mode is properly enabled

## 📝 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🤝 Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## 💡 Future Enhancements

- [ ] Real-time collaboration
- [ ] Cloud sync
- [ ] Mobile app
- [ ] Advanced AI features
- [ ] Custom theme builder
- [ ] Plugin system
- [ ] Version history
- [ ] Search across documents

---

Built with ❤️ using React and Flask
