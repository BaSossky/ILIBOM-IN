# ═══════════════════════════════════════════════════════════════
#  ILIBOM-IN · app.py  —  Funcionalidad completa con MySQL
#  Inmobiliaria EXAUMY
# ═══════════════════════════════════════════════════════════════

from flask import (Flask, render_template, request, redirect,
                   url_for, session, flash, jsonify, Response)
from dotenv import load_dotenv
from functools import wraps
from datetime import date, datetime, timedelta
from werkzeug.utils import secure_filename
import uuid
import bcrypt
import os
import db

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'ilibom-clave-2025')
db.init_app(app)

# ══════════════════════════════════════════════════════════════
#  HELPERS
# ══════════════════════════════════════════════════════════════

PERMISOS_ROL = {
    'Administrador': ['dashboard','propiedades','clientes','agenda',
                      'contratos','pagos','reportes','usuarios'],
    'Asesor':        ['dashboard','propiedades','clientes','agenda'],
    'Administrativo':['dashboard','propiedades','contratos','pagos'],
}

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'id_usuario' not in session:
            flash('Debes iniciar sesión primero', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def rol_requerido(modulo):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if modulo not in PERMISOS_ROL.get(session.get('rol',''), []):
                flash(f'Tu rol no tiene acceso a este módulo', 'error')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated
    return decorator

def hash_password(plain):
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()

def check_password(plain, hashed):
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return plain == hashed

def log_accion(modulo, accion, descripcion=''):
    try:
        db.execute(
            """INSERT INTO Bitacora_Auditoria
               (id_usuario, modulo, accion, descripcion, ip_origen)
               VALUES (%s,%s,%s,%s,%s)""",
            (session.get('id_usuario'), modulo, accion,
             descripcion, request.remote_addr)
        )
    except Exception:
        pass

def cliente_accesible(id_cliente):
    if session.get('rol') in ('Administrador', 'Administrativo'):
        return True
    cliente = db.query(
        "SELECT id_asesor FROM Clientes WHERE id_cliente=%s",
        (id_cliente,), one=True
    )
    if not cliente:
        return False
    return cliente['id_asesor'] == session.get('id_usuario')

def cita_modificable(id_cita):
    if session.get('rol') == 'Administrador':
        return True
    cita = db.query(
        "SELECT registrado_por FROM Citas WHERE id_cita=%s",
        (id_cita,), one=True
    )
    if not cita:
        return False
    return cita['registrado_por'] == session.get('id_usuario')

# ══════════════════════════════════════════════════════════════
#  AUTH
# ══════════════════════════════════════════════════════════════

@app.route('/', methods=['GET','POST'])
def login():
    if 'id_usuario' in session:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        email    = request.form.get('email','').strip().lower()
        password = request.form.get('password','').strip()
        usuario  = db.query(
            """SELECT u.id_usuario, u.nombre, u.password_hash,
                      u.estatus, r.nombre_rol
               FROM Usuarios u JOIN Roles r ON u.id_rol=r.id_rol
               WHERE u.email=%s""", (email,), one=True)
        if not usuario:
            flash('Correo o contraseña incorrectos','error')
            return render_template('login.html')
        if usuario['estatus'] == 'Inactivo':
            flash('Tu cuenta está inactiva. Contacta al administrador.','error')
            return render_template('login.html')
        if not check_password(password, usuario['password_hash']):
            flash('Correo o contraseña incorrectos','error')
            return render_template('login.html')
        session['id_usuario'] = usuario['id_usuario']
        session['nombre']     = usuario['nombre']
        session['rol']        = usuario['nombre_rol']
        db.execute("UPDATE Usuarios SET ultimo_acceso=%s WHERE id_usuario=%s",
                   (datetime.now(), usuario['id_usuario']))
        log_accion('Auth','LOGIN',f"Login: {email}")
        return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    log_accion('Auth','LOGOUT',f"Logout: {session.get('nombre')}")
    session.clear()
    return redirect(url_for('login'))

# ══════════════════════════════════════════════════════════════
#  DASHBOARD
# ══════════════════════════════════════════════════════════════

@app.route('/dashboard')
@login_required
def dashboard():
    kpis = db.query(
        """SELECT COUNT(*) AS total_propiedades,
            SUM(CASE WHEN estatus='Disponible' THEN 1 ELSE 0 END) AS disponibles,
            SUM(CASE WHEN estatus='Apartada'   THEN 1 ELSE 0 END) AS apartadas,
            SUM(CASE WHEN estatus='Vendida'    THEN 1 ELSE 0 END) AS vendidas
           FROM Propiedades WHERE estatus!='Inactiva'""", one=True)
    total_clientes   = db.query("SELECT COUNT(*) AS n FROM Clientes WHERE activo=1", one=True)['n']
    pagos_pendientes = db.query(
        "SELECT COUNT(*) AS n FROM Pagos_Renta WHERE estatus IN ('Pendiente','Atrasado')", one=True)['n']
    citas_hoy = db.query(
        """SELECT c.hora_inicio, c.hora_fin, c.estatus,
                  cl.nombre AS cliente, p.nombre AS propiedad, u.nombre AS asesor
           FROM Citas c
           JOIN Clientes cl ON cl.id_cliente=c.id_cliente
           JOIN Propiedades p ON p.id_propiedad=c.id_propiedad
           JOIN Usuarios u ON u.id_usuario=c.id_asesor
           WHERE DATE(c.fecha_cita)=CURDATE()
           ORDER BY c.hora_inicio""")
    return render_template('dashboard.html', kpis=kpis,
        total_clientes=total_clientes, pagos_pendientes=pagos_pendientes,
        citas_hoy=citas_hoy)

# ══════════════════════════════════════════════════════════════
#  PROPIEDADES  OBJ-01
# ══════════════════════════════════════════════════════════════

@app.route('/propiedades')
@login_required
@rol_requerido('propiedades')
def propiedades():
    filtro = request.args.get('filtro','Todas')
    buscar = request.args.get('q','')
    sql = """SELECT p.id_propiedad, p.nombre, p.tipo_inmueble,
                    p.precio_venta, p.precio_renta, p.origen_captacion,
                    p.estatus, p.calle, p.colonia, p.municipio,
                    u.nombre AS asesor
             FROM Propiedades p JOIN Usuarios u ON u.id_usuario=p.id_asesor WHERE 1=1"""
    params = []
    if filtro != 'Todas':
        sql += " AND p.estatus=%s"; params.append(filtro)
    if buscar:
        sql += " AND (p.nombre LIKE %s OR p.calle LIKE %s OR p.colonia LIKE %s)"
        params += [f'%{buscar}%',f'%{buscar}%',f'%{buscar}%']
    sql += " ORDER BY p.fecha_registro DESC"
    lista    = db.query(sql, params)
    conteos  = db.query(
        """SELECT SUM(CASE WHEN estatus='Disponible' THEN 1 ELSE 0 END) AS disponibles,
                  SUM(CASE WHEN estatus='Apartada'   THEN 1 ELSE 0 END) AS apartadas,
                  SUM(CASE WHEN estatus='Vendida'    THEN 1 ELSE 0 END) AS vendidas,
                  SUM(CASE WHEN estatus='Inactiva'   THEN 1 ELSE 0 END) AS inactivas,
                  COUNT(*) AS total FROM Propiedades""", one=True)
    asesores = db.query("SELECT id_usuario, nombre FROM Usuarios WHERE estatus='Activo' ORDER BY nombre")
    return render_template('propiedades.html',
        propiedades=lista, filtro=filtro,
        conteos=conteos, asesores=asesores, buscar=buscar)

@app.route('/propiedades/nueva', methods=['POST'])
@login_required
@rol_requerido('propiedades')
def nueva_propiedad():
    f = request.form
    nid = db.execute(
        """INSERT INTO Propiedades
            (nombre,tipo_inmueble,precio_venta,precio_renta,metros_cuadrados,
             recamaras,banos,estacionamientos,calle,numero_ext,numero_int,
             colonia,municipio,estado,cp,origen_captacion,id_asesor,notas,creado_por)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (f['nombre'],f['tipo_inmueble'],
         f.get('precio_venta') or None, f.get('precio_renta') or None,
         f.get('metros') or None, f.get('recamaras') or 0,
         f.get('banos') or 0, f.get('estacionamientos') or 0,
         f['calle'],f.get('num_ext'),f.get('num_int'),
         f.get('colonia'),f.get('municipio','León'),
         f.get('estado','Guanajuato'),f.get('cp'),
         f['origen_captacion'],f['id_asesor'],
         f.get('notas'), session['id_usuario']))
    db.execute(
        """INSERT INTO Historial_Estatus_Propiedad
           (id_propiedad,estatus_anterior,estatus_nuevo,motivo,id_usuario)
           VALUES (%s,%s,%s,%s,%s)""",
        (nid,'—','Disponible','Alta de propiedad',session['id_usuario']))
    log_accion('Propiedades','INSERT',f"Nueva propiedad #{nid}: {f['nombre']}")
    flash(f'Propiedad registrada — estado: Disponible','success')
    return redirect(url_for('propiedades'))

@app.route('/propiedades/editar/<int:id>', methods=['GET','POST'])
@login_required
@rol_requerido('propiedades')
def editar_propiedad(id):
    if request.method == 'POST':
        f = request.form
        anterior = db.query(
            "SELECT estatus FROM Propiedades WHERE id_propiedad=%s",
            (id,), one=True
        )
        estatus_anterior = anterior['estatus'] if anterior else None
        estatus_nuevo    = f.get('estatus', estatus_anterior)

        db.execute(
            """UPDATE Propiedades SET nombre=%s, tipo_inmueble=%s, precio_venta=%s,
               precio_renta=%s, metros_cuadrados=%s, recamaras=%s, banos=%s,
               calle=%s, colonia=%s, municipio=%s, origen_captacion=%s,
               id_asesor=%s, estatus=%s, notas=%s, fecha_actualizacion=NOW()
               WHERE id_propiedad=%s""",
            (f['nombre'], f['tipo_inmueble'],
             f.get('precio_venta') or None, f.get('precio_renta') or None,
             f.get('metros') or None, f.get('recamaras') or 0,
             f.get('banos') or 0,
             f['calle'], f.get('colonia'), f.get('municipio','León'),
             f['origen_captacion'], f['id_asesor'],
             estatus_nuevo, f.get('notas'), id))

        if estatus_anterior != estatus_nuevo:
            db.execute(
                """INSERT INTO Historial_Estatus_Propiedad
                   (id_propiedad, estatus_anterior, estatus_nuevo, motivo, id_usuario)
                   VALUES (%s,%s,%s,%s,%s)""",
                (id, estatus_anterior, estatus_nuevo,
                 'Cambio manual desde edición', session['id_usuario']))
            log_accion('Propiedades', 'UPDATE',
                       f"Estatus #{id}: {estatus_anterior} -> {estatus_nuevo}")

        flash(' Propiedad actualizada correctamente', 'success')
        return redirect(url_for('propiedades'))

    prop     = db.query("SELECT * FROM Propiedades WHERE id_propiedad=%s",(id,),one=True)
    asesores = db.query("SELECT id_usuario, nombre FROM Usuarios WHERE estatus='Activo'")
    return render_template('editar_propiedad.html', prop=prop, asesores=asesores)

@app.route('/propiedades/baja/<int:id>', methods=['POST'])
@login_required
@rol_requerido('propiedades')
def baja_propiedad(id):
    activo = db.query(
        "SELECT id_contrato FROM Contratos WHERE id_propiedad=%s AND estatus='Activo'",(id,),one=True)
    if activo:
        flash('No se puede dar de baja — tiene un contrato activo','error')
        return redirect(url_for('propiedades'))
    motivo = request.form.get('motivo','Baja solicitada')
    prop   = db.query("SELECT nombre, estatus FROM Propiedades WHERE id_propiedad=%s",(id,),one=True)
    db.execute(
        "UPDATE Propiedades SET estatus='Inactiva',fecha_baja=NOW(),motivo_baja=%s WHERE id_propiedad=%s",
        (motivo,id))
    db.execute(
        """INSERT INTO Historial_Estatus_Propiedad
           (id_propiedad,estatus_anterior,estatus_nuevo,motivo,id_usuario)
           VALUES (%s,%s,%s,%s,%s)""",
        (id,prop['estatus'],'Inactiva',motivo,session['id_usuario']))
    flash('Propiedad dada de baja','success')
    return redirect(url_for('propiedades'))

@app.route('/propiedades/reactivar/<int:id>', methods=['POST'])
@login_required
@rol_requerido('propiedades')
def reactivar_propiedad(id):
    db.execute(
        "UPDATE Propiedades SET estatus='Disponible',fecha_baja=NULL,motivo_baja=NULL WHERE id_propiedad=%s",(id,))
    db.execute(
        """INSERT INTO Historial_Estatus_Propiedad
           (id_propiedad,estatus_anterior,estatus_nuevo,motivo,id_usuario)
           VALUES (%s,%s,%s,%s,%s)""",
        (id,'Inactiva','Disponible','Reactivación ',session['id_usuario']))
    flash('Propiedad reactivada al inventario','success')
    return redirect(url_for('propiedades'))

@app.route('/propiedades/historial/<int:id>')
@login_required
def historial_propiedad(id):
    prop     = db.query("SELECT nombre FROM Propiedades WHERE id_propiedad=%s",(id,),one=True)
    historial= db.query(
        """SELECT h.*,u.nombre AS usuario
           FROM Historial_Estatus_Propiedad h
           JOIN Usuarios u ON u.id_usuario=h.id_usuario
           WHERE h.id_propiedad=%s ORDER BY h.fecha_cambio DESC""",(id,))
    return render_template('historial_propiedad.html', prop=prop, historial=historial)

# ══════════════════════════════════════════════════════════════
#  CLIENTES  OBJ-02
# ══════════════════════════════════════════════════════════════

@app.route('/clientes')
@login_required
@rol_requerido('clientes')
def clientes():
    buscar = request.args.get('q','')
    filtro = request.args.get('filtro','Todos')

    sql = """SELECT c.*, u.nombre AS asesor_nombre
             FROM Clientes c
             LEFT JOIN Usuarios u ON u.id_usuario = c.id_asesor
             WHERE c.activo = 1"""
    params = []

    if session.get('rol') == 'Asesor':
        sql += " AND c.id_asesor = %s"
        params.append(session['id_usuario'])

    if filtro != 'Todos':
        sql += " AND c.estatus_lead = %s"
        params.append(filtro)

    if buscar:
        sql += " AND (c.nombre LIKE %s OR c.email LIKE %s OR c.telefono LIKE %s)"
        params += [f'%{buscar}%', f'%{buscar}%', f'%{buscar}%']

    sql += " ORDER BY c.fecha_registro DESC"
    lista = db.query(sql, params)

    asesores = db.query("SELECT id_usuario, nombre FROM Usuarios WHERE estatus='Activo'")

    sql_kpi = """SELECT COUNT(*) AS total,
                SUM(CASE WHEN estatus_lead='Nuevo'         THEN 1 ELSE 0 END) AS nuevos,
                SUM(CASE WHEN estatus_lead='Cita agendada' THEN 1 ELSE 0 END) AS con_cita,
                SUM(CASE WHEN estatus_lead='Sin contactar' THEN 1 ELSE 0 END) AS sin_contactar
                FROM Clientes WHERE activo = 1"""
    kpi_params = []
    if session.get('rol') == 'Asesor':
        sql_kpi += " AND id_asesor = %s"
        kpi_params.append(session['id_usuario'])

    conteos = db.query(sql_kpi, kpi_params, one=True)

    return render_template('clientes.html',
        clientes=lista, asesores=asesores,
        conteos=conteos, buscar=buscar, filtro=filtro)

@app.route('/clientes/nuevo', methods=['POST'])
@login_required
@rol_requerido('clientes')
def nuevo_cliente():
    f = request.form
    existe = db.query(
        "SELECT id_cliente FROM Clientes WHERE telefono=%s OR email=%s",
        (f['telefono'], f.get('email','')), one=True)
    if existe:
        flash('Cliente duplicado — ya existe con ese teléfono o correo','error')
        return redirect(url_for('clientes'))

    if session.get('rol') == 'Asesor':
        id_asesor = session['id_usuario']
    else:
        id_asesor = f.get('id_asesor') or None

    db.execute(
        """INSERT INTO Clientes
            (nombre, apellido_paterno, telefono, email, tipo_inmueble_interes,
             presupuesto_min, presupuesto_max, zonas_interes, id_asesor,
             fuente_captacion, notas)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (f['nombre'], f.get('apellido'), f['telefono'], f.get('email'),
         f.get('tipo_interes'), f.get('pres_min') or None,
         f.get('pres_max') or None, f.get('zonas'),
         id_asesor, f.get('fuente'), f.get('notas')))

    log_accion('Clientes','INSERT', f"Nuevo cliente: {f['nombre']}")
    flash(f' Cliente "{f["nombre"]}" guardado — CRM actualizado','success')
    return redirect(url_for('clientes'))


@app.route('/clientes/editar/<int:id>', methods=['GET','POST'])
@login_required
@rol_requerido('clientes')
def editar_cliente(id):
    if not cliente_accesible(id):
        flash('No tienes permiso para acceder a este cliente', 'error')
        return redirect(url_for('clientes'))

    if request.method == 'POST':
        f = request.form
        db.execute(
            """UPDATE Clientes SET nombre=%s,apellido_paterno=%s,telefono=%s,
               email=%s,tipo_inmueble_interes=%s,presupuesto_min=%s,
               presupuesto_max=%s,zonas_interes=%s,estatus_lead=%s,
               id_asesor=%s,notas=%s,fecha_actualizacion=NOW()
               WHERE id_cliente=%s""",
            (f['nombre'],f.get('apellido'),f['telefono'],f.get('email'),
             f.get('tipo_interes'),f.get('pres_min') or None,
             f.get('pres_max') or None,f.get('zonas'),
             f['estatus_lead'],f.get('id_asesor') or None,
             f.get('notas'),id))
        flash(' Perfil de cliente actualizado','success')
        return redirect(url_for('clientes'))

    cliente  = db.query("SELECT * FROM Clientes WHERE id_cliente=%s",(id,),one=True)
    asesores = db.query("SELECT id_usuario,nombre FROM Usuarios WHERE estatus='Activo'")
    return render_template('editar_cliente.html', cliente=cliente, asesores=asesores)


@app.route('/clientes/historial/<int:id>')
@login_required
@rol_requerido('clientes')
def historial_cliente(id):
    if not cliente_accesible(id):
        flash('No tienes permiso para acceder a este cliente', 'error')
        return redirect(url_for('clientes'))

    cliente = db.query(
        """SELECT c.*, u.nombre AS asesor_nombre
           FROM Clientes c
           LEFT JOIN Usuarios u ON u.id_usuario = c.id_asesor
           WHERE c.id_cliente=%s""", (id,), one=True
    )
    if not cliente:
        flash('Cliente no encontrado', 'error')
        return redirect(url_for('clientes'))

    historial = db.query(
        """SELECT b.*, u.nombre AS usuario
           FROM Bitacora_Seguimiento b
           JOIN Usuarios u ON u.id_usuario = b.id_usuario
           WHERE b.id_cliente = %s
           ORDER BY b.fecha_contacto DESC""",
        (id,)
    )
    mensajes_wa = db.query(
        """SELECT m.*, u.nombre AS usuario
           FROM Mensajes_WhatsApp m
           JOIN Usuarios u ON u.id_usuario = m.id_usuario
           WHERE m.id_cliente = %s
           ORDER BY m.fecha_envio DESC""",
        (id,)
    )
    return render_template('historial_cliente.html',
        cliente=cliente, historial=historial, mensajes_wa=mensajes_wa)


@app.route('/clientes/baja/<int:id>', methods=['POST'])
@login_required
@rol_requerido('clientes')
def baja_cliente(id):
    if not cliente_accesible(id):
        flash('No tienes permiso para eliminar este cliente', 'error')
        return redirect(url_for('clientes'))

    cliente = db.query(
        "SELECT nombre FROM Clientes WHERE id_cliente=%s", (id,), one=True
    )
    if not cliente:
        flash('Cliente no encontrado', 'error')
        return redirect(url_for('clientes'))

    db.execute("UPDATE Clientes SET activo=0 WHERE id_cliente=%s", (id,))
    log_accion('Clientes', 'DELETE', f"Baja del cliente: {cliente['nombre']}")
    flash(f'Cliente "{cliente["nombre"]}" eliminado correctamente', 'success')
    return redirect(url_for('clientes'))


@app.route('/clientes/cambiar_estatus/<int:id>', methods=['POST'])
@login_required
@rol_requerido('clientes')
def cambiar_estatus_cliente(id):
    if not cliente_accesible(id):
        flash('No tienes permiso para modificar este cliente', 'error')
        return redirect(url_for('clientes'))

    nuevo  = request.form.get('estatus_lead')
    motivo = request.form.get('motivo', 'Cambio manual')

    cliente = db.query(
        "SELECT nombre, estatus_lead FROM Clientes WHERE id_cliente=%s",
        (id,), one=True
    )
    if not cliente:
        flash('Cliente no encontrado', 'error')
        return redirect(url_for('clientes'))

    estatus_anterior = cliente['estatus_lead']

    db.execute(
        """UPDATE Clientes SET estatus_lead=%s, fecha_actualizacion=NOW()
           WHERE id_cliente=%s""", (nuevo, id)
    )

    db.execute(
        """INSERT INTO Bitacora_Seguimiento
           (id_cliente, id_usuario, canal, descripcion)
           VALUES (%s,%s,%s,%s)""",
        (id, session['id_usuario'], 'Sistema',
         f'Cambio de estatus: {estatus_anterior} -> {nuevo}. {motivo}')
    )
    log_accion('Clientes', 'UPDATE',
               f"Estatus cliente #{id}: {estatus_anterior} -> {nuevo}")
    flash(f'Estatus actualizado: {estatus_anterior} -> {nuevo}', 'success')
    return redirect(url_for('clientes'))


@app.route('/clientes/seguimiento', methods=['POST'])
@login_required
@rol_requerido('clientes')
def registrar_seguimiento():
    f = request.form

    if not cliente_accesible(int(f['id_cliente'])):
        flash('No tienes permiso para este cliente', 'error')
        return redirect(url_for('clientes'))

    db.execute(
        """INSERT INTO Bitacora_Seguimiento
            (id_cliente, id_usuario, canal, descripcion)
           VALUES (%s,%s,%s,%s)""",
        (f['id_cliente'], session['id_usuario'],
         f['canal'], f['descripcion'])
    )
    db.execute(
        """UPDATE Clientes SET estatus_lead='Contactado',
           fecha_actualizacion=NOW()
           WHERE id_cliente=%s AND estatus_lead IN ('Nuevo','Sin contactar')""",
        (f['id_cliente'],)
    )
    log_accion('Clientes', 'INSERT', f"Seguimiento registrado para cliente #{f['id_cliente']}")
    flash('Contacto registrado en bitácora — estatus actualizado a "Contactado"', 'success')
    return redirect(url_for('clientes'))

# ══════════════════════════════════════════════════════════════
#  AGENDA  OBJ-05
# ══════════════════════════════════════════════════════════════

@app.route('/agenda')
@login_required
@rol_requerido('agenda')
def agenda():
    import calendar as cal
    from datetime import date

    mes  = int(request.args.get('mes',  date.today().month))
    anio = int(request.args.get('anio', date.today().year))

    if mes < 1: mes = 1
    if mes > 12: mes = 12
    if anio < 2020: anio = 2020
    if anio > 2050: anio = 2050

    if mes == 1:
        mes_anterior, anio_anterior = 12, anio - 1
    else:
        mes_anterior, anio_anterior = mes - 1, anio

    if mes == 12:
        mes_siguiente, anio_siguiente = 1, anio + 1
    else:
        mes_siguiente, anio_siguiente = mes + 1, anio

    nombres_meses = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                     'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']
    nombre_mes      = nombres_meses[mes - 1]
    primer_dia      = date(anio, mes, 1)
    primer_dia_sem  = primer_dia.weekday()
    dias_en_mes     = cal.monthrange(anio, mes)[1]

    hoy = date.today()

    citas = db.query(
        """SELECT c.id_cita, c.fecha_cita, c.hora_inicio, c.hora_fin,
                  c.estatus, c.notas, c.registrado_por,
                  cl.nombre AS cliente, cl.telefono,
                  p.nombre  AS propiedad,
                  u.nombre  AS asesor,
                  ru.nombre AS registrado_por_nombre
           FROM Citas c
           JOIN Clientes cl    ON cl.id_cliente  = c.id_cliente
           JOIN Propiedades p  ON p.id_propiedad = c.id_propiedad
           JOIN Usuarios u     ON u.id_usuario   = c.id_asesor
           JOIN Usuarios ru    ON ru.id_usuario  = c.registrado_por
           WHERE MONTH(c.fecha_cita)=%s AND YEAR(c.fecha_cita)=%s
           ORDER BY c.fecha_cita, c.hora_inicio""",
        (mes, anio)
    )

    citas_por_dia = {}
    for c in citas:
        if c['fecha_cita']:
            dia = c['fecha_cita'].day
            citas_por_dia.setdefault(dia, []).append(c)

    clientes_act = db.query(
        "SELECT id_cliente, nombre, telefono FROM Clientes WHERE activo=1 ORDER BY nombre")
    props_disp = db.query(
        "SELECT id_propiedad, nombre FROM Propiedades WHERE estatus='Disponible' ORDER BY nombre")
    asesores = db.query(
        "SELECT id_usuario, nombre FROM Usuarios WHERE estatus='Activo' AND id_rol IN (1,2)")

    return render_template('agenda.html',
        citas=citas, citas_por_dia=citas_por_dia,
        mes=mes, anio=anio, nombre_mes=nombre_mes,
        primer_dia_semana=primer_dia_sem, dias_en_mes=dias_en_mes,
        mes_anterior=mes_anterior, anio_anterior=anio_anterior,
        mes_siguiente=mes_siguiente, anio_siguiente=anio_siguiente,
        hoy_dia=hoy.day, hoy_mes=hoy.month, hoy_anio=hoy.year,
        hoy_iso=hoy.isoformat(),
        clientes=clientes_act, propiedades=props_disp, asesores=asesores,
        date=date)


