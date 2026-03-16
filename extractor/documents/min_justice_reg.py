from .simple_base import BaseSimpleDocumentHandler

class MinJusticeRegCertHandler(BaseSimpleDocumentHandler):
    document_code = "00010"
    label = "Ministry of Justice Registration Certificate"
    desc_instruction = "The description corresponds to the document title (1–2 sentences, **keep in Russian**)."