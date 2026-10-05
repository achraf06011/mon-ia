"""Stockage : utilisateurs, sessions, conversations et fichiers.

SQLite par défaut (data/app.db). En ligne, définis DATABASE_URL (Postgres gratuit chez
Neon ou Supabase) pour que les données survivent aux redémarrages de l'hébergeur."""
import os
import time
import uuid
from pathlib import Path

from sqlalchemy.pool import NullPool
from sqlalchemy import (
    Column, Float, Integer, LargeBinary, MetaData, PrimaryKeyConstraint, String, Table, Text,
    and_, create_engine, delete, insert, select, update,
)

DAY = 86400


def _url() -> str:
    u = os.getenv("DATABASE_URL", "").strip()
    if not u:
        folder = Path(__file__).parent / "data"
        folder.mkdir(exist_ok=True)
        return f"sqlite:///{folder / 'app.db'}"
    for prefix in ("postgres://", "postgresql://"):
        if u.startswith(prefix):
            return "postgresql+psycopg://" + u[len(prefix):]
    return u


_URL = _url()
engine = create_engine(
    _URL,
    pool_pre_ping=True,
    # serverless (Vercel) : pas de connexions gardées entre deux requêtes
    **({"poolclass": NullPool} if os.getenv("VERCEL") else {}),
    # pas de requêtes préparées : compatible avec le pooler de Neon/Supabase
    connect_args={"prepare_threshold": None} if _URL.startswith("postgresql") else {},
)
meta = MetaData()

users = Table(
    "users", meta,
    Column("id", String(32), primary_key=True),
    Column("username", String(40), unique=True, nullable=False),
    Column("pw_hash", Text, nullable=False),
    Column("created", Float, nullable=False),
)
sessions = Table(
    "sessions", meta,
    Column("token", String(64), primary_key=True),
    Column("user_id", String(32), nullable=False, index=True),
    Column("expires", Float, nullable=False),
)
conversations = Table(
    "conversations", meta,
    Column("id", String(32), primary_key=True),
    Column("user_id", String(32), nullable=False, index=True),
    Column("title", Text, nullable=False, default=""),
    Column("updated", Float, nullable=False),
    Column("excel_name", Text, nullable=False, default=""),
    Column("history", Text, nullable=False),  # JSON
)
files = Table(
    "files", meta,
    Column("conv_id", String(32), nullable=False),
    Column("name", String(200), nullable=False),
    Column("kind", String(10), nullable=False),  # 'excel' (classeur courant) ou 'output'
    Column("data", LargeBinary, nullable=False),
    PrimaryKeyConstraint("conv_id", "name"),
)
profiles = Table(
    "profiles", meta,
    Column("user_id", String(32), primary_key=True),
    Column("memory", Text, nullable=False, default=""),
)
usage = Table(
    "usage", meta,
    Column("user_id", String(32), nullable=False),
    Column("day", String(10), nullable=False),
    Column("n", Integer, nullable=False, default=0),
    PrimaryKeyConstraint("user_id", "day"),
)


def init():
    meta.create_all(engine)


def new_id() -> str:
    return uuid.uuid4().hex[:12]


# ---------- utilisateurs & sessions ----------
def create_user(username: str, pw_hash: str) -> str | None:
    """Retourne l'id, ou None si le nom est déjà pris."""
    uid = uuid.uuid4().hex
    with engine.begin() as c:
        if c.execute(select(users.c.id).where(users.c.username == username)).first():
            return None
        c.execute(insert(users).values(id=uid, username=username, pw_hash=pw_hash, created=time.time()))
    return uid


def get_user_by_name(username: str):
    with engine.connect() as c:
        return c.execute(select(users).where(users.c.username == username)).first()


def create_session(user_id: str, days: int = 30) -> str:
    token = uuid.uuid4().hex + uuid.uuid4().hex
    with engine.begin() as c:
        c.execute(delete(sessions).where(sessions.c.expires < time.time()))  # ménage
        c.execute(insert(sessions).values(token=token, user_id=user_id, expires=time.time() + days * DAY))
    return token


