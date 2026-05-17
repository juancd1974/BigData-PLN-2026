"""
Bootstrap de inicialización para NormaSearch.

Ejecuta en orden:
  1) inicializar_mongodb()       — crea el usuario administrador inicial
  2) inicializar_elasticsearch() — crea el índice principal con mappings y analyzers

Uso:
    python init_all.py

Opcional (recrear índice de Elasticsearch):
    python init_all.py --recreate-elastic

El script es idempotente: si los recursos ya existen, no realiza cambios,
salvo que se use --recreate-elastic.
"""

import argparse
import os
import sys

from dotenv import load_dotenv

load_dotenv()

# ── Configuración MongoDB ────────────────────────────────────────────────────
MONGO_URI             = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
MONGO_DB              = os.getenv('MONGO_DB', 'bigdataapp')
MONGO_COLECCION       = os.getenv('MONGO_COLECCION', 'usuario_roles')
APP_USER_ADMIN        = os.getenv('APP_USER_ADMIN')
APP_USER_ADMIN_PASSWORD = os.getenv('APP_USER_ADMIN_PASSWORD')

# ── Configuración Elasticsearch ──────────────────────────────────────────────
ELASTIC_URL             = os.getenv('ELASTIC_URL', 'http://localhost:9200')
ELASTIC_USER            = os.getenv('ELASTIC_USER', 'elastic')
ELASTIC_PASSWORD        = os.getenv('ELASTIC_PASSWORD', '')
ELASTIC_INDEX_DEFAULT   = os.getenv('ELASTIC_INDEX_DEFAULT', 'index_minagricultura')
ELASTIC_REQUEST_TIMEOUT = int(os.getenv('ELASTIC_REQUEST_TIMEOUT', '20'))


# ── MongoDB ───────────────────────────────────────────────────────────────────

def inicializar_mongodb() -> None:
    """
    Crea las colecciones necesarias e inserta el usuario administrador inicial.

    Lee credenciales desde .env (APP_USER_ADMIN, APP_USER_ADMIN_PASSWORD).
    Idempotente: si el usuario ya existe, no realiza cambios.
    """
    from pymongo import MongoClient
    from pymongo.errors import ConnectionFailure
    from werkzeug.security import generate_password_hash

    if not APP_USER_ADMIN or not APP_USER_ADMIN_PASSWORD:
        print("[init] ERROR: APP_USER_ADMIN y APP_USER_ADMIN_PASSWORD deben estar en .env")
        sys.exit(1)

    print(f"[init] MongoDB → {MONGO_URI} | DB: {MONGO_DB}")

    try:
        client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
        client.admin.command('ping')
    except ConnectionFailure as exc:
        print(f"[init] ERROR: No se pudo conectar a MongoDB: {exc}")
        sys.exit(1)

    coleccion = client[MONGO_DB][MONGO_COLECCION]

    if coleccion.find_one({'usuario': APP_USER_ADMIN}):
        print(f"[init] Usuario '{APP_USER_ADMIN}' ya existe. Sin cambios.")
        client.close()
        return

    coleccion.insert_one({
        'usuario':  APP_USER_ADMIN,
        'password': generate_password_hash(APP_USER_ADMIN_PASSWORD),
        'permisos': {
            'admin_usuarios':     True,
            'admin_elastic':      True,
            'admin_data_elastic': True,
        },
    })

    print(f"[init] ✓ Usuario '{APP_USER_ADMIN}' creado en '{MONGO_DB}.{MONGO_COLECCION}'.")
    print("[init]   IMPORTANTE: cambie la contraseña después del primer acceso.")
    client.close()


# ── Elasticsearch ─────────────────────────────────────────────────────────────

def _build_es_client():
    """Construye el cliente Elasticsearch según las variables de entorno."""
    from elasticsearch import Elasticsearch
    kwargs = dict(verify_certs=False, ssl_show_warn=False)
    if ELASTIC_PASSWORD:
        kwargs['basic_auth'] = (ELASTIC_USER, ELASTIC_PASSWORD)
    return Elasticsearch(ELASTIC_URL, **kwargs)


