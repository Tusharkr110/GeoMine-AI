# CMPDI AI-Based System — Restricted Officer & Admin Portal + Real-Time Python RAG Studio
### Central Mine Planning & Design Institute Limited (Coal India Limited / Ministry of Coal, Govt. of India)
*Smart India Hackathon (SIH) Project*

---

## 🏛️ Project Overview
This repository contains:
1. **Restricted Access Authentication Portal**: Designed exclusively for CMPDI Officers & System Administrators with 2FA OTP, biometric simulation, lockout security, and institutional Indian Government branding.
2. **Real-Time Python RAG & Document Intelligence Studio**: A pure-working, multi-page PDF ingestion, hybrid lexical & vector semantic search engine (BM25 + TF-IDF) with side-by-side snapshot viewing, automatic entity extraction, confidence scoring, page citations, and human-in-the-loop review persisted to PostgreSQL.

---

## 📄 Real-Time Python RAG & PDF Intelligence Studio

### 1. Multi-Page PDF Ingestion & Real-Time Scanning (`pypdf`)
- Drag-and-drop or select any real multi-page mining PDF.
- Extracts raw text page by page with full positional tracking.
- Performs semantic chunking into overlapping windows (150 words with 35-word overlap).

### 2. Entity Extraction with Confidence & Citations
Extracts critical mining parameters in real time directly from the document:
- **Targeted Production**: e.g., `45.0 Million Tonnes`, `42.5 MTPA`
- **Reviewing Officer**: e.g., `Col. R. S. Rathore, Chief General Manager (Planning Cell)`
- **Author / Mine Planner**: e.g., `Er. Sunita Rao, Superintending Mine Planner`
- **Report Date**: e.g., `24-September-2026`
- **Mine Site & Colliery**: e.g., `Gevra Opencast Project (Phase-IV Expansion)`
- **Location & Basin**: e.g., `Korba Coalfield, District: Korba, Chhattisgarh`
- **Coal Seam Grade**: e.g., `Grade G-11 Non-coking coal`
- **Stripping Ratio (SR)**: e.g., `1 : 1.85 Cum/Tonne`
- **Overburden (OB) Removal**: e.g., `83.25 Million Cu.m (BCM)`

Each extracted field is tagged with:
- **Confidence %**: e.g., `97.0% High`
- **Citation Page**: Exact page number where the evidence is located
- **Citation Snippet**: Contextual sentence preview
- **Jump Button**: Clicking auto-jumps the left viewer and highlights the text!

### 3. Side-by-Side Split Workspace
- **Left Column (Multi-Page Snapshot Viewer)**:
  - Page Navigation: `< Prev`, `Page X / Y`, `Next >`
  - High-fidelity visual snapshot of the page layout.
  - Interactive **Glowing Citation Highlight** (`.highlight-citation`) that pulses over the cited text when clicked!
- **Right Column (Intelligence & Human Review Console)**:
  - **Tab 1: Extracted Key Details**: Editable entity cards with confidence gauges and jump links.
  - **Human-in-the-Loop Review**: One-click `[Verify & Label as Officer]` that marks the document as verified and persists to PostgreSQL.
  - **Tab 2: Interactive RAG Q&A Assistant**: Hybrid BM25 (`rank_bm25`) + TF-IDF cosine retrieval with confidence scores and clickable citation cards.
  - **Tab 3: PostgreSQL Repository**: Table of all indexed documents in PostgreSQL table `cmpdi_documents`.

### 4. "No Seed Data — Pure Working" Real-Time Generator
- Click the button: **`[ ⚡ Generate & Scan Live CMPDI 3-Page Report (Pure Working) ]`**
- Uses Python's `reportlab` to compile a genuine 3-page CMPDI Mine Exploration & Production Report PDF in memory, then automatically scans, chunks, trains, and displays it live side-by-side!

---

## 👥 Pre-Configured Test Credentials

| Role | Name & Designation | Station / RI | EIS Number | Password | Admin Key / OTP |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **CMPDI Officer** | Dr. Alok K. Verma *(Chief Geologist)* | RI-III Ranchi | `90342118` | `Password@123` | Demo OTP: Auto / `742918` |
| **CMPDI Officer** | Er. Sunita Rao *(Sr. Mine Planner)* | RI-V Bilaspur | `90287415` | `Password@123` | Demo OTP: Auto / `742918` |
| **System Admin** | Col. R. S. Rathore *(CISO & IT Head)* | HQ Ranchi | `90110024` | `Admin@Cmpdi2026` | Token: `CMPDI-ROOT-SEC-8829` |

> *Tip: You can click the preset banner at the top (`Fill as Chief Geologist`, `Launch PDF RAG Studio`) to test instantly in 1 click!*

---

## 🚀 How to Run the Application

Both servers can run simultaneously:

### 1. Start the Node.js Web Portal (Port 5000)
```powershell
cd "C:\Users\Tushar Kumar\Desktop\SIH Proj\Cmpdi Ai Based"
npm start
```
*Accessible at: `http://localhost:5000`*

### 2. Start the Python RAG Service (Port 8000)
```powershell
cd "C:\Users\Tushar Kumar\Desktop\SIH Proj\Cmpdi Ai Based"
python rag_service.py
```
*Accessible at: `http://localhost:8000` (and proxied automatically via `http://localhost:5000/api/rag`)*

---

## 🗄️ PostgreSQL Database Schema (`Port 5433 / cmpdi_portal`)

- `users`: Registered Officers and System Administrators
- `audit_logs`: Timestamped cryptographic security logs
- `active_sessions`: 2FA OTP codes and session states
- `cmpdi_documents`: Ingested multi-page PDFs, page count, and review status
- `cmpdi_document_pages`: Page-by-page extracted raw text
- `cmpdi_document_chunks`: Indexed text chunks for RAG search
- `cmpdi_document_labels`: Extracted entities (Production, Reviewer, Site, etc.) with confidence and citations
- `cmpdi_rag_queries`: Log of queries, answers, and citation evidence
