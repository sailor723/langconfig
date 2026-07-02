/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { useState, useRef, KeyboardEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Send } from 'lucide-react';
import FileUploadButton from './FileUploadButton';
import type { SessionDocument } from '../types/chat';

interface MessageInputProps {
  onSendMessage: (message: string) => void;
  disabled?: boolean;
  isStreaming?: boolean;
  placeholder?: string;
  sessionId?: string | null;
  projectId?: number | null;
  onFileUploaded?: (file: SessionDocument) => void;
}

export default function MessageInput({
  onSendMessage,
  disabled = false,
  isStreaming = false,
  sessionId = null,
  projectId = null,
  onFileUploaded = () => {}
}: MessageInputProps) {
  const { t } = useTranslation('chat');
  const [inputValue, setInputValue] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);

  const handleSend = () => {
    const message = inputValue.trim();
    if (!message || disabled || isStreaming) return;

    onSendMessage(message);
    setInputValue('');

    setTimeout(() => {
      inputRef.current?.focus();
    }, 100);
  };

  const handleKeyPress = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex gap-2 items-center">
      <FileUploadButton
        sessionId={sessionId}
        projectId={projectId}
        onFileUploaded={onFileUploaded}
        disabled={disabled || isStreaming}
      />

      <input
        ref={inputRef}
        type="text"
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyPress={handleKeyPress}
        placeholder={t('type_message')}
        disabled={disabled || isStreaming}
        className="flex-1 px-3 py-2 rounded-lg border focus:outline-none focus:ring-2 transition-all disabled:opacity-50 disabled:cursor-not-allowed text-sm"
        style={{
          backgroundColor: 'var(--color-input-background)',
          borderColor: 'var(--color-border-dark)',
          color: 'var(--color-text-primary)',
        }}
        autoFocus
      />

      <button
        onClick={handleSend}
        disabled={!inputValue.trim() || disabled || isStreaming}
        className="px-4 py-2 rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed hover:opacity-90 flex items-center justify-center"
        style={{
          backgroundColor: 'var(--color-primary)',
          color: 'white',
        }}
        title={t('send_message')}
      >
        <Send className="w-4 h-4" />
      </button>
    </div>
  );
}