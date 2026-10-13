"""Espace licences : les clients voient leurs licences, les admins les gèrent.

L'identification est faite par Authelia : le reverse proxy transmet les
en-têtes Remote-User, Remote-Groups et Remote-Name à l'application.
"""

import os
import sqlite3
from datetime import date, datetime

from flask import Flask, abort, g, redirect, render_template, request, url_for

DB_PATH = os.environ.get("DB_PATH", "/data/licences.db")
ADMIN_GROUP = os.environ.get("ADMIN_GROUP", "admins")
APP_NAME = os.environ.get("APP_NAME", "Espace client")
LOGOUT_URL = os.environ.get("LOGOUT_URL", "")
SOON_DAYS = int(os.environ.get("SOON_DAYS", "30"))

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
        "août", "septembre", "octobre", "novembre", "décembre"]

MESSAGES = {
    "ajout": "Licence ajoutée.",
    "modif": "Licence modifiée.",
    "suppr": "Licence supprimée.",
}

app = Flask(__name__)


# ---------- Base de données ----------

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS licences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL,
                produit TEXT NOT NULL,
                debut TEXT NOT NULL,
                fin TEXT NOT NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        db.execute("CREATE INDEX IF NOT EXISTS idx_licences_user ON licences(username)")


init_db()


# ---------- Utilisateur connecté (fourni par Authelia) ----------

def _decode(value):
    # Les en-têtes arrivent en latin-1 : on corrige les accents envoyés en UTF-8
    try:
        return value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def current_user():
    username = request.headers.get("Remote-User", "").strip().lower()
    if not username:
        abort(401)
    groups = [x.strip() for x in request.headers.get("Remote-Groups", "").split(",") if x.strip()]
    name = _decode(request.headers.get("Remote-Name", "").strip()) or username
    return {"username": username, "name": name, "is_admin": ADMIN_GROUP in groups}


def require_admin():
    user = current_user()
    if not user["is_admin"]:
        abort(403)
    return user


# ---------- Mise en forme ----------

def date_fr(d):
    return f"{d.day} {MOIS[d.month - 1]} {d.year}"


def jours(n):
    return "1 jour" if n == 1 else f"{n} jours"


def decorer(row):
    """Ajoute le statut, la phrase d'échéance et l'avancement à une licence."""
    lic = dict(row)
    debut = date.fromisoformat(lic["debut"])
    fin = date.fromisoformat(lic["fin"])
    today = date.today()
    reste = (fin - today).days

    libelle, echeance = "Valable jusqu'au", date_fr(fin)
    if today < debut:
        statut, etat = "attente", "À venir"
        libelle, echeance = "Commence le", date_fr(debut)
        phrase = f"Active dans {jours((debut - today).days)}."
    elif reste < 0:
        statut, etat = "expiree", "Expirée"
        libelle = "A expiré le"
        phrase = "Cette licence n'est plus valable."
    elif reste == 0:
        statut, etat = "bientot", "Expire aujourd'hui"
        phrase = "Dernier jour de validité."
    elif reste <= SOON_DAYS:
        statut, etat = "bientot", "Expire bientôt"
        phrase = f"Plus que {jours(reste)} de validité."
    else:
        statut, etat = "active", "Active"
        phrase = f"Encore {jours(reste)} de validité."

    total = max((fin - debut).days, 1)
    ecoule = min(max((today - debut).days, 0), total)
    lic.update(
        statut=statut,
        etat=etat,
        phrase=phrase,
        libelle=libelle,
        echeance=echeance,
        avancement=round(ecoule / total * 100, 1),
        debut_fr=date_fr(debut),
        fin_fr=date_fr(fin),
    )
    return lic


def lire_formulaire():
    """Valide le formulaire d'ajout / modification. Renvoie (données, erreur)."""
    data = {
        "username": request.form.get("username", "").strip().lower(),
        "produit": request.form.get("produit", "").strip(),
        "debut": request.form.get("debut", "").strip(),
        "fin": request.form.get("fin", "").strip(),
        "note": request.form.get("note", "").strip(),
    }
    if not data["username"]:
        return data, "Indique l'identifiant du client."
    if not data["produit"]:
        return data, "Indique le produit ou le type de licence."
    try:
        debut = date.fromisoformat(data["debut"])
        fin = date.fromisoformat(data["fin"])
    except ValueError:
        return data, "Les dates de début et de fin sont obligatoires."
    if fin < debut:
        return data, "La date de fin doit être après la date de début."
    return data, None


