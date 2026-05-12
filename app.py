from flask import Flask, render_template, request, redirect, url_for,jsonify, session, flash
from dotenv import load_dotenv
import os
import glob
import time
import subprocess
from datetime import datetime
from werkzeug.utils import secure_filename
from Helpers import MongoDB, ElasticSearch, Funciones, WebScrapingMinAgricultura, PLN, RAG
import requests
from requests.exceptions import ConnectionError as RequestsConnectionError, RequestException
import warnings
warnings.filterwarnings("ignore")

# Cargar variables de entorno
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'clave_super_secreta_12345')

# Configuración MongoDB
MONGO_URI = os.getenv('MONGO_URI', 'mongodb://localhost:27017/')
MONGO_DB = os.getenv('MONGO_DB', 'bigdataapp')
MONGO_COLECCION = os.getenv('MONGO_COLECCION', 'usuario_roles')

# Configuración ElasticSearch local
ELASTIC_URL             = os.getenv('ELASTIC_URL', 'http://localhost:9200')
ELASTIC_USER            = os.getenv('ELASTIC_USER', 'elastic')
ELASTIC_PASSWORD        = os.getenv('ELASTIC_PASSWORD')
ELASTIC_INDEX_DEFAULT   = os.getenv('ELASTIC_INDEX_DEFAULT', 'index_minagricultura')

#Carpeta de descargas
UPLOAD_DIR = os.getenv('UPLOAD_DIR', 'static/uploads')

# Versión de la aplicación
VERSION_APP = "2.0.0"
CREATOR_APP = "JuanCDG"


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
        elasticsearch_bat = _find_elasticsearch_bat_path()
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

# Inicializar conexiones
ensure_elasticsearch_ready(max_wait_seconds=int(os.getenv('ELASTIC_STARTUP_TIMEOUT', 120)))
mongo = MongoDB(MONGO_URI, MONGO_DB)
mongo.verificar_colecciones(MONGO_COLECCION)
elastic = ElasticSearch(ELASTIC_URL, ELASTIC_USER, ELASTIC_PASSWORD)

# ==================== RUTAS ====================
@app.route('/')
def landing():
    """Landing page pública"""
    return render_template('landing.html', version=VERSION_APP, creador=CREATOR_APP)

@app.route('/about')
def about():
    """Página About"""
    return render_template('about.html', version=VERSION_APP, creador=CREATOR_APP)

#--------------rutas del buscador en elastic-inicio-------------
@app.route('/buscador')
def buscador():
    """Página de búsqueda pública"""
    return render_template('buscador.html', version=VERSION_APP, creador=CREATOR_APP)

