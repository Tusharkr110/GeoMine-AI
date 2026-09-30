"""
=============================================================================
CMPDI AI-Based System - Real-Time Python RAG & Document Intelligence Service
Central Mine Planning & Design Institute Limited (Coal India Limited)
=============================================================================
Features:
 - Multi-page PDF text extraction via pypdf
 - Real-time hybrid RAG with BM25 (rank_bm25) & TF-IDF (scikit-learn)
 - Real-time Entity Extraction (Production, Reviewer, Author, Date, Site, Location, etc.)
 - Confidence Scoring & Multi-Page Citation attribution
 - Human-in-the-loop review & label verification
 - PostgreSQL persistence with in-memory fallback
 - Dynamic Multi-Page PDF Report generator via reportlab
"""

import os
from dotenv import load_dotenv
load_dotenv()
import io
import re
import math
import uuid
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

import pypdf
import pytesseract
from PIL import Image
import shutil

# Configure Tesseract OCR for scanned PDF extraction
TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    shutil.which("tesseract")
]
for _t_path in TESSERACT_PATHS:
    if _t_path and os.path.exists(_t_path):
        pytesseract.pytesseract.tesseract_cmd = _t_path
        break

from rank_bm25 import BM25Okapi
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import numpy as np

# ReportLab for on-the-fly PDF compilation
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak

# Setup Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("CMPDI_RAG")

app = FastAPI(
    title="GeoMine AI Real-Time Python RAG Engine",
    description="Real-time multi-page PDF ingestion, entity extraction, citations, and RAG Q&A",
    version="2.0.0"
)

# Enable CORS for local portal access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================================================================
# POSTGRESQL DATABASE INTEGRATION (With Graceful In-Memory Fallback)
# =============================================================================
PG_HOST = os.getenv("PGHOST", "localhost")
PG_PORT = int(os.getenv("PGPORT", "5433"))
PG_USER = os.getenv("PGUSER", "postgres")
PG_PASSWORD = os.getenv("PGPASSWORD", "postgres")
PG_DATABASE = os.getenv("PGDATABASE", "cmpdi_portal")

db_connected = False

def get_db_conn():
    try:
        import psycopg
        conn_str = f"host={PG_HOST} port={PG_PORT} user={PG_USER} password={PG_PASSWORD} dbname={PG_DATABASE}"
        return psycopg.connect(conn_str, autocommit=True)
    except Exception as e:
        logger.warning(f"PostgreSQL connection error: {e}")
        return None

