/**
 * Download a backend file (blob) to the user's disk.
 *
 * The common inline pattern — detached <a>, click(), immediate revokeObjectURL —
 * is unreliable: some browsers need the anchor attached to the DOM, and revoking
 * synchronously can abort the download before it starts. Backend error responses
 * (JSON blobs) are also detected here so the user sees a message instead of
 * silently saving an error file.
 */
import apiClient from '../../../lib/api-client';

export async function downloadFile(
  url: string,
  params: Record<string, unknown> | undefined,
  filename: string,
): Promise<void> {
  try {
    const res = await apiClient.get(url, { params, responseType: 'blob' });
    const data = res.data as Blob;

    // In blob mode axios resolves even 4xx/5xx responses — detect JSON error bodies.
    if (data.type?.includes('application/json')) {
      throw new Error(await readErrorDetail(data));
    }

    const blobUrl = URL.createObjectURL(data);
    const a = document.createElement('a');
    a.href = blobUrl;
    a.download = filename;
    document.body.appendChild(a); // required for click() to register in some browsers
    a.click();
    a.remove();
    // Defer revocation so the browser can start reading the blob first.
    setTimeout(() => URL.revokeObjectURL(blobUrl), 1000);
  } catch (error) {
    const message = error instanceof Error ? error.message : 'Download failed';
    console.error('Download failed:', error);
    window.alert(message);
  }
}

async function readErrorDetail(blob: Blob): Promise<string> {
  try {
    const parsed = JSON.parse(await blob.text());
    if (parsed?.detail) return `Download failed: ${String(parsed.detail)}`;
  } catch {
    /* not JSON despite the content-type — fall through to generic message */
  }
  return 'Download failed';
}