@app.route('/buscar-elastic', methods=['POST'])
def buscar_elastic(): 
    """API para realizar búsqueda en ElasticSearch"""
    try:
        data = request.get_json()
        texto_buscar = data.get('texto', '').strip()
        #campo = data.get('campo', '_all') # _opciones (traidos de un select del formulario): titulo, contenido, autor, fecha_creacion
        #campo = 'texto'
        pagina = int(data.get("pagina", 1))
        tamano_pagina = int(data.get("tamano_pagina", 10))
        
        '''
        if not texto_buscar:
            return jsonify({
                'success': False,
                'error': 'Texto de búsqueda es requerido'
            }), 400
        
        # Definir aggregations/filtros
        query_base= {"query": {
                            "match": {
                                campo: texto_buscar
                            }
                        } 
                    }
        aggs = {
            "por_tipo_norma": {
                "terms": {"field": "tipo_norma.keyword"}
            },
            "por_anio": {
                "terms": {"field": "anio_norma"}
            },
            "por_entidad": {
                "terms": {"field": "entidad_emisora.keyword"}
            },
            "por_tema": {
                "terms": {"field": "temas.palabra.keyword"}
            }
        }
        '''

        query_base = {
            "from": (pagina - 1) * tamano_pagina,
            "query": {
                "bool": {
                    "must": [
                        {
                            "multi_match": {
                                "query": texto_buscar,
                                "type": "best_fields",
                                "minimum_should_match": "60%",
                                "fields": [
                                    "titulo_norma^5",
                                    "resumen^4",
                                    "texto^3",
                                    "entidades.personas^2",
                                    "entidades.lugares^2",
                                    "entidades.organizaciones^2",
                                    "entidades.leyes^2",
                                    "entidades.otros",
                                    "tipo_norma^3",
                                    "entidad_emisora^3",
                                    "temas.palabra^4"
                                ]
                            }
                        }
                    ],
                }
            }
        }

        aggs = {
            "filtro_anio": {
                "terms": { "field": "anio_norma", "size": 200, "order": { "_key": "desc" } }
            },
            "filtro_tipo_norma": {
                "terms": { "field": "tipo_norma", "size": 50 }
            },
            "filtro_entidad": {
                "terms": { "field": "entidad_emisora", "size": 100 }
            },
            "filtro_temas": {
                "nested": {
                    "path": "temas"
                },
                "aggs": {
                    "temas_palabras": {
                        "terms": { "field": "temas.palabra", "size": 50 }
                    }
                }
            }
        }
        

        # Aplicar filtros
        filtros = data.get("filtros", {})

        filtros_must = []

        # Filtro tipo_norma
        if filtros.get("tipo_norma"):
            filtros_must.append({
                "terms": {"tipo_norma": filtros["tipo_norma"]}
            })

        # Filtro año
        if filtros.get("anio_norma"):
            filtros_must.append({
                "terms": {"anio_norma": filtros["anio_norma"]}
            })

        # Filtro entidad_emisora
        if filtros.get("entidad_emisora"):
            filtros_must.append({
                "terms": {"entidad_emisora": filtros["entidad_emisora"]}
            })

        # Filtro temas (nested)
        if filtros.get("temas"):
            filtros_must.append({
                "nested": {
                    "path": "temas",
                    "query": {
                        "terms": {"temas.palabra": filtros["temas"]}
                    }
                }
            })

        # Insertar filtros dentro del bool.must
        query_base["query"]["bool"].setdefault("filter", []).extend(filtros_must)


        # Ejecutar búsqueda sobre elastic
        resultado = elastic.buscar(
            index=ELASTIC_INDEX_DEFAULT,
            query=query_base,
            aggs=aggs,
            size=tamano_pagina
        )
        #print(resultado) 
        
        return jsonify(resultado)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
#--------------rutas del buscador en elastic-fin-------------

#--------------rutas de mongodb (usuarios)-inicio-------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    """Página de login con validación"""
    if request.method == 'POST':
        usuario = request.form.get('usuario')
        password = request.form.get('password')
        
        # Validar usuario en MongoDB
        user_data = mongo.validar_usuario(usuario, password, MONGO_COLECCION)
        
        if user_data:
            # Guardar sesión
            session['usuario'] = usuario
            session['permisos'] = user_data.get('permisos', {})
            session['logged_in'] = True
            
            flash('¡Bienvenido! Inicio de sesión exitoso', 'success')
            return redirect(url_for('admin'))
        else:
            flash('Usuario o contraseña incorrectos', 'danger')
    
    return render_template('login.html')

@app.route('/listar-usuarios')
def listar_usuarios():
    try:

        usuarios = mongo.listar_usuarios(MONGO_COLECCION)
        
        # Convertir ObjectId a string para serialización JSON
        for usuario in usuarios:
            usuario['_id'] = str(usuario['_id'])
        
        return jsonify(usuarios)
    except Exception as e:
        return jsonify({'error': str(e)}), 500 

@app.route('/gestor_usuarios')
def gestor_usuarios():
    """Página de gestión de usuarios (protegida requiere login y permiso admin_usuarios) """
    if not session.get('logged_in'):
        flash('Por favor, inicia sesión para acceder a esta página', 'warning')
        return redirect(url_for('login'))
    
    permisos = session.get('permisos', {})
    if not permisos.get('admin_usuarios'):
        flash('No tiene permisos para gestionar usuarios', 'danger')
        return redirect(url_for('admin'))
    
    return render_template('gestor_usuarios.html', usuario=session.get('usuario'), permisos=permisos, version=VERSION_APP, creador=CREATOR_APP)

