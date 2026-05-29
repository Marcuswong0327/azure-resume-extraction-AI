import docx
import os
import shutil
import subprocess
import sys
import tempfile
import streamlit as st
from io import BytesIO


class WordProcessor:
    """Handles Word documents (.docx) and legacy Word 97-2003 (.doc) text extraction."""

    def __init__(self):
        pass

    def _extract_text_from_doc_bytes(self, doc_bytes: bytes) -> str:
        """
        Extract plain text from legacy .doc using **antiword** (CLI, no .NET / no libicu).

        Streamlit Community Cloud: list `antiword` in `packages.txt` (this repo includes it).
        Local Windows: install antiword and put it on PATH, or re-save as .docx.

        (Aspose.Words FOSS is MIT and avoids Word/LibreOffice, but PyPI wheels are limited by
        Python version; antiword is the most reliable option on Linux deploys.)
        """
        exe = shutil.which("antiword")
        if not exe:
            st.error(
                "Legacy **.doc** needs the **antiword** program on the machine. "
                "For Streamlit Cloud, commit **`packages.txt`** in the repo root with a line `antiword` "
                "and redeploy. On Windows, install [antiword](http://www.winfield.demon.nl/) and add it to PATH, "
                "or save the file as **.docx**."
            )
            return ""

        with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as tf:
            tf.write(doc_bytes)
            path = tf.name

        try:
            run_kw: dict = {
                "args": [exe, path],
                "capture_output": True,
                "timeout": 120,
            }
            if sys.platform == "win32" and hasattr(subprocess, "CREATE_NO_WINDOW"):
                run_kw["creationflags"] = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(**run_kw)
        except (subprocess.TimeoutExpired, OSError) as e:
            st.error(f"Could not read .doc file: {e}")
            return ""
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

        if result.returncode != 0:
            err = result.stderr or b""
            if isinstance(err, bytes):
                err = err.decode("latin-1", errors="replace")
            st.error(
                f"antiword failed (exit {result.returncode}). "
                f"{str(err).strip() or 'The file may be corrupted.'}"
            )
            return ""

        raw = result.stdout or b""
        if isinstance(raw, bytes):
            text = raw.decode("utf-8", errors="replace")
            if not text.strip():
                text = raw.decode("latin-1", errors="replace")
        else:
            text = str(raw)
        return text.strip()

    def extract_text_from_docx(self, file_path_or_bytes):
        """
        Extract text from DOCX file.
        Accepts a file path or BytesIO object.
        """
        try:
            document = docx.Document(file_path_or_bytes)

            text_content = []

            for paragraph in document.paragraphs:
                if paragraph.text.strip():
                    text_content.append(paragraph.text.strip())

            for table in document.tables:
                for row in table.rows:
                    for cell in row.cells:
                        if cell.text.strip():
                            text_content.append(cell.text.strip())

            return "\n".join(text_content)

        except Exception as e:
            st.error(f"Error extracting text from DOCX file: {str(e)}")
            return ""

    def process_word_file(self, uploaded_file):
        """
        Process DOCX (python-docx) or legacy .doc (antiword).
        """
        try:
            file_extension = uploaded_file.name.lower().split(".")[-1]

            if file_extension == "docx":
                file_content = uploaded_file.read()
                return self.extract_text_from_docx(BytesIO(file_content))

            if file_extension == "doc":
                file_content = uploaded_file.read()
                return self._extract_text_from_doc_bytes(file_content)

            st.error(f"Unsupported file format: {file_extension}")
            return ""

        except Exception as e:
            st.error(f"Error processing Word file: {str(e)}")
            return ""
