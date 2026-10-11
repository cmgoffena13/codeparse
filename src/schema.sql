PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

-- DROP TABLE IF EXISTS watermarks; -- TODO: Remove this after testing.
-- DROP TABLE IF EXISTS directories;
-- DROP TABLE IF EXISTS files;
-- DROP TABLE IF EXISTS symbol_bases;
-- DROP TABLE IF EXISTS symbols;
-- DROP TABLE IF EXISTS symbol_references_staging;
-- DROP TABLE IF EXISTS symbol_references;
-- DROP TABLE IF EXISTS imports;
-- DROP TABLE IF EXISTS symbols_fts;

CREATE TABLE IF NOT EXISTS watermarks (
    id                  INTEGER NOT NULL PRIMARY KEY CHECK (id = 1),
    last_full_parse     INTEGER NOT NULL DEFAULT 0,
    last_incremental    INTEGER DEFAULT 0
);
INSERT OR IGNORE INTO watermarks (id, last_full_parse, last_incremental) VALUES (1, 0, 0);

CREATE TABLE IF NOT EXISTS directories (
    id              INTEGER NOT NULL PRIMARY KEY,
    parent_id       INTEGER REFERENCES directories(id),  
    name            TEXT NOT NULL,                     
    path            TEXT UNIQUE NOT NULL,               
    depth           INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS files (
    id              INTEGER NOT NULL PRIMARY KEY,
    directory_id    INTEGER REFERENCES directories(id),
    name            TEXT NOT NULL,                       
    path            TEXT UNIQUE NOT NULL,   
    normalized_path TEXT NOT NULL,             
    language        TEXT,                                          
    content_hash    TEXT NOT NULL,                               
    line_count      INTEGER NOT NULL DEFAULT 0,
    symbol_count    INTEGER NOT NULL DEFAULT 0,
    is_test         BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE UNIQUE INDEX IF NOT EXISTS files_normalized_path_index ON files (normalized_path);

CREATE TABLE IF NOT EXISTS symbols (
    id              INTEGER NOT NULL PRIMARY KEY,
    file_id         INTEGER NOT NULL REFERENCES files(id),
    parent_id       INTEGER REFERENCES symbols(id), 
    name            TEXT NOT NULL,                  
    qualified_name  TEXT NOT NULL,                        
    kind            TEXT NOT NULL,                  
    line_start      INTEGER NOT NULL,                
    line_end        INTEGER NOT NULL,                
    line_count      INTEGER NOT NULL,               
    signature       TEXT NOT NULL,                           
    docstring       TEXT,                            
    modifiers       TEXT,                           
    language        TEXT NOT NULL,
    is_test         BOOLEAN NOT NULL DEFAULT FALSE               
);
CREATE INDEX IF NOT EXISTS symbols_file_id_index ON symbols (file_id);
CREATE UNIQUE INDEX IF NOT EXISTS symbols_qualified_name_index ON symbols (qualified_name);

CREATE TABLE IF NOT EXISTS symbol_bases (
    symbol_id               INTEGER NOT NULL REFERENCES symbols(id),
    base_qualified_name     TEXT NOT NULL,
    PRIMARY KEY (symbol_id, base_qualified_name)
);
CREATE INDEX IF NOT EXISTS symbol_bases_base_qualified_name_index
    ON symbol_bases (base_qualified_name);

CREATE TABLE IF NOT EXISTS symbol_references_staging (
    id                          INTEGER NOT NULL,
    ref_symbol_name             TEXT NOT NULL,                 
    ref_symbol_qualified_name   TEXT NOT NULL,
    source_file_id              INTEGER NOT NULL REFERENCES files(id),
    source_line                 INTEGER NOT NULL,
    source_column               INTEGER NOT NULL,
    ref_kind                    TEXT NOT NULL,                  
    context                     TEXT                             
);

CREATE TABLE IF NOT EXISTS symbol_references (
    id                          INTEGER NOT NULL PRIMARY KEY,
    ref_symbol_id               INTEGER NOT NULL REFERENCES symbols(id), 
    ref_symbol_file_id          INTEGER NOT NULL REFERENCES files(id),
    ref_symbol_name             TEXT NOT NULL,       
    ref_symbol_qualified_name   TEXT NOT NULL,
    source_file_id              INTEGER NOT NULL REFERENCES files(id), 
    source_line                 INTEGER NOT NULL,
    source_column               INTEGER NOT NULL,
    ref_kind                    TEXT NOT NULL,                  
    context                     TEXT NOT NULL                     
);
CREATE INDEX IF NOT EXISTS symbol_references_source_file_id_index ON symbol_references (source_file_id);
CREATE INDEX IF NOT EXISTS symbol_references_ref_symbol_qualified_name_index ON symbol_references (ref_symbol_qualified_name);

CREATE TABLE IF NOT EXISTS imports (
    id                    INTEGER NOT NULL PRIMARY KEY,
    file_id               INTEGER NOT NULL REFERENCES files(id),
    import_path           TEXT NOT NULL,                           
    imported_symbol       TEXT NOT NULL DEFAULT '',                           
    alias                 TEXT,                           
    line_number           INTEGER NOT NULL,                        
    import_type           TEXT NOT NULL, 
    import_scope          TEXT NOT NULL, 
    signature             TEXT NOT NULL, 
    imported_file_id      INTEGER REFERENCES files(id),
    watermark             INTEGER NOT NULL DEFAULT (strftime('%s','now'))
);
CREATE INDEX IF NOT EXISTS imports_file_id_index ON imports (file_id);
CREATE INDEX IF NOT EXISTS imports_import_path_index ON imports (import_path, watermark);
CREATE INDEX IF NOT EXISTS imports_imported_file_id_index ON imports (imported_file_id);


/* NOTE: Full Text Search "Tables" for symbols */
CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
    qualified_name,
    docstring,
    signature,
    content='symbols',
    content_rowid='id'
);
