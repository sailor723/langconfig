"""Shared document-type resolution from file extensions.

Consolidates the doc_type_map dictionaries that were previously duplicated
across workspace routes, knowledge RAG, and chat routes into one canonical
map plus a small resolver.
"""

from models.core import DocumentType

# Canonical extension -> DocumentType map (keys without leading dots).
EXT_TO_DOC_TYPE = {
    'txt': DocumentType.TEXT,
    'md': DocumentType.MARKDOWN,
    'pdf': DocumentType.PDF,
    'json': DocumentType.JSON,
    'py': DocumentType.CODE,
    'js': DocumentType.CODE,
    'ts': DocumentType.CODE,
    'tsx': DocumentType.CODE,
    'jsx': DocumentType.CODE,
    'java': DocumentType.CODE,
    'c': DocumentType.CODE,
    'cpp': DocumentType.CODE,
    'h': DocumentType.CODE,
    'hpp': DocumentType.CODE,
    'cs': DocumentType.CODE,
    'rb': DocumentType.CODE,
    'go': DocumentType.CODE,
    'rs': DocumentType.CODE,
    'php': DocumentType.CODE,
    'swift': DocumentType.CODE,
    'kt': DocumentType.CODE,
    'scala': DocumentType.CODE,
    'r': DocumentType.CODE,
    'sql': DocumentType.CODE,
    'sh': DocumentType.CODE,
    'bash': DocumentType.CODE,
    'html': DocumentType.HTML,
    'htm': DocumentType.HTML,
    'xml': DocumentType.XML,
    'csv': DocumentType.CSV,
    'yaml': DocumentType.YAML,
    'yml': DocumentType.YAML,
    'doc': DocumentType.DOCX,
    'docx': DocumentType.DOCX,
    'rtf': DocumentType.TEXT,
    'odt': DocumentType.TEXT,
    'epub': DocumentType.TEXT,
    'ppt': DocumentType.TEXT,
    'pptx': DocumentType.TEXT,
    'xls': DocumentType.CSV,
    'xlsx': DocumentType.CSV,
    'png': DocumentType.IMAGE,
    'jpg': DocumentType.IMAGE,
    'jpeg': DocumentType.IMAGE,
    'gif': DocumentType.IMAGE,
    'bmp': DocumentType.IMAGE,
    'tiff': DocumentType.IMAGE,
    'webp': DocumentType.IMAGE,
}


def resolve_document_type(filename_or_ext: str) -> DocumentType:
    """Resolve a DocumentType from a filename or extension (dot optional).

    Accepts ".md", "md", or "README.md"; unknown extensions fall back to TEXT.
    """
    ext = filename_or_ext.rsplit('.', 1)[-1].lower()
    return EXT_TO_DOC_TYPE.get(ext, DocumentType.TEXT)
