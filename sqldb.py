"""Lecture et modification encadrées d'une base de données SQLite envoyée par l'utilisateur.

Tout se passe sur une COPIE en mémoire (le fichier d'origine n'est jamais modifié). Un « autorisateur »
SQLite refuse les opérations dangereuses (ATTACH, PRAGMA, extensions, accès aux fichiers) et une limite
de temps interrompt les requêtes trop longues."""
import sqlite3
import time

TIME_LIMIT = 5  # secondes par requête / script
MAX_ROWS = 40
MAX_CHARS = 4000

_C = sqlite3
READ_ACTIONS = {_C.SQLITE_SELECT, _C.SQLITE_READ, _C.SQLITE_FUNCTION, _C.SQLITE_RECURSIVE}
WRITE_ACTIONS = READ_ACTIONS | {
    _C.SQLITE_INSERT, _C.SQLITE_UPDATE, _C.SQLITE_DELETE,
    _C.SQLITE_CREATE_TABLE, _C.SQLITE_CREATE_INDEX, _C.SQLITE_CREATE_VIEW, _C.SQLITE_CREATE_TRIGGER,
    _C.SQLITE_ALTER_TABLE, _C.SQLITE_DROP_TABLE, _C.SQLITE_DROP_INDEX, _C.SQLITE_DROP_VIEW,
    _C.SQLITE_DROP_TRIGGER, _C.SQLITE_TRANSACTION, _C.SQLITE_SAVEPOINT,
}
SAFE_PRAGMAS = {"table_info", "table_xinfo", "foreign_key_list", "index_list", "index_info"}
BANNED_FUNCTIONS = {"load_extension", "readfile", "writefile", "edit", "fts3_tokenizer", "zipfile"}


def _authorizer(write: bool):
    allowed = WRITE_ACTIONS if write else READ_ACTIONS

    def auth(action, arg1, arg2, dbname, source):
        if action == _C.SQLITE_PRAGMA:
            return _C.SQLITE_OK if (arg1 or "").lower() in SAFE_PRAGMAS else _C.SQLITE_DENY
        if action == _C.SQLITE_FUNCTION and (arg2 or "").lower() in BANNED_FUNCTIONS:
            return _C.SQLITE_DENY
        return _C.SQLITE_OK if action in allowed else _C.SQLITE_DENY

    return auth


def check(data: bytes):
    """Vérifie qu'il s'agit bien d'un fichier SQLite lisible."""
    if not data.startswith(b"SQLite format 3\x00"):
        raise ValueError("Ce fichier n'est pas une base de données SQLite (.db / .sqlite).")
    try:
        _open(data, write=False).execute("select count(*) from sqlite_master").fetchone()
    except sqlite3.Error as e:
        raise ValueError(f"Base SQLite illisible : {e}")


def _open(data: bytes, write: bool):
    conn = sqlite3.connect(":memory:")
    conn.deserialize(data)
    conn.execute("PRAGMA foreign_keys=ON")  # les contraintes de clés étrangères sont respectées
    conn.set_authorizer(_authorizer(write))
    deadline = time.time() + TIME_LIMIT
    conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 20000)
    return conn


def from_sql_dump(data: bytes) -> bytes | None:
    """Construit une base SQLite à partir d'un script .sql ; None si le script n'est pas du SQLite valide
    (par ex. un dump MySQL ou PostgreSQL)."""
    try:
        text = data.decode("utf-8-sig")
        conn = sqlite3.connect(":memory:")
        conn.set_authorizer(_authorizer(True))
        deadline = time.time() + TIME_LIMIT
        conn.set_progress_handler(lambda: 1 if time.time() > deadline else 0, 20000)
        conn.executescript(text)
        if not conn.execute("select count(*) from sqlite_master where type='table'").fetchone()[0]:
            return None
        conn.set_authorizer(None)  # serialize() a besoin de PRAGMA page_count ; le script a déjà été exécuté
        return conn.serialize()
    except Exception:
        return None


def _q(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def counts(data: bytes) -> dict[str, int]:
    conn = _open(data, write=False)
    names = [r[0] for r in conn.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%' order by name")]
    return {n: conn.execute(f"select count(*) from {_q(n)}").fetchone()[0] for n in names}


def summary(data: bytes) -> str:
    """Structure + aperçu, envoyés à l'IA : CREATE TABLE, nombre de lignes, dernier identifiant, 3 exemples."""
    conn = _open(data, write=False)
    out = []
    tables = conn.execute("select name, sql from sqlite_master where type='table' and name not like 'sqlite_%' order by name").fetchall()
    for name, sql in tables[:15]:
        n = conn.execute(f"select count(*) from {_q(name)}").fetchone()[0]
        cols = conn.execute(f"pragma table_info({_q(name)})").fetchall()  # cid, name, type, notnull, dflt, pk
        line = f"Table « {name} » : {n} ligne(s)"
        pks = [c for c in cols if c[5]]
        if len(pks) == 1 and "INT" in (pks[0][2] or "").upper():
            last = conn.execute(f"select max({_q(pks[0][1])}) from {_q(name)}").fetchone()[0]
            line += f", dernier identifiant ({pks[0][1]}) = {last}"
        out.append(line)
        out.append((sql or "").strip()[:600])
        for row in conn.execute(f"select * from {_q(name)} limit 3"):
            out.append("  " + " | ".join(str(v)[:30] for v in row))
    if len(tables) > 15:
        out.append(f"... et {len(tables) - 15} autre(s) table(s)")
    return "\n".join(out)[:MAX_CHARS]


def query(data: bytes, sql: str) -> str:
    """Exécute une requête de LECTURE et retourne le résultat sous forme de texte."""
    try:
        conn = _open(data, write=False)
        cur = conn.execute(sql)
        rows = cur.fetchmany(MAX_ROWS + 1)
    except sqlite3.Error as e:
        return f"Erreur SQL : {e}"
    if cur.description is None:
        return "Cette requête ne retourne pas de données (lecture seule : utilise SELECT)."
    header = " | ".join(d[0] for d in cur.description)
    lines = [header] + [" | ".join("NULL" if v is None else str(v)[:60] for v in r) for r in rows[:MAX_ROWS]]
    text = "\n".join(lines)
    if len(rows) > MAX_ROWS:
        text += f"\n[... résultat tronqué à {MAX_ROWS} lignes : affine la requête (WHERE, COUNT, SUM...)]"
    return text[:MAX_CHARS]


def execute_script(data: bytes, script: str) -> dict:
    """Applique un script SQL sur une copie. Retourne {error, data, changes, before, after}."""
    before = counts(data)
    try:
        conn = _open(data, write=True)
        conn.executescript(script)
        changes = conn.total_changes
        conn.set_authorizer(None)  # le script a déjà été exécuté ; serialize() a besoin de PRAGMA page_count
        new = conn.serialize()
    except sqlite3.Error as e:
        return {"error": f"Erreur SQL : {e}", "data": None, "changes": 0, "before": before, "after": before}
    try:
        after = counts(new)
    except sqlite3.Error as e:
        return {"error": f"Base invalide après le script : {e}", "data": None, "changes": 0, "before": before, "after": before}
    return {"error": None, "data": new, "changes": changes, "before": before, "after": after}
