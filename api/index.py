"""Point d'entrée Vercel : toutes les URL sont réécrites vers cette fonction (voir vercel.json)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if not os.getenv("DATABASE_URL"):
    raise RuntimeError("DATABASE_URL manquante : ajoute la chaîne Neon dans les variables Vercel.")

import db  # noqa: E402
import web  # noqa: E402

db.init()  # crée les tables au premier démarrage (sans effet ensuite)


class handler(web.Handler):  # Vercel cherche une classe nommée « handler »
    pass
