"""Coeur de l'agent : plusieurs fournisseurs gratuits avec bascule automatique,
conversations par utilisateur (base de données), lecture de PDF/Excel/images,
création de fichiers Excel / Word / PDF."""
import datetime
import io
import json
import os
import re
import time

from dotenv import load_dotenv
from openai import OpenAI
from pathlib import Path

import db
import docgen
import sandbox

load_dotenv()

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "Tu es l'agent IA personnel d'Achraf : il t'a créé pour son usage. Si on te demande qui "
    "tu es, de qui tu es l'agent, qui t'a créé ou à qui tu appartiens, réponds que tu es "
    "l'agent IA personnel d'Achraf. Ne dis jamais que tu as été développé par OpenAI, Google, "
    "Alibaba, Meta ou une autre entreprise ; si on insiste sur la technologie, dis seulement "
    "que tu fonctionnes grâce à des modèles d'IA ouverts, sans citer de marque. "
    "Tu es un assistant expert dans tous les domaines : programmation, "
    "cuisine, sciences, santé, droit, voyages, etc. Réponds de façon correcte, "
    "claire et structurée, dans la langue de l'utilisateur. Si tu n'es pas sûr "
    "d'une information, dis-le au lieu d'inventer. Pour le code, donne des "
    "exemples fonctionnels. Tu peux chercher sur le web pour les infos récentes, "
    "mais fais au maximum 3 recherches puis réponds.",
)

DOC_PROMPT = (
    "Si l'utilisateur te demande de CRÉER un document téléchargeable (lettre, rapport, CV, "
    "contrat, devis, fiche...) : écris le contenu COMPLET et définitif en Markdown dans un "
    "bloc ```document_docx (fichier Word) ou ```document_pdf (fichier PDF) ; un seul bloc par "
    "format, et seulement si l'utilisateur veut ce format (les deux s'il ne précise pas ou "
    "demande les deux). Dans le bloc : # titre, ## sections, listes, tableaux | a | b |, "
    "**gras**, pas d'emojis, aucun commentaire. Après le bloc, une courte phrase. Pour modifier "
    "un document déjà créé, renvoie le document entier corrigé dans un nouveau bloc. "
    "Utilise de vraies informations fournies par l'utilisateur ; ne mets pas de faux détails : "
    "laisse un champ [À compléter] si une donnée manque."
)

# Ordre = priorité. Chaque fournisseur est ignoré si sa clé n'est pas définie.
# Si l'un est saturé (quota) ou lent, le suivant prend le relais automatiquement.
# Les modèles peuvent être changés dans .env (les modèles gratuits évoluent).
GROQ_VISION = os.getenv("GROQ_VISION_MODEL", "qwen/qwen3.8-27b")
GROQ_URL = "https://api.groq.com/openai/v1"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/openai/"
PROVIDERS = [
    {
        "name": "Groq",
        "key": "GROQ_API_KEY",
        "base_url": GROQ_URL,
        "model": os.getenv("GROQ_MODEL", "openai/gpt-oss-120b"),
        "vision": True,
        "vision_model": GROQ_VISION,
        "vision_max_tokens": 900,  # ce modèle plafonne à 1000 tokens de sortie / minute
    },
    {  # plus petit modèle Groq : quota journalier séparé du premier
        "name": "Groq (20B)",
        "key": "GROQ_API_KEY",
        "base_url": GROQ_URL,
        "model": os.getenv("GROQ_SMALL_MODEL", "openai/gpt-oss-20b"),
    },
    {
        "name": "Gemini",
        "key": "GEMINI_API_KEY",
        "base_url": GEMINI_URL,
        "model": os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        "vision": True,
        "vision_model": os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
        "options": {"reasoning_effort": "low"},  # réflexion légère : réponses ~3x plus rapides
    },
    {  # modèle plus léger : souvent disponible quand le principal est surchargé
        "name": "Gemini (Lite)",
        "key": "GEMINI_API_KEY",
        "base_url": GEMINI_URL,
        "model": os.getenv("GEMINI_LITE_MODEL", "gemini-3.1-flash-lite"),
        "vision": True,
        "vision_model": os.getenv("GEMINI_LITE_MODEL", "gemini-3.1-flash-lite"),
        "options": {"reasoning_effort": "low"},
    },
    {  # dernier recours : limité à 1000 tokens de sortie / minute côté Groq
        "name": "Groq (Qwen)",
        "key": "GROQ_API_KEY",
        "base_url": GROQ_URL,
        "model": GROQ_VISION,
        "max_tokens": 900,
    },
    {
        "name": "OpenRouter (Qwen)",
        "key": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        "model": os.getenv("OPENROUTER_MODEL", "qwen/qwen3-235b-a22b:free"),
    },
]

