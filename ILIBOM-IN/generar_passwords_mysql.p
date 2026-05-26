"""
Encripta las contraseñas de los usuarios con bcrypt.
Ejecuta este script UNA VEZ después de crear la BD.
"""
import bcrypt
import mysql.connector

# Conectar a MySQL
conn = mysql.connector.connect(
    host='localhost',
    user='root',
    password='Jazmin2005',
    database='ILIBOM_IN'
)
cursor = conn.cursor(dictionary=True)

# Buscar usuarios sin hash bcrypt
cursor.execute("SELECT id_usuario, email, password_hash FROM Usuarios")
usuarios = cursor.fetchall()

print(f"\n🔐 Encriptando contraseñas de {len(usuarios)} usuarios...\n")

for u in usuarios:
    # Si el hash NO empieza con $2 (formato bcrypt), lo encripta
    if not u['password_hash'].startswith('$2'):
        password_plano = u['password_hash']
        hash_bcrypt = bcrypt.hashpw(password_plano.encode(), bcrypt.gensalt()).decode()

        cursor.execute(
            "UPDATE Usuarios SET password_hash=%s WHERE id_usuario=%s",
            (hash_bcrypt, u['id_usuario'])
        )
        print(f"  ✅ {u['email']:30s}  →  encriptado")
    else:
        print(f"  ⏭️  {u['email']:30s}  →  ya estaba encriptado")

conn.commit()
cursor.close()
conn.close()

print("\n✅ ¡Listo! Todas las contraseñas están encriptadas.")
print("    Puedes hacer login con: 12345")