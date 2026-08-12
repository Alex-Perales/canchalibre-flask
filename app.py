"""
CanchaLibre — Reserva de canchas deportivas
Aplicacion Flask con SQLite. Sin autenticacion: la persona escribe su nombre,
elige deporte, fecha y hora, y reserva con un clic. Protege contra dobles
reservas a nivel de base de datos.
"""

import os
import sqlite3
from datetime import datetime, date, timedelta

from flask import (
    Flask, g, redirect, render_template, request, url_for, flash,
)

app = Flask(__name__)
app.config["SECRET_KEY"] = "cambia-esto-en-produccion"
app.config["DATABASE"] = os.path.join(os.path.dirname(__file__), "reservas.db")
# Evita que el navegador guarde en cache CSS/imagenes viejas mientras se desarrolla.
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0

# Canchas: (nombre, deporte, emoji, color, imagen)
# El color identifica visualmente cada deporte en toda la interfaz.
# La imagen es el fondo que se muestra al elegir esa cancha para reservar.
CANCHAS = [
    ("Cancha de Futbol",   "futbol",   "\u26bd", "#16a34a", "futbol.jpg"),
    ("Cancha de Voleybol", "voley",    "\U0001f3d0", "#f59e0b", "Voleybal.jpg"),
    ("Cancha de Basquet",  "basquet",  "\U0001f3c0", "#ea580c", "basketball-court.webp"),
    ("Cancha de Tenis",    "tenis",    "\U0001f3be", "#65a30d", "tenis.webp"),
    ("Piscina",            "natacion", "\U0001f3ca", "#0ea5e9", "Nataci\u00f3n.webp"),
]

# Horarios disponibles (bloques de 1 hora).
HORARIOS = [
    "08:00", "09:00", "10:00", "11:00", "12:00", "13:00", "14:00",
    "15:00", "16:00", "17:00", "18:00", "19:00", "20:00", "21:00",
]


