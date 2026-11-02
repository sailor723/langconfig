/**
 * Copyright (c) 2025 Cade Russell (Ghost Peony)
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { memo } from 'react';
import { useTranslation } from 'react-i18next';

interface SaveVersionDialogProps {
  isOpen: boolean;
  onClose: () => void;
  onSave: () => void;
  versionNotes: string;
  setVersionNotes: (notes: string) => void;
}

/**
 * Modal for saving a new workflow version with notes
 */
const SaveVersionDialog = memo(function SaveVersionDialog({
  isOpen,
  onClose,
  onSave,
  versionNotes,
  setVersionNotes,
}: SaveVersionDialogProps) {
  const { t: tr } = useTranslation('chat');
  if (!isOpen) return null;

  const handleClose = () => {
    onClose();
    setVersionNotes('');
  };

  return (
    <div
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={handleClose}
    >
      <div
        className="rounded-lg shadow-xl p-6 max-w-md w-full mx-4"
        style={{
          backgroundColor: 'var(--color-panel-dark)',
          border: '1px solid var(--color-border-dark)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        <h2
          className="text-xl font-semibold mb-4"
          style={{ color: 'var(--color-text-primary)' }}
        >
          {tr('sv_title')}
        </h2>
        <p
          className="mb-4 text-sm"
          style={{ color: 'var(--color-text-muted)' }}
        >
          Create a snapshot of your current workflow configuration. Add notes to describe what changed:
        </p>
        <textarea
          value={versionNotes}
          onChange={(e) => setVersionNotes(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              handleClose();
            }
          }}
          placeholder={tr('sv_what_changed')}
          rows={4}
          autoFocus
          className="w-full px-3 py-2 rounded-lg mb-4 border focus:outline-none focus:ring-2"
          style={{
            backgroundColor: 'var(--color-input-background)',
            borderColor: 'var(--color-border-dark)',
            color: 'var(--color-text-primary)',
          }}
        />
        <div className="flex gap-2 justify-end">
          <button
            onClick={handleClose}
            className="px-4 py-2 rounded-lg border transition-colors"
            style={{
              borderColor: 'var(--color-border-dark)',
              color: 'var(--color-text-muted)',
            }}
          >
            {tr('c_cancel')}
          </button>
          <button
            onClick={onSave}
            className="px-4 py-2 rounded-lg transition-colors"
            style={{
              backgroundColor: 'var(--color-primary)',
              color: 'white',
            }}
          >
            {tr('sv_create')}
          </button>
        </div>
      </div>
    </div>
  );
});

export default SaveVersionDialog;
