"""
db.py — Conexión a MySQL para ILIBOM-IN
Inmobiliaria EXAUMY
"""
import os
import mysql.connector
from mysql.connector import pooling

_pool = None


def init_app(app):
    """Inicializa el pool de conexiones MySQL."""
    global _pool
    _pool = pooling.MySQLConnectionPool(
        pool_name="ilibom_pool",
        pool_size=5,
        host=os.getenv('DB_SERVER', 'localhost'),
        port=int(os.getenv('DB_PORT', 3306)),
        user=os.getenv('DB_USER', 'root'),
        password=os.getenv('DB_PASSWORD', ''),
        database=os.getenv('DB_NAME', 'ILIBOM_IN'),
        charset='utf8mb4',
        collation='utf8mb4_spanish_ci',
        autocommit=False
    )


def _get_conn():
    """Obtiene una conexión del pool."""
    return _pool.get_connection()


def query(sql, params=None, one=False):
    """
    Ejecuta una consulta SELECT y devuelve los resultados como lista de dicts.
    - one=True devuelve solo el primer registro (o None)
    - params puede ser una tupla o lista
    """
    conn = _get_conn()
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params or ())
        if one:
            row = cursor.fetchone()
            cursor.close()
            return row
        rows = cursor.fetchall()
        cursor.close()
        return rows
    finally:
        conn.close()


def execute(sql, params=None):
    """
    Ejecuta INSERT/UPDATE/DELETE.
    Devuelve el ID del registro insertado (lastrowid).
    """
    conn = _get_conn()
    try:
        cursor = conn.cursor()
        cursor.execute(sql, params or ())
        last_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        return last_id
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()