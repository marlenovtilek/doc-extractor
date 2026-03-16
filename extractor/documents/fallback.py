from .simple_base import BaseSimpleDocumentHandler

class FallbackElseHandler(BaseSimpleDocumentHandler):
    document_code = "ELSE"
    label = "Unknown / Fallback Document"