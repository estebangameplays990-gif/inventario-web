"""
app.py — Inventario Web (Flask + SQLAlchemy + PostgreSQL)
Ejecutar local: python app.py
Producción:     gunicorn app:app
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey
from sqlalchemy.orm import relationship
import os
from datetime import datetime

# ── App & DB setup ────────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "inventario_secret_2024")

# PostgreSQL en producción (Render), SQLite en local si no hay variable de entorno
DATABASE_URL = os.environ.get("DATABASE_URL", f"sqlite:///{os.path.join(os.path.dirname(os.path.abspath(__file__)), 'inventario.db')}")

# Render a veces entrega la URL con "postgres://" (viejo formato), SQLAlchemy necesita "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
Base = declarative_base()


# ── Models ────────────────────────────────────────────────────────────────────
class Categoria(Base):
    __tablename__ = "categorias"
    id     = Column(Integer, primary_key=True, autoincrement=True)
    nombre = Column(String(80), nullable=False, unique=True)
    productos = relationship("Producto", back_populates="cat_rel", cascade="all, delete-orphan")
    def __repr__(self): return self.nombre


class Proveedor(Base):
    __tablename__ = "proveedores"
    id       = Column(Integer, primary_key=True, autoincrement=True)
    nombre   = Column(String(120), nullable=False)
    contacto = Column(String(120))
    telefono = Column(String(30))
    email    = Column(String(120))
    productos = relationship("Producto", back_populates="prov_rel")
    def __repr__(self): return self.nombre


class Producto(Base):
    __tablename__ = "productos"
    id           = Column(Integer, primary_key=True, autoincrement=True)
    nombre       = Column(String(150), nullable=False)
    descripcion  = Column(String(300))
    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=True)
    proveedor_id = Column(Integer, ForeignKey("proveedores.id"), nullable=True)
    cantidad     = Column(Integer, default=0, nullable=False)
    precio       = Column(Float, nullable=False)
    stock_minimo = Column(Integer, default=5)
    creado_en    = Column(DateTime, default=func.now())
    actualizado  = Column(DateTime, default=func.now(), onupdate=func.now())
    cat_rel  = relationship("Categoria", back_populates="productos")
    prov_rel = relationship("Proveedor", back_populates="productos")

    @property
    def bajo_stock(self):
        return self.cantidad <= self.stock_minimo


class Movimiento(Base):
    __tablename__ = "movimientos"
    id          = Column(Integer, primary_key=True, autoincrement=True)
    producto_id = Column(Integer, ForeignKey("productos.id"), nullable=False)
    tipo        = Column(String(10), nullable=False)
    cantidad    = Column(Integer, nullable=False)
    nota        = Column(String(200))
    fecha       = Column(DateTime, default=func.now())
    producto    = relationship("Producto")


Base.metadata.create_all(engine)


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_session():
    return Session()


# ══════════════════════════════════════════════════════════════════════════════
# DASHBOARD
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/")
def dashboard():
    db = get_session()
    try:
        total_productos  = db.query(Producto).count()
        total_categorias = db.query(Categoria).count()
        total_proveedores= db.query(Proveedor).count()
        bajo_stock       = db.query(Producto).filter(Producto.cantidad <= Producto.stock_minimo).all()

        # Valor total del inventario
        productos = db.query(Producto).all()
        valor_total = sum(p.cantidad * p.precio for p in productos)

        # Últimos 8 movimientos
        ultimos_movs = (db.query(Movimiento)
                          .order_by(Movimiento.fecha.desc())
                          .limit(8).all())

        # Productos por categoría (para gráfico)
        cat_stats = (db.query(Categoria.nombre, func.count(Producto.id))
                       .outerjoin(Producto)
                       .group_by(Categoria.id)
                       .all())

        return render_template("dashboard.html",
            total_productos=total_productos,
            total_categorias=total_categorias,
            total_proveedores=total_proveedores,
            bajo_stock=bajo_stock,
            valor_total=valor_total,
            ultimos_movs=ultimos_movs,
            cat_stats=cat_stats,
        )
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
# PRODUCTOS
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/productos")
def productos():
    db = get_session()
    try:
        q      = request.args.get("q", "").strip()
        cat_id = request.args.get("categoria", "")
        query  = db.query(Producto)
        if q:
            query = query.filter(Producto.nombre.ilike(f"%{q}%"))
        if cat_id:
            query = query.filter(Producto.categoria_id == int(cat_id))
        productos   = query.order_by(Producto.nombre).all()
        categorias  = db.query(Categoria).order_by(Categoria.nombre).all()
        return render_template("productos.html",
            productos=productos, categorias=categorias, q=q, cat_id=cat_id)
    finally:
        db.close()


@app.route("/productos/nuevo", methods=["GET", "POST"])
def producto_nuevo():
    db = get_session()
    try:
        if request.method == "POST":
            p = Producto(
                nombre       = request.form["nombre"],
                descripcion  = request.form.get("descripcion", ""),
                categoria_id = request.form.get("categoria_id") or None,
                proveedor_id = request.form.get("proveedor_id") or None,
                cantidad     = int(request.form.get("cantidad", 0)),
                precio       = float(request.form["precio"]),
                stock_minimo = int(request.form.get("stock_minimo", 5)),
            )
            db.add(p)
            # Movimiento inicial si hay cantidad
            if p.cantidad > 0:
                db.flush()
                db.add(Movimiento(producto_id=p.id, tipo="entrada",
                                  cantidad=p.cantidad, nota="Stock inicial"))
            db.commit()
            flash("Producto creado exitosamente.", "success")
            return redirect(url_for("productos"))

        categorias = db.query(Categoria).order_by(Categoria.nombre).all()
        proveedores= db.query(Proveedor).order_by(Proveedor.nombre).all()
        return render_template("producto_form.html",
            producto=None, categorias=categorias, proveedores=proveedores)
    finally:
        db.close()


@app.route("/productos/<int:pid>/editar", methods=["GET", "POST"])
def producto_editar(pid):
    db = get_session()
    try:
        p = db.query(Producto).get(pid)
        if not p:
            flash("Producto no encontrado.", "danger")
            return redirect(url_for("productos"))

        if request.method == "POST":
            p.nombre       = request.form["nombre"]
            p.descripcion  = request.form.get("descripcion", "")
            p.categoria_id = request.form.get("categoria_id") or None
            p.proveedor_id = request.form.get("proveedor_id") or None
            p.precio       = float(request.form["precio"])
            p.stock_minimo = int(request.form.get("stock_minimo", 5))
            db.commit()
            flash("Producto actualizado.", "success")
            return redirect(url_for("productos"))

        categorias = db.query(Categoria).order_by(Categoria.nombre).all()
        proveedores= db.query(Proveedor).order_by(Proveedor.nombre).all()
        return render_template("producto_form.html",
            producto=p, categorias=categorias, proveedores=proveedores)
    finally:
        db.close()


@app.route("/productos/<int:pid>/eliminar", methods=["POST"])
def producto_eliminar(pid):
    db = get_session()
    try:
        p = db.query(Producto).get(pid)
        if p:
            db.query(Movimiento).filter_by(producto_id=pid).delete()
            db.delete(p)
            db.commit()
            flash("Producto eliminado.", "info")
    finally:
        db.close()
    return redirect(url_for("productos"))


@app.route("/productos/<int:pid>/movimiento", methods=["POST"])
def producto_movimiento(pid):
    db = get_session()
    try:
        p       = db.query(Producto).get(pid)
        tipo    = request.form["tipo"]
        cant    = int(request.form["cantidad"])
        nota    = request.form.get("nota", "")
        if tipo == "salida" and cant > p.cantidad:
            flash("No hay suficiente stock para esa salida.", "danger")
        else:
            if tipo == "entrada":
                p.cantidad += cant
            else:
                p.cantidad -= cant
            db.add(Movimiento(producto_id=pid, tipo=tipo, cantidad=cant, nota=nota))
            db.commit()
            flash(f"Movimiento de {tipo} registrado.", "success")
    finally:
        db.close()
    return redirect(url_for("productos"))


# ══════════════════════════════════════════════════════════════════════════════
# CATEGORÍAS
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/categorias")
def categorias():
    db = get_session()
    try:
        cats = db.query(Categoria).order_by(Categoria.nombre).all()
        return render_template("categorias.html", categorias=cats)
    finally:
        db.close()


@app.route("/categorias/nueva", methods=["POST"])
def categoria_nueva():
    db = get_session()
    try:
        nombre = request.form["nombre"].strip()
        if nombre:
            db.add(Categoria(nombre=nombre))
            db.commit()
            flash("Categoría creada.", "success")
    finally:
        db.close()
    return redirect(url_for("categorias"))


@app.route("/categorias/<int:cid>/editar", methods=["POST"])
def categoria_editar(cid):
    db = get_session()
    try:
        c = db.query(Categoria).get(cid)
        if c:
            c.nombre = request.form["nombre"].strip()
            db.commit()
            flash("Categoría actualizada.", "success")
    finally:
        db.close()
    return redirect(url_for("categorias"))


@app.route("/categorias/<int:cid>/eliminar", methods=["POST"])
def categoria_eliminar(cid):
    db = get_session()
    try:
        c = db.query(Categoria).get(cid)
        if c:
            db.delete(c)
            db.commit()
            flash("Categoría eliminada.", "info")
    finally:
        db.close()
    return redirect(url_for("categorias"))


# ══════════════════════════════════════════════════════════════════════════════
# PROVEEDORES
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/proveedores")
def proveedores():
    db = get_session()
    try:
        provs = db.query(Proveedor).order_by(Proveedor.nombre).all()
        return render_template("proveedores.html", proveedores=provs)
    finally:
        db.close()


@app.route("/proveedores/nuevo", methods=["GET", "POST"])
def proveedor_nuevo():
    db = get_session()
    try:
        if request.method == "POST":
            db.add(Proveedor(
                nombre   = request.form["nombre"],
                contacto = request.form.get("contacto", ""),
                telefono = request.form.get("telefono", ""),
                email    = request.form.get("email", ""),
            ))
            db.commit()
            flash("Proveedor creado.", "success")
            return redirect(url_for("proveedores"))
        return render_template("proveedor_form.html", proveedor=None)
    finally:
        db.close()


@app.route("/proveedores/<int:pid>/editar", methods=["GET", "POST"])
def proveedor_editar(pid):
    db = get_session()
    try:
        p = db.query(Proveedor).get(pid)
        if not p:
            flash("Proveedor no encontrado.", "danger")
            return redirect(url_for("proveedores"))
        if request.method == "POST":
            p.nombre   = request.form["nombre"]
            p.contacto = request.form.get("contacto", "")
            p.telefono = request.form.get("telefono", "")
            p.email    = request.form.get("email", "")
            db.commit()
            flash("Proveedor actualizado.", "success")
            return redirect(url_for("proveedores"))
        return render_template("proveedor_form.html", proveedor=p)
    finally:
        db.close()


@app.route("/proveedores/<int:pid>/eliminar", methods=["POST"])
def proveedor_eliminar(pid):
    db = get_session()
    try:
        p = db.query(Proveedor).get(pid)
        if p:
            db.delete(p)
            db.commit()
            flash("Proveedor eliminado.", "info")
    finally:
        db.close()
    return redirect(url_for("proveedores"))


# ══════════════════════════════════════════════════════════════════════════════
# MOVIMIENTOS
# ══════════════════════════════════════════════════════════════════════════════
@app.route("/movimientos")
def movimientos():
    db = get_session()
    try:
        movs = (db.query(Movimiento)
                  .order_by(Movimiento.fecha.desc())
                  .limit(200).all())
        return render_template("movimientos.html", movimientos=movs)
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
