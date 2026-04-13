from __future__ import annotations

import base64
import io
from pathlib import Path


_IMAGE_EXTENSIONS = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
}


def _to_data_url(payload: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _image_file_to_data_url(path: Path) -> str:
    mime_type = _IMAGE_EXTENSIONS[path.suffix.lower()]
    return _to_data_url(path.read_bytes(), mime_type)


def render_pdf_to_data_urls(
    pdf_path: str | Path,
    *,
    dpi: int = 144,
    max_pages: int = 12,
) -> list[str]:
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - dependency is optional until VLM is used
        raise RuntimeError(
            "PDF rendering for VLM requires 'pypdfium2' and 'Pillow'. Rebuild the environment after updating dependencies."
        ) from exc

    path = Path(pdf_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Source file not found: {path}")

    scale = max(float(dpi), 72.0) / 72.0
    doc = pdfium.PdfDocument(str(path))
    try:
        page_count = min(len(doc), max_pages)
        rendered_pages: list[str] = []
        for index in range(page_count):
            page = doc[index]
            bitmap = page.render(scale=scale)
            image = bitmap.to_pil()
            buffer = io.BytesIO()
            image.save(buffer, format="PNG")
            rendered_pages.append(_to_data_url(buffer.getvalue(), "image/png"))
        return rendered_pages
    finally:
        doc.close()


def build_visual_inputs(
    source_file_path: str,
    *,
    pdf_dpi: int = 144,
    max_pages: int = 12,
) -> list[str]:
    path = Path(source_file_path).expanduser().resolve()
    if not path.exists():
        raise ValueError(f"Source file not found: {path}")

    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return render_pdf_to_data_urls(path, dpi=pdf_dpi, max_pages=max_pages)
    if suffix in _IMAGE_EXTENSIONS:
        return [_image_file_to_data_url(path)]

    raise ValueError(
        f"Unsupported VLM source file type '{suffix or '<none>'}'. Use PDF or image files."
    )