@app.route('/agenda/api/citas')
@login_required
@rol_requerido('agenda')
def api_citas():
    from datetime import date
    mes  = int(request.args.get('mes',  date.today().month))
    anio = int(request.args.get('anio', date.today().year))

    citas = db.query(
        """SELECT c.id_cita, c.fecha_cita, c.estatus, c.registrado_por
           FROM Citas c
           WHERE MONTH(c.fecha_cita)=%s AND YEAR(c.fecha_cita)=%s""",
        (mes, anio)
    )

    resumen = []
    for c in citas:
        resumen.append({
            'id': c['id_cita'],
            'estatus': c['estatus'],
        })

    return jsonify({
        'total': len(resumen),
        'citas': resumen,
        'mi_id': session.get('id_usuario'),
        'mi_rol': session.get('rol'),
    })

@app.route('/agenda/nueva', methods=['POST'])
@login_required
@rol_requerido('agenda')
def nueva_cita():
    from datetime import datetime, date
    f = request.form

    fecha_cita = datetime.strptime(f['fecha'], '%Y-%m-%d').date()
    if fecha_cita < date.today():
        flash('No puedes agendar citas en fechas pasadas','error')
        return redirect(url_for('agenda'))

    if f['hora_fin'] <= f['hora_inicio']:
        flash('La hora de fin debe ser mayor que la hora de inicio','error')
        return redirect(url_for('agenda'))

    empalme = db.query(
        """SELECT id_cita FROM Citas
           WHERE id_asesor=%s AND fecha_cita=%s
             AND estatus NOT IN ('Cancelada')
             AND (hora_inicio<%s AND hora_fin>%s)""",
        (f['id_asesor'], f['fecha'], f['hora_fin'], f['hora_inicio']),
        one=True)
    if empalme:
        flash('Conflicto de horario — el asesor ya tiene una cita en ese intervalo','error')
        return redirect(url_for('agenda'))

    db.execute(
        """INSERT INTO Citas
            (id_cliente, id_propiedad, id_asesor, fecha_cita,
             hora_inicio, hora_fin, notas, registrado_por)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        (f['id_cliente'], f['id_propiedad'], f['id_asesor'],
         f['fecha'], f['hora_inicio'], f['hora_fin'],
         f.get('notas'), session['id_usuario']))

    db.execute(
        """UPDATE Clientes SET estatus_lead='Cita agendada',
           fecha_actualizacion=NOW()
           WHERE id_cliente=%s AND estatus_lead NOT IN ('Ganado','Perdido')""",
        (f['id_cliente'],))

    log_accion('Agenda','INSERT', f"Cita agendada para {f['fecha']} {f['hora_inicio']}")
    flash('Cita confirmada — calendario actualizado','success')
    return redirect(url_for('agenda'))

@app.route('/agenda/cambiar/<int:id>', methods=['POST'])
@login_required
@rol_requerido('agenda')
def cambiar_estatus_cita(id):
    if not cita_modificable(id):
        flash('Solo el asesor que registró la cita o el administrador pueden modificarla', 'error')
        return redirect(url_for('agenda'))

    nuevo = request.form.get('estatus')

    cita = db.query(
        """SELECT c.estatus, c.id_cliente, cl.nombre AS cliente
           FROM Citas c
           JOIN Clientes cl ON cl.id_cliente = c.id_cliente
           WHERE c.id_cita=%s""", (id,), one=True
    )
    if not cita:
        flash('Cita no encontrada', 'error')
        return redirect(url_for('agenda'))

    db.execute("UPDATE Citas SET estatus=%s WHERE id_cita=%s", (nuevo, id))

    if nuevo == 'Realizada':
        db.execute(
            """UPDATE Clientes SET estatus_lead='Activo',
               fecha_actualizacion=NOW()
               WHERE id_cliente=%s AND estatus_lead='Cita agendada'""",
            (cita['id_cliente'],))

    log_accion('Agenda', 'UPDATE',
               f"Cita #{id} ({cita['cliente']}): {cita['estatus']} -> {nuevo}")
    flash(f'Cita actualizada a "{nuevo}"', 'success')
    return redirect(url_for('agenda'))

# ══════════════════════════════════════════════════════════════
#  CONTRATOS  OBJ-03
# ══════════════════════════════════════════════════════════════

@app.route('/contratos')
@login_required
@rol_requerido('contratos')
def contratos():
    filtro = request.args.get('filtro', 'Todos')
    buscar = request.args.get('q', '')

    sql = """SELECT ct.id_contrato, ct.folio, ct.tipo_contrato,
                    ct.fecha_inicio, ct.fecha_fin, ct.monto_total, ct.monto_renta,
                    ct.estatus, ct.fecha_generacion,
                    cl.nombre AS cliente, cl.telefono,
                    p.nombre  AS propiedad,
                    u.nombre  AS generado_por
             FROM Contratos ct
             JOIN Clientes    cl ON cl.id_cliente  = ct.id_cliente
             JOIN Propiedades p  ON p.id_propiedad = ct.id_propiedad
             JOIN Usuarios    u  ON u.id_usuario   = ct.id_usuario_genera
             WHERE 1=1"""
    params = []
    if filtro != 'Todos':
        sql += " AND ct.estatus=%s"
        params.append(filtro)
    if buscar:
        sql += " AND (ct.folio LIKE %s OR cl.nombre LIKE %s OR p.nombre LIKE %s)"
        params += [f'%{buscar}%', f'%{buscar}%', f'%{buscar}%']
    sql += " ORDER BY ct.fecha_generacion DESC"
    lista = db.query(sql, params)

    tramites = db.query(
        """SELECT t.*, ct.folio, cl.nombre AS cliente
           FROM Tramites_Bancarios t
           JOIN Contratos ct ON ct.id_contrato = t.id_contrato
           JOIN Clientes cl ON cl.id_cliente = ct.id_cliente
           ORDER BY t.fecha_registro DESC""")

    kpis = db.query(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN estatus='Activo' THEN 1 ELSE 0 END) AS activos,
                  SUM(CASE WHEN tipo_contrato='Compraventa' THEN 1 ELSE 0 END) AS compraventas,
                  SUM(CASE WHEN tipo_contrato='Arrendamiento' THEN 1 ELSE 0 END) AS arrendamientos,
                  SUM(monto_total) AS monto_total
           FROM Contratos""", one=True)

    depositos_validados = db.query(
        """SELECT d.id_deposito, d.id_propiedad, d.id_cliente, d.monto,
                  cl.nombre AS cliente, p.nombre AS propiedad,
                  p.precio_venta, p.precio_renta
           FROM Depositos d
           JOIN Clientes cl ON cl.id_cliente = d.id_cliente
           JOIN Propiedades p ON p.id_propiedad = d.id_propiedad
           WHERE d.validado = 1
             AND NOT EXISTS (
               SELECT 1 FROM Contratos ct
               WHERE ct.id_propiedad = d.id_propiedad
                 AND ct.id_cliente = d.id_cliente
                 AND ct.estatus = 'Activo'
             )
           ORDER BY d.fecha_validacion DESC""")

    return render_template('contratos.html',
        contratos=lista, tramites=tramites, kpis=kpis,
        depositos_validados=depositos_validados,
        filtro=filtro, buscar=buscar)