def user_for_token(token: str):
    if not token:
        return None
    with engine.connect() as c:
        return c.execute(
            select(users.c.id, users.c.username)
            .select_from(sessions.join(users, users.c.id == sessions.c.user_id))
            .where(and_(sessions.c.token == token, sessions.c.expires > time.time()))
        ).first()


def delete_session(token: str):
    with engine.begin() as c:
        c.execute(delete(sessions).where(sessions.c.token == token))


# ---------- conversations ----------
def list_convs(user_id: str) -> list[dict]:
    with engine.connect() as c:
        rows = c.execute(
            select(conversations.c.id, conversations.c.title, conversations.c.updated)
            .where(conversations.c.user_id == user_id)
            .order_by(conversations.c.updated.desc())
        ).all()
    return [{"id": r.id, "title": r.title or "Sans titre", "updated": r.updated} for r in rows]


def get_conv(user_id: str, conv_id: str):
    with engine.connect() as c:
        return c.execute(
            select(conversations).where(and_(conversations.c.id == conv_id, conversations.c.user_id == user_id))
        ).first()


def save_conv(user_id: str, conv_id: str, title: str, excel_name: str, history_json: str):
    values = dict(title=title, excel_name=excel_name, history=history_json, updated=time.time())
    with engine.begin() as c:
        res = c.execute(
            update(conversations)
            .where(and_(conversations.c.id == conv_id, conversations.c.user_id == user_id))
            .values(**values)
        )
        if res.rowcount == 0:
            c.execute(insert(conversations).values(id=conv_id, user_id=user_id, **values))


def delete_conv(user_id: str, conv_id: str):
    with engine.begin() as c:
        res = c.execute(
            delete(conversations).where(and_(conversations.c.id == conv_id, conversations.c.user_id == user_id))
        )
        if res.rowcount:
            c.execute(delete(files).where(files.c.conv_id == conv_id))


def rename_conv(user_id: str, conv_id: str, title: str):
    with engine.begin() as c:
        c.execute(
            update(conversations)
            .where(and_(conversations.c.id == conv_id, conversations.c.user_id == user_id))
            .values(title=title[:80])
        )


# ---------- fichiers ----------
def put_file(conv_id: str, name: str, kind: str, data: bytes):
    with engine.begin() as c:
        c.execute(delete(files).where(and_(files.c.conv_id == conv_id, files.c.name == name)))
        c.execute(insert(files).values(conv_id=conv_id, name=name, kind=kind, data=data))


def get_file(conv_id: str, name: str) -> bytes | None:
    with engine.connect() as c:
        row = c.execute(
            select(files.c.data).where(and_(files.c.conv_id == conv_id, files.c.name == name))
        ).first()
    return bytes(row.data) if row else None


def list_outputs(conv_id: str) -> list[str]:
    with engine.connect() as c:
        rows = c.execute(
            select(files.c.name).where(and_(files.c.conv_id == conv_id, files.c.kind == "output")).order_by(files.c.name)
        ).all()
    return [r.name for r in rows]


# ---------- mémoire personnelle ----------
def get_memory(user_id: str) -> str:
    with engine.connect() as c:
        row = c.execute(select(profiles.c.memory).where(profiles.c.user_id == user_id)).first()
    return row.memory if row else ""


def set_memory(user_id: str, text: str):
    with engine.begin() as c:
        res = c.execute(update(profiles).where(profiles.c.user_id == user_id).values(memory=text))
        if res.rowcount == 0:
            c.execute(insert(profiles).values(user_id=user_id, memory=text))


# ---------- quota journalier ----------
def bump_usage(user_id: str) -> int:
    """Compte un message pour aujourd'hui et retourne le total du jour."""
    day = time.strftime("%Y-%m-%d")
    with engine.begin() as c:
        res = c.execute(
            update(usage).where(and_(usage.c.user_id == user_id, usage.c.day == day)).values(n=usage.c.n + 1)
        )
        if res.rowcount == 0:
            c.execute(insert(usage).values(user_id=user_id, day=day, n=1))
            return 1
        return c.execute(select(usage.c.n).where(and_(usage.c.user_id == user_id, usage.c.day == day))).scalar_one()