@app.route('/crear-usuario', methods=['POST'])
def crear_usuario():
    """API para crear un nuevo usuario"""
    try:
        if not session.get('logged_in'):
            return jsonify({'success': False, 'error': 'No autorizado'}), 401
        
        permisos = session.get('permisos', {})
        if not permisos.get('admin_usuarios'):
            return jsonify({'success': False, 'error': 'No tiene permisos para crear usuarios'}), 403
        
        data = request.get_json()
        usuario = data.get('usuario')
        password = data.get('password')
        permisos_usuario = data.get('permisos', {})
        
        if not usuario or not password:
            return jsonify({'success': False, 'error': 'Usuario y password son requeridos'}), 400
        
        # Verificar si el usuario ya existe
        usuario_existente = mongo.obtener_usuario(usuario, MONGO_COLECCION)
        if usuario_existente:
            return jsonify({'success': False, 'error': 'El usuario ya existe'}), 400
        
        # Crear usuario
        resultado = mongo.crear_usuario(usuario, password, permisos_usuario, MONGO_COLECCION)
        
        if resultado:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Error al crear usuario'}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/actualizar-usuario', methods=['POST'])
def actualizar_usuario():
    """API para actualizar un usuario existente"""
    try:
        if not session.get('logged_in'):
            return jsonify({'success': False, 'error': 'No autorizado'}), 401
        
        permisos = session.get('permisos', {})
        if not permisos.get('admin_usuarios'):
            return jsonify({'success': False, 'error': 'No tiene permisos para actualizar usuarios'}), 403
        
        data = request.get_json()
        usuario_original = data.get('usuario_original')
        datos_usuario = data.get('datos', {})
        
        if not usuario_original:
            return jsonify({'success': False, 'error': 'Usuario original es requerido'}), 400
        
        # Verificar si el usuario existe
        usuario_existente = mongo.obtener_usuario(usuario_original, MONGO_COLECCION)
        if not usuario_existente:
            return jsonify({'success': False, 'error': 'Usuario no encontrado'}), 404
        
        # Si el nombre de usuario cambió, verificar que no exista otro con ese nombre
        nuevo_usuario = datos_usuario.get('usuario')
        if nuevo_usuario and nuevo_usuario != usuario_original:
            usuario_duplicado = mongo.obtener_usuario(nuevo_usuario, MONGO_COLECCION)
            if usuario_duplicado:
                return jsonify({'success': False, 'error': 'Ya existe otro usuario con ese nombre'}), 400
        
        # Actualizar usuario
        resultado = mongo.actualizar_usuario(usuario_original, datos_usuario, MONGO_COLECCION)
        
        if resultado:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Error al actualizar usuario'}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/eliminar-usuario', methods=['POST'])
def eliminar_usuario():
    """API para eliminar un usuario"""
    try:
        if not session.get('logged_in'):
            return jsonify({'success': False, 'error': 'No autorizado'}), 401
        
        permisos = session.get('permisos', {})
        if not permisos.get('admin_usuarios'):
            return jsonify({'success': False, 'error': 'No tiene permisos para eliminar usuarios'}), 403
        
        data = request.get_json()
        usuario = data.get('usuario')
        
        if not usuario:
            return jsonify({'success': False, 'error': 'Usuario es requerido'}), 400
        
        # Verificar si el usuario existe
        usuario_existente = mongo.obtener_usuario(usuario, MONGO_COLECCION)
        if not usuario_existente:
            return jsonify({'success': False, 'error': 'Usuario no encontrado'}), 404
        
        # No permitir eliminar al usuario actual
        if usuario == session.get('usuario'):
            return jsonify({'success': False, 'error': 'No puede eliminarse a sí mismo'}), 400
        
        # Eliminar usuario
        resultado = mongo.eliminar_usuario(usuario, MONGO_COLECCION)
        
        if resultado:
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': 'Error al eliminar usuario'}), 500
            
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
#--------------rutas de mongodb (usuarios)-fin-------------

#--------------rutas de elasitcsearch - inicio-------------
@app.route('/gestor_elastic')
def gestor_elastic():
    """Página de gestión de ElasticSearch (protegida requiere login y permiso admin_elastic)"""
    if not session.get('logged_in'):
        flash('Por favor, inicia sesión para acceder a esta página', 'warning')
        return redirect(url_for('login'))
    
    permisos = session.get('permisos', {})
    if not permisos.get('admin_elastic'):
        flash('No tiene permisos para gestionar ElasticSearch', 'danger')
        return redirect(url_for('admin'))
    
    return render_template('gestor_elastic.html', usuario=session.get('usuario'), permisos=permisos, version=VERSION_APP, creador=CREATOR_APP)

