from elasticsearch import Elasticsearch
from typing import Dict, List, Optional, Any
import glob
import json
import os
import subprocess
import time
from datetime import datetime
import requests
from requests.exceptions import ConnectionError as RequestsConnectionError, RequestException

class ElasticSearch:
    def __init__(self, elastic_url: Optional[str] = None, elastic_user: Optional[str] = None, elastic_password: Optional[str] = None):
        """
        Inicializa conexión a ElasticSearch local o remota
        
        Args:
            elastic_url: URL de ElasticSearch
            elastic_user: Usuario para autenticación básica
            elastic_password: Contraseña para autenticación básica
        """
        elastic_url = elastic_url or os.getenv('ELASTIC_URL', 'http://localhost:9200')
        elastic_user = elastic_user or os.getenv('ELASTIC_USER', 'elastic')
        elastic_password = elastic_password or os.getenv('ELASTIC_PASSWORD', '')

        # verify_certs y ssl_show_warn solo aplican si el esquema es https
        # Con http:// el cliente los ignora sin error
        self.client = Elasticsearch(
            elastic_url,
            basic_auth=(elastic_user, elastic_password),
            verify_certs=False,
            ssl_show_warn=False
        )
        self.url = elastic_url
        
    def test_connection(self) -> bool:
        """Prueba la conexión a Elasticsearch y muestra el entorno detectado"""
        try:
            info = self.client.info()
            entorno = "Local" if any(h in self.url for h in ('localhost', '127.0.0.1')) else "Cloud"
            print(f"✅ Elasticsearch {entorno}: Conectado (v{info['version']['number']})")
            return True
        except Exception as e:
            entorno = "Local" if any(h in self.url for h in ('localhost', '127.0.0.1')) else "Cloud"
            print(f"❌ Elasticsearch {entorno}: Error al conectar → {e}")
            return False
    
    def ejecutar_comando(self, comando_json: str) -> Dict:
        """
        Ejecuta un comando JSON en ElasticSearch
        
        Args:
            comando_json: Comando en formato JSON string
            
        Returns:
            Resultado de la ejecución o error
        """
        try:
            comando = json.loads(comando_json)
            
            # Extraer operación y parámetros
            operacion = comando.get('operacion')
            index = comando.get('index')
            
            if operacion == 'crear_index':
                # Crear índice
                mappings = comando.get('mappings', {})
                settings = comando.get('settings', {})
                
                response = self.client.indices.create(
                    index=index,
                    mappings=mappings,
                    settings=settings
                )
                return {'success': True, 'data': response}
                
            elif operacion == 'eliminar_index':
                # Eliminar índice
                response = self.client.indices.delete(index=index)
                return {'success': True, 'data': response}
                
            elif operacion == 'actualizar_mappings':
                # Actualizar mappings
                mappings = comando.get('mappings', {})
                response = self.client.indices.put_mapping(
                    index=index,
                    body=mappings
                )
                return {'success': True, 'data': response}
                
            elif operacion == 'info_index':
                # Obtener información del índice
                response = self.client.indices.get(index=index)
                return {'success': True, 'data': response}
                
            elif operacion == 'listar_indices':
                # Listar todos los índices
                response = self.client.cat.indices(format='json')
                return {'success': True, 'data': response}
                
            else:
                return {'success': False, 'error': f'Operación no soportada: {operacion}'}
                
        except json.JSONDecodeError as e:
            return {'success': False, 'error': f'JSON inválido: {str(e)}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def crear_index(self, nombre_index: str, mappings: Dict = None, settings: Dict = None) -> bool:
        """
        Crea un nuevo índice
        
        Args:
            nombre_index: Nombre del índice
            mappings: Definición de campos (opcional)
            settings: Configuración del índice (opcional)
        """
        try:
            body = {}
            if mappings:
                body['mappings'] = mappings
            if settings:
                body['settings'] = settings
                
            self.client.indices.create(index=nombre_index, body=body)
            return True
        except Exception as e:
            print(f"Error al crear índice: {e}")
            return False
    
    def eliminar_index(self, nombre_index: str) -> bool:
        """Elimina un índice"""
        try:
            self.client.indices.delete(index=nombre_index)
            return True
        except Exception as e:
            print(f"Error al eliminar índice: {e}")
            return False
    
    def _contar_documentos(self, index: str) -> int:
        """
        Retorna el conteo real de documentos en un índice
        usando la API _count, que excluye documentos eliminados
        pendientes de purga a diferencia de cat.indices.

        Retorna 0 si el índice no existe o hay error.
        """
        try:
            respuesta = self.client.count(index=index)
            return respuesta.get('count', 0)
        except Exception:
            return 0

    def listar_indices(self) -> List[Dict]:
        """Lista todos los índices con información detallada (excluye índices internos)"""
        try:
            indices = self.client.cat.indices(format='json', h='index,docs.count,store.size,health,status')
            
            # Filtro para ocultar índices internos (empiezan por '.')
            indices_filtrados = [
                idx for idx in indices 
                if not idx['index'].startswith('.')    # excluye .internal*, .ds-*, etc.
        ]
            # Convertir a formato más legible
            indices_formateados = []
            for idx in indices_filtrados:
                indices_formateados.append({
                    'nombre': idx.get('index', ''),
                    'total_documentos': self._contar_documentos(idx.get('index', '')),
                    'tamaño': idx.get('store.size', '0b'),
                    'salud': idx.get('health', 'unknown'),
                    'estado': idx.get('status', 'unknown')
                })
            
            return indices_formateados
        except Exception as e:
            print(f"Error al listar índices: {e}")
            return []
    
    def indexar_documento(self, index: str, documento: Dict, doc_id: str = None) -> bool:
        """
        Indexa un documento en ElasticSearch
        
        Args:
            index: Nombre del índice
            documento: Documento a indexar
            doc_id: ID del documento (opcional)
        """
        try:
            if doc_id:
                self.client.index(index=index, id=doc_id, document=documento)
            else:
                self.client.index(index=index, document=documento)
            return True
        except Exception as e:
            print(f"Error al indexar documento: {e}")
            return False
    
    def indexar_bulk(self, index: str, documentos: List[Dict]) -> Dict:
        """
        Indexa múltiples documentos de forma masiva
        
        Args:
            index: Nombre del índice
            documentos: Lista de documentos a indexar
            
        Returns:
            Diccionario con estadísticas de indexación
        """
        from elasticsearch.helpers import bulk
        
        try:
            # Preparar acciones para bulk
            acciones = []
            for doc in documentos:
                accion = {
                    '_index': index,
                    '_source': doc
                }
                #print("--- Documento enviado a bulk ---", accion)
                acciones.append(accion)
            
            # Ejecutar bulk
            success, failed = bulk(self.client, acciones, raise_on_error=False)
            
            return {
                'success': True,
                'indexados': success,
                'fallidos': len(failed) if failed else 0,
                'errores': failed if failed else []
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def buscar(self, index: str, query: Dict, aggs=None, size: int = 10) -> Dict:
        """
        Realiza una búsqueda en ElasticSearch
        
        Args:
            index: Nombre del índice
            query: Query de búsqueda (puede ser un dict completo con 'query' o solo la query)
            aggs: Agregaciones a ejecutar (opcional)
            size: Número de resultados
        """
        try:
            # Construir el body de la búsqueda
            body = query.copy() if query else {}
            
            # Agregar las agregaciones al body si existen
            if aggs:
                body['aggs'] = aggs
            
            # Ejecutar búsqueda
            response = self.client.search(index=index, body=body, size=size)
            
            return {
                'success': True,
                'total': response['hits']['total']['value'],
                'resultados': response['hits']['hits'],
                #'aggs': aggs
                'aggs': response.get('aggregations', {})
            }
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def ejecutar_query(self, query_json: str) -> Dict:
        """
        Ejecuta una query en ElasticSearch
        
        Args:
            query_json: Query en formato JSON string
            
        Returns:
            Resultado de la búsqueda con hits y aggregations
        """
        try:
            import json
            query = json.loads(query_json)
            
            # Si la query tiene 'index' específico, extraerlo
            index = query.pop('index', '_all')
            
            # Ejecutar búsqueda
            response = self.client.search(index=index, body=query)
            
            return {
                'success': True,
                'total': response['hits']['total']['value'],
                'hits': response['hits']['hits'],
                'aggs': response.get('aggregations', {})
            }
        except json.JSONDecodeError as e:
            return {'success': False, 'error': f'JSON inválido: {str(e)}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def ejecutar_dml(self, comando_json: str) -> Dict:
        """
        Ejecuta un comando DML (Data Manipulation Language) en ElasticSearch
        Permite ejecutar comandos como index, update, delete directamente
        
        Args:
            comando_json: Comando DML en formato JSON string
            
        Returns:
            Resultado de la ejecución
        """
        try:
            import json
            comando = json.loads(comando_json)
            
            operacion = comando.get('operacion')
            
            if operacion == 'index' or operacion == 'create':
                # Indexar documento
                index = comando.get('index')
                documento = comando.get('documento', comando.get('body', {}))
                doc_id = comando.get('id')
                
                if doc_id:
                    response = self.client.index(index=index, id=doc_id, document=documento)
                else:
                    response = self.client.index(index=index, document=documento)
                
                return {'success': True, 'data': response}
                
            elif operacion == 'update':
                # Actualizar documento
                index = comando.get('index')
                doc_id = comando.get('id')
                doc = comando.get('doc', comando.get('documento', {}))
                
                response = self.client.update(index=index, id=doc_id, doc=doc)
                return {'success': True, 'data': response}
                
            elif operacion == 'delete':
                # Eliminar documento
                index = comando.get('index')
                doc_id = comando.get('id')
                
                response = self.client.delete(index=index, id=doc_id)
                return {'success': True, 'data': response}
                
            elif operacion == 'delete_by_query':
                # Eliminar por query
                index = comando.get('index')
                query = comando.get('query', {})
                
                response = self.client.delete_by_query(index=index, body={'query': query}, refresh=True)
                response_dict = response.body if hasattr(response, 'body') else response    # Convertir a dict (serializable)
                #return {'success': True, 'data': response}
                return {'success': True, 'data': response_dict}
                
            else:
                return {'success': False, 'error': f'Operación DML no soportada: {operacion}'}
                
        except json.JSONDecodeError as e:
            return {'success': False, 'error': f'JSON inválido: {str(e)}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def buscar_texto(self, index: str, texto: str, campos: List[str] = None, size: int = 10) -> Dict:
        """
        Búsqueda simple de texto en campos específicos
        
        Args:
            index: Nombre del índice
            texto: Texto a buscar
            campos: Lista de campos donde buscar (si es None, busca en todos)
            size: Número de resultados
        """
        try:
            if campos:
                query = {
                    "query": {
                        "multi_match": {
                            "query": texto,
                            "fields": campos,
                            "type": "best_fields"
                        }
                    }
                }
            else:
                query = {
                    "query": {
                        "query_string": {
                            "query": texto
                        }
                    }
                }
            
            return self.buscar(index, query, size)
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def obtener_documento(self, index: str, doc_id: str) -> Optional[Dict]:
        """Obtiene un documento por su ID"""
        try:
            response = self.client.get(index=index, id=doc_id)
            return response['_source']
        except Exception as e:
            print(f"Error al obtener documento: {e}")
            return None
    
    def actualizar_documento(self, index: str, doc_id: str, datos: Dict) -> bool:
        """Actualiza un documento existente"""
        try:
            self.client.update(index=index, id=doc_id, doc=datos)
            return True
        except Exception as e:
            print(f"Error al actualizar documento: {e}")
            return False
    
    def eliminar_documento(self, index: str, doc_id: str) -> bool:
        """Elimina un documento"""
        try:
            self.client.delete(index=index, id=doc_id)
            return True
        except Exception as e:
            print(f"Error al eliminar documento: {e}")
            return False
    
    def close(self):
        """Cierra la conexión"""
        self.client.close()

    def existe_hash(self, hash_archivo: str, index: str) -> bool:
        """
        Verifica si un documento con el hash dado ya existe en Elasticsearch.

        Args:
            hash_valor: string 'sha256:<valor>'

        Returns:
            True  -> si existe al menos un documento con ese hash
            False -> si no existe
        """
        try:
            consulta = {
                "query": {
                    "term": {
                        "hash_archivo": hash_archivo      # búsquedas exactas
                    }
                }
            }

            respuesta = self.buscar(index=index, query=consulta, size=1)

            if not respuesta["success"]:
                print(f"[WARN] Error en búsqueda de hash: {respuesta.get('error')}")
                return False

            total = respuesta.get("total", 0)
            #print(f"[INFO] Hash '{hash_archivo}' encontrado {total} veces en índice '{index}'.")
            return total > 0

        except Exception as e:
            print(f"Error verificando hash en Elasticsearch: {e}")
            return False

    @staticmethod
    def _find_elasticsearch_bat_path():
        """Busca elasticsearch.bat en rutas comunes o usando variable de entorno."""
        path_from_env = os.getenv("ELASTICSEARCH_BAT_PATH")
        if path_from_env and os.path.isfile(path_from_env):
            return path_from_env

        drive = os.path.splitdrive(os.path.abspath(__file__))[0] or "C:"
        search_patterns = [
            os.path.join(drive + "\\", "elasticsearch*", "bin", "elasticsearch.bat"),
            os.path.join(drive + "\\", "Program Files", "elasticsearch*", "bin", "elasticsearch.bat"),
        ]

        matches = []
        for pattern in search_patterns:
            matches.extend(glob.glob(pattern))

        return sorted(matches)[-1] if matches else None

    @staticmethod
    def ensure_elasticsearch_ready(max_wait_seconds=15):
        """Verifica Elasticsearch local y lo inicia automáticamente si no responde."""
        health_url = "http://localhost:9200"
        starter_process = None
        startup_log_path = os.path.join("static", "uploads", "elasticsearch_startup.log")

        try:
            requests.get(health_url, timeout=1.5)
            print("✅ Elasticsearch local ya está respondiendo en http://localhost:9200")
            return
        except RequestsConnectionError:
            elasticsearch_bat = ElasticSearch._find_elasticsearch_bat_path()
            if not elasticsearch_bat:
                raise RuntimeError(
                    "No se encontró elasticsearch.bat automáticamente. "
                    "Indique la ruta exacta en la variable ELASTICSEARCH_BAT_PATH."
                )

            print(f"⚠️ Elasticsearch no está activo. Iniciando: {elasticsearch_bat}")
            os.makedirs(os.path.dirname(startup_log_path), exist_ok=True)
            log_file = open(startup_log_path, "a", encoding="utf-8")
            log_file.write("\n" + "=" * 60 + "\n")
            log_file.write(f"Inicio de intento: {datetime.now().isoformat()}\n")
            log_file.flush()

            starter_process = subprocess.Popen(
                ["cmd.exe", "/c", elasticsearch_bat],
                cwd=os.path.dirname(elasticsearch_bat),
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                close_fds=False,
            )
        except RequestException as e:
            print(f"⚠️ Elasticsearch respondió con un error temporal: {e}")

        deadline = time.monotonic() + max_wait_seconds
        while time.monotonic() < deadline:
            if starter_process and starter_process.poll() is not None:
                log_tail = ""
                if os.path.exists(startup_log_path):
                    with open(startup_log_path, "r", encoding="utf-8", errors="ignore") as f:
                        lines = f.readlines()
                        log_tail = "".join(lines[-20:]).strip()

                raise RuntimeError(
                    "El proceso de Elasticsearch terminó antes de quedar disponible en el puerto 9200. "
                    f"Revise el log en '{startup_log_path}'. "
                    f"Últimas líneas:\n{log_tail if log_tail else '(sin salida en log)'}"
                )

            try:
                requests.get(health_url, timeout=1.5)
                print("✅ Elasticsearch local respondió correctamente. Continuando arranque...")
                return
            except RequestsConnectionError:
                time.sleep(1)
            except RequestException:
                time.sleep(1)

        raise RuntimeError("Elasticsearch no respondió en el puerto 9200 dentro de 15 segundos.")