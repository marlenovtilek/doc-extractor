from .simple_base import BaseSimpleDocumentHandler

class OtherDocumentsHandler(BaseSimpleDocumentHandler):
    document_code = "09999"
    label = "Other Documents"
    desc_instruction = "The name of the document, depending on what the document is. Example: 'Свидетельство', 'Лицензия', 'Письмо'. Only in russian."