@app.route('/listar-indices-elastic')
def listar_indices_elastic():
    """API para listar índices de ElasticSearch"""
    try:
        if not session.get('logged_in'):
            return jsonify({'error': 'No autorizado'}), 401
        
        permisos = session.get('permisos', {})
        if not permisos.get('admin_elastic'):
            return jsonify({'error': 'No tiene permisos para gestionar ElasticSearch'}), 403
        
        indices = elastic.listar_indices()
        return jsonify(indices)
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    
@app.route('/ejecutar-query-elastic', methods=['POST'])
def ejecutar_query_elastic():
    """API para ejecutar una query en ElasticSearch"""
    try:
        if not session.get('logged_in'):
            return jsonify({'success': False, 'error': 'No autorizado'}), 401
        
        permisos = session.get('permisos', {})
        if not permisos.get('admin_elastic'):
            return jsonify({'success': False, 'error': 'No tiene permisos para gestionar ElasticSearch'}), 403
        
        data = request.get_json()
        query_json = data.get('query')
        
        if not query_json:
            return jsonify({'success': False, 'error': 'Query es requerida'}), 400
        
        resultado = elastic.ejecutar_query(query_json)
        return jsonify(resultado)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/ejecutar-dml-elastic', methods=['POST'])
def ejecutar_dml_elastic():
    try:
        if not session.get('logged_in'):
            return jsonify({'success': False, 'error': 'No autorizado'}), 401
        
        permisos = session.get('permisos', {})
        if not permisos.get('admin_elastic'):
            return jsonify({'success': False, 'error': 'No tiene permisos para gestionar ElasticSearch'}), 403
        
        data = request.get_json()
        query_json = data.get("comando", "")
        
        if not query_json:
            return jsonify({'success': False, 'error': 'Comando DML vacío'}), 400
        
        resultado = elastic.ejecutar_dml(query_json)
        return jsonify(resultado)
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/cargar_doc_elastic')
def cargar_doc_elastic():
    """Página de carga de documentos a ElasticSearch (protegida requiere login y permiso admin_data_elastic)"""
    if not session.get('logged_in'):
        flash('Por favor, inicia sesión para acceder a esta página', 'warning')
        return redirect(url_for('login'))
    
    permisos = session.get('permisos', {})
    if not permisos.get('admin_data_elastic'):
        flash('No tiene permisos para cargar datos a ElasticSearch', 'danger')
        return redirect(url_for('admin'))
    
    return render_template('documentos_elastic.html', usuario=session.get('usuario'), permisos=permisos, version=VERSION_APP, creador=CREATOR_APP)