@app.route('/contratos/nuevo', methods=['POST'])
@login_required
@rol_requerido('contratos')
def nuevo_contrato():
    from datetime import datetime, date
    f = request.form

    deposito = db.query(
        """SELECT id_deposito FROM Depositos
           WHERE id_propiedad=%s AND id_cliente=%s AND validado=1""",
        (f['id_propiedad'], f['id_cliente']), one=True)
    if not deposito:
        flash('Se requiere un depósito validado para generar el contrato','error')
        return redirect(url_for('contratos'))

    activo = db.query(
        """SELECT id_contrato FROM Contratos
           WHERE id_propiedad=%s AND estatus='Activo'""",
        (f['id_propiedad'],), one=True)
    if activo:
        flash('Esta propiedad ya tiene un contrato activo','error')
        return redirect(url_for('contratos'))

    fecha_inicio = datetime.strptime(f['fecha_inicio'], '%Y-%m-%d').date()
    fecha_fin = None
    if f.get('fecha_fin'):
        fecha_fin = datetime.strptime(f['fecha_fin'], '%Y-%m-%d').date()
        if fecha_fin <= fecha_inicio:
            flash('La fecha de fin debe ser mayor a la de inicio','error')
            return redirect(url_for('contratos'))

    nid = db.execute(
        """INSERT INTO Contratos
            (id_cliente, id_propiedad, id_usuario_genera, tipo_contrato,
             fecha_inicio, fecha_fin, monto_total, monto_renta, notas)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (f['id_cliente'], f['id_propiedad'], session['id_usuario'],
         f['tipo_contrato'], f['fecha_inicio'], f.get('fecha_fin') or None,
         f['monto_total'], f.get('monto_renta') or None, f.get('notas')))

    nuevo_est = 'Vendida' if f['tipo_contrato'] == 'Compraventa' else 'Apartada'
    db.execute("UPDATE Propiedades SET estatus=%s WHERE id_propiedad=%s",
               (nuevo_est, f['id_propiedad']))
    db.execute(
        """INSERT INTO Historial_Estatus_Propiedad
           (id_propiedad, estatus_anterior, estatus_nuevo, motivo, id_usuario)
           VALUES (%s,%s,%s,%s,%s)""",
        (f['id_propiedad'], 'Apartada', nuevo_est,
         f'Contrato generado #{nid}', session['id_usuario']))

    if f['tipo_contrato'] == 'Arrendamiento' and fecha_fin and f.get('monto_renta'):
        monto_renta = float(f['monto_renta'])
        fecha_pago = fecha_inicio
        meses_generados = 0
        while fecha_pago <= fecha_fin and meses_generados < 60:
            try:
                fecha_limite = fecha_pago.replace(day=5) if fecha_pago.day < 5 else fecha_pago + timedelta(days=5)
                db.execute(
                    """INSERT INTO Pagos_Renta
                       (id_contrato, mes_correspondiente, monto_esperado, fecha_limite, estatus)
                       VALUES (%s,%s,%s,%s,'Pendiente')""",
                    (nid, fecha_pago.replace(day=1), monto_renta, fecha_limite))
                meses_generados += 1
                if fecha_pago.month == 12:
                    fecha_pago = fecha_pago.replace(year=fecha_pago.year+1, month=1)
                else:
                    fecha_pago = fecha_pago.replace(month=fecha_pago.month+1)
            except Exception as e:
                print(f"Error generando pago: {e}")
                break

        log_accion('Contratos', 'INSERT',
                   f"Contrato {nid} arrendamiento — {meses_generados} pagos generados")
        flash(f'Contrato generado #{nid} — {meses_generados} pagos mensuales creados', 'success')
    else:
        if f['tipo_contrato'] == 'Compraventa':
            try:
                prop = db.query(
                    "SELECT id_asesor FROM Propiedades WHERE id_propiedad=%s",
                    (f['id_propiedad'],), one=True)
                if prop and prop['id_asesor']:
                    monto_comision = float(f['monto_total']) * 0.03
                    db.execute(
                        """INSERT INTO Comisiones
                           (id_contrato, id_asesor, porcentaje, monto_comision)
                           VALUES (%s,%s,%s,%s)""",
                        (nid, prop['id_asesor'], 3.0, monto_comision))
            except Exception:
                pass

        log_accion('Contratos', 'INSERT', f"Contrato compraventa #{nid}")
        flash(f'Contrato generado #{nid} — propiedad marcada como Vendida', 'success')

    return redirect(url_for('contratos'))


@app.route('/contratos/gestoria', methods=['POST'])
@login_required
@rol_requerido('contratos')
def nueva_gestoria():
    f = request.form

    if f.get('estatus_tramite') == 'Rechazado' and not f.get('motivo_rechazo','').strip():
        flash('Debes registrar el motivo de rechazo', 'error')
        return redirect(url_for('contratos'))

    db.execute(
        """INSERT INTO Tramites_Bancarios
            (id_contrato, institucion, numero_expediente,
             estatus_tramite, motivo_rechazo, id_usuario)
           VALUES (%s,%s,%s,%s,%s,%s)""",
        (f['id_contrato'], f['institucion'],
         f.get('numero_expediente'), f['estatus_tramite'],
         f.get('motivo_rechazo'), session['id_usuario']))

    log_accion('Contratos', 'INSERT',
               f"Trámite {f['institucion']} para contrato #{f['id_contrato']}: {f['estatus_tramite']}")

    if f['estatus_tramite'] == 'Aprobado':
        flash('Trámite bancario aprobado', 'success')
    elif f['estatus_tramite'] == 'Rechazado':
        flash('Trámite rechazado registrado', 'error')
    else:
        flash('Trámite bancario registrado', 'success')

    return redirect(url_for('contratos'))


@app.route('/contratos/cancelar/<int:id>', methods=['POST'])
@login_required
@rol_requerido('contratos')
def cancelar_contrato(id):
    if session.get('rol') != 'Administrador':
        flash('Solo el Administrador puede cancelar contratos', 'error')
        return redirect(url_for('contratos'))

    contrato = db.query(
        """SELECT id_propiedad, folio, estatus, tipo_contrato
           FROM Contratos WHERE id_contrato=%s""", (id,), one=True)
    if not contrato:
        flash('Contrato no encontrado', 'error')
        return redirect(url_for('contratos'))

    motivo = request.form.get('motivo', 'Cancelación manual')

    db.execute("UPDATE Contratos SET estatus='Cancelado' WHERE id_contrato=%s", (id,))

    db.execute(
        """UPDATE Pagos_Renta SET estatus='Cancelado'
           WHERE id_contrato=%s AND estatus IN ('Pendiente','Atrasado')""", (id,))

    db.execute(
        "UPDATE Propiedades SET estatus='Disponible' WHERE id_propiedad=%s",
        (contrato['id_propiedad'],))
    db.execute(
        """INSERT INTO Historial_Estatus_Propiedad
           (id_propiedad, estatus_anterior, estatus_nuevo, motivo, id_usuario)
           VALUES (%s,%s,%s,%s,%s)""",
        (contrato['id_propiedad'],
         'Vendida' if contrato['tipo_contrato'] == 'Compraventa' else 'Apartada',
         'Disponible',
         f'Contrato {contrato["folio"]} cancelado: {motivo}',
         session['id_usuario']))

    log_accion('Contratos', 'UPDATE', f"Contrato {contrato['folio']} cancelado: {motivo}")
    flash(f'Contrato {contrato["folio"]} cancelado correctamente', 'success')
    return redirect(url_for('contratos'))

# ══════════════════════════════════════════════════════════════
#  PAGOS  OBJ-04
# ══════════════════════════════════════════════════════════════

UPLOAD_COMPROBANTES = os.path.join('static', 'uploads', 'comprobantes')
ALLOWED_COMPROBANTE = {'jpg', 'jpeg', 'png', 'webp', 'pdf'}

def comprobante_permitido(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_COMPROBANTE

def guardar_comprobante(archivo, prefijo):
    if not archivo or archivo.filename == '':
        return None
    if not comprobante_permitido(archivo.filename):
        return None
    archivo.seek(0, os.SEEK_END)
    tamanio = archivo.tell()
    archivo.seek(0)
    if tamanio > 15 * 1024 * 1024:
        return None
    os.makedirs(UPLOAD_COMPROBANTES, exist_ok=True)
    ext        = archivo.filename.rsplit('.', 1)[1].lower()
    nombre_uid = f"{prefijo}_{uuid.uuid4().hex[:10]}.{ext}"
    ruta_disco = os.path.join(UPLOAD_COMPROBANTES, nombre_uid)
    archivo.save(ruta_disco)
    return f"/static/uploads/comprobantes/{nombre_uid}"


@app.route('/pagos')
@login_required
@rol_requerido('pagos')
def pagos():
    filtro_pago = request.args.get('filtro_pago', 'Todos')
    filtro_dep  = request.args.get('filtro_dep',  'Todos')

    sql_pagos = """SELECT pr.id_pago, pr.mes_correspondiente,
                          pr.monto_esperado, pr.monto_recibido,
                          pr.fecha_limite, pr.fecha_pago,
                          pr.dias_retraso, pr.estatus, pr.comprobante,
                          ct.folio, ct.id_contrato,
                          cl.nombre AS cliente, cl.telefono,
                          p.nombre  AS propiedad
                   FROM Pagos_Renta pr
                   JOIN Contratos ct ON ct.id_contrato = pr.id_contrato
                   JOIN Clientes  cl ON cl.id_cliente  = ct.id_cliente
                   JOIN Propiedades p ON p.id_propiedad = ct.id_propiedad
                   WHERE 1=1"""
    params_pagos = []
    if filtro_pago != 'Todos':
        sql_pagos += " AND pr.estatus=%s"
        params_pagos.append(filtro_pago)
    sql_pagos += " ORDER BY pr.fecha_limite DESC"
    pagos_l = db.query(sql_pagos, params_pagos)

    sql_dep = """SELECT d.*, p.nombre AS propiedad, cl.nombre AS cliente,
                        u.nombre AS registrado_por_nombre,
                        uv.nombre AS validado_por_nombre
                 FROM Depositos d
                 JOIN Propiedades p ON p.id_propiedad = d.id_propiedad
                 JOIN Clientes   cl ON cl.id_cliente  = d.id_cliente
                 JOIN Usuarios   u  ON u.id_usuario   = d.registrado_por
                 LEFT JOIN Usuarios uv ON uv.id_usuario = d.validado_por
                 WHERE 1=1"""
    params_dep = []
    if filtro_dep == 'Validados':
        sql_dep += " AND d.validado = 1"
    elif filtro_dep == 'Pendientes':
        sql_dep += " AND d.validado = 0"
    sql_dep += " ORDER BY d.fecha_registro DESC"
    depositos_l = db.query(sql_dep, params_dep)

    kpis_pagos = db.query(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN estatus='Completado' THEN 1 ELSE 0 END) AS completados,
                  SUM(CASE WHEN estatus='Pendiente' THEN 1 ELSE 0 END) AS pendientes,
                  SUM(CASE WHEN estatus='Atrasado' THEN 1 ELSE 0 END) AS atrasados,
                  SUM(CASE WHEN estatus='Completado' THEN monto_recibido ELSE 0 END) AS monto_cobrado,
                  SUM(CASE WHEN estatus IN ('Pendiente','Atrasado') THEN monto_esperado ELSE 0 END) AS monto_pendiente
           FROM Pagos_Renta""", one=True)

    kpis_deps = db.query(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN validado=1 THEN 1 ELSE 0 END) AS validados,
                  SUM(CASE WHEN validado=0 THEN 1 ELSE 0 END) AS pendientes,
                  SUM(monto) AS monto_total
           FROM Depositos""", one=True)

    contratos_l = db.query(
        """SELECT ct.id_contrato, ct.folio, cl.nombre AS cliente
           FROM Contratos ct
           JOIN Clientes cl ON cl.id_cliente = ct.id_cliente
           WHERE ct.estatus='Activo' AND ct.tipo_contrato='Arrendamiento'
           ORDER BY ct.folio""")
    props_l = db.query(
        "SELECT id_propiedad, nombre, precio_venta, precio_renta FROM Propiedades WHERE estatus='Disponible'")
    clientes_l = db.query(
        "SELECT id_cliente, nombre FROM Clientes WHERE activo=1 ORDER BY nombre")

    # Marcar pagos atrasados automáticamente y actualizar días de retraso
    db.execute(
        """UPDATE Pagos_Renta
           SET estatus='Atrasado',
               dias_retraso=DATEDIFF(CURDATE(), fecha_limite)
           WHERE estatus='Pendiente' AND fecha_limite < CURDATE()""")

    return render_template('pagos.html',
        pagos=pagos_l, depositos=depositos_l,
        contratos=contratos_l, propiedades=props_l, clientes=clientes_l,
        kpis_pagos=kpis_pagos, kpis_deps=kpis_deps,
        filtro_pago=filtro_pago, filtro_dep=filtro_dep)


@app.route('/pagos/registrar', methods=['POST'])
@login_required
@rol_requerido('pagos')
def registrar_pago():
    f = request.form
    pago = db.query(
        """SELECT pr.monto_esperado, pr.estatus,
                  ct.folio, cl.nombre AS cliente
           FROM Pagos_Renta pr
           JOIN Contratos ct ON ct.id_contrato = pr.id_contrato
           JOIN Clientes cl ON cl.id_cliente = ct.id_cliente
           WHERE pr.id_pago=%s""", (f['id_pago'],), one=True)

    if not pago:
        flash('Pago no encontrado','error')
        return redirect(url_for('pagos'))

    if pago['estatus'] == 'Completado':
        flash('Este pago ya fue registrado anteriormente','error')
        return redirect(url_for('pagos'))

    try:
        monto_rec = float(f['monto_recibido'])
        monto_esp = float(pago['monto_esperado'])
        if monto_rec <= 0:
            flash('El monto debe ser mayor a cero', 'error')
            return redirect(url_for('pagos'))
    except ValueError:
        flash('Monto inválido', 'error')
        return redirect(url_for('pagos'))

    est = 'Completado' if monto_rec >= monto_esp else 'Parcial'

    ruta_comprobante = None
    if 'comprobante' in request.files:
        ruta_comprobante = guardar_comprobante(
            request.files['comprobante'],
            f"pago_{f['id_pago']}")

    if ruta_comprobante:
        db.execute(
            """UPDATE Pagos_Renta SET monto_recibido=%s, fecha_pago=NOW(),
               estatus=%s, registrado_por=%s, fecha_registro=NOW(),
               comprobante=%s
               WHERE id_pago=%s""",
            (monto_rec, est, session['id_usuario'], ruta_comprobante, f['id_pago']))
    else:
        db.execute(
            """UPDATE Pagos_Renta SET monto_recibido=%s, fecha_pago=NOW(),
               estatus=%s, registrado_por=%s, fecha_registro=NOW()
               WHERE id_pago=%s""",
            (monto_rec, est, session['id_usuario'], f['id_pago']))

    log_accion('Pagos', 'UPDATE',
               f"Pago {pago['folio']} de {pago['cliente']}: ${monto_rec:,.2f} ({est})")

    if est == 'Completado':
        flash(f' Pago completado — ${monto_rec:,.2f} de {pago["cliente"]}','success')
    else:
        flash(f' Pago parcial registrado — faltan ${monto_esp - monto_rec:,.2f}','error')
    return redirect(url_for('pagos'))


@app.route('/pagos/deposito', methods=['POST'])
@login_required
@rol_requerido('pagos')
def nuevo_deposito():
    f = request.form
    prop = db.query(
        "SELECT estatus, nombre FROM Propiedades WHERE id_propiedad=%s",
        (f['id_propiedad'],), one=True)

    if not prop:
        flash('Propiedad no encontrada', 'error')
        return redirect(url_for('pagos'))
    if prop['estatus'] != 'Disponible':
        flash(f' La propiedad "{prop["nombre"]}" ya está {prop["estatus"]}', 'error')
        return redirect(url_for('pagos'))

    try:
        monto = float(f['monto'])
        if monto <= 0:
            flash('El monto debe ser mayor a cero', 'error')
            return redirect(url_for('pagos'))
    except ValueError:
        flash('Monto inválido', 'error')
        return redirect(url_for('pagos'))

    ruta_comprobante = None
    if 'comprobante' in request.files:
        ruta_comprobante = guardar_comprobante(
            request.files['comprobante'], 'dep')

    nid = db.execute(
        """INSERT INTO Depositos
            (id_propiedad, id_cliente, monto, fecha_deposito,
             validado, registrado_por, notas, comprobante)
           VALUES (%s,%s,%s,%s,0,%s,%s,%s)""",
        (f['id_propiedad'], f['id_cliente'], monto, f['fecha'],
         session['id_usuario'], f.get('notas'), ruta_comprobante))

    db.execute("UPDATE Propiedades SET estatus='Apartada' WHERE id_propiedad=%s",
               (f['id_propiedad'],))
    db.execute(
        """INSERT INTO Historial_Estatus_Propiedad
           (id_propiedad, estatus_anterior, estatus_nuevo, motivo, id_usuario)
           VALUES (%s,%s,%s,%s,%s)""",
        (f['id_propiedad'], 'Disponible', 'Apartada',
         f'Depósito #{nid} registrado', session['id_usuario']))

    log_accion('Pagos', 'INSERT', f"Depósito #{nid} de ${monto:,.2f}")
    flash(f' Depósito de ${monto:,.2f} registrado — propiedad apartada','success')
    return redirect(url_for('pagos'))


@app.route('/pagos/validar/<int:id>', methods=['POST'])
@login_required
@rol_requerido('pagos')
def validar_deposito(id):
    if session.get('rol') != 'Administrador':
        flash('Solo el Administrador puede validar depósitos', 'error')
        return redirect(url_for('pagos'))

    deposito = db.query(
        """SELECT d.monto, cl.nombre AS cliente, p.nombre AS propiedad
           FROM Depositos d
           JOIN Clientes cl ON cl.id_cliente = d.id_cliente
           JOIN Propiedades p ON p.id_propiedad = d.id_propiedad
           WHERE d.id_deposito=%s""", (id,), one=True)
    if not deposito:
        flash('Depósito no encontrado', 'error')
        return redirect(url_for('pagos'))

    db.execute(
        """UPDATE Depositos SET validado=1, validado_por=%s, fecha_validacion=NOW()
           WHERE id_deposito=%s""",
        (session['id_usuario'], id))

    log_accion('Pagos', 'UPDATE',
               f"Depósito #{id} validado: {deposito['cliente']} ${deposito['monto']:,.2f}")
    flash(f' Depósito de {deposito["cliente"]} validado — ya puedes generar el contrato','success')
    return redirect(url_for('pagos'))


@app.route('/pagos/deposito/eliminar/<int:id>', methods=['POST'])
@login_required
@rol_requerido('pagos')
def eliminar_deposito(id):
    deposito = db.query(
        "SELECT id_propiedad, validado FROM Depositos WHERE id_deposito=%s",
        (id,), one=True)

    if not deposito:
        flash('Depósito no encontrado', 'error')
        return redirect(url_for('pagos'))

    if deposito['validado']:
        flash('No se puede eliminar un depósito ya validado', 'error')
        return redirect(url_for('pagos'))

    db.execute("DELETE FROM Depositos WHERE id_deposito=%s", (id,))

    otros = db.query(
        "SELECT COUNT(*) AS n FROM Depositos WHERE id_propiedad=%s",
        (deposito['id_propiedad'],), one=True)
    if otros['n'] == 0:
        db.execute(
            "UPDATE Propiedades SET estatus='Disponible' WHERE id_propiedad=%s",
            (deposito['id_propiedad'],))

    log_accion('Pagos', 'DELETE', f"Depósito #{id} eliminado")
    flash('Depósito eliminado correctamente', 'success')
    return redirect(url_for('pagos'))

# ══════════════════════════════════════════════════════════════
#  REPORTES  OBJ-06
# ══════════════════════════════════════════════════════════════

@app.route('/reportes')
@login_required
@rol_requerido('reportes')
def reportes():
    mes  = int(request.args.get('mes',  date.today().month))
    anio = int(request.args.get('anio', date.today().year))

    kpis = db.query(
        """SELECT
            IFNULL(SUM(ct.monto_total),0) AS ganancias,
            COUNT(ct.id_contrato) AS ventas,
            IFNULL(SUM(c.monto_comision),0) AS comisiones,
            SUM(CASE WHEN ct.tipo_contrato='Compraventa' THEN 1 ELSE 0 END) AS compraventas,
            SUM(CASE WHEN ct.tipo_contrato='Arrendamiento' THEN 1 ELSE 0 END) AS arrendamientos
           FROM Contratos ct
           LEFT JOIN Comisiones c ON c.id_contrato = ct.id_contrato
           WHERE MONTH(ct.fecha_generacion)=%s AND YEAR(ct.fecha_generacion)=%s
             AND ct.estatus IN ('Activo','Finalizado')""",
        (mes, anio), one=True)

    ticket = 0
    if kpis['ventas'] and kpis['ventas'] > 0:
        ticket = float(kpis['ganancias']) / kpis['ventas']

    mes_ant  = mes - 1 if mes > 1 else 12
    anio_ant = anio if mes > 1 else anio - 1
    kpis_ant = db.query(
        """SELECT IFNULL(SUM(monto_total),0) AS ganancias,
                  COUNT(id_contrato) AS ventas
           FROM Contratos
           WHERE MONTH(fecha_generacion)=%s AND YEAR(fecha_generacion)=%s
             AND estatus IN ('Activo','Finalizado')""",
        (mes_ant, anio_ant), one=True)

    delta_ganancias = 0
    delta_ventas = 0
    if kpis_ant['ganancias'] and kpis_ant['ganancias'] > 0:
        delta_ganancias = ((float(kpis['ganancias']) - float(kpis_ant['ganancias'])) / float(kpis_ant['ganancias'])) * 100
    if kpis_ant['ventas'] and kpis_ant['ventas'] > 0:
        delta_ventas = ((kpis['ventas'] - kpis_ant['ventas']) / kpis_ant['ventas']) * 100

    por_asesor = db.query(
        """SELECT u.nombre AS asesor,
                  COUNT(c.id_comision) AS ventas,
                  IFNULL(SUM(c.monto_comision),0) AS comision,
                  IFNULL(SUM(ct.monto_total),0) AS volumen
           FROM Comisiones c
           JOIN Usuarios u   ON u.id_usuario  = c.id_asesor
           JOIN Contratos ct ON ct.id_contrato = c.id_contrato
           WHERE MONTH(ct.fecha_generacion)=%s AND YEAR(ct.fecha_generacion)=%s
           GROUP BY u.id_usuario, u.nombre
           ORDER BY comision DESC""", (mes, anio))

    max_comision = 0.0
    for a in por_asesor:
        if a['comision']:
            val = float(a['comision'])
            if val > max_comision:
                max_comision = val

    captacion = db.query(
        """SELECT origen_captacion, COUNT(*) AS total
           FROM Propiedades
           WHERE origen_captacion IS NOT NULL
           GROUP BY origen_captacion
           ORDER BY total DESC""")

    total_capt = sum([c['total'] for c in captacion]) or 1

    ventas_mes = db.query(
        """SELECT MONTH(fecha_generacion) AS mes,
                  YEAR(fecha_generacion) AS anio,
                  COUNT(*) AS cantidad,
                  IFNULL(SUM(monto_total),0) AS monto
           FROM Contratos
           WHERE fecha_generacion >= DATE_SUB(NOW(), INTERVAL 11 MONTH)
             AND estatus IN ('Activo','Finalizado')
           GROUP BY MONTH(fecha_generacion), YEAR(fecha_generacion)
           ORDER BY anio, mes""")

    max_monto_mes = 1.0
    for v in ventas_mes:
        if v['monto']:
            val = float(v['monto'])
            if val > max_monto_mes:
                max_monto_mes = val

    top_props = db.query(
        """SELECT p.nombre AS propiedad, p.tipo_inmueble,
                  ct.tipo_contrato, ct.monto_total,
                  cl.nombre AS cliente, ct.fecha_generacion
           FROM Contratos ct
           JOIN Propiedades p ON p.id_propiedad = ct.id_propiedad
           JOIN Clientes cl   ON cl.id_cliente  = ct.id_cliente
           WHERE MONTH(ct.fecha_generacion)=%s AND YEAR(ct.fecha_generacion)=%s
             AND ct.estatus IN ('Activo','Finalizado')
           ORDER BY ct.monto_total DESC
           LIMIT 5""", (mes, anio))

    clientes_stats = db.query(
        """SELECT estatus_lead, COUNT(*) AS total
           FROM Clientes WHERE activo = 1
           GROUP BY estatus_lead""")

    inventario = db.query(
        """SELECT estatus, COUNT(*) AS total
           FROM Propiedades
           GROUP BY estatus""")

    tiempo_venta = db.query(
        """SELECT AVG(DATEDIFF(ct.fecha_generacion, p.fecha_registro)) AS dias
           FROM Contratos ct
           JOIN Propiedades p ON p.id_propiedad = ct.id_propiedad
           WHERE ct.tipo_contrato='Compraventa'
             AND MONTH(ct.fecha_generacion)=%s AND YEAR(ct.fecha_generacion)=%s""",
        (mes, anio), one=True)

    nombres_meses = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                     'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']

    return render_template('reportes.html',
        kpis=kpis, ticket=ticket,
        delta_ganancias=delta_ganancias, delta_ventas=delta_ventas,
        por_asesor=por_asesor, max_comision=max_comision,
        captacion=captacion, total_capt=total_capt,
        ventas_mes=ventas_mes, max_monto_mes=max_monto_mes,
        top_props=top_props,
        clientes_stats=clientes_stats, inventario=inventario,
        tiempo_venta=tiempo_venta,
        mes=mes, anio=anio,
        nombre_mes=nombres_meses[mes - 1],
        nombres_meses=nombres_meses)


@app.route('/reportes/exportar')
@login_required
@rol_requerido('reportes')
def exportar_reporte():
    from io import StringIO
    import csv

    mes  = int(request.args.get('mes',  date.today().month))
    anio = int(request.args.get('anio', date.today().year))

    contratos = db.query(
        """SELECT ct.folio, ct.tipo_contrato, ct.fecha_generacion,
                  ct.fecha_inicio, ct.fecha_fin, ct.monto_total, ct.estatus,
                  cl.nombre AS cliente, p.nombre AS propiedad,
                  u.nombre AS asesor,
                  IFNULL(c.monto_comision, 0) AS comision
           FROM Contratos ct
           JOIN Clientes cl   ON cl.id_cliente  = ct.id_cliente
           JOIN Propiedades p ON p.id_propiedad = ct.id_propiedad
           JOIN Usuarios u    ON u.id_usuario   = ct.id_usuario_genera
           LEFT JOIN Comisiones c ON c.id_contrato = ct.id_contrato
           WHERE MONTH(ct.fecha_generacion)=%s AND YEAR(ct.fecha_generacion)=%s
           ORDER BY ct.fecha_generacion""",
        (mes, anio))

    output = StringIO()
    output.write('\ufeff')
    writer = csv.writer(output)

    writer.writerow(['REPORTE INMOBILIARIA EXAUMY'])
    writer.writerow([f'Periodo: {mes}/{anio}'])
    writer.writerow([f'Generado: {datetime.now().strftime("%d/%m/%Y %H:%M")}'])
    writer.writerow([])
    writer.writerow(['Folio','Tipo','Fecha generacion','Fecha inicio','Fecha fin',
                     'Cliente','Propiedad','Asesor','Monto total','Comision','Estatus'])

    total_monto = 0
    total_comision = 0
    for c in contratos:
        writer.writerow([
            c['folio'], c['tipo_contrato'],
            c['fecha_generacion'].strftime('%d/%m/%Y') if c['fecha_generacion'] else '',
            c['fecha_inicio'].strftime('%d/%m/%Y') if c['fecha_inicio'] else '',
            c['fecha_fin'].strftime('%d/%m/%Y') if c['fecha_fin'] else '',
            c['cliente'], c['propiedad'], c['asesor'],
            f"${float(c['monto_total']):,.2f}",
            f"${float(c['comision']):,.2f}",
            c['estatus']
        ])
        total_monto    += float(c['monto_total'])
        total_comision += float(c['comision'])

    writer.writerow([])
    writer.writerow(['','','','','','','','TOTAL', f"${total_monto:,.2f}", f"${total_comision:,.2f}",''])

    log_accion('Reportes', 'EXPORT', f"Exportacion mes {mes}/{anio}")

    response = Response(output.getvalue(), mimetype='text/csv; charset=utf-8')
    response.headers['Content-Disposition'] = f'attachment; filename=Reporte_EXAUMY_{mes:02d}_{anio}.csv'
    return response

# ══════════════════════════════════════════════════════════════
#  USUARIOS  OBJ-07
# ══════════════════════════════════════════════════════════════

@app.route('/usuarios')
@login_required
@rol_requerido('usuarios')
def usuarios():
    filtro = request.args.get('filtro', 'Todos')
    buscar = request.args.get('q', '')

    sql = """SELECT u.id_usuario, u.nombre, u.email, u.telefono,
                    u.estatus, u.ultimo_acceso, u.fecha_registro,
                    u.direccion,
                    r.id_rol, r.nombre_rol AS rol
             FROM Usuarios u JOIN Roles r ON r.id_rol = u.id_rol
             WHERE 1=1"""
    params = []

    if filtro == 'Activos':
        sql += " AND u.estatus='Activo'"
    elif filtro == 'Inactivos':
        sql += " AND u.estatus='Inactivo'"
    elif filtro in ('Administrador', 'Asesor', 'Administrativo'):
        sql += " AND r.nombre_rol=%s"
        params.append(filtro)

    if buscar:
        sql += " AND (u.nombre LIKE %s OR u.email LIKE %s)"
        params += [f'%{buscar}%', f'%{buscar}%']

    sql += " ORDER BY u.estatus DESC, u.nombre"
    personal = db.query(sql, params)

    kpis = db.query(
        """SELECT COUNT(*) AS total,
                  SUM(CASE WHEN estatus='Activo'   THEN 1 ELSE 0 END) AS activos,
                  SUM(CASE WHEN estatus='Inactivo' THEN 1 ELSE 0 END) AS inactivos
           FROM Usuarios""", one=True)

    por_rol = db.query(
        """SELECT r.nombre_rol, COUNT(u.id_usuario) AS total
           FROM Roles r
           LEFT JOIN Usuarios u ON u.id_rol = r.id_rol AND u.estatus='Activo'
           GROUP BY r.id_rol, r.nombre_rol
           ORDER BY r.id_rol""")

    roles = db.query("SELECT id_rol, nombre_rol FROM Roles ORDER BY id_rol")

    permisos_raw = db.query(
        """SELECT r.id_rol, r.nombre_rol, p.modulo,
                  p.puede_crear, p.puede_leer, p.puede_editar, p.puede_borrar
           FROM Permisos p JOIN Roles r ON r.id_rol = p.id_rol
           ORDER BY r.id_rol, p.modulo""")

    permisos = {}
    for p in permisos_raw:
        rol = p['nombre_rol']
        if rol not in permisos:
            permisos[rol] = {'id_rol': p['id_rol'], 'modulos': {}}
        permisos[rol]['modulos'][p['modulo']] = {
            'crear':  p['puede_crear'],
            'leer':   p['puede_leer'],
            'editar': p['puede_editar'],
            'borrar': p['puede_borrar']
        }

    return render_template('usuarios.html',
        personal=personal, roles=roles, permisos=permisos,
        kpis=kpis, por_rol=por_rol,
        filtro=filtro, buscar=buscar)


@app.route('/usuarios/nuevo', methods=['POST'])
@login_required
@rol_requerido('usuarios')
def nuevo_usuario():
    f = request.form

    existe = db.query("SELECT id_usuario FROM Usuarios WHERE email=%s",
                      (f['email'].lower(),), one=True)
    if existe:
        flash(' El correo ya está registrado','error')
        return redirect(url_for('usuarios'))

    if f['password'] != f['password2']:
        flash(' Las contraseñas no coinciden','error')
        return redirect(url_for('usuarios'))

    if len(f['password']) < 5:
        flash('La contraseña debe tener al menos 5 caracteres','error')
        return redirect(url_for('usuarios'))

    db.execute(
        """INSERT INTO Usuarios
            (id_rol, nombre, email, telefono, direccion,
             password_hash, creado_por)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (f['id_rol'], f['nombre'], f['email'].lower(),
         f.get('telefono'), f.get('direccion'),
         hash_password(f['password']), session['id_usuario']))

    log_accion('Usuarios','INSERT', f"Nuevo usuario: {f['email']}")
    flash(f' "{f["nombre"]}" registrado correctamente','success')
    return redirect(url_for('usuarios'))


