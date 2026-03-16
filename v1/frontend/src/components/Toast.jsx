import React, { useEffect } from 'react';
import { X, CheckCircle, AlertCircle, Loader } from 'lucide-react';

export default function Toast({ message, type = 'info', onClose, duration = 3000 }) {
  useEffect(() => {
    if (type !== 'loading' && duration > 0) {
      const timer = setTimeout(onClose, duration);
      return () => clearTimeout(timer);
    }
  }, [duration, onClose, type]);

  const iconColors = {
    success: 'text-green-600 dark:text-green-400',
    error: 'text-red-600 dark:text-red-400',
    loading: 'text-blue-600 dark:text-blue-400',
    info: 'text-blue-600 dark:text-blue-400'
  };

  const bgColors = {
    success: 'bg-green-50 dark:bg-green-900/30 border-green-200 dark:border-green-600',
    error: 'bg-red-50 dark:bg-red-900/30 border-red-200 dark:border-red-600',
    loading: 'bg-blue-50 dark:bg-blue-900/30 border-blue-200 dark:border-blue-600',
    info: 'bg-blue-50 dark:bg-blue-900/30 border-blue-200 dark:border-blue-600'
  };

  const icons = {
    success: <CheckCircle size={20} className={iconColors[type]} />,
    error: <AlertCircle size={20} className={iconColors[type]} />,
    loading: <Loader size={20} className={`${iconColors[type]} animate-spin`} />,
    info: <AlertCircle size={20} className={iconColors[type]} />
  };

  return (
    <div 
      className={`fixed top-20 right-6 z-[9999] flex items-center gap-3 px-4 py-3 rounded-lg shadow-2xl border-2 ${bgColors[type]} animate-slide-in min-w-[300px]`}
      style={{
        backdropFilter: 'blur(10px)',
        WebkitBackdropFilter: 'blur(10px)'
      }}
    >
      {icons[type]}
      <span className="flex-1 font-medium text-gray-900 dark:text-white">{message}</span>
      {type !== 'loading' && (
        <button
          onClick={onClose}
          className="p-1 hover:bg-black/10 dark:hover:bg-white/10 rounded transition-all text-gray-700 dark:text-gray-300"
        >
          <X size={16} />
        </button>
      )}
    </div>
  );
}

