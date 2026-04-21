import io
import logging

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_PDF_MAGIC = b"%PDF"

_BASE_CSS = """
@page { size: A4; margin: 2cm; }
body {
    font-family: "Noto Sans CJK JP", "Hiragino Kaku Gothic Pro", "Meiryo",
                 "MS Gothic", sans-serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #000;
}
img { max-width: 100%; height: auto; }
table { border-collapse: collapse; width: 100%; }
td, th { padding: 4px 8px; border: 1px solid #ccc; }
pre { white-space: pre-wrap; word-wrap: break-word; }
"""


def is_pdf_bytes(data):
    """Return True if data starts with the PDF magic bytes."""
    return data[:4] == _PDF_MAGIC


def html_to_pdf(html_content):
    """
    Convert HTML string to PDF bytes using WeasyPrint.
    Ensures UTF-8 encoding and injects print-friendly CSS.
    """
    from weasyprint import HTML, CSS

    soup = BeautifulSoup(html_content, "lxml")

    # Ensure charset meta tag
    head = soup.find("head") or soup.new_tag("head")
    if not soup.find("meta", {"charset": True}):
        meta = soup.new_tag("meta", charset="utf-8")
        head.insert(0, meta)

    # Remove scripts and iframes that could interfere
    for tag in soup.find_all(["script", "iframe", "noscript"]):
        tag.decompose()

    clean_html = str(soup)

    css = CSS(string=_BASE_CSS)
    pdf_bytes = HTML(string=clean_html, base_url=None).write_pdf(stylesheets=[css])
    return pdf_bytes


def plain_text_to_pdf(text):
    """Wrap plain text in minimal HTML and convert to PDF."""
    import html as html_module
    escaped = html_module.escape(text)
    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body><pre>{escaped}</pre></body></html>"""
    return html_to_pdf(html_content)


def image_to_pdf(image_bytes):
    """
    Convert image bytes (JPEG/PNG) to a single-page A4 PDF.
    The image is embedded in HTML and converted via WeasyPrint.
    """
    import base64
    from PIL import Image

    img = Image.open(io.BytesIO(image_bytes))
    fmt = img.format or "PNG"
    mime = "image/png" if fmt.upper() == "PNG" else "image/jpeg"

    b64 = base64.b64encode(image_bytes).decode("ascii")
    html_content = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;text-align:center;">
<img src="data:{mime};base64,{b64}" style="max-width:100%;max-height:100%;">
</body></html>"""
    return html_to_pdf(html_content)