@app.route('/usuarios/editar/<int:id>', methods=['POST'])
@login_required
@rol_requerido('usuarios')
def editar_usuario(id):
    f = request.form

    existe = db.query(
        "SELECT id_usuario FROM Usuarios WHERE email=%s AND id_usuario<>%s",
        (f['email'].lower(), id), one=True)
    if existe:
        flash(' El correo ya está en uso por otro usuario','error')
        return redirect(url_for('usuarios'))

    sql = """UPDATE Usuarios SET nombre=%s, email=%s, id_rol=%s,
             telefono=%s, direccion=%s"""
    params = [f['nombre'], f['email'].lower(), f['id_rol'],
              f.get('telefono'), f.get('direccion')]

    if f.get('password'):
        if len(f['password']) < 5:
            flash('La contraseña debe tener al menos 5 caracteres','error')
            return redirect(url_for('usuarios'))
        sql += ", password_hash=%s"
        params.append(hash_password(f['password']))

    sql += " WHERE id_usuario=%s"
    params.append(id)
    db.execute(sql, params)

    log_accion('Usuarios','UPDATE', f"Usuario #{id} actualizado")
    flash(' Información actualizada correctamente','success')
    return redirect(url_for('usuarios'))


@app.route('/usuarios/baja/<int:id>', methods=['POST'])
@login_required
@rol_requerido('usuarios')
def baja_usuario(id):
    if id == session['id_usuario']:
        flash(' No puedes dar de baja tu propia cuenta','error')
        return redirect(url_for('usuarios'))
    usuario = db.query("SELECT nombre FROM Usuarios WHERE id_usuario=%s",(id,),one=True)
    db.execute(
        "UPDATE Usuarios SET estatus='Inactivo',fecha_baja=NOW() WHERE id_usuario=%s",(id,))
    log_accion('Usuarios','DELETE',f"Baja  {usuario['nombre']}")
    flash(f' {usuario["nombre"]} dado de baja — acceso revocado inmediatamente','success')
    return redirect(url_for('usuarios'))


