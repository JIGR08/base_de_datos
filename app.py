# app.py
from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, os
from werkzeug.security import generate_password_hash, check_password_hash

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
USERS_DB = os.path.join(DATA_DIR, "users.db")

app = Flask(__name__)
app.secret_key = "CAMBIA_ESTA_CLAVE_POR_OTRA_MUY_SECRETA"

# ---------- Helpers ----------
def ensure_data_dir():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR)

def get_users_conn():
    ensure_data_dir()
    conn = sqlite3.connect(USERS_DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_users_db():
    ensure_data_dir()
    conn = get_users_conn()
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_name TEXT NOT NULL,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        db_path TEXT NOT NULL
    )
    """)
    conn.commit()
    conn.close()

def init_company_db(db_path):
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS campos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        tipo TEXT NOT NULL DEFAULT 'text'
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS registros (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        creado_at TEXT DEFAULT CURRENT_TIMESTAMP
    )
    """)
    c.execute("""
    CREATE TABLE IF NOT EXISTS valores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        registro_id INTEGER NOT NULL,
        campo_id INTEGER NOT NULL,
        valor TEXT,
        FOREIGN KEY(registro_id) REFERENCES registros(id),
        FOREIGN KEY(campo_id) REFERENCES campos(id)
    )
    """)
    # default fields
    defaults = [("descripcion","text"), ("comprador","text"), ("costo","number")]
    for n,t in defaults:
        c.execute("INSERT OR IGNORE INTO campos (nombre,tipo) VALUES (?,?)", (n,t))
    conn.commit()
    conn.close()

# init users DB at startup
init_users_db()