# ---------- Pages client ----------

@app.context_processor
def variables_globales():
    return {"app_name": APP_NAME, "logout_url": LOGOUT_URL}


@app.route("/")
def accueil():
    user = current_user()
    rows = get_db().execute(
        "SELECT * FROM licences WHERE username = ? ORDER BY fin DESC", (user["username"],)
    ).fetchall()
    return render_template("client.html", user=user, licences=[decorer(r) for r in rows])


# ---------- Administration ----------

@app.route("/admin")
def admin():
    user = require_admin()
    q = request.args.get("q", "").strip().lower()
    sql = "SELECT * FROM licences"
    params = ()
    if q:
        sql += " WHERE username LIKE ? OR lower(produit) LIKE ?"
        params = (f"%{q}%", f"%{q}%")
    rows = get_db().execute(sql + " ORDER BY fin ASC", params).fetchall()
    return render_template(
        "admin.html",
        user=user,
        licences=[decorer(r) for r in rows],
        q=q,
        message=MESSAGES.get(request.args.get("msg", "")),
        form={"debut": date.today().isoformat()},
        erreur=None,
    )


@app.route("/admin/licences", methods=["POST"])
def ajouter():
    user = require_admin()
    data, erreur = lire_formulaire()
    if erreur:
        rows = get_db().execute("SELECT * FROM licences ORDER BY fin ASC").fetchall()
        return render_template(
            "admin.html", user=user, licences=[decorer(r) for r in rows],
            q="", message=None, form=data, erreur=erreur,
        ), 400
    db = get_db()
    db.execute(
        "INSERT INTO licences (username, produit, debut, fin, note, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (data["username"], data["produit"], data["debut"], data["fin"], data["note"],
         datetime.now().isoformat(timespec="seconds")),
    )
    db.commit()
    return redirect(url_for("admin", msg="ajout"))


@app.route("/admin/licences/<int:lic_id>", methods=["GET", "POST"])
def modifier(lic_id):
    user = require_admin()
    db = get_db()
    row = db.execute("SELECT * FROM licences WHERE id = ?", (lic_id,)).fetchone()
    if row is None:
        abort(404)
    if request.method == "POST":
        data, erreur = lire_formulaire()
        if erreur:
            return render_template("modifier.html", user=user, lic_id=lic_id, form=data, erreur=erreur), 400
        db.execute(
            "UPDATE licences SET username = ?, produit = ?, debut = ?, fin = ?, note = ? WHERE id = ?",
            (data["username"], data["produit"], data["debut"], data["fin"], data["note"], lic_id),
        )
        db.commit()
        return redirect(url_for("admin", msg="modif"))
    return render_template("modifier.html", user=user, lic_id=lic_id, form=dict(row), erreur=None)


@app.route("/admin/licences/<int:lic_id>/supprimer", methods=["POST"])
def supprimer(lic_id):
    require_admin()
    db = get_db()
    db.execute("DELETE FROM licences WHERE id = ?", (lic_id,))
    db.commit()
    return redirect(url_for("admin", msg="suppr"))


# ---------- Erreurs ----------

@app.errorhandler(401)
def non_identifie(_e):
    return render_template(
        "erreur.html",
        titre="Connexion requise",
        texte="Ouvrez cette page depuis le portail de connexion pour accéder à vos licences.",
        technique="En-tête Remote-User absent : vérifier que le reverse proxy passe bien par Authelia.",
    ), 401


@app.errorhandler(403)
def interdit(_e):
    return render_template(
        "erreur.html",
        titre="Accès réservé",
        texte="Cette page est réservée aux administrateurs.",
        technique=None,
    ), 403


@app.errorhandler(404)
def introuvable(_e):
    return render_template(
        "erreur.html",
        titre="Page introuvable",
        texte="Cette licence n'existe pas ou a été supprimée.",
        technique=None,
    ), 404
