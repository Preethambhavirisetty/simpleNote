// Determine API URL based on environment
const getApiUrl = () => {
  // If explicitly set via env var, use it
  if (import.meta.env.VITE_API_URL) {
    return import.meta.env.VITE_API_URL;
  }
  
  // In production (when served from same origin), use relative path
  if (import.meta.env.PROD) {
    return ''; // Empty string means same origin, Nginx will proxy /api to backend
  }
  
  // In development, connect to backend directly
  return 'http://localhost:5002';
};

export const API_URL = getApiUrl();