MAX_HISTORY = 12  # messages envoyés à l'IA (tout est quand même sauvegardé)
MAX_FILE_CHARS = int(os.getenv("MAX_FILE_CHARS", "20000"))  # texte PDF envoyé à l'IA
# Mettre ENABLE_EXCEL_SCRIPTS=0 pour interdire la modification d'Excel (analyse seulement)
EXCEL_EDIT = os.getenv("ENABLE_EXCEL_SCRIPTS", "1") != "0"
SERVERLESS = bool(os.getenv("VERCEL"))


def web_search(query: str) -> str:
    try:
        from ddgs import DDGS

        results = DDGS().text(query, max_results=5)
        return "\n\n".join(f"{r['title']}\n{r['body']}\n{r['href']}" for r in results) or "Aucun résultat."
    except Exception as e:
        return f"Recherche impossible : {e}"


TOOL_WEB = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Cherche sur internet. À utiliser pour l'actualité, les prix, "
        "les événements récents ou toute info susceptible d'avoir changé.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
}

# Le script Excel est écrit dans un bloc ```excel_script (et non dans un appel d'outil JSON,
# que les modèles échappent mal quand le code est long).
SCRIPT_RE = re.compile(r"```excel_script[ \t]*\r?\n(.*?)```", re.DOTALL)
DOC_RE = re.compile(r"```document_(docx|pdf)[ \t]*\r?\n(.*?)```", re.DOTALL)

if sandbox.HAS_PANDAS:
    _LIBS = (
        "pandas (pd) et openpyxl sont déjà importés. Seuls pandas, numpy, openpyxl, datetime, "
        "re, math, random et quelques modules standards sont autorisés"
    )
else:  # hébergement léger (Vercel) : pas de pandas
    _LIBS = (
        "openpyxl est déjà importé. pandas n'est PAS disponible : utilise uniquement openpyxl "
        "(pour trier/dédoublonner : lis les lignes dans une liste Python, traite-les, puis "
        "réécris-les dans la feuille). Seuls openpyxl, datetime, re, math, random et quelques "
        "modules standards sont autorisés"
    )

