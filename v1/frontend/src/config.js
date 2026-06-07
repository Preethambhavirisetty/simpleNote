// Determine API URL based on environment
const getApiUrl = () => {
  // If explicitly set via env var, use it
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }
  
  // In production (when served from same origin), use empty string
  // Nginx will proxy /api requests to the backend
  if (import.meta.env.PROD) {
    return ''; // Same origin - Nginx handles proxying
  }
  
  // In development, connect to backend directly
  return 'http://localhost:5002';
};

export const API_URL = getApiUrl();

// Debug log (remove in production if needed)
console.log('API_URL:', API_URL);
console.log('Environment:', import.meta.env.MODE);

