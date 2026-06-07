import React, { useState, useRef, useEffect } from 'react';
import { Mic } from 'lucide-react';

export default function VoiceRecorder({ editor, showToast, hoverClass }) {
  const [isRecording, setIsRecording] = useState(false);
  const [transcript, setTranscript] = useState('');
  const recognitionRef = useRef(null);

  useEffect(() => {
    if (!editor) return;

    if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
      const SpeechRecognition =
        window.SpeechRecognition || window.webkitSpeechRecognition;

      if (!recognitionRef.current) {
        const recognitionInstance = new SpeechRecognition();
        recognitionInstance.continuous = true;
        recognitionInstance.interimResults = true;
        recognitionInstance.lang = 'en-US';
        recognitionInstance.maxAlternatives = 1;

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
            editor.chain().focus().insertContent(finalTranscript).run();
          }
        };

        recognitionInstance.onerror = (event) => {
          console.error('Speech recognition error:', event.error);
          recognitionRef.current.shouldContinue = false;
          setIsRecording(false);
          setTranscript('');
          showToast?.(`Speech error: ${event.error}`, 'error', 3000);
        };

        recognitionInstance.onend = () => {
          if (recognitionRef.current.shouldContinue) {
            try {
              recognitionInstance.start();
            } catch (err) {
              console.error('Error restarting:', err);
            }
          } else {
            setIsRecording(false);
            setTranscript('');
          }
        };

        recognitionRef.current = recognitionInstance;
        recognitionRef.current.shouldContinue = false;
      }
    }
  }, [editor, showToast]);

  const handleVoiceRecording = () => {
    const recognition = recognitionRef.current;

    if (!recognition) {
      showToast?.(
        'Speech recognition not supported. Use Chrome, Edge, or Safari.',
        'error',
        3000
      );
      return;
    }

    if (isRecording) {
      try {
        if (recognitionRef.current) {
          recognitionRef.current.shouldContinue = false;
        }
        recognition.abort();
        setIsRecording(false);
        setTranscript('');
        showToast?.('Voice stopped', 'success', 1000);
      } catch (error) {
        console.error('Error stopping recognition:', error);
        setIsRecording(false);
        setTranscript('');
        if (recognitionRef.current) {
          recognitionRef.current.shouldContinue = false;
        }
      }
    } else {
      try {
        if (recognitionRef.current) {
          recognitionRef.current.shouldContinue = true;
        }
        recognition.start();
        setIsRecording(true);
        showToast?.('Listening... Speak now', 'info', 2000);
      } catch (error) {
        console.error('Error starting recognition:', error);
        setIsRecording(false);
        if (recognitionRef.current) {
          recognitionRef.current.shouldContinue = false;
        }
        showToast?.('Failed to start voice recording', 'error', 2000);
      }
    }
  };

  return (
    <div className="mb-4">
      <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--color-text-muted)] mb-2 pb-1 border-b border-[var(--color-border-light)]">
        Speech-to-Text
      </div>

      <button
        onClick={handleVoiceRecording}
        className={`w-full p-2 rounded transition-all border ${
          isRecording
            ? 'bg-[var(--color-accent-primary)] border-[var(--color-accent-primary)] text-[var(--color-bg-primary)] animate-pulse'
            : `${hoverClass} border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)]`
        }`}
        title={isRecording ? 'Stop Recording' : 'Start Voice Recording'}
      >
        <Mic size={14} strokeWidth={2} className="mx-auto" />
      </button>

      {isRecording && (
        <div className="mt-2 text-center">
          <div className="flex items-center justify-center gap-1 mb-1">
            <div className="w-1 h-1 bg-[var(--color-accent-primary)] rounded-full animate-pulse"></div>
            <div
              className="w-1 h-1 bg-[var(--color-accent-primary)] rounded-full animate-pulse"
              style={{ animationDelay: '0.2s' }}
            ></div>
            <div
              className="w-1 h-1 bg-[var(--color-accent-primary)] rounded-full animate-pulse"
              style={{ animationDelay: '0.4s' }}
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
  );
}

// Export for mobile toolbar
export function VoiceButton({ editor, showToast, hoverClass, isRecording, onToggle }) {
  return (
    <button
      onClick={onToggle}
      className={`p-2 rounded flex-shrink-0 transition-all border ${hoverClass} border-[var(--color-border-medium)] ${
        isRecording ? 'animate-pulse bg-red-500/20' : ''
      }`}
      title="Voice Input"
    >
      <Mic size={16} strokeWidth={2} />
    </button>
  );
}

