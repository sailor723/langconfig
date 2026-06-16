"""
Simple PDF Chat with Upload — read a PDF, load all text, chat with DeepSeek.

Usage:
    uv run python chat_pdf_simple.py                     # auto-detect PDF
    uv run python chat_pdf_simple.py /path/to/file.pdf   # specify path
    uv run python chat_pdf_simple.py --serve             # web upload mode
"""
import sys
import os
import tempfile
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from pypdf import PdfReader
from openai import OpenAI


def extract_text(pdf_path: str) -> str:
    """Extract all text from a PDF file."""
    reader = PdfReader(pdf_path)
    pages = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text()
        if text and text.strip():
            pages.append(f"--- Page {i}/{len(reader.pages)} ---\n{text.strip()}")
    return "\n\n".join(pages)


def chat_loop(full_text: str):
    """Interactive chat with DeepSeek about the PDF content."""
    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"),
        base_url="https://api.deepseek.com",
    )

    messages = [
        {
            "role": "system",
            "content": "You are a helpful assistant. Answer questions based on the PDF content below. "
                       f"Here is the full PDF text:\n\n{full_text}",
        }
    ]

    print("\nReady! Ask questions about the PDF (type 'quit' to exit).")
    print("-" * 50)

    while True:
        try:
            question = input("\n❓ You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if question.lower() in ("quit", "exit", "q"):
            break
        if not question:
            continue

        messages.append({"role": "user", "content": question})
        response = client.chat.completions.create(
            model="deepseek-chat",
            messages=messages,
            temperature=0.3,
        )
        answer = response.choices[0].message.content
        print(f"\n🤖 DeepSeek: {answer}")
        messages.append({"role": "assistant", "content": answer})


# --- Web upload server (used with --serve) ---

UPLOAD_HTML = """<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"><title>Upload PDF</title>
<style>
  body{font-family:sans-serif;max-width:600px;margin:2em auto;padding:0 1em}
  .box{border:2px dashed #888;border-radius:12px;padding:2em;text-align:center}
  input[type=file]{margin:1em 0}
  button{background:#4f46e5;color:#fff;border:none;padding:10px 24px;border-radius:6px;font-size:1em;cursor:pointer}
  button:hover{background:#4338ca}
  #status{margin-top:1em;color:#666}
</style></head>
<body>
  <h2>📄 Upload a PDF to Chat</h2>
  <div class="box">
    <form method="post" enctype="multipart/form-data" action="/upload">
      <input type="file" name="pdf" accept=".pdf" required><br>
      <button type="submit">Upload & Start Chat</button>
    </form>
    <div id="status"></div>
  </div>
  <p style="color:#888;font-size:0.9em">After uploading, chat with DeepSeek in the terminal.</p>
</body></html>"""


def _parse_upload(rfile, headers):
    """Parse multipart/form-data from POST request body (stdlib only)."""
    content_type = headers.get("Content-Type", "")
    boundary = None
    for part in content_type.split(";"):
        part = part.strip()
        if part.startswith("boundary="):
            boundary = part[len("boundary="):].strip().strip('"')
            break
    if not boundary:
        return None

    boundary = boundary.encode("utf-8")
    content_length = int(headers.get("Content-Length", 0))
    body = rfile.read(content_length)

    # Split by boundary and find the PDF content
    parts = body.split(b"--" + boundary)
    for part in parts:
        if b'Content-Disposition' not in part or b'filename=' not in part:
            continue
        # Split headers from body
        header_end = part.find(b"\r\n\r\n")
        if header_end == -1:
            continue
        file_data = part[header_end + 4:]
        # Remove trailing \r\n--
        if file_data.endswith(b"\r\n"):
            file_data = file_data[:-2]
        if file_data.endswith(b"--"):
            file_data = file_data[:-2]
        if file_data.endswith(b"\r\n"):
            file_data = file_data[:-2]
        return file_data
    return None


OK_HTML = b"<html><body><h2>PDF loaded!</h2><p>Check the terminal to start chatting.</p></body></html>"
ERR_HTML = b"<html><body><h2>Error</h2><p>{}</p></body></html>"


class UploadHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/upload":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(UPLOAD_HTML.encode("utf-8"))
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path != "/upload":
            self.send_error(404)
            return

        file_data = _parse_upload(self.rfile, self.headers)
        if not file_data:
            self.send_response(400)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"<html><body><h2>No PDF file received</h2></body></html>")
            return

        # Save to a temp file
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        tmp.write(file_data)
        tmp.close()

        print(f"\nUploaded PDF saved to: {tmp.name}")
        try:
            full_text = extract_text(tmp.name)
            print(f"Extracted {len(full_text):,} characters ({len(full_text.split()):,} words)")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(OK_HTML)
            # Chat in terminal after response is sent
            t = threading.Thread(target=chat_loop, args=(full_text,), daemon=True)
            t.start()
        except Exception as e:
            print(f"Error extracting text: {e}")
            self.send_response(500)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(ERR_HTML.replace(b"{}", str(e).encode("utf-8")))
        finally:
            os.unlink(tmp.name)

    def log_message(self, format, *args):
        pass  # quiet


def run_server(port=8767):
    server = HTTPServer(("0.0.0.0", port), UploadHandler)
    print(f"🌐 Open http://localhost:{port} in your browser to upload a PDF")
    print("   Press Ctrl+C to stop the server\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServer stopped.")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--serve":
        run_server()
        return

    if len(sys.argv) < 2:
        pdf_dir = "/Users/weiping/dev/Learn/langchain-ai/data"
        pdfs = [f for f in os.listdir(pdf_dir) if f.endswith(".pdf")]
        if not pdfs:
            print("No PDF found. Provide a path or drag file: uv run python chat_pdf_simple.py <pdf_path>")
            sys.exit(1)
        pdf_path = os.path.join(pdf_dir, pdfs[0])
    else:
        pdf_path = sys.argv[1]

    if not os.path.exists(pdf_path):
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    print(f"📄 Loading: {pdf_path}")
    full_text = extract_text(pdf_path)
    print(f"Extracted {len(full_text):,} characters ({len(full_text.split()):,} words)")
    chat_loop(full_text)


if __name__ == "__main__":
    main()