@app.route('/usuarios/reactivar/<int:id>', methods=['POST'])
@login_required
@rol_requerido('usuarios')
def reactivar_usuario(id):
    usuario = db.query("SELECT nombre FROM Usuarios WHERE id_usuario=%s",(id,),one=True)
    db.execute("UPDATE Usuarios SET estatus='Activo',fecha_baja=NULL WHERE id_usuario=%s",(id,))
    flash(f' {usuario["nombre"]} reactivado correctamente','success')
    return redirect(url_for('usuarios'))

@app.route('/usuarios/eliminar/<int:id>', methods=['POST'])
@login_required
@rol_requerido('usuarios')
def eliminar_usuario(id):
    # 1. No puedes eliminarte a ti misma
    if id == session['id_usuario']:
        flash('No puedes eliminar tu propia cuenta', 'error')
        return redirect(url_for('usuarios'))

    # 2. Obtener datos del usuario
    usuario = db.query(
        """SELECT u.nombre, u.email, r.nombre_rol
           FROM Usuarios u JOIN Roles r ON r.id_rol = u.id_rol
           WHERE u.id_usuario=%s""", (id,), one=True)

    if not usuario:
        flash('Usuario no encontrado', 'error')
        return redirect(url_for('usuarios'))

    # 3. No se pueden eliminar Administradores
    if usuario['nombre_rol'] == 'Administrador':
        flash('No se pueden eliminar usuarios con rol Administrador', 'error')
        return redirect(url_for('usuarios'))

    # 4. Verificar si tiene datos relacionados
    relaciones = db.query(
        """SELECT
            (SELECT COUNT(*) FROM Propiedades WHERE id_asesor=%s OR creado_por=%s) AS propiedades,
            (SELECT COUNT(*) FROM Clientes    WHERE id_asesor=%s) AS clientes,
            (SELECT COUNT(*) FROM Citas       WHERE id_asesor=%s OR registrado_por=%s) AS citas,
            (SELECT COUNT(*) FROM Contratos   WHERE id_usuario_genera=%s) AS contratos,
            (SELECT COUNT(*) FROM Depositos   WHERE registrado_por=%s OR validado_por=%s) AS depositos,
            (SELECT COUNT(*) FROM Comisiones  WHERE id_asesor=%s) AS comisiones""",
        (id, id, id, id, id, id, id, id, id), one=True)

    total = (relaciones['propiedades'] + relaciones['clientes'] +
             relaciones['citas'] + relaciones['contratos'] +
             relaciones['depositos'] + relaciones['comisiones'])

    if total > 0:
        detalle = []
        if relaciones['propiedades']: detalle.append(f"{relaciones['propiedades']} propiedades")
        if relaciones['clientes']:    detalle.append(f"{relaciones['clientes']} clientes")
        if relaciones['citas']:       detalle.append(f"{relaciones['citas']} citas")
        if relaciones['contratos']:   detalle.append(f"{relaciones['contratos']} contratos")
        if relaciones['depositos']:   detalle.append(f"{relaciones['depositos']} depósitos")
        if relaciones['comisiones']:  detalle.append(f"{relaciones['comisiones']} comisiones")

        flash(f'No se puede eliminar: {usuario["nombre"]} tiene {", ".join(detalle)}. '
              f'Solo se puede dar de baja (Inactivar).', 'error')
        return redirect(url_for('usuarios'))

    # 5. Limpiar registros donde solo es referencia opcional
    db.execute("UPDATE Bitacora_Auditoria SET id_usuario=NULL WHERE id_usuario=%s", (id,))
    db.execute("DELETE FROM Bitacora_Seguimiento WHERE id_usuario=%s", (id,))
    db.execute("DELETE FROM Mensajes_WhatsApp WHERE id_usuario=%s", (id,))
    db.execute("UPDATE Usuarios SET creado_por=NULL WHERE creado_por=%s", (id,))

    # 6. Eliminar el usuario
    nombre = usuario['nombre']
    email = usuario['email']
    db.execute("DELETE FROM Usuarios WHERE id_usuario=%s", (id,))

    log_accion('Usuarios', 'DELETE', f"Eliminado permanentemente: {email}")
    flash(f'Usuario "{nombre}" eliminado permanentemente', 'success')
    return redirect(url_for('usuarios'))

