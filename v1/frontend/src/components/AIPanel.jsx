import React, { useState } from 'react';
import { X, Sparkles, RefreshCw, FileText, Loader2 } from 'lucide-react';
import * as api from '../services/api';

export default function AIPanel({
  documentId,
  selectedText,
  onClose,
  glassClass,
  hoverClass,
  textClass
}) {
  const [result, setResult] = useState('');
  const [isProcessing, setIsProcessing] = useState(false);

  const handleSummarize = async () => {
    if (!selectedText) {
      alert('Please select some text first!');
      return;
    }

    setIsProcessing(true);
    try {
      const response = await api.summarizeText(documentId, selectedText);
      setResult(response.summary || response.message);
    } catch (error) {
      setResult('Error: ' + error.message);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleRewrite = async (style = 'professional') => {
    if (!selectedText) {
      alert('Please select some text first!');
      return;
    }

    setIsProcessing(true);
    try {
      const response = await api.rewriteText(documentId, selectedText, style);
      setResult(response.rewrittenText || response.message);
    } catch (error) {
      setResult('Error: ' + error.message);
    } finally {
      setIsProcessing(false);
    }
  };

  return (
    <div className={`${glassClass} rounded-lg p-4 w-72 overflow-y-auto animate-fade-in shadow-2xl border border-[var(--color-border-medium)]`}>
      <div className="flex items-center justify-between mb-4 pb-3 border-b border-[var(--color-border-medium)]">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 rounded bg-[var(--color-accent-primary)] flex items-center justify-center">
            <Sparkles size={16} strokeWidth={2} className="text-[var(--color-bg-primary)]" />
          </div>
          <h3 className={`text-base font-bold tracking-tight ${textClass}`}>AI Tools</h3>
        </div>
        <button
          onClick={onClose}
          className={`p-1.5 rounded ${hoverClass} transition-all border border-[var(--color-border-medium)]`}
        >
          <X size={14} strokeWidth={2} />
        </button>
      </div>

      <div className="space-y-4">
        {/* Selected Text Display */}
        <div className={`p-4 rounded-md border border-[var(--color-border-medium)] bg-[var(--color-bg-tertiary)]`}>
          <p className="text-xs font-bold tracking-wider uppercase text-[var(--color-text-secondary)] mb-2">SELECTED</p>
          <p className="text-sm text-[var(--color-text-primary)] line-clamp-3 font-medium">
            {selectedText ? selectedText : 'Select text in the editor to use AI features'}
          </p>
        </div>

        {/* AI Action Buttons */}
        <div className="space-y-2">
          <button
            onClick={handleSummarize}
            disabled={isProcessing || !selectedText}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-md ${hoverClass} transition-all disabled:opacity-50 disabled:cursor-not-allowed border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)] group`}
          >
            <Sparkles size={18} strokeWidth={2} />
            <span className="font-semibold text-sm">Summarize</span>
          </button>

          <button
            onClick={() => handleRewrite('professional')}
            disabled={isProcessing || !selectedText}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-md ${hoverClass} transition-all disabled:opacity-50 disabled:cursor-not-allowed border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)] group`}
          >
            <RefreshCw size={18} strokeWidth={2} />
            <span className="font-semibold text-sm">Make Professional</span>
          </button>

          <button
            onClick={() => handleRewrite('casual')}
            disabled={isProcessing || !selectedText}
            className={`w-full flex items-center gap-3 px-4 py-3 rounded-md ${hoverClass} transition-all disabled:opacity-50 disabled:cursor-not-allowed border border-[var(--color-border-medium)] hover:border-[var(--color-accent-primary)] group`}
          >
            <FileText size={18} strokeWidth={2} />
            <span className="font-semibold text-sm">Make Casual</span>
          </button>
        </div>

        {/* Processing State */}
        {isProcessing && (
          <div className="flex items-center justify-center py-6">
            <Loader2 size={32} className="animate-spin" strokeWidth={2} />
          </div>
        )}

        {/* Result Display */}
        {result && !isProcessing && (
          <div className={`p-4 rounded-md border border-[var(--color-accent-primary)] bg-[var(--color-bg-tertiary)] animate-fade-in`}>
            <h4 className="text-xs font-bold tracking-wider uppercase text-[var(--color-text-secondary)] mb-2">Result</h4>
            <p className={`text-sm ${textClass} leading-relaxed font-medium`}>{result}</p>
          </div>
        )}

        {/* Info Box */}
        <div className={`p-4 rounded-md border border-[var(--color-border-medium)] bg-[var(--color-bg-tertiary)]`}>
          <div className="flex gap-2">
            <span className="text-lg">💡</span>
            <p className="text-xs text-[var(--color-text-secondary)] leading-relaxed font-medium">
              AI features are ready for integration. See documentation for setup instructions.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
