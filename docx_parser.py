import os
import logging

logger = logging.getLogger("generator_kreo")

try:
    import docx
except ImportError:
    docx = None
    logger.warning("python-docx is not installed. Word docx files cannot be parsed.")

def parse_docx(file_path: str) -> str:
    """Parses a .docx file and returns its text content."""
    if not docx:
        return "[Error: python-docx library is not installed on this system]"
    
    try:
        doc = docx.Document(file_path)
        full_text = []
        for para in doc.paragraphs:
            full_text.append(para.text)
        return "\n".join(full_text)
    except Exception as e:
        logger.error(f"Error parsing docx file {file_path}: {e}")
        return f"[Error parsing docx: {str(e)}]"

def parse_txt(file_path: str) -> str:
    """Parses a plain text file, handling different encodings."""
    encodings = ["utf-8", "windows-1251", "cp1252", "latin-1"]
    for encoding in encodings:
        try:
            with open(file_path, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    # Fallback to binary representation or error
    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception as e:
        return f"[Error parsing text: {str(e)}]"

def extract_text_from_file(file_path: str) -> str:
    """Detects file type and extracts text from docx or text files."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".docx":
        return parse_docx(file_path)
    elif ext in [".txt", ".text"]:
        return parse_txt(file_path)
    elif ext == ".doc":
        return "[Warning: Legacy binary .doc files are not supported. Please save as .docx or .txt]"
    else:
        return f"[Unsupported text file format: {ext}]"
