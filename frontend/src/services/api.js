export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5002/api';

// Generic fetch wrapper
async function fetchAPI(endpoint, options = {}) {
  const response = await fetch(`${API_BASE_URL}${endpoint}`, {
    credentials: 'include', // IMPORTANT: Send cookies for authentication
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'API request failed');
  }

  return response.json();
}

// Document operations
export async function fetchDocuments() {
  return fetchAPI('/documents');
}

export async function fetchDocument(id) {
  return fetchAPI(`/documents/${id}`);
}

export async function createDocument(document) {
  return fetchAPI('/documents', {
    method: 'POST',
    body: JSON.stringify(document),
  });
}

export async function updateDocument(id, data) {
  return fetchAPI(`/documents/${id}`, {
    method: 'PUT',
    body: JSON.stringify(data),
  });
}

export async function deleteDocument(id) {
  return fetchAPI(`/documents/${id}`, {
    method: 'DELETE',
  });
}

// AI operations (placeholders for future implementation)
export async function summarizeText(documentId, selectedText) {
  return fetchAPI('/ai/summarize', {
    method: 'POST',
    body: JSON.stringify({ documentId, selectedText }),
  });
}

export async function rewriteText(documentId, selectedText, style) {
  return fetchAPI('/ai/rewrite', {
    method: 'POST',
    body: JSON.stringify({ documentId, selectedText, style }),
  });
}

// Speech-to-text operations (placeholder for future implementation)
export async function transcribeSpeech(documentId, audioData) {
  return fetchAPI('/speech/transcribe', {
    method: 'POST',
    body: JSON.stringify({ documentId, audioData }),
  });
}