@app.route('/usuarios/permisos/<int:id_rol>', methods=['POST'])
@login_required
@rol_requerido('usuarios')
def actualizar_permisos(id_rol):
    for modulo in ['Propiedades','Clientes','Agenda','Contratos','Pagos','Reportes','Usuarios']:
        db.execute(
            """UPDATE Permisos SET
                puede_crear=%s,puede_leer=%s,puede_editar=%s,puede_borrar=%s
               WHERE id_rol=%s AND modulo=%s""",
            (1 if request.form.get(f'{modulo}_crear')  else 0,
             1 if request.form.get(f'{modulo}_leer')   else 0,
             1 if request.form.get(f'{modulo}_editar') else 0,
             1 if request.form.get(f'{modulo}_borrar') else 0,
             id_rol, modulo))
    log_accion('Usuarios','UPDATE', f"Permisos del rol #{id_rol} actualizados")
    flash(' Privilegios actualizados correctamente','success')
    return redirect(url_for('usuarios'))

# ══════════════════════════════════════════════════════════════
#  MÓDULO FOTOS DE PROPIEDADES  —  RF-08
# ══════════════════════════════════════════════════════════════

UPLOAD_FOLDER = os.path.join('static', 'uploads', 'propiedades')
ALLOWED_EXT   = {'jpg', 'jpeg', 'png', 'webp'}
MAX_SIZE_MB   = 15