# ---------- Auth ----------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        company = request.form.get("company","").strip()
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","").strip()
        if not company or not email or not password:
            flash("Completa todos los campos", "danger")
            return redirect(url_for("register"))
        conn = get_users_conn()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO users (company_name, email, password_hash, db_path) VALUES (?,?,?,?)",
                        (company, email, generate_password_hash(password), ""))
            uid = cur.lastrowid
            db_path = os.path.join(DATA_DIR, f"company_{uid}.db")
            cur.execute("UPDATE users SET db_path=? WHERE id=?", (db_path, uid))
            conn.commit()
            conn.close()
            init_company_db(db_path)
            flash("Cuenta creada. Inicia sesión.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            conn.close()
            flash("El correo ya está registrado.", "danger")
            return redirect(url_for("register"))
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email","").strip().lower()
        password = request.form.get("password","").strip()
        conn = get_users_conn()
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = cur.fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["company_name"] = user["company_name"]
            session["company_db"] = user["db_path"]
            flash("Bienvenido, " + user["company_name"], "success")
            return redirect(url_for("index"))
        flash("Email o contraseña incorrectos", "danger")
        return redirect(url_for("login"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("Sesión cerrada", "info")
    return redirect(url_for("login"))

# ---------- Helpers company ----------
def company_conn():
    db = session.get("company_db")
    if not db:
        print("Error: session['company_db'] no está definido")
        return None
    if not os.path.exists(db):
        print(f"Error: archivo de base de datos no encontrado en {db}")
        return None
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    return conn

@app.route("/campos/add", methods=["POST"])
@login_required
def campos_add():
    nombre = request.form.get("nombre","").strip()
    tipo = request.form.get("tipo","text").strip()
    
    if nombre == "":
        flash("Nombre requerido", "danger")
        return redirect(url_for("manage"))

    conn = company_conn()
    if not conn:
        flash("Base de datos no disponible", "danger")
        return redirect(url_for("manage"))

    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO campos (nombre, tipo) VALUES (?, ?)", (nombre, tipo))
        conn.commit()
        flash(f"Campo '{nombre}' agregado", "success")
    except sqlite3.IntegrityError:
        flash("El campo ya existe", "warning")
    except Exception as e:
        flash(f"Error interno al agregar campo: {e}", "danger")
        print("Error al agregar campo:", e)
    finally:
        conn.close()

    return redirect(url_for("manage"))

def get_registros():
    conn = company_conn()
    if not conn:
        return []
    reg_cur = conn.execute("SELECT id, creado_at FROM registros ORDER BY id DESC")
    registros = []
    for r in reg_cur.fetchall():
        registro = {"id": r["id"], "creado_at": r["creado_at"], "valores": {}}
        vcur = conn.execute("""
            SELECT c.nombre, v.valor
            FROM valores v
            JOIN campos c ON c.id = v.campo_id
            WHERE v.registro_id = ?
        """, (r["id"],))
        for v in vcur.fetchall():
            registro["valores"][v["nombre"]] = v["valor"]
        registros.append(registro)
    conn.close()
    return registros

# ---------- Protected pages ----------
from functools import wraps
def login_required(f):
    @wraps(f)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Inicia sesión primero", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapped

@app.route("/")
@login_required
def index():
    campos = get_campos()
    registros = get_registros()
    return render_template("index.html", campos=campos, registros=registros)

@app.route("/agregar", methods=["GET","POST"])
@login_required
def agregar():
    if request.method == "GET":
        campos = get_campos()
        return render_template("agregar.html", campos=campos)
    conn = company_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO registros DEFAULT VALUES")
    registro_id = cur.lastrowid
    campos = get_campos()
    for campo in campos:
        key = f"field_{campo['id']}"
        val = request.form.get(key)
        if val is not None and val != "":
            cur.execute("INSERT INTO valores (registro_id, campo_id, valor) VALUES (?,?,?)",
                        (registro_id, campo['id'], val))
    conn.commit()
    conn.close()
    flash("Registro agregado", "success")
    return redirect(url_for("index"))

@app.route("/editar/<int:id>", methods=["GET","POST"])
@login_required
def editar(id):
    conn = company_conn()
    if not conn:
        flash("DB no disponible", "danger")
        return redirect(url_for("index"))
    if request.method == "GET":
        campos = get_campos()
        vals = {v["campo_id"]: v["valor"] for v in conn.execute("SELECT campo_id,valor FROM valores WHERE registro_id=?", (id,)).fetchall()}
        conn.close()
        return render_template("editar.html", campos=campos, registro_id=id, valores=vals)
    # POST update
    cur = conn.cursor()
    cur.execute("DELETE FROM valores WHERE registro_id = ?", (id,))
    campos = get_campos()
    for campo in campos:
        key = f"field_{campo['id']}"
        val = request.form.get(key)
        if val is not None and val != "":
            cur.execute("INSERT INTO valores (registro_id, campo_id, valor) VALUES (?,?,?)",
                        (id, campo['id'], val))
    conn.commit()
    conn.close()
    flash("Registro actualizado", "success")
    return redirect(url_for("index"))

@app.route("/manage", methods=["GET"])
@login_required
def manage():
    campos = get_campos()
    registros = get_registros()
    return render_template("manage.html", campos=campos, registros=registros)

@app.route("/campos/add", methods=["POST"])
@login_required
def campos_add():
    nombre = request.form.get("nombre","").strip()
    tipo = request.form.get("tipo","text").strip()
    if nombre == "":
        flash("Nombre requerido", "danger")
        return redirect(url_for("manage"))
    conn = company_conn()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO campos (nombre, tipo) VALUES (?, ?)", (nombre, tipo))
        conn.commit()
    except sqlite3.IntegrityError:
        flash("El campo ya existe", "warning")
    conn.close()
    return redirect(url_for("manage"))

@app.route("/campos/delete/<int:id>", methods=["POST"])
@login_required
def campos_delete(id):
    conn = company_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM valores WHERE campo_id = ?", (id,))
    cur.execute("DELETE FROM campos WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash("Campo eliminado", "info")
    return redirect(url_for("manage"))

@app.route("/registros/delete/<int:id>", methods=["POST"])
@login_required
def registros_delete(id):
    conn = company_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM valores WHERE registro_id = ?", (id,))
    cur.execute("DELETE FROM registros WHERE id = ?", (id,))
    conn.commit()
    conn.close()
    flash("Registro eliminado", "info")
    return redirect(url_for("manage"))

# run
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=5000, debug=True)
