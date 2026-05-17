from pymongo import MongoClient
from pymongo.errors import ConnectionFailure, OperationFailure
from werkzeug.security import generate_password_hash, check_password_hash
import warnings
import os
from typing import Dict, List, Optional

LOCAL_MONGO_URI = 'mongodb://localhost:27017/'

class MongoDB:
    def __init__(self, uri: str = None, db_name: str = None):
        """Inicializa conexión a MongoDB.

        Si no se proporciona uri, usa la instancia local (localhost:27017).
        La base de datos y las colecciones se crean automáticamente por MongoDB
        en la primera operación de escritura; este constructor solo advierte si
        aún no existen.
        """
        env_uri = os.getenv('MONGO_URI')
        env_db_name = os.getenv('MONGO_DB', 'bigdataapp')
        self.default_collection = os.getenv('MONGO_COLECCION', 'usuario_roles')

        effective_uri = uri or env_uri or LOCAL_MONGO_URI
        db_name = db_name or env_db_name
        if not uri:
            warnings.warn(
                f"MONGO_URI no configurado explícitamente. Usando URI: {effective_uri}",
                UserWarning,
                stacklevel=2,
            )

        # serverSelectionTimeoutMS evita que la app se bloquee si MongoDB no está activo
        self.client = MongoClient(effective_uri, serverSelectionTimeoutMS=5000)
        self.db = self.client[db_name]
        self.uri = effective_uri

        # Validar la conexión de inmediato para detectar problemas al arrancar
        if not self.test_connection(log=False):
            raise ConnectionFailure(
                f"No se pudo conectar a MongoDB en '{effective_uri}'. "
                "Verifique que el servicio esté activo (Get-Service -Name MongoDB)."
            )

    def test_connection(self, log: bool = True) -> bool:
        """Prueba la conexión a MongoDB y registra el entorno detectado."""
        entorno = "Local" if any(h in self.uri.lower() for h in ('localhost', '127.0.0.1')) else "Atlas (Cloud)"
        try:
            self.client.admin.command('ping')
            if log:
                print(f"✅ MongoDB {entorno}: Conectado")
            return True
        except ConnectionFailure as e:
            if log:
                print(f"❌ MongoDB {entorno}: Error al conectar -> {e}")
            return False

    def verificar_colecciones(self, *nombres_coleccion: str) -> None:
        """Advierte si alguna de las colecciones indicadas no existe todavía en la base de datos.

        MongoDB crea las colecciones en la primera escritura, por lo que este método
        es puramente informativo: registra un aviso para que el desarrollador sepa
        que la colección se creará cuando se inserte el primer documento.
        """
        existentes = self.db.list_collection_names()
        for nombre in nombres_coleccion:
            if nombre not in existentes:
                warnings.warn(
                    f"[MongoDB] La colección '{nombre}' no existe en '{self.db.name}'. "
                    "Se creará automáticamente en la primera operación de escritura.",
                    UserWarning,
                    stacklevel=2,
                )
    
    def validar_usuario(self, usuario: str, password: str, coleccion: str) -> Optional[Dict]:
        """Valida usuario y contraseña con hash werkzeug"""
        try:
            user = self.db[coleccion].find_one({'usuario': usuario})
            if user and check_password_hash(user.get('password', ''), password):
                return user
            return None
        except Exception as e:
            print(f"Error al validar usuario: {e}")
            return None
    
    def obtener_usuario(self, usuario: str, coleccion: str) -> Optional[Dict]:
        """Obtiene información de un usuario"""
        try:
            return self.db[coleccion].find_one({'usuario': usuario})
        except Exception as e:
            print(f"Error al obtener usuario: {e}")
            return None
    
    def listar_usuarios(self, coleccion: str) -> List[Dict]:
        """Lista todos los usuarios"""
        try:
            return list(self.db[coleccion].find({}))
        except Exception as e:
            print(f"Error al listar usuarios: {e}")
            return []
    
    def crear_usuario(self, usuario: str, password: str, permisos: Dict, coleccion: str) -> bool:
        """Crea un nuevo usuario con contraseña encriptada"""
        try:
            documento = {
                'usuario': usuario,
                'password': generate_password_hash(password),
                'permisos': permisos
            }
            self.db[coleccion].insert_one(documento)
            return True
        except Exception as e:
            print(f"Error al crear usuario: {e}")
            return False
    
    def actualizar_usuario(self, usuario: str, nuevos_datos: Dict, coleccion: str) -> bool:
        """Actualiza un usuario existente"""
        try:
            if 'password' in nuevos_datos:
                nuevos_datos['password'] = generate_password_hash(nuevos_datos['password'])
            self.db[coleccion].update_one(
                {'usuario': usuario},
                {'$set': nuevos_datos}
            )
            return True
        except Exception as e:
            print(f"Error al actualizar usuario: {e}")
            return False
    
    def eliminar_usuario(self, usuario: str, coleccion: str) -> bool:
        """Elimina un usuario"""
        try:
            resultado = self.db[coleccion].delete_one({'usuario': usuario})
            return resultado.deleted_count > 0
        except Exception as e:
            print(f"Error al eliminar usuario: {e}")
            return False
    
    def close(self):
        """Cierra la conexión"""
        self.client.close()