"""Exécution encadrée du code Python (pandas/openpyxl) écrit par l'IA pour modifier un Excel.

Protections : vérification du code avant exécution (imports autorisés, pas de fonctions
dangereuses, pas de chemins/URL), processus séparé SANS les variables d'environnement
(donc sans clés API), dossier temporaire jetable, limite de temps et de mémoire (Linux)."""
import ast
import importlib.util
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

# pandas est optionnel (lourd) : absent de l'hébergement léger. NO_PANDAS=1 pour le simuler.
HAS_PANDAS = importlib.util.find_spec("pandas") is not None and not os.getenv("NO_PANDAS")

ALLOWED_MODULES = {
    "pandas", "numpy", "openpyxl", "datetime", "random", "math", "re", "collections", "itertools",
    "string", "statistics", "decimal", "copy", "json", "unicodedata", "calendar", "typing",
    "functools", "operator", "fractions", "time",
}
BANNED_NAMES = {
    "open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "globals", "locals",
    "vars", "getattr", "setattr", "delattr", "exit", "quit", "memoryview", "help",
}
BANNED_ATTRS = {
    "system", "popen", "read_pickle", "to_pickle", "read_sql", "read_sql_query", "read_sql_table",
    "to_sql", "read_html", "read_clipboard", "to_clipboard", "read_feather", "to_feather",
    "read_parquet", "to_parquet", "read_orc", "read_stata", "to_stata", "read_sas", "read_spss",
    "read_hdf", "to_hdf", "read_xml", "to_xml", "read_fwf", "eval", "fromfile", "tofile",
    "load", "loadtxt", "genfromtxt", "save", "savetxt", "savez",
}
# chemins absolus/parents, URL, accès au système de fichiers sensibles
BAD_STRING = re.compile(r"^(/|~|[A-Za-z]:[\\/]|\\\\)|\.\.[\\/]|://|/proc|/etc|/sys")


def check(code: str) -> str | None:
    """Retourne un message d'erreur si le code est refusé, sinon None."""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"Erreur de syntaxe ligne {e.lineno} : {e.msg}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.name.split(".")[0] not in ALLOWED_MODULES:
                    return f"Import interdit : {a.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.level or (node.module or "").split(".")[0] not in ALLOWED_MODULES:
                return f"Import interdit : {node.module}"
        elif isinstance(node, ast.Name) and (node.id in BANNED_NAMES or node.id.startswith("__")):
            return f"Nom interdit : {node.id}"
        elif isinstance(node, ast.Attribute) and (node.attr in BANNED_ATTRS or node.attr.startswith("__")):
            # .save est autorisé sur un classeur openpyxl (wb.save(OUTPUT)) : géré ci-dessous
            if node.attr == "save":
                continue
            return f"Méthode interdite : .{node.attr}"
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and BAD_STRING.search(node.value):
            return "Chemin ou URL interdit : utilise uniquement INPUT et OUTPUT."
    return None


def _limits():  # Linux uniquement
    import resource

    resource.setrlimit(resource.RLIMIT_AS, (2 << 30, 2 << 30))
    resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
    resource.setrlimit(resource.RLIMIT_FSIZE, (50 << 20, 50 << 20))


def run(code: str, base: bytes, timeout: int = 60) -> tuple[str, bytes | None]:
    """Exécute le script sur une copie du classeur. Retourne (message, octets du résultat)."""
    err = check(code)
    if err:
        return "Script refusé : " + err, None
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "base.xlsx").write_bytes(base)
        out = td / "output.xlsx"
        (td / "task.py").write_text(
            f"INPUT = {str(td / 'base.xlsx')!r}\nOUTPUT = {str(out)!r}\n"
            + ("import pandas as pd\n" if HAS_PANDAS else "")
            + "import openpyxl\n" + code,
            encoding="utf-8",
        )
        env = {k: os.environ[k] for k in ("SYSTEMROOT", "PATH", "LANG") if k in os.environ}
        env.update(TEMP=str(td), TMP=str(td), TMPDIR=str(td), PYTHONIOENCODING="utf-8")
        # le processus enfant doit retrouver les bibliothèques installées (venv, Vercel...)
        env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
        try:
            r = subprocess.run(
                [sys.executable, str(td / "task.py")],
                capture_output=True, text=True, timeout=timeout, cwd=td, env=env,
                preexec_fn=_limits if os.name == "posix" else None,
            )
        except subprocess.TimeoutExpired:
            return "Erreur : le script a dépassé 60 secondes.", None
        if r.returncode != 0:
            return "Erreur d'exécution :\n" + r.stderr[-1500:], None
        if not out.exists():
            return "Le script n'a pas enregistré le fichier dans OUTPUT.", None
        return "OK", out.read_bytes()
