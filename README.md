# SimpleNote - Advanced Text Editor

A modern, full-stack text editor with multi-page support, rich formatting, and built-in infrastructure for AI-powered features including speech-to-text, text summarization, and intelligent rewriting.

## 🚀 Features

### Current Features
- **Multi-Document Support**: Create, edit, and manage multiple documents
- **Rich Text Editing**: Bold, italic, underline, alignment, lists, and more
- **Template System**: Pre-built templates for meetings, journals, to-do lists, and more
- **Theme Support**: Light and dark mode with beautiful glassmorphic UI
- **Auto-Save**: Automatic saving to backend database
- **Persistent Storage**: All documents saved to SQLite database
- **Modern UI**: Beautiful gradient backgrounds with glass-morphism effects

### Future-Ready Architecture
- **AI Integration Ready**: Pre-built endpoints for text summarization and rewriting
- **Speech-to-Text Ready**: Infrastructure for voice recording and transcription
- **Scalable Database**: SQLite with tables for documents, AI interactions, and speech sessions
- **RESTful API**: Clean, documented API endpoints

## 🏗️ Architecture

```
simpleNote/
├── backend/                  # Express.js API server
│   ├── server.js            # Main server with REST API
│   ├── package.json         # Backend dependencies
│   └── notes.db             # SQLite database (auto-created)
│
├── frontend/                # React + Vite frontend
│   ├── src/
│   │   ├── components/      # React components
│   │   │   ├── Sidebar.jsx
│   │   │   ├── Editor.jsx
│   │   │   ├── Toolbar.jsx
│   │   │   ├── TemplateSelector.jsx
│   │   │   └── AIPanel.jsx
│   │   ├── services/        # API integration
│   │   │   └── api.js
│   │   ├── utils/           # Utilities
│   │   │   └── templates.js
│   │   ├── App.jsx          # Main app component
│   │   ├── main.jsx         # Entry point
│   │   └── index.css        # Global styles
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── tailwind.config.js
│
└── main.jsx                 # Original file (can be removed)
```

## 📦 Installation

### Prerequisites
- Node.js 16+ and npm
- Git

### Setup Instructions

1. **Clone or navigate to the project**
   ```bash
   cd simpleNote
   ```

2. **Install Backend Dependencies**
   ```bash
   cd backend
   npm install
   ```

3. **Install Frontend Dependencies**
   ```bash
   cd ../frontend
   npm install
   ```

4. **Install additional Tailwind plugin**
   ```bash
   npm install -D @tailwindcss/typography
   ```

## 🚀 Running the Application

You need to run both the backend and frontend servers.

### Terminal 1: Start Backend Server
```bash
cd backend
npm start
```
The backend API will run on `http://localhost:3001`

### Terminal 2: Start Frontend Development Server
```bash
cd frontend
npm run dev
```
The frontend will run on `http://localhost:3000`

Open your browser and navigate to `http://localhost:3000`

## 🔌 API Endpoints

### Document Management
- `GET /api/documents` - Get all documents
- `GET /api/documents/:id` - Get specific document
- `POST /api/documents` - Create new document
- `PUT /api/documents/:id` - Update document
- `DELETE /api/documents/:id` - Delete document (soft delete)

### AI Features (Ready for Integration)
- `POST /api/ai/summarize` - Summarize selected text
  ```json
  {
    "documentId": "string",
    "selectedText": "string"
  }
  ```

- `POST /api/ai/rewrite` - Rewrite text with style
  ```json
  {
    "documentId": "string",
    "selectedText": "string",
    "style": "professional|casual"
  }
  ```

### Speech-to-Text (Ready for Integration)
- `POST /api/speech/transcribe` - Transcribe audio to text
  ```json
  {
    "documentId": "string",
    "audioData": "base64_encoded_audio"
  }
  ```

## 🤖 Adding AI Features

The application is designed to easily integrate AI capabilities:

### 1. Text Summarization & Rewriting

Update `/backend/server.js` endpoints to integrate with your preferred AI service:

**Option A: OpenAI**
```javascript
const OpenAI = require('openai');
const openai = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });

app.post('/api/ai/summarize', async (req, res) => {
  const { selectedText } = req.body;
  
  const completion = await openai.chat.completions.create({
    model: "gpt-3.5-turbo",
    messages: [
      {
        role: "system",
        content: "Summarize the following text concisely:"
      },
      {
        role: "user",
        content: selectedText
      }
    ]
  });
  
  res.json({ summary: completion.choices[0].message.content });
});
```

**Option B: Anthropic Claude**
```javascript
const Anthropic = require('@anthropic-ai/sdk');
const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

app.post('/api/ai/summarize', async (req, res) => {
  const { selectedText } = req.body;
  
  const message = await client.messages.create({
    model: "claude-3-sonnet-20240229",
    max_tokens: 1024,
    messages: [
      {
        role: "user",
        content: `Summarize this text: ${selectedText}`
      }
    ]
  });
  
  res.json({ summary: message.content[0].text });
});
```

