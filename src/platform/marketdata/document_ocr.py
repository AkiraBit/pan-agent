"""Optional on-device OCR for small scanned official PDFs.

Source bytes remain authoritative. OCR is labeled and cannot by itself establish
a regulatory event. Unsupported platforms return an explicit capability gap.
Compiler cache, executable and temporary documents stay inside DATA_DIR.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading

from src.platform.runtime.paths import get_data_dir

_compile_lock = threading.Lock()


def recognize_pdf(raw):
    if sys.platform != 'darwin' or not shutil.which('swiftc'):
        raise ValueError('local_ocr_unavailable')
    if not raw.startswith(b'%PDF') or len(raw) > 8_000_000:
        raise ValueError('ocr_document_limit')
    source = Path(__file__).with_name('pdf_ocr.swift')
    root = get_data_dir() / 'document_ocr'
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    executable = root / ('vision-' + hashlib.sha256(source.read_bytes()).hexdigest()[:16])
    with _compile_lock:
        if not executable.is_file():
            with tempfile.TemporaryDirectory(dir=root) as tmp:
                output = Path(tmp) / 'vision'
                subprocess.run(['swiftc', '-module-cache-path', str(root / 'modules'),
                                str(source), '-o', str(output)], check=True,
                               capture_output=True, timeout=60)
                output.replace(executable)
    with tempfile.TemporaryDirectory(dir=root) as tmp:
        pdf = Path(tmp) / 'source.pdf'
        pdf.write_bytes(raw)
        result = subprocess.run([str(executable), str(pdf)], check=True,
                                capture_output=True, timeout=25)
    if len(result.stdout) > 400_000:
        raise ValueError('ocr_output_limit')
    parsed = json.loads(result.stdout)
    pages = parsed['pages']
    if not 1 <= len(pages) <= 8 or any(len(p['text'].strip()) < 40 or p['reliable_fraction'] < .5 for p in pages):
        raise ValueError('ocr_confidence_insufficient')
    text = '\n'.join(p['text'] for p in pages)[:80000]
    if len(text.strip()) < 40:
        raise ValueError('document_text_missing')
    return text, {'method': 'ocr', 'engine': parsed['engine'], 'page_count': len(pages),
                  'uncertain_lines_omitted': True, 'retained_line_minimum_confidence': .6,
                  'minimum_confidence': min(p['minimum_confidence'] for p in pages),
                  'pages':[{k:v for k,v in p.items() if k!='text'} for p in pages]}