# --------------------------------------------------------------------------
# Base de datos
# --------------------------------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(app.config["DATABASE"])
    db.row_factory = sqlite3.Row
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS canchas (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre  TEXT NOT NULL,
            deporte TEXT NOT NULL,
            emoji   TEXT NOT NULL,
            color   TEXT NOT NULL,
            imagen  TEXT
        )
        """
    )
    columnas = [f["name"] for f in db.execute("PRAGMA table_info(canchas)").fetchall()]
    if "imagen" not in columnas:
        db.execute("ALTER TABLE canchas ADD COLUMN imagen TEXT")
    for nombre, deporte, emoji, color, imagen in CANCHAS:
        db.execute(
            "UPDATE canchas SET imagen = ? WHERE deporte = ? AND (imagen IS NULL OR imagen = '')",
            (imagen, deporte),
        )
    db.execute(
        """
        CREATE TABLE IF NOT EXISTS reservas (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            cancha_id  INTEGER NOT NULL,
            nombre     TEXT NOT NULL,
            telefono   TEXT NOT NULL DEFAULT '',
            personas   INTEGER,
            fecha      TEXT NOT NULL,
            hora       TEXT NOT NULL,
            creada_en  TEXT NOT NULL,
            FOREIGN KEY (cancha_id) REFERENCES canchas (id),
            UNIQUE (cancha_id, fecha, hora)
        )
        """
    )
    columnas_reservas = [f["name"] for f in db.execute("PRAGMA table_info(reservas)").fetchall()]
    if "telefono" not in columnas_reservas:
        db.execute("ALTER TABLE reservas ADD COLUMN telefono TEXT NOT NULL DEFAULT ''")
    if "personas" not in columnas_reservas:
        db.execute("ALTER TABLE reservas ADD COLUMN personas INTEGER")
    if db.execute("SELECT COUNT(*) FROM canchas").fetchone()[0] == 0:
        db.executemany(
            "INSERT INTO canchas (nombre, deporte, emoji, color, imagen) VALUES (?, ?, ?, ?, ?)",
            CANCHAS,
        )
    db.commit()
    db.close()


# --------------------------------------------------------------------------
# Rutas
# --------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def landing():
    """Pantalla 1: portada futurista."""
    db = get_db()
    canchas = db.execute("SELECT * FROM canchas ORDER BY id").fetchall()

    return render_template("landing.html", canchas=canchas)


@app.route("/reservas", methods=["GET"])
def reservas_view():
    """Pantalla 2: elegir deporte, fecha y horario para reservar."""
    db = get_db()
    canchas = db.execute("SELECT * FROM canchas ORDER BY id").fetchall()

    fecha_sel = request.args.get("fecha") or date.today().isoformat()
    try:
        cancha_sel = int(request.args.get("cancha", canchas[0]["id"]))
    except (ValueError, IndexError):
        cancha_sel = canchas[0]["id"] if canchas else None

    cancha_activa = next((c for c in canchas if c["id"] == cancha_sel), None)

    ocupadas = {}
    if cancha_sel is not None:
        filas = db.execute(
            "SELECT hora, nombre FROM reservas WHERE cancha_id = ? AND fecha = ?",
            (cancha_sel, fecha_sel),
        ).fetchall()
        ocupadas = {f["hora"]: f["nombre"] for f in filas}

    reservas = db.execute(
        """
        SELECT r.id, r.nombre, r.telefono, r.personas, r.hora, c.nombre AS cancha, c.emoji, c.color
        FROM reservas r
        JOIN canchas c ON c.id = r.cancha_id
        WHERE r.fecha = ?
        ORDER BY r.hora, c.nombre
        """,
        (fecha_sel,),
    ).fetchall()

    return render_template(
        "reservas.html",
        canchas=canchas,
        horarios=HORARIOS,
        fecha_sel=fecha_sel,
        cancha_sel=cancha_sel,
        cancha_activa=cancha_activa,
        ocupadas=ocupadas,
        reservas=reservas,
        hoy=date.today().isoformat(),
        max_fecha=(date.today() + timedelta(days=30)).isoformat(),
    )


@app.route("/reservar", methods=["POST"])
def reservar():
    nombre = request.form.get("nombre", "").strip()
    telefono = request.form.get("telefono", "").strip()
    personas_raw = request.form.get("personas", "").strip()
    cancha_id = request.form.get("cancha_id", "").strip()
    fecha = request.form.get("fecha", "").strip()
    hora = request.form.get("hora", "").strip()

    personas = int(personas_raw) if personas_raw.isdigit() and int(personas_raw) > 0 else None

    if not nombre:
        flash("Escribe tu nombre para reservar.", "error")
        return redirect(url_for("reservas_view", fecha=fecha, cancha=cancha_id))
    if not telefono:
        flash("Escribe tu telefono para reservar.", "error")
        return redirect(url_for("reservas_view", fecha=fecha, cancha=cancha_id))
    if not cancha_id.isdigit():
        flash("Selecciona una cancha valida.", "error")
        return redirect(url_for("reservas_view", fecha=fecha))
    if hora not in HORARIOS:
        flash("Selecciona un horario valido.", "error")
        return redirect(url_for("reservas_view", fecha=fecha, cancha=cancha_id))
    if fecha < date.today().isoformat():
        flash("No puedes reservar en una fecha pasada.", "error")
        return redirect(url_for("reservas_view", cancha=cancha_id))

    db = get_db()
    cancha = db.execute("SELECT * FROM canchas WHERE id = ?", (cancha_id,)).fetchone()
    if cancha is None:
        flash("Esa cancha no existe.", "error")
        return redirect(url_for("reservas_view", fecha=fecha))

    try:
        db.execute(
            "INSERT INTO reservas (cancha_id, nombre, telefono, personas, fecha, hora, creada_en) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cancha_id, nombre, telefono, personas, fecha, hora, datetime.now().strftime("%Y-%m-%d %H:%M")),
        )
        db.commit()
        detalle_personas = f" ({personas} personas)" if personas else ""
        flash(f"Listo {nombre}. Reservaste {cancha['nombre']} a las {hora}{detalle_personas}.", "success")
    except sqlite3.IntegrityError:
        db.rollback()
        flash(f"Ese horario ({hora}) ya esta reservado. Elige otro.", "error")

    return redirect(url_for("reservas_view", fecha=fecha, cancha=cancha_id))


@app.route("/cancelar/<int:reserva_id>", methods=["POST"])
def cancelar(reserva_id):
    fecha = request.form.get("fecha", "")
    cancha = request.form.get("cancha", "")
    db = get_db()
    db.execute("DELETE FROM reservas WHERE id = ?", (reserva_id,))
    db.commit()
    flash("Reserva cancelada.", "success")
    return redirect(url_for("reservas_view", fecha=fecha, cancha=cancha))


init_db()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