EXCEL_PROMPT = (
    "Un classeur Excel est chargé (« {name} »). Structure actuelle :\n{summary}\n\n"
    "Pour le modifier ou l'organiser selon la demande, réponds UNIQUEMENT par un bloc de "
    "code complet de ce format exact (sans texte avant ni après) :\n"
    "```excel_script\n# code Python\n```\n"
    "Les variables INPUT (chemin du fichier à lire) et OUTPUT (chemin où enregistrer le "
    "résultat avec wb.save(OUTPUT)) sont déjà définies ; " + _LIBS + " ; n'écris aucun autre "
    "chemin que INPUT et OUTPUT. Utilise exactement les noms de feuilles et de colonnes "
    "de la structure ci-dessus. Garde toutes les données sauf si on te demande de les "
    "supprimer. Pour AJOUTER des lignes : ne te fie pas à ws.max_row (il compte des lignes vides mises "
    "en forme) ; écris à partir de « dernière ligne contenant des données » + 1, continue la "
    "numérotation/les codes existants avec des valeurs réalistes cohérentes avec les colonnes, copie "
    "le style de la ligne précédente (bordures, formats), et si un tableau Excel existe étends sa plage "
    "(ws.tables['nom'].ref = 'A1:G33'). Pour un fichier « bien organisé » : en-têtes en gras avec fond coloré, "
    "première ligne figée, filtres automatiques, largeur de colonnes ajustée, formats "
    "cohérents (dates, nombres). Commence ton script par UNE ligne de commentaire de la forme "
    "« # RESUME: ce que tu fais, en une phrase en français ». Je t'enverrai le résultat de "
    "l'exécution : si erreur, renvoie un nouveau script complet. "
    "Si la demande ne nécessite pas de modifier le fichier (simple question), réponds normalement."
)
EXCEL_READONLY_PROMPT = (
    "Un classeur Excel est chargé (« {name} »). Structure actuelle :\n{summary}\n\n"
    "Tu peux l'analyser et répondre aux questions, mais la modification de fichiers Excel "
    "est désactivée sur ce serveur : dis-le si on te demande de le modifier."
)


def display_text(text: str) -> str:
    """Texte affiché à l'utilisateur : les blocs de document sont remplacés par une mention."""
    def mention(m):
        label = "Word" if m.group(1) == "docx" else "PDF"
        return f"\n\n📄 *Document {label} généré — télécharge-le avec le bouton ci-dessous.*\n\n"

    return DOC_RE.sub(mention, text).strip()


def _create(client, model, msgs, tools, max_tokens=None, options=None):
    """Appel API avec nouvelle tentative si le modèle formate mal un appel d'outil."""
    extra = {"max_tokens": max_tokens} if max_tokens else {}
    extra.update(options or {})
    for attempt in range(3):
        try:
            if tools:
                extra["tools"] = tools
            return client.chat.completions.create(model=model, messages=msgs, **extra)
        except Exception as e:
            if options and "reasoning" in str(e).lower():  # option non gérée : on la retire
                for k in options:
                    extra.pop(k, None)
                continue
            if "tool_use_failed" in str(e) and attempt < 2:
                continue
            raise


_COOLDOWN: dict[str, float] = {}  # fournisseur -> heure avant laquelle on ne le réessaie pas