def archivo_permitido(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXT


@app.route('/propiedades/<int:id>/fotos', methods=['GET', 'POST'])
@login_required
@rol_requerido('propiedades')
def fotos_propiedad(id):
    if request.method == 'POST':
        if 'foto' not in request.files:
            flash('No se recibió ningún archivo', 'error')
            return redirect(url_for('fotos_propiedad', id=id))

        archivo = request.files['foto']
        if archivo.filename == '':
            flash('No seleccionaste ningún archivo', 'error')
            return redirect(url_for('fotos_propiedad', id=id))

        if not archivo_permitido(archivo.filename):
            flash('Formato no permitido. Solo JPG, PNG o WEBP', 'error')
            return redirect(url_for('fotos_propiedad', id=id))

        archivo.seek(0, os.SEEK_END)
        tamanio = archivo.tell()
        archivo.seek(0)
        if tamanio > MAX_SIZE_MB * 1024 * 1024:
            flash(f'El archivo excede el límite de {MAX_SIZE_MB} MB', 'error')
            return redirect(url_for('fotos_propiedad', id=id))

        os.makedirs(UPLOAD_FOLDER, exist_ok=True)
        ext        = archivo.filename.rsplit('.', 1)[1].lower()
        nombre_uid = f"prop_{id}_{uuid.uuid4().hex[:8]}.{ext}"
        ruta_disco = os.path.join(UPLOAD_FOLDER, nombre_uid)
        archivo.save(ruta_disco)
        ruta_web = f"/static/uploads/propiedades/{nombre_uid}"

        existe = db.query(
            "SELECT COUNT(*) AS n FROM Fotos_Propiedad WHERE id_propiedad=%s",
            (id,), one=True
        )
        es_principal = 1 if existe['n'] == 0 else 0
        descripcion = request.form.get('descripcion', '')

        db.execute(
            """INSERT INTO Fotos_Propiedad
               (id_propiedad, ruta_imagen, descripcion, es_principal, subido_por)
               VALUES (%s,%s,%s,%s,%s)""",
            (id, ruta_web, descripcion, es_principal, session['id_usuario'])
        )
        log_accion('Propiedades', 'INSERT', f"Foto subida a propiedad #{id}")
        flash(' Fotografía subida correctamente', 'success')
        return redirect(url_for('fotos_propiedad', id=id))

    prop = db.query(
        "SELECT id_propiedad, nombre FROM Propiedades WHERE id_propiedad=%s",
        (id,), one=True
    )
    fotos = db.query(
        """SELECT f.*, u.nombre AS usuario
           FROM Fotos_Propiedad f
           JOIN Usuarios u ON u.id_usuario = f.subido_por
           WHERE f.id_propiedad = %s
           ORDER BY f.es_principal DESC, f.fecha_subida DESC""",
        (id,)
    )
    return render_template('fotos_propiedad.html', prop=prop, fotos=fotos)


@app.route('/propiedades/foto/principal/<int:id_foto>', methods=['POST'])
@login_required
@rol_requerido('propiedades')
def marcar_principal(id_foto):
    foto = db.query(
        "SELECT id_propiedad FROM Fotos_Propiedad WHERE id_foto=%s",
        (id_foto,), one=True
    )
    if foto:
        db.execute(
            "UPDATE Fotos_Propiedad SET es_principal=0 WHERE id_propiedad=%s",
            (foto['id_propiedad'],)
        )
        db.execute(
            "UPDATE Fotos_Propiedad SET es_principal=1 WHERE id_foto=%s",
            (id_foto,)
        )
        flash('Foto principal actualizada', 'success')
        return redirect(url_for('fotos_propiedad', id=foto['id_propiedad']))
    return redirect(url_for('propiedades'))


@app.route('/propiedades/foto/eliminar/<int:id_foto>', methods=['POST'])
@login_required
@rol_requerido('propiedades')
def eliminar_foto(id_foto):
    foto = db.query(
        "SELECT id_propiedad, ruta_imagen, es_principal FROM Fotos_Propiedad WHERE id_foto=%s",
        (id_foto,), one=True
    )
    if not foto:
        flash('Foto no encontrada', 'error')
        return redirect(url_for('propiedades'))

    try:
        ruta_fisica = foto['ruta_imagen'].lstrip('/')
        if os.path.exists(ruta_fisica):
            os.remove(ruta_fisica)
    except Exception:
        pass

    db.execute("DELETE FROM Fotos_Propiedad WHERE id_foto=%s", (id_foto,))

    if foto['es_principal']:
        otra = db.query(
            "SELECT id_foto FROM Fotos_Propiedad WHERE id_propiedad=%s ORDER BY fecha_subida LIMIT 1",
            (foto['id_propiedad'],), one=True
        )
        if otra:
            db.execute(
                "UPDATE Fotos_Propiedad SET es_principal=1 WHERE id_foto=%s",
                (otra['id_foto'],)
            )

    flash('Foto eliminada correctamente', 'success')
    return redirect(url_for('fotos_propiedad', id=foto['id_propiedad']))


# ══════════════════════════════════════════════════════════════
#  ARRANQUE DE LA APLICACIÓN
# ══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    app.run(debug=True, port=5000)

