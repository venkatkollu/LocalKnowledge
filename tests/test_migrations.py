import hashlib
import sqlite3

from app.chunking import StructuredChunker, sha256
from app.config import Settings
from app.parsing import StructuredParser
from app.storage import SQLiteStorage


def test_additive_schema_migration_preserves_original_tables(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as con:
        con.executescript("""
        CREATE TABLE documents(id INTEGER PRIMARY KEY,path TEXT UNIQUE,filename TEXT,content_hash TEXT,size INTEGER,modified REAL,version INTEGER,status TEXT,error TEXT,updated_at REAL);
        CREATE TABLE document_versions(id INTEGER PRIMARY KEY,document_id INTEGER,version INTEGER,content_hash TEXT,size INTEGER,parser_version TEXT,chunker_version TEXT,embedding_model TEXT,created_at REAL);
        CREATE TABLE chunks(id INTEGER PRIMARY KEY,content TEXT);
        INSERT INTO documents VALUES(1,'/legacy.txt','legacy.txt','sha',5,0,1,'indexed',NULL,0);
        INSERT INTO chunks VALUES(1,'original evidence');
        """)
    settings = Settings(db_path=database, knowledge_dir=tmp_path / "knowledge", auto_sync=False)
    storage = SQLiteStorage(settings)
    storage.initialize()
    storage.initialize() # Migration is idempotent.
    with storage.connect() as con:
        assert con.execute("SELECT content FROM chunks WHERE id=1").fetchone()[0] == "original evidence"
        assert con.execute("SELECT tenant_id,owner_id FROM documents WHERE id=1").fetchone()[0] == "local"
        assert con.execute("SELECT value FROM rag_state WHERE key='schema_version'").fetchone()[0] == "2"


def test_hashing_and_heading_attribution_preserve_original_bytes(tmp_path):
    raw = b"# Title\n\n## First\nFirst section facts.\n\n## Second\nSecond section facts.\n"
    assert sha256(raw) == hashlib.sha256(raw).hexdigest()
    sections = StructuredParser().parse(tmp_path / "notes.md", raw)
    chunks = StructuredChunker(100, 10).split(sections)
    first = next(chunk for chunk in chunks if "First section" in chunk["raw_content"])
    second = next(chunk for chunk in chunks if "Second section" in chunk["raw_content"])
    assert first["metadata"]["section"] == "First"
    assert second["metadata"]["section"] == "Second"
    assert first["raw_content"] in raw.decode()


def test_pdf_page_provenance_is_preserved(tmp_path):
    from pypdf import PdfWriter
    from io import BytesIO
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_blank_page(width=100, height=100)
    stream = BytesIO()
    writer.write(stream)
    sections = StructuredParser().parse(tmp_path / "notes.pdf", stream.getvalue())
    assert [section["page"] for section in sections] == [1, 2]