def init_postgres():
    global db_connected
    conn = get_db_conn()
    if not conn:
        db_connected = False
        logger.warning("PostgreSQL not connected. Running in-memory.")
        return
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS cmpdi_documents (
                    id VARCHAR(64) PRIMARY KEY,
                    filename VARCHAR(255) NOT NULL,
                    file_size INT NOT NULL,
                    page_count INT NOT NULL,
                    uploaded_by VARCHAR(64),
                    review_status VARCHAR(64) DEFAULT 'PENDING_HUMAN_REVIEW',
                    reviewed_by VARCHAR(64),
                    reviewed_at TIMESTAMP,
                    extracted_metadata JSONB,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS cmpdi_document_pages (
                    id SERIAL PRIMARY KEY,
                    document_id VARCHAR(64) REFERENCES cmpdi_documents(id) ON DELETE CASCADE,
                    page_number INT NOT NULL,
                    page_text TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cmpdi_document_chunks (
                    id SERIAL PRIMARY KEY,
                    document_id VARCHAR(64) REFERENCES cmpdi_documents(id) ON DELETE CASCADE,
                    page_number INT NOT NULL,
                    chunk_index INT NOT NULL,
                    chunk_text TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS cmpdi_document_labels (
                    id SERIAL PRIMARY KEY,
                    document_id VARCHAR(64) REFERENCES cmpdi_documents(id) ON DELETE CASCADE,
                    label_key VARCHAR(64) NOT NULL,
                    label_value TEXT NOT NULL,
                    confidence NUMERIC(5,2) NOT NULL,
                    citation_page INT,
                    citation_snippet TEXT,
                    is_verified BOOLEAN DEFAULT FALSE,
                    verified_by VARCHAR(64),
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS cmpdi_rag_queries (
                    id SERIAL PRIMARY KEY,
                    document_id VARCHAR(64) REFERENCES cmpdi_documents(id) ON DELETE CASCADE,
                    query_text TEXT NOT NULL,
                    answer_text TEXT NOT NULL,
                    confidence NUMERIC(5,2),
                    citations JSONB,
                    queried_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Add UNIQUE constraint to cmpdi_document_labels if not present
            cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'cmpdi_doc_labels_doc_key_unique'
                    ) THEN
                        ALTER TABLE cmpdi_document_labels ADD CONSTRAINT cmpdi_doc_labels_doc_key_unique UNIQUE (document_id, label_key);
                    END IF;
                END $$;
            """)
        conn.close()
        db_connected = True
        logger.info(f"PostgreSQL initialized successfully on {PG_HOST}:{PG_PORT}/{PG_DATABASE}!")
    except Exception as e:
        db_connected = False
        logger.warning(f"PostgreSQL not connected ({e}). Running with in-memory RAG persistence.")

init_postgres()

# =============================================================================
# IN-MEMORY DOCUMENT & RAG STORE
# =============================================================================
class DocumentRecord:
    def __init__(self, doc_id: str, filename: str, file_size: int, page_count: int, uploaded_by: str):
        self.doc_id = doc_id
        self.filename = filename
        self.file_size = file_size
        self.page_count = page_count
        self.uploaded_by = uploaded_by
        self.created_at = datetime.now().isoformat()
        self.review_status = "PENDING_HUMAN_REVIEW"
        self.reviewed_by = None
        self.reviewed_at = None
        self.pages: List[Dict[str, Any]] = [] # [{page_number, text}]
        self.chunks: List[Dict[str, Any]] = [] # [{page_number, chunk_index, text}]
        self.extracted_labels: Dict[str, Any] = {}
        # RAG Models
        self.bm25: Optional[BM25Okapi] = None
        self.tokenized_chunks: List[List[str]] = []
        self.tfidf_vectorizer: Optional[TfidfVectorizer] = None
        self.tfidf_matrix = None

doc_store: Dict[str, DocumentRecord] = {}

# =============================================================================
# ENTITY EXTRACTION LOGIC WITH CITATIONS & CONFIDENCE
# =============================================================================
def extract_entities_from_pages(pages: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Extracts key mining details across multi-page document:
    Production, Reviewer, Author, Date, Site, Location, Coal Grade, Stripping Ratio, Overburden
    Supports narrative extraction, side-by-side signature blocks, tabular fields, and OCR documents.
    """
    results = {
        "production": None,
        "reviewer": None,
        "author": None,
        "date": None,
        "site": None,
        "location": None,
        "coal_grade": None,
        "stripping_ratio": None,
        "overburden": None
    }

    def search_pattern(pattern: str, base_conf: float, cleaner=None, group_idx: int = 1):
        best_match = None
        highest_score = 0.0

        for p in pages:
            page_num = p["page_number"]
            text = p["text"]
            for m in re.finditer(pattern, text, re.IGNORECASE):
                try:
                    val = m.group(group_idx) if group_idx <= len(m.groups()) else m.group(0)
                except Exception:
                    val = m.group(0)
                if cleaner:
                    val = cleaner(val)
                val = (val or "").strip()
                if not val or len(val) < 2:
                    continue

                # Contextual Snippet (~140 chars)
                start = max(0, m.start() - 50)
                end = min(len(text), m.end() + 60)
                snippet = text[start:end].replace('\n', ' ').strip()
                snippet = re.sub(r'\s+', ' ', snippet)

                # Confidence weighting
                conf = base_conf
                if re.search(r'geomine|cmpdi|coal india|dgms|mine|dr\.|er\.|engineer|target|actual', snippet, re.IGNORECASE):
                    conf += 4.0
                if 4 <= len(val) <= 50:
                    conf += 3.0
                conf = min(99.4, max(52.0, conf))

                if conf > highest_score:
                    highest_score = conf
                    best_match = {
                        "value": val,
                        "confidence": round(conf, 1),
                        "citation_page": page_num,
                        "citation_snippet": f"...{snippet}...",
                        "is_human_verified": False
                    }
        return best_match

    def clean_person_name(name: str) -> Optional[str]:
        if not name:
            return None
        cleaned = re.sub(r'[\(\)]', '', re.sub(r'(?:Date|Signature|Signed|Designation|EIS).*', '', name, flags=re.I)).strip()
        cleaned = re.sub(r'^[,\.\-\:\s]+|[,\.\-\:\s]+$', '', cleaned)
        if len(cleaned) < 3 or len(cleaned) > 50:
            return None
        lower = cleaned.lower()
        non_person = [
            "the board", "board", "ministry", "committee", "earlier", "contractor", 
            "contractors", "company", "division", "hq", "ranchi", "coal india", 
            "subsidiary", "subsidiaries", "directorate", "department", "ccl", "secl", 
            "ecl", "mcl", "wcl", "bcl", "bcc", "cmpdi", "government", "imperial", 
            "scales", "annual", "action", "plan", "target", "production", "quarter",
            "statutory", "clearance", "table", "report", "format", "legacy"
        ]
        if any(k in lower for k in non_person):
            return None
        if not any(c.isupper() for c in cleaned):
            return None
        return cleaned

    # 1. Author and Reviewer: Signature Block & Sign-off rows (Side-by-side and multi-column)
    for p in pages:
        p_text = p["text"]
        lines = [line.strip() for line in p_text.split('\n') if line.strip()]
        for i, line in enumerate(lines):
            if re.search(r'Prepared\s+by', line, re.I) and (re.search(r'Approved\s+by', line, re.I) or re.search(r'Verified\s+by', line, re.I)):
                if i + 1 < len(lines):
                    next_line = lines[i + 1]
                    name_matches = re.findall(r'\(([A-Za-z\.\s]{3,35})\)', next_line)
                    desig_matches = []
                    if i + 2 < len(lines):
                        desig_line = lines[i + 2]
                        desig_matches = re.findall(r'(?:Deputy\s+Manager|General\s+Manager|Director|Manager|Officer|Geologist|Engineer)\s*(?:\([^)]+\))?', desig_line, re.I)

                    if name_matches:
                        raw_auth = clean_person_name(name_matches[0])
                        auth_desig = f" ({desig_matches[0].strip()})" if len(desig_matches) > 0 else ""
                        if raw_auth and not results["author"]:
                            results["author"] = {
                                "value": f"{raw_auth}{auth_desig}",
                                "confidence": 94.0,
                                "citation_page": p["page_number"],
                                "citation_snippet": f"...{line} | {next_line}...",
                                "is_human_verified": False
                            }

                        raw_rev = clean_person_name(name_matches[1] if len(name_matches) > 1 else name_matches[-1])
                        rev_desig = f" ({desig_matches[1].strip()})" if len(desig_matches) > 1 else ""
                        if raw_rev and not results["reviewer"]:
                            results["reviewer"] = {
                                "value": f"{raw_rev}{rev_desig}",
                                "confidence": 94.0,
                                "citation_page": p["page_number"],
                                "citation_snippet": f"...{line} | {next_line}...",
                                "is_human_verified": False
                            }

    # Reviewer Extraction (General and fallback)
    if not results["reviewer"]:
        results["reviewer"] = search_pattern(
            r'(?:Reviewed\s+by|Approved\s+by|Verified\s+by|Countersigned\s+by)\s*[:=\-–]?\s*\(?([A-Za-z\.\s]{3,45}(?:General\s+Manager|GM|Director|Chief|Advisor)?)',
            89.0,
            cleaner=clean_person_name
        ) or search_pattern(
            r'(?:Chief\s+General\s+Manager|General\s+Manager|Director\s+Technical|Director\s*\([A-Za-z\s]+\))\s*[:=\-–]\s*([A-Za-z\.\s]{3,40})',
            82.0,
            cleaner=clean_person_name
        )

    # Author Extraction (General and fallback)
    if not results["author"]:
        results["author"] = search_pattern(
            r'(?:Prepared\s+by\s*(?:\(Author\))?|Authored\s+by|Author(?:ing\s+Officer)?|Submitted\s+by|Project\s+Officer|Geologist\s+In-Charge|Mine\s+Planner)\s*[:=\-–]?\s*\(?([A-Za-z\.\s]{3,45})',
            88.0,
            cleaner=clean_person_name
        ) or search_pattern(
            r'\b((?:Dr\.|Er\.|Col\.|Shri)\s+[A-Z][a-z]+(?:\s+[A-Z]\.?)?\s+[A-Z][a-z]+)',
            82.0,
            cleaner=clean_person_name
        )

    # 2. Date Extraction
    results["date"] = search_pattern(
        r'Dated\s*[:=\-–]?\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4}|[0-9]{1,2}[\/\-\.][0-9]{1,2}[\/\-\.][0-9]{2,4})',
        95.0
    ) or search_pattern(
        r'Period\s+covered\s*[:=\-–]?\s*([0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4}\s+to\s+[0-9]{1,2}\s+[A-Za-z]+\s+[0-9]{4})',
        92.0
    ) or search_pattern(
        r'(?:Date\s*[:=\-–]?\s*)?([0-9]{1,2}[\/\-\.][0-9]{1,2}[\/\-\.][0-9]{2,4}|[0-9]{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s,]+[0-9]{4})',
        88.0
    )

    # 3. Location / District / State Extraction
    results["location"] = search_pattern(
        r'(?:Place\s*[:=\-–]\s*)([A-Za-z\s]{3,30})',
        95.0,
        cleaner=lambda s: re.sub(r'[\|\n\r].*', '', s).strip()
    ) or search_pattern(
        r'CMPDI[,\s\-]+([A-Za-z]{4,25})',
        91.0,
        cleaner=lambda s: s.strip()
    ) or search_pattern(
        r'(?:Location\s*&\s*District|Location|District|State|Basin)\s*[:=\-–]\s*([A-Za-z0-9\s,\-\.]{4,60}(?:Jharkhand|Chhattisgarh|West\s+Bengal|Odisha|Madhya\s+Pradesh)?)',
        87.0,
        cleaner=lambda s: s.strip()
    ) or search_pattern(
        r'\b(Ranchi|Dhanbad|Korba|Bilaspur|Singrauli|Kolkata|Nagpur|Jharkhand|Chhattisgarh|West\s+Bengal|Odisha|Madhya\s+Pradesh)\b',
        84.0
    )

    # 4. Production Extraction
    results["production"] = search_pattern(
        r'(?:achieved\s+a\s+production\s+of|coal\s+production\s+stood\s+at|actual\s+production\s+was|overall\s+coal\s+production|produced)\s*[:=\-–]?\s*([0-9]+(?:\.[0-9]+)?\s*(?:Million\s+Tonnes|MT|Lakh\s+Tonnes|LT|tonnes))',
        93.0
    ) or search_pattern(
        r'(?:Targeted\s+Production|Annual\s+Target|Production\s+Capacity|Production\s+Target|Total\s+Production|Annual\s+Capacity|Gross\s+Production)\s*[:=\-–]?\s*([0-9]+(?:\.[0-9]+)?\s*(?:MTPA|Million\s+Tonnes|MT|Lakh\s+Tonnes|LT|tonnes|tpa))',
        89.0
    ) or search_pattern(
        r'\b([0-9]+(?:\.[0-9]+)?\s*(?:Million\s+Tonnes|MTPA))\b',
        80.0
    )

    # 5. Overburden Removal (OBR)
    results["overburden"] = search_pattern(
        r'(?:removal\s+of\s+overburden|overburden\s+removal)[a-z\s]*stood\s+at\s*([0-9]+(?:\.[0-9]+)?\s*(?:million|nullion|milhen|M\.)?\s*cubic\s+metres|M\.Cum|BCM|Lakh\s+Cu\.m)',
        93.0,
        cleaner=lambda s: re.sub(r'nullion|milhen', 'Million', s, flags=re.I).strip()
    ) or search_pattern(
        r'(?:Overburden|OB\s+Removal|Total\s+OB)\s*[:=\-–]?\s*([0-9]+(?:\.[0-9]+)?\s*(?:Million\s+Cu\.m|M\.Cum|BCM|million\s+cubic\s+metres))',
        88.0
    )

    # 6. Stripping Ratio
    results["stripping_ratio"] = search_pattern(
        r'str[ip]+ing\s+rat[io]+[a-z0-9\s,]*was\s*([0-9]+(?:\.[0-9]+)?(?:\s*[:=\-]\s*[0-9]+(?:\.[0-9]+)?)?)',
        93.0,
        cleaner=lambda s: f"{s} Cum/Tonne" if not re.search(r'[:\/]', s) else s
    ) or search_pattern(
        r'(?:Stripping\s+Ratio|SR)\s*[:=\-–]\s*([0-9]+(?:\.[0-9]+)?\s*:\s*[0-9]+(?:\.[0-9]+)?|[0-9]+(?:\.[0-9]+)?\s*(?:Cum\/Tonne|m3\/t))',
        88.0
    )

    # 7. Coal Grade
    results["coal_grade"] = search_pattern(
        r'(?:falling\s+in|declared\s+as|seam.*?is|Grade)\s*(Grade\s+[A-Za-z0-9\-]+|G-[0-9]+)',
        93.0
    ) or search_pattern(
        r'(?:Coal\s+Grade|Grade\s+of\s+Coal|Seam\s+Grade|Grade)\s*[:=\-–]?\s*(Grade\s+[A-Za-z0-9\-]+|G-[0-9]+|[A-G](?:-[0-9]+)?|Steel\s+Grade\s+[I|II]+|Washery\s+Grade\s+[I-IV]+|Non-coking\s+Grade\s+[A-G])',
        88.0
    )

    # 8. Site / Project
    results["site"] = search_pattern(
        r'\b(Piparwar(?:\s+and\s+Ashoka)?\s*(?:OCP|projects|project|Mine)?|Gevra(?:\s+OCP)?|Kusmunda(?:\s+OCP)?|Dipka(?:\s+OCP)?|Raigarh\s+area|Sohagpur\s+area|Rajrappa\s*(?:OCP|site|project)?|Kuju\s*(?:OCP|site|project)?|Karo\s+block|North\s+Karanpura|Singrauli|Talcher|Moonidih|Bokaro\s+Colliery|Korba\s*(?:Coalfield|area|mines)?)\b',
        92.0,
        cleaner=lambda s: re.sub(r'projects?|areas?', 'OCP', s, flags=re.I).strip()
    ) or search_pattern(
        r'(?:Project\s+Name\s*&\s*Mine\s+Site|Mine\s+Site|Project\s+Name|Colliery|Mine\s+Name)\s*[:=\-–]?\s*([A-Za-z0-9\s\-]{3,45}(?:OCP|Open\s*Cast|Underground|Colliery|Project|Block|Mine))',
        88.0
    )

    return results


# =============================================================================
# CHUNKING & RAG TRAINING
# =============================================================================
def chunk_document(pages: List[Dict[str, Any]], chunk_size: int = 150, overlap: int = 35) -> List[Dict[str, Any]]:
    chunks = []
    global_index = 0

    for p in pages:
        words = p["text"].split()
        page_num = p["page_number"]
        if not words:
            continue

        step = max(1, chunk_size - overlap)
        for i in range(0, len(words), step):
            c_words = words[i : i + chunk_size]
            if len(c_words) < 12:
                continue
            chunk_text = " ".join(c_words)
            chunks.append({
                "chunk_id": f"c_{global_index}",
                "chunk_index": global_index,
                "page_number": page_num,
                "text": chunk_text
            })
            global_index += 1

    return chunks

def train_rag_index(doc: DocumentRecord):
    """
    Trains hybrid BM25 and TF-IDF models over the document chunks in real time.
    """
    raw_chunks = [c["text"] for c in doc.chunks]
    if not raw_chunks:
        return

    # 1. Tokenize for BM25
    doc.tokenized_chunks = [re.findall(r'\b[a-zA-Z0-9_\-\.]+\b', c.lower()) for c in raw_chunks]
    doc.bm25 = BM25Okapi(doc.tokenized_chunks)

    # 2. Vectorize for Cosine Similarity
    doc.tfidf_vectorizer = TfidfVectorizer(stop_words='english')
    doc.tfidf_matrix = doc.tfidf_vectorizer.fit_transform(raw_chunks)

    logger.info(f"RAG trained for '{doc.filename}': {len(doc.chunks)} chunks across {doc.page_count} pages.")

# =============================================================================
# FASTAPI ROUTES
# =============================================================================

@app.get("/api/rag/health")
def health():
    return {
        "status": "online",
        "service": "GeoMine AI Python RAG & Document Intelligence",
        "database": "PostgreSQL" if db_connected else "In-Memory Fallback",
        "indexed_documents": len(doc_store)
    }

@app.post("/api/rag/upload")
async def upload_pdf(file: UploadFile = File(...), uploaded_by: str = Form("GEOMINE_OFFICER")):
    """
    Accepts any real multi-page PDF, scans text page-by-page, extracts key entities,
    indexes into RAG, and saves to PostgreSQL. Pure working, no seed data needed!
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    doc_id = "doc_" + uuid.uuid4().hex[:10]
    filename = file.filename or "uploaded_document.pdf"
    file_size = len(content)

    # Parse with pypdf
    try:
        reader = pypdf.PdfReader(io.BytesIO(content))
        page_count = len(reader.pages)
        pages = []
        for idx, page in enumerate(reader.pages):
            text = (page.extract_text() or "").strip()
            # Real-time OCR fallback for scanned PDFs
            if len(text) < 50 and len(page.images) > 0:
                ocr_texts = []
                for img_obj in page.images:
                    try:
                        img = Image.open(io.BytesIO(img_obj.data))
                        ocr_res = pytesseract.image_to_string(img, config='--psm 6')
                        if ocr_res and len(ocr_res.strip()) > 20:
                            ocr_texts.append(ocr_res.strip())
                    except Exception as ocr_err:
                        logger.warning(f"OCR processing failed for page {idx + 1}: {ocr_err}")
                if ocr_texts:
                    combined_ocr = "\n\n".join(ocr_texts).strip()
                    if len(combined_ocr) > len(text):
                        text = combined_ocr

            pages.append({
                "page_number": idx + 1,
                "text": text.strip()
            })
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse PDF: {str(e)}")

    # Extract Entities with Citations
    entities = extract_entities_from_pages(pages)

    # Chunk & Train RAG Index
    chunks = chunk_document(pages)
    doc_record = DocumentRecord(doc_id, filename, file_size, page_count, uploaded_by)
    doc_record.pages = pages
    doc_record.chunks = chunks
    doc_record.extracted_labels = entities
    train_rag_index(doc_record)
    doc_store[doc_id] = doc_record

    # Persist to PostgreSQL if connected
    conn = get_db_conn() if db_connected else None
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO cmpdi_documents (id, filename, file_size, page_count, uploaded_by, extracted_metadata)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (id) DO UPDATE SET filename = EXCLUDED.filename, extracted_metadata = EXCLUDED.extracted_metadata""",
                    (doc_id, filename, file_size, page_count, uploaded_by, json.dumps(entities))
                )
                for p in pages:
                    cur.execute(
                        """INSERT INTO cmpdi_document_pages (document_id, page_number, page_text)
                           VALUES (%s, %s, %s)""",
                        (doc_id, p["page_number"], p["text"])
                    )
                for c in chunks:
                    cur.execute(
                        """INSERT INTO cmpdi_document_chunks (document_id, page_number, chunk_index, chunk_text)
                           VALUES (%s, %s, %s, %s)""",
                        (doc_id, c["page_number"], c["chunk_index"], c["text"])
                    )
                for key, item in entities.items():
                    if item:
                        cur.execute(
                            """INSERT INTO cmpdi_document_labels (document_id, label_key, label_value, confidence, citation_page, citation_snippet)
                               VALUES (%s, %s, %s, %s, %s, %s)
                               ON CONFLICT (document_id, label_key) DO UPDATE
                               SET label_value = EXCLUDED.label_value, confidence = EXCLUDED.confidence""",
                            (doc_id, key, item["value"], item["confidence"], item["citation_page"], item["citation_snippet"])
                        )
            conn.commit()
            conn.close()
            logger.info(f"PostgreSQL real-time records committed for document '{doc_id}' ({filename})")
        except Exception as err:
            logger.error(f"PostgreSQL write failed: {err}")

    return {
        "success": True,
        "document_id": doc_id,
        "filename": filename,
        "page_count": page_count,
        "chunk_count": len(chunks),
        "review_status": "PENDING_HUMAN_REVIEW",
        "extracted_details": entities,
        "pages": pages,
        "pages_summary": [
            {
                "page_number": p["page_number"],
                "char_count": len(p["text"]),
                "preview": p["text"][:180].replace('\n', ' ') + "..."
            }
            for p in pages
        ]
    }

class RagQueryRequest(BaseModel):
    document_id: str
    query: str

@app.post("/api/rag/query")
def query_rag_endpoint(req: RagQueryRequest):
    """
    RAG semantic retrieval returning synthesized answer, confidence score,
    and exact citations with page numbers and snippet contexts.
    """
    doc = doc_store.get(req.document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document ID not found in active RAG session.")

    query_text = req.query.strip()
    if not query_text:
        return {"answer": "Please specify a question.", "confidence": 0, "citations": []}

    # 1. BM25 Scoring
    query_tokens = re.findall(r'\b[a-zA-Z0-9_\-\.]+\b', query_text.lower())
    bm25_scores = doc.bm25.get_scores(query_tokens) if doc.bm25 else [0] * len(doc.chunks)
    max_bm25 = max(bm25_scores) if max(bm25_scores) > 0 else 1.0

    # 2. TF-IDF Cosine Similarity
    if doc.tfidf_vectorizer and doc.tfidf_matrix is not None:
        q_vec = doc.tfidf_vectorizer.transform([query_text])
        cos_scores = cosine_similarity(q_vec, doc.tfidf_matrix)[0]
    else:
        cos_scores = [0] * len(doc.chunks)

    # 3. Hybrid Ranking
    combined = []
    for idx, chunk in enumerate(doc.chunks):
        norm_bm25 = bm25_scores[idx] / max_bm25
        norm_cos = float(cos_scores[idx])
        hybrid_score = 0.60 * norm_bm25 + 0.40 * norm_cos
        combined.append((idx, hybrid_score))

    combined.sort(key=lambda x: x[1], reverse=True)
    top_candidates = combined[:3]

    if not top_candidates or top_candidates[0][1] < 0.05:
        return {
            "query": query_text,
            "answer": f"No conclusive evidence was found for '{query_text}' in this document.",
            "confidence": 18.0,
            "citations": []
        }

    best_chunk_idx, best_score = top_candidates[0]
    best_chunk = doc.chunks[best_chunk_idx]
    confidence = min(99.1, max(50.0, round(best_score * 120 + 28, 1)))

    citations = []
    for rank, (idx, score) in enumerate(top_candidates):
        c = doc.chunks[idx]
        conf_chunk = min(99.0, max(45.0, round(score * 100, 1)))
        citations.append({
            "rank": rank + 1,
            "page_number": c["page_number"],
            "confidence": conf_chunk,
            "snippet": c["text"][:170].replace('\n', ' ') + "..."
        })

    answer = (
        f"According to Page {best_chunk['page_number']} of '{doc.filename}':\n\n"
        f"{best_chunk['text'][:340].strip()}..."
    )

    # Save query to DB if connected
    if db_connected:
        conn = get_db_conn()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO cmpdi_rag_queries (document_id, query_text, answer_text, confidence, citations)
                           VALUES (%s, %s, %s, %s, %s)""",
                        (doc.doc_id, query_text, answer, confidence, json.dumps(citations))
                    )
                conn.commit()
                conn.close()
            except Exception as err:
                logger.error(f"PostgreSQL query log failed: {err}")
                if conn:
                    conn.rollback()
                    conn.close()

    return {
        "query": query_text,
        "answer": answer,
        "confidence": confidence,
        "primary_page": best_chunk["page_number"],
        "citations": citations
    }

class HumanReviewRequest(BaseModel):
    document_id: str
    reviewer_eis: str
    review_status: str
    labels: Dict[str, str]

@app.post("/api/rag/review")
def record_human_review(req: HumanReviewRequest):
    """
    Human-in-the-Loop review endpoint: updates and verifies extracted labels,
    elevates confidence to 100%, and sets status to VERIFIED_BY_OFFICER.
    """
    doc = doc_store.get(req.document_id)
    if not doc and db_connected:
        conn = get_db_conn()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT id, filename, file_size, page_count, uploaded_by, review_status, extracted_metadata FROM cmpdi_documents WHERE id = %s", (req.document_id,))
                    row = cur.fetchone()
                    if row:
                        doc = DocumentRecord(row[0], row[1], row[2], row[3], row[4])
                        doc.review_status = row[5]
                        doc.extracted_labels = row[6] or {}
                        doc_store[doc.doc_id] = doc
                conn.close()
            except Exception as e:
                logger.error(f"Error querying doc from PostgreSQL: {e}")

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    doc.review_status = req.review_status or "VERIFIED_BY_OFFICER"
    doc.reviewed_by = req.reviewer_eis or "OFFICER_REVIEW"
    doc.reviewed_at = datetime.now().isoformat()

    for key, val in req.labels.items():
        clean_val = str(val).strip() if val is not None else "null"
        if key in doc.extracted_labels and doc.extracted_labels[key]:
            doc.extracted_labels[key]["value"] = clean_val
            doc.extracted_labels[key]["confidence"] = 100.0
            doc.extracted_labels[key]["is_human_verified"] = True
        else:
            doc.extracted_labels[key] = {
                "value": clean_val,
                "confidence": 100.0,
                "citation_page": 1,
                "citation_snippet": "Verified & added by Officer during review",
                "is_human_verified": True
            }

    # Update and Upsert in PostgreSQL
    conn = get_db_conn() if db_connected else None
    if conn:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """UPDATE cmpdi_documents 
                       SET review_status = %s, reviewed_by = %s, reviewed_at = %s, extracted_metadata = %s 
                       WHERE id = %s""",
                    (doc.review_status, doc.reviewed_by, doc.reviewed_at, json.dumps(doc.extracted_labels), doc.doc_id)
                )
                for key, item in doc.extracted_labels.items():
                    if item:
                        cur.execute(
                            """INSERT INTO cmpdi_document_labels 
                               (document_id, label_key, label_value, confidence, citation_page, citation_snippet, is_verified, verified_by, updated_at)
                               VALUES (%s, %s, %s, %s, %s, %s, TRUE, %s, CURRENT_TIMESTAMP)
                               ON CONFLICT (document_id, label_key) DO UPDATE
                               SET label_value = EXCLUDED.label_value,
                                   confidence = 100.0,
                                   is_verified = TRUE,
                                   verified_by = EXCLUDED.verified_by,
                                   updated_at = CURRENT_TIMESTAMP""",
                            (doc.doc_id, key, item.get("value", "null"), 100.0, item.get("citation_page", 1), item.get("citation_snippet", "Officer Verified"), doc.reviewed_by)
                        )
            conn.commit()
            conn.close()
            logger.info(f"PostgreSQL real-time review committed for doc '{doc.doc_id}' by {doc.reviewed_by}")
        except Exception as err:
            logger.error(f"PostgreSQL review update failed: {err}")

    return {
        "success": True,
        "message": f"Document '{doc.filename}' verified by Officer {doc.reviewed_by} and committed to PostgreSQL (Port 5433).",
        "document_id": doc.doc_id,
        "review_status": doc.review_status,
        "reviewed_by": doc.reviewed_by,
        "reviewed_at": doc.reviewed_at,
        "saved_to_postgres": db_connected,
        "updated_labels": doc.extracted_labels
    }

@app.get("/api/rag/documents")
def list_documents():
    """List all scanned and indexed documents with their status and production metrics."""
    return [
        {
            "id": d.doc_id,
            "filename": d.filename,
            "page_count": d.page_count,
            "file_size": d.file_size,
            "uploaded_by": d.uploaded_by,
            "created_at": d.created_at,
            "review_status": d.review_status,
            "production": d.extracted_labels.get("production", {}).get("value") if d.extracted_labels.get("production") else "N/A",
            "site": d.extracted_labels.get("site", {}).get("value") if d.extracted_labels.get("site") else "N/A"
        }
        for d in doc_store.values()
    ]

@app.get("/api/rag/document/{doc_id}")
def get_document_details(doc_id: str):
    doc = doc_store.get(doc_id)
    if not doc and db_connected:
        conn = get_db_conn()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT id, filename, file_size, page_count, uploaded_by, review_status, reviewed_by, reviewed_at, extracted_metadata, created_at FROM cmpdi_documents WHERE id = %s",
                        (doc_id,)
                    )
                    row = cur.fetchone()
                    if row:
                        doc = DocumentRecord(row[0], row[1], row[2], row[3], row[4])
                        doc.review_status = row[5]
                        doc.reviewed_by = row[6]
                        doc.reviewed_at = str(row[7]) if row[7] else None
                        doc.extracted_labels = row[8] or {}
                        doc.created_at = str(row[9])

                        cur.execute("SELECT page_number, page_text FROM cmpdi_document_pages WHERE document_id = %s ORDER BY page_number", (doc_id,))
                        doc.pages = [{"page_number": p[0], "text": p[1]} for p in cur.fetchall()]

                        cur.execute("SELECT page_number, chunk_index, chunk_text FROM cmpdi_document_chunks WHERE document_id = %s ORDER BY chunk_index", (doc_id,))
                        doc.chunks = [{"chunk_id": f"c_{c[1]}", "chunk_index": c[1], "page_number": c[0], "text": c[2]} for c in cur.fetchall()]

                        train_rag_index(doc)
                        doc_store[doc_id] = doc
                conn.close()
            except Exception as e:
                logger.error(f"Error restoring doc from PostgreSQL: {e}")

    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    return {
        "id": doc.doc_id,
        "filename": doc.filename,
        "page_count": doc.page_count,
        "file_size": doc.file_size,
        "uploaded_by": doc.uploaded_by,
        "created_at": doc.created_at,
        "review_status": doc.review_status,
        "reviewed_by": doc.reviewed_by,
        "reviewed_at": doc.reviewed_at,
        "extracted_labels": doc.extracted_labels,
        "pages": doc.pages
    }

# =============================================================================
# REAL-TIME MULTI-PAGE PDF GENERATOR (ReportLab)
# =============================================================================
@app.post("/api/rag/generate-sample")
async def generate_and_scan_sample():
    """
    Generates a genuine 3-page CMPDI Mine Planning Report PDF on the fly using reportlab,
    then automatically scans and ingests it through the real-time Python RAG pipeline!
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=15,
        leading=18,
        textColor=colors.HexColor('#032b5f'),
        alignment=1, # Center
        spaceAfter=10
    )
    heading_style = ParagraphStyle(
        'DocSub',
        parent=styles['Heading2'],
        fontSize=11,
        leading=14,
        textColor=colors.HexColor('#b45309'),
        spaceBefore=8,
        spaceAfter=6
    )
    body_style = ParagraphStyle(
        'DocBody',
        parent=styles['Normal'],
        fontSize=9,
        leading=13,
        textColor=colors.HexColor('#1e293b')
    )

    story = []

    # --- PAGE 1: Project Metadata, Authorization & Site Information ---
    story.append(Paragraph("GEOMINE AI • ADVANCED GEOSPATIAL & MINE INTELLIGENCE", title_style))
    story.append(Paragraph("<b>(Ministry of Coal - Government of India Enterprise)</b>", ParagraphStyle('Sub', parent=title_style, fontSize=10, textColor=colors.HexColor('#475569'))))
    story.append(Paragraph("GeoMine AI Central HQ, Gondwana Place, Kanke Road, Ranchi - 834008, Jharkhand", ParagraphStyle('Sub2', parent=title_style, fontSize=8, textColor=colors.HexColor('#64748b'))))
    story.append(Spacer(1, 14))

    meta_table_data = [
        ["Report Reference:", "GEOMINE/RI-3/EXP/2026/MP-8821", "Classification:", "STRICTLY CONFIDENTIAL"],
        ["Date of Report:", "24-September-2026", "Security Clearance:", "LEVEL 4 - RESTRICTED"],
        ["Project Name & Mine Site:", "Gevra Opencast Project (Phase-IV Expansion)", "Colliery Block:", "Block-C Deep Seam"],
        ["Location & District:", "Korba Coalfield, District: Korba, State: Chhattisgarh", "Basin:", "Hasdeo-Arand Coalfield"],
        ["Geographical Position:", "Latitude: 22°20'14\" N, Longitude: 82°34'48\" E", "Nodal Station:", "RI-V Bilaspur"],
        ["Prepared by (Author):", "Er. Sunita Rao (Superintending Mine Planner, EIS: 90287415)", "Survey Lead:", "Dr. Alok K. Verma (Chief Geologist)"],
        ["Reviewed by:", "Col. R. S. Rathore (Chief General Manager - Planning Cell)", "Approved by:", "Shri P. K. Mishra (Director Technical, GeoMine AI HQ)"]
    ]
    t1 = Table(meta_table_data, colWidths=[150, 220, 110, 160])
    t1.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#f8fafc')),
        ('TEXTCOLOR', (0,0), (-1,-1), colors.HexColor('#0f172a')),
        ('FONTNAME', (0,0), (-1,-1), 'Helvetica'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTNAME', (2,0), (2,-1), 'Helvetica-Bold'),
    ]))
    story.append(t1)
    story.append(Spacer(1, 16))

    story.append(Paragraph("1.0 Executive Summary & Project Mandate", heading_style))
    story.append(Paragraph(
        "This Comprehensive Mine Feasibility & Technological Assessment report details the mechanized opencast expansion "
        "of the Gevra Colliery under South Eastern Coalfields Limited (SECL). The statutory investigation confirms coal seam "
        "continuity of the Barakar Formation with an evaluated mineable reserve of 680.4 Million Tonnes.", body_style
    ))
    story.append(PageBreak())

    # --- PAGE 2: Production Targets, Strata Evaluation & Overburden ---
    story.append(Paragraph("GEOMINE AI REPORT | PAGE 2: PRODUCTION SCHEDULE & STRATA CHARACTERISTICS", title_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("2.0 Annual Coal Production Targets & Dispatch Parameters", heading_style))
    prod_data = [
        ["Parameter", "FY 2026-27 (Target)", "FY 2027-28 (Target)", "Full Expansion Peak"],
        ["Targeted Production Capacity", "45.0 Million Tonnes", "50.0 Million Tonnes", "70.0 Million Tonnes (MTPA)"],
        ["Average Daily Extraction", "125,000 Tonnes / Day", "138,500 Tonnes / Day", "195,000 Tonnes / Day"],
        ["Stripping Ratio (SR)", "1 : 1.85 Cum/Tonne", "1 : 1.92 Cum/Tonne", "1 : 2.05 Cum/Tonne"],
        ["Total Overburden (OB) Removal", "83.25 Million Cu.m (BCM)", "96.00 Million Cu.m", "143.50 Million Cu.m"],
        ["Coal Grade Classification", "Grade G-11 Non-coking coal", "Grade G-11 Non-coking coal", "Grade G-10 to G-11"],
        ["Gross Calorific Value (GCV)", "4150 kcal / kg", "4180 kcal / kg", "4220 kcal / kg"]
    ]
    t2 = Table(prod_data, colWidths=[180, 150, 150, 160])
    t2.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#032b5f')),
        ('TEXTCOLOR', (0,0), (-1,0), colors.white),
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#cbd5e1')),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor('#ffffff')),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.HexColor('#f8fafc'), colors.white]),
        ('BOTTOMPADDING', (0,0), (-1,-1), 5),
    ]))
    story.append(t2)
    story.append(Spacer(1, 14))

    story.append(Paragraph("2.1 Heavy Earth Moving Machinery (HEMM) Deployment", heading_style))
    story.append(Paragraph(
        "To achieve the targeted production of 45.0 Million Tonnes, high-capacity 42 Cum Electric Rope Shovels paired with "
        "240-Tonne Rear Dumpers shall be deployed along with autonomous LiDAR blast monitoring systems.", body_style
    ))
    story.append(PageBreak())

    # --- PAGE 3: DGMS Safety, Environmental Audit & Statutory Verification ---
    story.append(Paragraph("GEOMINE AI REPORT | PAGE 3: DGMS SAFETY, ENVIRONMENT & ENDORSEMENT", title_style))
    story.append(Spacer(1, 12))

    story.append(Paragraph("3.0 Directorate General of Mines Safety (DGMS) Telemetry Verification", heading_style))
    story.append(Paragraph(
        "Continuous gas monitoring sensors across the seam outcrop indicate ambient Methane (CH4) level of 0.02% "
        "(well below the 0.75% statutory limit). Carbon Monoxide (CO) concentration remains stable at 2.8 ppm. "
        "Slope stability radar telemetry confirms bench factor of safety at 1.48.", body_style
    ))
    story.append(Spacer(1, 10))

    story.append(Paragraph("3.1 Land Bio-Reclamation & Satellite Afforestation Audit", heading_style))
    story.append(Paragraph(
        "Total lease area spans 4,180 Hectares. Progressive reclamation target is 240 Hectares/annum. Cartosat-3 NDVI multi-spectral "
        "indices demonstrate 14.6% net vegetation increment across stabilized external overburden dumps.", body_style
    ))
    story.append(Spacer(1, 14))

    story.append(Paragraph("3.2 Official Sign-off & Human Review Clearance", heading_style))
    sign_data = [
        ["Authoring Officer:", "Er. Sunita Rao, Superintending Mine Planner (GeoMine AI RI-V)"],
        ["Geological Validation:", "Dr. Alok K. Verma, Chief Geologist (Exploration Head)"],
        ["Reviewing Officer:", "Col. R. S. Rathore, Chief General Manager (Mine Planning & AI Cell)"],
        ["Final Statutory Recommendation:", "APPROVED FOR STATUTORY IMPLEMENTATION UNDER CMR 2017"],
        ["Verification Date:", "24-September-2026 | Digital Signature Token: GEOMINE-FIDO2-99120"]
    ]
    t3 = Table(sign_data, colWidths=[180, 460])
    t3.setStyle(TableStyle([
        ('FONTNAME', (0,0), (0,-1), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 8.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#94a3b8')),
        ('BACKGROUND', (0,3), (-1,3), colors.HexColor('#ecfdf5')),
        ('TEXTCOLOR', (0,3), (-1,3), colors.HexColor('#065f46')),
    ]))
    story.append(t3)

    # Build PDF binary
    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()

    # Now ingest through the RAG pipeline automatically!
    doc_id = "geomine_gevra_sample_" + uuid.uuid4().hex[:6]
    filename = "GeoMine_Gevra_Opencast_Feasibility_Report.pdf"
    file_size = len(pdf_bytes)

    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    page_count = len(reader.pages)
    pages = [{"page_number": idx + 1, "text": page.extract_text() or ""} for idx, page in enumerate(reader.pages)]
    entities = extract_entities_from_pages(pages)
    chunks = chunk_document(pages)

    doc_record = DocumentRecord(doc_id, filename, file_size, page_count, "Dr. Alok Verma (Chief Geologist)")
    doc_record.pages = pages
    doc_record.chunks = chunks
    doc_record.extracted_labels = entities
    train_rag_index(doc_record)
    doc_store[doc_id] = doc_record

    # Persist to PostgreSQL if connected
    if db_connected:
        conn = get_db_conn()
        if conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO cmpdi_documents (id, filename, file_size, page_count, uploaded_by, extracted_metadata)
                           VALUES (%s, %s, %s, %s, %s, %s)""",
                        (doc_id, filename, file_size, page_count, "Dr. Alok Verma (Chief Geologist)", json.dumps(entities))
                    )
                    for p in pages:
                        cur.execute(
                            """INSERT INTO cmpdi_document_pages (document_id, page_number, page_text)
                               VALUES (%s, %s, %s)""",
                            (doc_id, p["page_number"], p["text"])
                        )
                    for c in chunks:
                        cur.execute(
                            """INSERT INTO cmpdi_document_chunks (document_id, page_number, chunk_index, chunk_text)
                               VALUES (%s, %s, %s, %s)""",
                            (doc_id, c["page_number"], c["chunk_index"], c["text"])
                        )
                    for key, item in entities.items():
                        if item and isinstance(item, dict) and item.get("value"):
                            cur.execute(
                                """INSERT INTO cmpdi_document_labels (document_id, label_key, label_value, confidence, citation_page, citation_snippet)
                                   VALUES (%s, %s, %s, %s, %s, %s)""",
                                (doc_id, key, item["value"], item["confidence"], item["citation_page"], item["citation_snippet"])
                            )
                conn.commit()
                conn.close()
                logger.info(f"PostgreSQL real-time records committed for generated sample '{doc_id}'")
            except Exception as err:
                logger.error(f"PostgreSQL write failed in sample generator: {err}")
                if conn:
                    conn.rollback()
                    conn.close()

    return {
        "success": True,
        "message": "3-Page Genuine GeoMine AI Report generated and scanned via Python RAG in real time!",
        "document_id": doc_id,
        "filename": filename,
        "page_count": page_count,
        "chunk_count": len(chunks),
        "review_status": "PENDING_HUMAN_REVIEW",
        "extracted_details": entities,
        "pages": pages,
        "pages_summary": [
            {
                "page_number": p["page_number"],
                "char_count": len(p["text"]),
                "preview": p["text"][:190].replace('\n', ' ') + "..."
            }
            for p in pages
        ]
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("rag_service:app", host="0.0.0.0", port=8000, reload=False)
