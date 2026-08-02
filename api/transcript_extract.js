'use strict';
/**
 * CertChain — Transcript Text Extraction
 * ==========================================
 * Extracts plain text from an uploaded transcript file (PDF/DOCX/TXT) so it
 * can be handed to integration/pipeline.py's --transcript path, unchanged.
 * All extraction lives here in Node, next to the upload endpoint itself —
 * BERT parsing and scoring stay entirely in Python, unchanged. No logic is
 * split across languages.
 *
 * PDFs with no extractable text layer (scanned documents) fall back to OCR
 * via pdftoppm (poppler-utils, a system dependency — see README Prerequisites)
 * + tesseract.js.
 */
const fs = require('fs');
const path = require('path');
const os = require('os');
const { execFile } = require('child_process');
const { PDFParse } = require('pdf-parse');
const mammoth = require('mammoth');
const { createWorker } = require('tesseract.js');

// Below this character count, treat extraction as failed / try OCR.
const MIN_EXTRACTED_CHARS = 20;

async function extractText(filePath, mimetype, originalName) {
    const ext = path.extname(originalName || '').toLowerCase();

    if (ext === '.txt' || mimetype === 'text/plain') {
        const text = fs.readFileSync(filePath, 'utf8').trim();
        if (text.length < MIN_EXTRACTED_CHARS) {
            throw new Error('Text file is empty or too short to process.');
        }
        return { text, method: 'passthrough' };
    }

    if (ext === '.pdf' || mimetype === 'application/pdf') {
        const buf = fs.readFileSync(filePath);
        let text = '';
        try {
            const parser = new PDFParse({ data: buf });
            const parsed = await parser.getText();
            text = (parsed.text || '').trim();
            await parser.destroy();
        } catch (e) {
            throw new Error(`Could not parse PDF: ${e.message}`);
        }
        if (text.length >= MIN_EXTRACTED_CHARS) {
            return { text, method: 'pdf-parse' };
        }
        // No (or near-empty) text layer — likely a scanned image PDF.
        const ocrText = await ocrScannedPdf(filePath);
        if (ocrText.length >= MIN_EXTRACTED_CHARS) {
            return { text: ocrText, method: 'ocr' };
        }
        throw new Error('No extractable text found in PDF, including after OCR fallback.');
    }

    if (ext === '.docx' ||
        mimetype === 'application/vnd.openxmlformats-officedocument.wordprocessingml.document') {
        let text;
        try {
            const result = await mammoth.extractRawText({ path: filePath });
            text = (result.value || '').trim();
        } catch (e) {
            throw new Error(`Could not parse DOCX: ${e.message}`);
        }
        if (text.length < MIN_EXTRACTED_CHARS) {
            throw new Error('No extractable text found in DOCX.');
        }
        return { text, method: 'mammoth' };
    }

    throw new Error(`Unsupported file type: ${ext || mimetype}`);
}

// Rasterizes each PDF page to a PNG via pdftoppm, then OCRs each page with
// Tesseract. Requires poppler-utils on the host — fails with a clear,
// actionable error (not a crash) if pdftoppm isn't installed.
async function ocrScannedPdf(pdfPath) {
    const tmpPrefix = path.join(os.tmpdir(), `certchain-ocr-${Date.now()}-${Math.random().toString(36).slice(2)}`);

    await new Promise((resolve, reject) => {
        execFile('pdftoppm', ['-png', '-r', '200', pdfPath, tmpPrefix], (err) => {
            if (err) {
                if (err.code === 'ENOENT') {
                    return reject(new Error(
                        'OCR fallback requires poppler-utils (the `pdftoppm` command) to be ' +
                        'installed on the server — this scanned/image-only PDF cannot be ' +
                        'processed without it.'
                    ));
                }
                return reject(new Error(`pdftoppm failed: ${err.message}`));
            }
            resolve();
        });
    });

    const dir = path.dirname(tmpPrefix);
    const prefix = path.basename(tmpPrefix);
    const pageFiles = fs.readdirSync(dir)
        .filter(f => f.startsWith(prefix) && f.endsWith('.png'))
        .sort()
        .map(f => path.join(dir, f));

    if (pageFiles.length === 0) {
        throw new Error('pdftoppm produced no page images to OCR.');
    }

    const worker = await createWorker('eng');
    try {
        let combined = '';
        for (const pageFile of pageFiles) {
            const { data } = await worker.recognize(pageFile);
            combined += (data.text || '') + '\n';
        }
        return combined.trim();
    } finally {
        await worker.terminate();
        for (const f of pageFiles) { try { fs.unlinkSync(f); } catch (e) { /* best effort */ } }
    }
}

module.exports = { extractText, MIN_EXTRACTED_CHARS };