def _wait_seconds(msg: str) -> float | None:
    """Extrait « try again in 14m22.7s » d'un message d'erreur de limite."""
    m = re.search(r"try again in (?:(\d+)h)?(?:(\d+)m)?(?:([\d.]+)s)?", msg)
    if not m or not any(m.groups()):
        return None
    h, mi, sec = (float(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + sec


def _explain(e: Exception) -> tuple[str, float]:
    """(explication lisible, secondes pendant lesquelles ne pas réessayer ce fournisseur)."""
    msg = str(e)
    low = msg.lower()
    wait = _wait_seconds(msg)
    if "invalid auth" in low or "api key" in low or "401" in low[:30] or "403" in low[:30]:
        return "clé API refusée ou invalide", 3600
    if "tokens per day" in low or "per day" in low:
        mins = f" (réessaie dans ~{int(wait // 60) + 1} min)" if wait else ""
        return "limite journalière gratuite atteinte" + mins, min(wait or 1800, 3600)
    if "429" in low[:30] or "rate limit" in low or "quota" in low:
        return "limite de débit atteinte, patiente un peu", min(wait or 60, 600)
    if "503" in low[:30] or "unavailable" in low or "high demand" in low or "overloaded" in low:
        return "service surchargé", 30
    if "timed out" in low or "timeout" in low:
        return "trop lent à répondre", 30
    if "404" in low[:30] or "not found" in low or "does not exist" in low:
        return "modèle indisponible", 600
    return msg[:140], 20


_JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
_MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
         "septembre", "octobre", "novembre", "décembre"]
DOC_HINT = re.compile(
    r"lettre|\bcv\b|curriculum|rapport|word|docx|pdf|document|contrat|devis|fiche|attestation|"
    r"cr[ée]e|g[ée]n[èe]re|fichier|t[ée]l[ée]charg|modifie|corrige|rends",
    re.IGNORECASE,
)


def _today() -> str:
    d = datetime.date.today()
    return f"{_JOURS[d.weekday()]} {d.day} {_MOIS[d.month - 1]} {d.year}"


def _clean(text: str) -> str:
    # Les modèles de raisonnement (Qwen3...) ajoutent un bloc <think>...</think>
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = [f"--- Page {i + 1} ---\n{p.extract_text() or ''}" for i, p in enumerate(reader.pages)]
    text = "\n".join(pages).strip()
    if len(text.replace("--- Page", "")) < 50:
        return "(Ce PDF ne contient pas de texte lisible : probablement un scan/image.)"
    if len(text) > MAX_FILE_CHARS:
        text = text[:MAX_FILE_CHARS] + f"\n[... tronqué, {len(reader.pages)} pages au total]"
    return text


def _data_rows(ws) -> list[int]:
    """Numéros des lignes qui contiennent vraiment des valeurs (ignore les lignes vides mises en forme)."""
    return [
        i for i, row in enumerate(ws.iter_rows(values_only=True), 1)
        if any(v not in (None, "") for v in row)
    ]


def _excel_summary(data: bytes, rows: int = 8, cols: int = 12) -> str:
    import openpyxl

    wb = openpyxl.load_workbook(io.BytesIO(data))
    out = []
    for ws in wb.worksheets:
        last = (_data_rows(ws) or [0])[-1]
        out.append(
            f"Feuille « {ws.title} » : dernière ligne contenant des données = {last} "
            f"(ws.max_row = {ws.max_row} inclut des lignes vides mises en forme), {ws.max_column} colonnes"
        )
        for t in ws.tables.values():
            out.append(f"Tableau Excel « {t.displayName} » : plage {t.ref} (à étendre si on ajoute des lignes)")
        for row in ws.iter_rows(
            min_row=1, max_row=rows, max_col=min(cols, ws.max_column), values_only=True
        ):
            out.append(" | ".join("" if v is None else str(v)[:30] for v in row))
    return "\n".join(out)


def _excel_report(code: str, base: bytes, new: bytes) -> str:
    """Message de fin : phrase de l'IA (# RESUME) + différences mesurées dans le fichier."""
    import openpyxl

    lines = []
    m = re.search(r"#\s*RESUME\s*:\s*(.+)", code)
    if m:
        lines.append(f"**Ce qui a été fait :** {m.group(1).strip()}")
    old = {w.title: w for w in openpyxl.load_workbook(io.BytesIO(base)).worksheets}
    for ws in openpyxl.load_workbook(io.BytesIO(new)).worksheets:
        after = len(_data_rows(ws))
        before = len(_data_rows(old[ws.title])) if ws.title in old else 0
        diff = after - before
        if ws.title not in old:
            lines.append(f"- Nouvelle feuille « {ws.title} » : {after} lignes")
        elif diff > 0:
            lines.append(f"- Feuille « {ws.title} » : **{diff} ligne(s) ajoutée(s)** ({before} → {after} lignes avec données)")
        elif diff < 0:
            lines.append(f"- Feuille « {ws.title} » : {-diff} ligne(s) supprimée(s) ({before} → {after})")
        else:
            lines.append(f"- Feuille « {ws.title} » : {after} lignes, contenu réorganisé ou mis en forme")
    return "✅ **Ton fichier Excel est prêt.**\n\n" + "\n".join(lines) + "\n\nTélécharge-le avec le bouton ci-dessous."


def _signature(data: bytes) -> list:
    """Empreinte du contenu ET de la mise en forme, pour détecter un script qui ne change rien."""
    import openpyxl

    sig = []
    for ws in openpyxl.load_workbook(io.BytesIO(data)).worksheets:
        rows = [tuple(r) for r in ws.iter_rows(values_only=True)]
        while rows and all(v in (None, "") for v in rows[-1]):
            rows.pop()
        style = []
        for r in ws.iter_rows(min_row=1, max_row=3):
            for c in r[:20]:
                style.append((c.font.b, c.fill.fgColor.rgb if c.fill.fill_type else None, c.number_format))
        sig.append((
            ws.title, rows, style, ws.freeze_panes, ws.auto_filter.ref,
            sorted((k, round(v.width or 0)) for k, v in ws.column_dimensions.items()),
            sorted(str(m) for m in ws.merged_cells.ranges),
            sorted((t.displayName, t.ref) for t in ws.tables.values()),
        ))
    return sig


def _check_result(base: bytes, new: bytes) -> str | None:
    """Refuse un résultat suspect (aucun changement, ou lignes écrites loin sous les données)."""
    import openpyxl

    if _signature(base) == _signature(new):
        return (
            "Aucune modification détectée : le fichier produit est identique à l'original. "
            "Refais le script pour que la demande soit réellement appliquée "
            "(pour ajouter des lignes, écris-les juste après la dernière ligne contenant des données)."
        )
    old_ws = {w.title: w for w in openpyxl.load_workbook(io.BytesIO(base)).worksheets}
    for ws in openpyxl.load_workbook(io.BytesIO(new)).worksheets:
        rows = _data_rows(ws)
        gap = max((b - a - 1 for a, b in zip(rows, rows[1:])), default=0)
        before = _data_rows(old_ws[ws.title]) if ws.title in old_ws else []
        old_gap = max((b - a - 1 for a, b in zip(before, before[1:])), default=0)
        if gap >= 3 and gap > old_gap:
            start = next(a for a, b in zip(rows, rows[1:]) if b - a - 1 == gap)
            return (
                f"Feuille « {ws.title} » : des données ont été écrites après un trou de {gap} lignes "
                f"vides (après la ligne {start}) : elles seraient invisibles. N'utilise PAS ws.max_row : "
                f"ajoute les lignes directement sous la dernière ligne contenant des données "
                f"(ligne {before[-1] if before else start}), puis étends le tableau Excel s'il y en a un."
            )
    return None


def _csv_to_xlsx(data: bytes) -> bytes:
    import csv

    import openpyxl

    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("latin-1")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    wb = openpyxl.Workbook()
    ws = wb.active
    for row in csv.reader(io.StringIO(text), dialect):
        cells = []
        for v in row:  # nombres reconnus automatiquement
            try:
                cells.append(int(v))
            except ValueError:
                try:
                    cells.append(float(v))
                except ValueError:
                    cells.append(v)
        ws.append(cells)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def available_providers() -> list[dict]:
    return [p for p in PROVIDERS if os.getenv(p["key"])]


class Chat:
    """Une conversation d'un utilisateur (chargée depuis / sauvegardée dans la base)."""

    def __init__(self, user_id: str, conv_id: str | None = None):
        self.user_id = user_id
        self.title = ""
        self.history: list[dict] = []
        self.excel_name = ""  # nom d'origine du classeur Excel chargé
        self.turn_files: list[str] = []  # fichiers produits pendant la demande en cours
        if conv_id:
            row = db.get_conv(user_id, conv_id)
            if not row:
                raise ValueError("Conversation introuvable")
            self.title, self.excel_name = row.title, row.excel_name
            self.history = json.loads(row.history)
        self.conv_id = conv_id or db.new_id()

    # ---------- affichage ----------
    def messages(self) -> list[dict]:
        return [
            {"role": m["role"], "text": display_text(m["content"]) if m["role"] == "assistant" else m["content"]}
            for m in self.history
        ]

    def outputs(self) -> list[str]:
        return db.list_outputs(self.conv_id)

    def save(self):
        db.save_conv(self.user_id, self.conv_id, self.title, self.excel_name, json.dumps(self.history, ensure_ascii=False))

    # ---------- fichiers joints ----------
    def _excel(self) -> bytes | None:
        return db.get_file(self.conv_id, "current.xlsx") if self.excel_name else None

    def _load_file(self, name: str, data: bytes) -> str:
        """Charge un fichier joint. Retourne du texte à ajouter à la question."""
        ext = Path(name).suffix.lower()
        if ext == ".pdf":
            return f"\n\n[Contenu du PDF « {name} »]\n{_pdf_text(data)}"
        if ext in (".xlsx", ".xlsm", ".csv"):
            if ext == ".csv":
                data = _csv_to_xlsx(data)
            _excel_summary(data)  # lève une erreur claire si le fichier est illisible
            db.put_file(self.conv_id, "current.xlsx", "excel", data)
            self.excel_name = name
            return f"\n\n[Fichier Excel « {name} » chargé]"
        if ext in (".txt", ".md", ".py", ".json", ".html", ".js", ".sql"):
            return f"\n\n[Contenu de « {name} »]\n{data.decode('utf-8', 'replace')[:MAX_FILE_CHARS]}"
        raise ValueError(f"Type de fichier non géré : {ext} (PDF, xlsx, csv, txt, images)")

    def _edit_excel(self, code: str, base: bytes) -> str:
        # `base` = classeur tel qu'il était au début de la demande : un nouvel essai après
        # une erreur repart donc toujours de la même base (pas d'ajouts en double).
        msg, data = sandbox.run(code, base)
        if data is None:
            return msg
        try:
            summary = _excel_summary(data)
            problem = _check_result(base, data)
        except Exception:
            return "Erreur : le fichier produit n'est pas un classeur Excel valide."
        if problem:
            return "Résultat refusé : " + problem
        db.put_file(self.conv_id, "current.xlsx", "excel", data)  # devient le classeur courant
        name = f"organise_{Path(self.excel_name).stem}.xlsx"
        db.put_file(self.conv_id, name, "output", data)
        if name not in self.turn_files:
            self.turn_files.append(name)
        return "OK, fichier produit. Aperçu :\n" + summary

    # ---------- conversation ----------
    def ask(
        self,
        question: str,
        image: str | None = None,
        file: tuple[str, bytes] | None = None,
    ) -> tuple[str, str]:
        """Retourne (réponse affichée, nom du fournisseur utilisé).

        `image` = data URL optionnelle. `file` = (nom, octets) : PDF, Excel, CSV, texte.
        Les fichiers produits pendant l'appel sont listés dans `self.turn_files`.
        """
        self.turn_files = []
        full_q = question
        marker = ""
        if file:
            full_q += self._load_file(*file)
            marker += f" [fichier joint : {file[0]}]"
        if image:
            marker += " [image jointe]"
        # L'historique ne garde que le texte court (fichiers/images coûtent beaucoup de tokens)
        self.history.append({"role": "user", "content": question + marker})

        system = SYSTEM_PROMPT + f"\n\nDate d'aujourd'hui : {_today()}."
        recent = self.history[-5:-1]
        if DOC_HINT.search(question) or any("```document_" in m["content"] for m in recent):
            system += "\n\n" + DOC_PROMPT
        base = self._excel()
        if base:
            tpl = EXCEL_PROMPT if EXCEL_EDIT else EXCEL_READONLY_PROMPT
            system += "\n\n" + tpl.format(name=self.excel_name, summary=_excel_summary(base))
        ctx = self.history[-MAX_HISTORY:]
        # les anciennes réponses longues sont tronquées pour économiser les tokens gratuits
        ctx = [
            {**m, "content": m["content"][:1500]} if (m["role"] == "assistant" and i < len(ctx) - 4) else m
            for i, m in enumerate(ctx)
        ]
        messages = [{"role": "system", "content": system}, *ctx]
        if image:
            messages[-1] = {
                "role": "user",
                "content": [
                    {"type": "text", "text": full_q or "Décris cette image."},
                    {"type": "image_url", "image_url": {"url": image}},
                ],
            }
        elif file:
            messages[-1] = {"role": "user", "content": full_q}

        # pas de recherche web pendant un travail sur Excel (les petits modèles s'y perdent)
        tools = [] if (base and EXCEL_EDIT) else [TOOL_WEB]
        providers = available_providers()
        if image:
            providers = [p for p in providers if p.get("vision")]
        if not providers:
            self.history.pop()
            raise RuntimeError("Aucun fournisseur disponible pour cette demande (clé API manquante).")

        now = time.time()
        # on saute les fournisseurs en pause (quota épuisé, clé invalide...) sauf si tous le sont
        providers = [p for p in providers if _COOLDOWN.get(p["name"], 0) <= now] or providers
        errors = []
        for idx, p in enumerate(providers):
            try:
                # Délai court tant qu'il reste un fournisseur de secours : si celui-ci est
                # lent ou saturé, on bascule vite sur le suivant.
                last = idx == len(providers) - 1
                # Vercel coupe toute requête à 60 s : délais plus courts pour pouvoir basculer
                client = OpenAI(
                    api_key=os.environ[p["key"]],
                    base_url=p["base_url"],
                    timeout=(35 if last else 20) if SERVERLESS else (90 if last else 45),
                    max_retries=0 if not last else 1,  # pas d'attente cachée : on bascule
                )
                model = p["vision_model"] if image else p["model"]
                msgs = list(messages)
                stored = shown = ""
                for _ in range(12):  # boucle : recherche web / script Excel
                    r = _create(client, model, msgs, tools, p.get("vision_max_tokens" if image else "max_tokens"), p.get("options"))
                    m = r.choices[0].message
                    if m.tool_calls:
                        msgs.append(m)
                        for call in m.tool_calls:
                            try:
                                args = json.loads(call.function.arguments or "{}")
                            except json.JSONDecodeError:
                                args = {}
                            msgs.append(
                                {
                                    "role": "tool",
                                    "tool_call_id": call.id,
                                    "content": web_search(args.get("query", "")),
                                }
                            )
                        continue
                    text = _clean(m.content)
                    script = SCRIPT_RE.search(text) if (base and EXCEL_EDIT) else None
                    if script:
                        code = script.group(1)
                        result = self._edit_excel(code, base)
                        if self.turn_files:
                            # Fichier produit : réponse construite localement (pas d'appel IA
                            # supplémentaire : plus rapide, et pas de nouveau script en réponse)
                            stored = shown = _excel_report(code, base, db.get_file(self.conv_id, "current.xlsx"))
                            break
                        msgs.append({"role": "assistant", "content": text})
                        msgs.append(
                            {
                                "role": "user",
                                "content": "[Résultat de l'exécution de ton script]\n"
                                f"{result}\nCorrige l'erreur et renvoie un script complet.",
                            }
                        )
                        continue
                    for fmt, md in DOC_RE.findall(text):
                        name, data = docgen.render(fmt, md.strip())
                        db.put_file(self.conv_id, name, "output", data)
                        if name not in self.turn_files:
                            self.turn_files.append(name)
                    stored, shown = text, display_text(text)
                    break
                if not shown:
                    raise RuntimeError("réponse vide")
                self.history.append({"role": "assistant", "content": stored})
                if not self.title:
                    self.title = (question or (file[0] if file else "Image")).strip()[:50]
                self.save()
                return shown, p["name"]
            except Exception as e:  # quota, réseau, modèle indisponible...
                why, pause = _explain(e)
                _COOLDOWN[p["name"]] = time.time() + pause
                errors.append(f"• {p['name']} : {why}")
                self.turn_files = []

        self.history.pop()  # on retire la question qui n'a pas eu de réponse
        raise RuntimeError(
            "Les services d'IA gratuits sont momentanément indisponibles :\n"
            + "\n".join(errors)
            + "\nRéessaie dans quelques minutes."
        )