**Option C: Local Models (Ollama)**
```javascript
const axios = require('axios');

app.post('/api/ai/summarize', async (req, res) => {
  const { selectedText } = req.body;
  
  const response = await axios.post('http://localhost:11434/api/generate', {
    model: 'llama2',
    prompt: `Summarize this text: ${selectedText}`,
    stream: false
  });
  
  res.json({ summary: response.data.response });
});
```

### 2. Speech-to-Text Integration

**Option A: Web Speech API (Browser-based)**

Update `/frontend/src/components/Toolbar.jsx`:
```javascript
const handleVoiceRecording = () => {
  if (!isRecording) {
    const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
    recognition.continuous = true;
    recognition.interimResults = true;

    recognition.onresult = (event) => {
      const transcript = Array.from(event.results)
        .map(result => result[0].transcript)
        .join('');
      
      // Insert transcript into editor
      document.execCommand('insertText', false, transcript);
    };

    recognition.start();
    setIsRecording(true);
  } else {
    recognition.stop();
    setIsRecording(false);
  }
};
```

**Option B: External Service (Deepgram, AssemblyAI)**
```javascript
// Backend implementation
const axios = require('axios');

app.post('/api/speech/transcribe', async (req, res) => {
  const { audioData } = req.body;
  
  const response = await axios.post('https://api.deepgram.com/v1/listen', 
    Buffer.from(audioData, 'base64'),
    {
      headers: {
        'Authorization': `Token ${process.env.DEEPGRAM_API_KEY}`,
        'Content-Type': 'audio/wav'
      }
    }
  );
  
  res.json({ transcript: response.data.results.channels[0].alternatives[0].transcript });
});
```

## 🎨 Customization

### Adding New Templates

Edit `/frontend/src/utils/templates.js`:
```javascript
export const templates = {
  // ... existing templates
  myTemplate: {
    name: 'My Custom Template',
    content: '<h2>Title</h2><p>Content...</p>'
  }
};
```

### Styling

The app uses Tailwind CSS. Modify styles in:
- `/frontend/src/index.css` - Global styles
- Component files - Component-specific styles

## 🗄️ Database Schema

### documents
- `id` (TEXT PRIMARY KEY)
- `title` (TEXT)
- `content` (TEXT)
- `created_at` (TEXT)
- `updated_at` (TEXT)
- `is_deleted` (INTEGER)

### ai_interactions
- `id` (INTEGER PRIMARY KEY)
- `document_id` (TEXT)
- `interaction_type` (TEXT)
- `input_text` (TEXT)
- `output_text` (TEXT)
- `created_at` (TEXT)

### speech_sessions
- `id` (INTEGER PRIMARY KEY)
- `document_id` (TEXT)
- `transcript` (TEXT)
- `duration` (INTEGER)
- `created_at` (TEXT)

## 🔐 Environment Variables

Create a `.env` file in the backend directory:
```env
PORT=3001
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
DEEPGRAM_API_KEY=your_key_here
```

## 🚢 Production Deployment

### Build Frontend
```bash
cd frontend
npm run build
```

### Serve Static Files
Update backend server.js:
```javascript
app.use(express.static(path.join(__dirname, '../frontend/dist')));

app.get('*', (req, res) => {
  res.sendFile(path.join(__dirname, '../frontend/dist/index.html'));
});
```

### Deploy Options
- **Vercel/Netlify**: Frontend
- **Heroku/Railway**: Backend + Database
- **Docker**: Full stack containerization

## 📝 Development Tips

1. **Hot Reload**: Both servers support hot reload
2. **Database Reset**: Delete `backend/notes.db` to reset
3. **API Testing**: Use Postman or `curl` to test endpoints
4. **Debugging**: Check browser console and backend terminal

## 🤝 Contributing

Feel free to contribute by:
1. Adding new features
2. Improving UI/UX
3. Integrating AI services
4. Adding tests
5. Improving documentation

## 📄 License

See LICENSE file for details.

## 🎯 Roadmap

- [ ] Real-time collaboration
- [ ] Export to PDF/Word
- [ ] Cloud sync
- [ ] Mobile app
- [ ] Browser extensions
- [ ] Offline mode
- [ ] End-to-end encryption

## 💡 Tips for AI Integration

1. **Rate Limiting**: Implement rate limiting for AI endpoints
2. **Caching**: Cache AI responses to reduce API costs
3. **Streaming**: Add streaming support for real-time AI responses
4. **Error Handling**: Add robust error handling for AI failures
5. **User Feedback**: Show loading states and error messages

---

Built with ❤️ using React, Express, and SQLite