def _index_definition() -> dict:
    """Devuelve settings y mappings del índice normativo."""
    return {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "analyzer": {
                    "spanish_text": {
                        "tokenizer": "standard",
                        "filter": ["lowercase", "asciifolding", "spanish_stop", "spanish_stemmer"],
                    }
                },
                "filter": {
                    "spanish_stop":    {"type": "stop",    "stopwords": "_spanish_"},
                    "spanish_stemmer": {"type": "stemmer", "language": "light_spanish"},
                },
            },
        },
        "mappings": {
            "properties": {
                "texto":          {"type": "text",    "analyzer": "spanish_text"},
                "resumen":        {"type": "text",    "analyzer": "spanish_text"},
                "titulo_norma":   {"type": "text",    "analyzer": "spanish_text"},
                "tipo_norma":     {"type": "keyword"},
                "numero_norma":   {"type": "integer"},
                "anio_norma":     {"type": "integer"},
                "entidad_emisora":{"type": "keyword"},
                "fecha_documento": {
                    "type": "date",
                    "format": "yyyy-MM-dd||dd-MM-yyyy||yyyy/MM/dd||strict_date_optional_time",
                },
                "fecha_carga":    {"type": "date"},
                "ruta":           {"type": "keyword"},
                "nombre_archivo": {"type": "keyword"},
                "hash_archivo":   {"type": "keyword"},
                "entidades": {
                    "properties": {
                        "personas":       {"type": "keyword"},
                        "lugares":        {"type": "keyword"},
                        "organizaciones": {"type": "keyword"},
                        "fechas":         {"type": "keyword"},
                        "leyes":          {"type": "keyword"},
                        "otros":          {"type": "keyword"},
                    }
                },
                "temas": {
                    "type": "nested",
                    "properties": {
                        "palabra":     {"type": "keyword"},
                        "relevancia":  {"type": "float"},
                    },
                },
            }
        },
    }


def inicializar_elasticsearch(recrear: bool = False) -> None:
    """
    Crea el índice principal con settings y mappings en Elasticsearch.

    Args:
        recrear: Si True, elimina el índice existente antes de recrearlo.

    Idempotente: si el índice ya existe y recrear=False, no realiza cambios.
    """
    from elasticsearch import exceptions as es_exceptions

    print(f"[init] Elasticsearch → {ELASTIC_URL} | Índice: {ELASTIC_INDEX_DEFAULT}")

    client = _build_es_client()

    try:
        if not client.ping(request_timeout=5):
            print("[init] ERROR: Elasticsearch no responde al ping.")
            sys.exit(1)

        exists = client.indices.exists(
            index=ELASTIC_INDEX_DEFAULT, request_timeout=ELASTIC_REQUEST_TIMEOUT
        )

        if exists and not recrear:
            print("[init] Índice ya existe. Sin cambios. Usa --recreate-elastic para forzar.")
            return

        if exists and recrear:
            print("[init] Eliminando índice existente...")
            client.indices.delete(
                index=ELASTIC_INDEX_DEFAULT, request_timeout=ELASTIC_REQUEST_TIMEOUT
            )

        definition = _index_definition()
        client.indices.create(
            index=ELASTIC_INDEX_DEFAULT,
            settings=definition["settings"],
            mappings=definition["mappings"],
            request_timeout=ELASTIC_REQUEST_TIMEOUT,
        )
        print(f"[init] ✓ Índice '{ELASTIC_INDEX_DEFAULT}' creado correctamente.")

    except es_exceptions.AuthenticationException as exc:
        print(f"[init] ERROR de autenticación: {exc}")
        sys.exit(1)
    except es_exceptions.ConnectionError as exc:
        print(f"[init] ERROR de conexión: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"[init] ERROR inesperado: {exc}")
        sys.exit(1)
    finally:
        client.close()


# ── Orquestador ───────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Inicializa MongoDB y Elasticsearch para NormaSearch")
    parser.add_argument(
        "--recreate-elastic",
        action="store_true",
        help="Elimina y vuelve a crear el índice de Elasticsearch si ya existe",
    )
    args = parser.parse_args()

    print("\n" + "=" * 55)
    print("  NormaSearch — Inicialización del entorno")
    print("=" * 55)

    print("\n[Paso 1/2] Inicializando MongoDB...")
    inicializar_mongodb()

    print("\n[Paso 2/2] Inicializando Elasticsearch...")
    inicializar_elasticsearch(recrear=args.recreate_elastic)

    print("\n[init] ✓ Inicialización completada correctamente.")
    print("=" * 55 + "\n")


if __name__ == "__main__":
    main()