@app.route('/procesar-zip-elastic', methods=['POST'])
def procesar_zip_elastic():
    """API para procesar archivo ZIP con archivos JSON"""
    try:
        if not session.get('logged_in'):
            return jsonify({'success': False, 'error': 'No autorizado'}), 401
        
        permisos = session.get('permisos', {})
        if not permisos.get('admin_data_elastic'):
            return jsonify({'success': False, 'error': 'No tiene permisos para cargar datos'}), 403
        
        if 'file' not in request.files:
            return jsonify({'success': False, 'error': 'No se envió ningún archivo'}), 400
        
        file = request.files['file']
        index = request.form.get('index')
        
        if not file.filename:
            return jsonify({'success': False, 'error': 'Archivo no válido'}), 400
        
        if not index:
            return jsonify({'success': False, 'error': 'Índice no especificado'}), 400
        
        # Guardar archivo ZIP temporalmente
        filename = secure_filename(file.filename)
        carpeta_upload = 'static/uploads'
        Funciones.crear_carpeta(carpeta_upload)
        Funciones.borrar_contenido_carpeta(carpeta_upload)
        
        zip_path = os.path.join(carpeta_upload, filename)
        file.save(zip_path)
        print(f"Archivo ZIP guardado en: {zip_path}")
        
        # Descomprimir ZIP
        archivos = Funciones.descomprimir_zip_local(zip_path, carpeta_upload)
        
        # Eliminar archivo ZIP
        os.remove(zip_path)
        
        # Listar archivos JSON
        archivos_json = Funciones.listar_archivos_json(carpeta_upload)
        
        return jsonify({
            'success': True,
            'archivos': archivos_json,
            'mensaje': f'Se encontraron {len(archivos_json)} archivos JSON'
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
    
@app.route('/cargar-documentos-elastic', methods=['POST'])
def cargar_documentos_elastic():
    """API para cargar documentos a ElasticSearch"""
    try:
        if not session.get('logged_in'):
            return jsonify({'success': False, 'error': 'No autorizado'}), 401
        
        permisos = session.get('permisos', {})
        if not permisos.get('admin_data_elastic'):
            return jsonify({'success': False, 'error': 'No tiene permisos para cargar datos'}), 403
        
        data = request.get_json()
        archivos = data.get('archivos', [])
        index = data.get('index')
        metodo = data.get('metodo', 'zip')

        print("\n===== CARGAR DOCUMENTOS ELASTIC =====")
        print("Archivos recibidos:", len(archivos))
        print("Índice seleccionado:", index)
        
        if not archivos or not index:
            return jsonify({'success': False, 'error': 'Archivos e índice son requeridos'}), 400
        
        documentos = []
        
        if metodo == 'zip':
            # Cargar archivos JSON directamente
            for archivo in archivos:
                ruta = archivo.get('ruta')
                print(f"Procesando archivo JSON: {ruta}")
                if ruta and os.path.exists(ruta):
                    doc = Funciones.leer_json(ruta)
                    print(doc)
                    if doc:
                        documentos.append(doc)
        
        elif metodo == 'webscraping':
            # Procesar archivos con PLN
            
            # 1. Filtrar archivos nuevos (no duplicados)
            archivos_filtrados = []
            
            for archivo in archivos:
                # verificar que el archivo exista
                ruta = archivo.get('ruta')
                print(f"--- Verificando archivo: {ruta}")
                if not ruta or not os.path.exists(ruta):
                    print(f"   ✖ Archivo no encontrado: {ruta}")
                    continue

                # Calcular hash del archivo PDF
                hash_archivo = Funciones.calcular_hash_archivo(ruta)
                if not hash_archivo:
                    print(f"Error calculando hash del archivo {ruta}. Se omite.")
                    continue

                # Validar si el hash ya existe en Elastic
                if elastic.existe_hash(hash_archivo, index):
                    print(f"Documento ya indexado (hash duplicado): {ruta}")
                    continue
                archivo['hash_archivo'] = hash_archivo                  # agregar hash al diccionario del archivo
                archivos_filtrados.append(archivo)       
                
            # Si no hay archivos nuevos, retornar
            if not archivos_filtrados:
                print("No hay archivos nuevos para procesar.")
                return jsonify({'success': True, 'indexados': 0, 'errores': 0})
            
            # Cargar PLN (LENTO)
            pln = PLN(cargar_modelos=True)

            total_archivos = len(archivos_filtrados)
            print(f"\nTotal de archivos a procesar con PLN: {total_archivos}")

            archivos_fallidos = []
            for i, archivo in enumerate(archivos_filtrados, start=1):
                # ----- Extracción de texto -----
                ruta = archivo.get('ruta')
                hash_archivo = archivo.get('hash_archivo')
                print(f"\n--- Procesando archivo [{i} / {total_archivos}]: {ruta} ---")
                # Extraer texto según tipo de archivo
                extension = archivo.get('extension', '').lower()

                texto = ""
                if extension == 'pdf':
                    # Intentar extracción normal
                    texto = Funciones.extraer_texto_pdf(ruta)
                    if texto and len(texto.strip()) >= 50:
                        print(f" → Texto extraído (longitud {len(texto)} caracteres): ✓")
                    else:
                        print(f" → Texto extraído (longitud {len(texto)} caracteres): ✗ (insuficiente, intentando OCR...)")
                        
                        # Si no se extrajo texto suficiente, intentar con OCR
                        try:
                            texto = Funciones.extraer_texto_pdf_ocr(ruta)
                            if texto and len(texto.strip()) >= 50:
                                print(f" → Texto extraído con OCR (longitud {len(texto)} caracteres): ✓")
                            else:
                                print(f" → Texto extraído con OCR (longitud {len(texto)} caracteres): ✗ (insuficiente)")
                        except Exception as e:
                            print(f" → Texto extraído con OCR: ✗ (error: {str(e)[:80]})")
                
                elif extension == 'txt':
                    try:
                        with open(ruta, 'r', encoding='utf-8') as f:
                            texto = f.read()
                    except:
                        try:
                            with open(ruta, 'r', encoding='latin-1') as f:
                                texto = f.read()
                        except:
                            pass
                
                if not texto or len(texto.strip()) < 50:        # si no se extrajo texto suficiente, omitir
                    archivos_fallidos.append({
                        'ruta': ruta,
                        'razon': 'No se extrajo texto suficiente (< 50 caracteres)'
                    })
                    continue
                
                # ------ Procesar con PLN -------
                try:
                    # Procesar con PLN usando chunks
                    print(" → Procesando texto con PLN (método chunks)...")
                    resultado_pln = pln.procesar_texto_largo(texto)
                    print("   → Resumen generado (longitud {} caracteres)".format(len(resultado_pln.get('resumen', ''))))

                    temas_pln = resultado_pln.get("temas", [])

                    # Convertir lista de tuplas → lista de objetos
                    temas_convertidos = [
                        {"palabra": palabra, "relevancia": float(relevancia)}
                        for palabra, relevancia in temas_pln
                    ]

                    # Extraer metadatos normativos
                    meta = pln.extraer_metadatos_norma(texto)

                    #print("fecha encontrada (raw):", meta.get("fecha_documento"))
                    fecha_normalizada = pln.normalizar_fecha(meta.get("fecha_documento"))
                    #print("fecha normalizada:", fecha_normalizada)

                    # Crear documento
                    documento = {
                        "tipo_norma": meta.get("tipo_norma"),
                        "numero_norma": meta.get("numero_norma"),
                        "anio_norma": meta.get("anio_norma"),
                        "entidad_emisora": meta.get("entidad_emisora"),
                        "fecha_documento": fecha_normalizada,
                        "titulo_norma": meta.get("titulo_norma"),    
                        'texto': texto[:2_000_000],  # limitar tamaño para Elastic
                        'resumen': resultado_pln.get('resumen', ''),
                        'entidades': resultado_pln.get('entidades', {}),
                        'temas': temas_convertidos,
                        'ruta': ruta,
                        'nombre_archivo': archivo.get('nombre', ''),
                        'hash_archivo': hash_archivo,
                        'fecha_carga': datetime.now().isoformat()
                    }

                    documentos.append(documento)      
                                 
                
                except Exception as e:
                    print(f"Error al procesar {archivo.get('nombre')}: {e}")
                    continue
            
            pln.close()
        
        # Si no hay documentos a insertar en elastic, terminar sin error
        if not documentos:
            #return jsonify({'success': False, 'error': 'No se pudieron procesar documentos'}), 400
            print(f"No hay documentos nuevos para procesar (todos duplicados o sin texto).")
            print(f"Archivos fallidos por extracción: {len(archivos_fallidos)}")
            for fallo in archivos_fallidos[:5]:  # mostrar primeros 5
                print(f"  - {fallo['ruta']}: {fallo['razon']}")
            if len(archivos_fallidos) > 5:
                print(f"  ... y {len(archivos_fallidos) - 5} más")
            return jsonify({
                "success": True, 
                "indexados": 0, 
                "duplicados": 0,
                "fallidos_extraccion": len(archivos_fallidos)
            }), 200
        
        # Indexar documentos en Elastic
        print(f"\nTotal de documentos a indexar: {len(documentos)}")
        resultado = elastic.indexar_bulk(index, documentos)
        print("Resultado de indexación:", resultado)
        
        return jsonify({
            'success': resultado['success'],
            'indexados': resultado['indexados'],
            'errores': resultado['fallidos'],
            'fallidos_extraccion': len(archivos_fallidos)
        })
        
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/procesar-webscraping-elastic', methods=['POST'])
def procesar_webscraping_elastic():
    """
    Inicia el proceso de web scraping dinámico y descarga de PDFs.
    """
    # Validación de sesión
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'Acceso no autorizado'}), 401

    permisos = session.get('permisos', {})
    if not permisos.get('admin_data_elastic'):
        return jsonify({'success': False, 'error': 'No tiene permisos para cargar datos'}), 403

    try:
        data = request.get_json()                           # Captura los datos que vienen del formulario (frontend)
        base_url = data.get("url", "").strip()              # URL digitada por el usuario (frontend)
        if not base_url:
            return jsonify({"success": False, "message": "Debe ingresar una URL válida"}), 400

        # 1. Crear scraper
        scraper = WebScrapingMinAgricultura(base_url)

        # 2. Crear si no existe carpeta uploads y limpiar su contenido
        Funciones.crear_carpeta(UPLOAD_DIR)
        Funciones.borrar_contenido_carpeta(UPLOAD_DIR)

        # 3. EXTRAER ENLACES
        enlaces = scraper.extraer_todos_los_enlaces()

        # 4. DESCARGAR ARCHIVOS
        resultado_descarga = scraper.descargar_archivos(enlaces, UPLOAD_DIR)

        # 5. LISTAR ARCHIVOS DESCARGADOS
        archivos = Funciones.listar_archivos_carpeta(UPLOAD_DIR, ['pdf'])

        return jsonify({
            "success": True,
            "archivos": archivos,
            "mensaje": f"Se descargaron {len(archivos)} archivos",
            "stats": {
                "total_enlaces": resultado_descarga["total"],
                "descargados": resultado_descarga["descargados"],
                "errores": resultado_descarga["errores"]
            }
        })

    except Exception as e:
        print("ERROR SCRAPING:", e)
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "message": str(e) if str(e) else "Error en Playwright (ver consola)"}), 500

