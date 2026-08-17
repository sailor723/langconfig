/**
 * office-compat — capture browser natives before third-party office libs
 * can replace them.
 *
 * pptxviewjs overwrites `window.FileReader` at module load with its
 * `FileReaderAsync` class. That class only has *static* methods, so a
 * `new FileReader()` instance exposes no instance methods — which breaks
 * docx-preview's jszip (it constructs a FileReader and calls
 * `readAsArrayBuffer`). We snapshot the native constructor here.
 *
 * IMPORTANT: this module must be imported BEFORE pptxviewjs in OfficeViewer
 * (ESM evaluates imports in order), and the restore must run after all
 * imports so pptxviewjs has already polluted the global.
 */
const nativeFileReader: typeof FileReader | undefined =
  typeof window !== 'undefined' && typeof window.FileReader === 'function'
    ? window.FileReader
    : undefined;

export function restoreNativeFileReader(): void {
  if (
    typeof window !== 'undefined' &&
    nativeFileReader &&
    window.FileReader !== nativeFileReader
  ) {
    window.FileReader = nativeFileReader;
  }
}

export { nativeFileReader };
