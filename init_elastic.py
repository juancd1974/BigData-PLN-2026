"""
Script de inicializacion de Elasticsearch.

Crea el indice principal de la aplicacion con settings y mappings base.

Uso:
    python init_elastic.py

Opcional (recrear indice):
    python init_elastic.py --recreate

El script es idempotente: si el indice ya existe, no realiza cambios,
a menos que se use --recreate.
"""

import argparse
import os
import sys

from dotenv import load_dotenv
from elasticsearch import Elasticsearch
from elasticsearch import exceptions as es_exceptions


load_dotenv()

ELASTIC_URL = os.getenv("ELASTIC_URL", "http://localhost:9200")
ELASTIC_USER = os.getenv("ELASTIC_USER", "elastic")
ELASTIC_PASSWORD = os.getenv("ELASTIC_PASSWORD", "")
ELASTIC_INDEX_DEFAULT = os.getenv("ELASTIC_INDEX_DEFAULT", "index_minagricultura")
ELASTIC_REQUEST_TIMEOUT = int(os.getenv("ELASTIC_REQUEST_TIMEOUT", "20"))


def build_client() -> Elasticsearch:
    if ELASTIC_PASSWORD:
        return Elasticsearch(
            ELASTIC_URL,
            basic_auth=(ELASTIC_USER, ELASTIC_PASSWORD),
            verify_certs=False,
            ssl_show_warn=False,
        )

    return Elasticsearch(
        ELASTIC_URL,
        verify_certs=False,
        ssl_show_warn=False,
    )


def index_definition() -> dict:
    return {
        "settings": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "analysis": {
                "analyzer": {
                    "spanish_text": {
                        "tokenizer": "standard",
                        "filter": [
                            "lowercase",
                            "asciifolding",
                            "spanish_stop",
                            "spanish_stemmer",
                        ],
                    }
                },
                "filter": {
                    "spanish_stop": {
                        "type": "stop",
                        "stopwords": "_spanish_",
                    },
                    "spanish_stemmer": {
                        "type": "stemmer",
                        "language": "light_spanish",
                    },
                },
            },
        },
        "mappings": {
            "properties": {
                "texto": {
                    "type": "text",
                    "analyzer": "spanish_text",
                },
                "resumen": {
                    "type": "text",
                    "analyzer": "spanish_text",
                },
                "titulo_norma": {
                    "type": "text",
                    "analyzer": "spanish_text",
                },
                "tipo_norma": {"type": "keyword"},
                "numero_norma": {"type": "integer"},
                "anio_norma": {"type": "integer"},
                "entidad_emisora": {"type": "keyword"},
                "fecha_documento": {
                    "type": "date",
                    "format": "yyyy-MM-dd||dd-MM-yyyy||yyyy/MM/dd||strict_date_optional_time",
                },
                "fecha_carga": {"type": "date"},
                "ruta": {"type": "keyword"},
                "nombre_archivo": {"type": "keyword"},
                "hash_archivo": {"type": "keyword"},
                "entidades": {
                    "properties": {
                        "personas": {"type": "keyword"},
                        "lugares": {"type": "keyword"},
                        "organizaciones": {"type": "keyword"},
                        "fechas": {"type": "keyword"},
                        "leyes": {"type": "keyword"},
                        "otros": {"type": "keyword"},
                    }
                },
                "temas": {
                    "type": "nested",
                    "properties": {
                        "palabra": {"type": "keyword"},
                        "relevancia": {"type": "float"},
                    },
                },
            }
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Inicializa el indice principal en Elasticsearch")
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="Elimina y vuelve a crear el indice si ya existe",
    )
    args = parser.parse_args()

    print(f"[init_elastic] Conectando a Elasticsearch -> {ELASTIC_URL}")
    print(f"[init_elastic] Indice objetivo -> {ELASTIC_INDEX_DEFAULT}")

    client = build_client()

    try:
        if not client.ping(request_timeout=5):
            print("[init_elastic] ERROR: Elasticsearch no responde al ping.")
            sys.exit(1)

        exists = client.indices.exists(index=ELASTIC_INDEX_DEFAULT, request_timeout=ELASTIC_REQUEST_TIMEOUT)

        if exists and not args.recreate:
            print("[init_elastic] El indice ya existe. No se realizaron cambios.")
            return

        if exists and args.recreate:
            print("[init_elastic] Eliminando indice existente...")
            client.indices.delete(index=ELASTIC_INDEX_DEFAULT, request_timeout=ELASTIC_REQUEST_TIMEOUT)

        print("[init_elastic] Creando indice...")
        definition = index_definition()
        client.indices.create(
            index=ELASTIC_INDEX_DEFAULT,
            settings=definition["settings"],
            mappings=definition["mappings"],
            request_timeout=ELASTIC_REQUEST_TIMEOUT,
        )

        print("[init_elastic] Indice creado correctamente.")

    except es_exceptions.AuthenticationException as exc:
        print(f"[init_elastic] ERROR de autenticacion: {exc}")
        sys.exit(1)
    except es_exceptions.ConnectionError as exc:
        print(f"[init_elastic] ERROR de conexion: {exc}")
        sys.exit(1)
    except Exception as exc:
        print(f"[init_elastic] ERROR inesperado: {exc}")
        sys.exit(1)
    finally:
        client.close()


if __name__ == "__main__":
    main()