#--------------rutas de elasitcsearch - fin-------------

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada correctamente', 'info')
    return redirect(url_for('landing'))


@app.route('/admin')
def admin():
    """Página de administración (protegida requiere login)"""
    if not session.get('logged_in'):
        flash('Por favor, inicia sesión para acceder al área de administración', 'warning')
        return redirect(url_for('login'))
    
    return render_template('admin.html', usuario=session.get('usuario'),
                           permisos=session.get('permisos'),
                           version=VERSION_APP, creador=CREATOR_APP)



@app.route('/consultar-rag', methods=['POST'])
def consultar_rag():
    """API de consulta RAG — recupera docs de Elastic y genera respuesta con citación (S14)."""
    try:
        data = request.get_json()
        consulta = data.get('consulta', '').strip()
        if not consulta:
            return jsonify({'success': False, 'error': 'Consulta vacía'}), 400

        # 1. Recuperar candidatos desde Elasticsearch
        query_elastic = {
            "query": {
                "multi_match": {
                    "query": consulta,
                    "fields": ["titulo_norma^3", "resumen^2", "texto", "temas.palabra^2"],
                    "type": "best_fields"
                }
            }
        }
        resultado_elastic = elastic.buscar(
            index=ELASTIC_INDEX_DEFAULT, query=query_elastic, size=20
        )

        hits = resultado_elastic.get('hits', {}).get('hits', [])
        if not hits:
            return jsonify({'success': True, 'respuesta': 'No se encontraron documentos relevantes.', 'fuentes': []})

        # 2. Preparar corpus para RAG (usa resumen si existe, si no los primeros 3000 chars del texto)
        documentos_rag = [
            {
                'id': hit['_id'],
                'texto': hit['_source'].get('resumen') or hit['_source'].get('texto', '')[:3000],
                'fuente': hit['_source'].get('nombre_archivo', hit['_id'])
            }
            for hit in hits
            if hit['_source'].get('resumen') or hit['_source'].get('texto')
        ]

        if not documentos_rag:
            return jsonify({'success': True, 'respuesta': 'Sin texto disponible.', 'fuentes': []})

        # 3. Indexar y responder con RAG
        rag = RAG(n_vecinos=min(6, len(documentos_rag)))
        rag.indexar(documentos_rag)
        resultado = rag.responder(consulta, n_docs=3, n_oraciones=3)

        return jsonify({'success': True, **resultado})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# ==================== MAIN ====================
if __name__ == '__main__':
    # Crear carpetas necesarias
    Funciones.crear_carpeta('static/uploads')
    
    # Verificar conexiones
    print("\n" + "="*50)
    print("VERIFICANDO CONEXIONES")

    mongo.test_connection()
    elastic.test_connection()

    # Ejecutar la aplicación (localmente para pruebas)
    app.run(debug=True, host='0.0.0.0', port=5000)