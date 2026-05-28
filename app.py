from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash, Response
from dotenv import load_dotenv
import os
from werkzeug.utils import secure_filename
from Helpers import MongoDB, ElasticSearch, Funciones, WebScrapingMinAgricultura, PLN
from Helpers.PLN import pipeline, metrics, vector_search
import json
from datetime import datetime
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
VERSION_APP = "3.0.0"
CREATOR_APP = "JuanCDG"


# Inicializar conexiones
ElasticSearch.ensure_elasticsearch_ready(max_wait_seconds=int(os.getenv('ELASTIC_STARTUP_TIMEOUT', 120)))
mongo = MongoDB(MONGO_URI, MONGO_DB)
mongo.verificar_colecciones(MONGO_COLECCION)
elastic      = ElasticSearch(ELASTIC_URL, ELASTIC_USER, ELASTIC_PASSWORD)
pln_busqueda = PLN(cargar_modelos=True)
_W2V_PATH = 'models/normasearch_w2v_sg_v100_w5.model'
if os.path.exists(_W2V_PATH):
    pln_busqueda.cargar_word2vec(_W2V_PATH)

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
        pagina = int(data.get("pagina", 1))
        tamano_pagina = int(data.get("tamano_pagina", 20))

        query_base = {
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
        # Pool de 100 para re-ranking semántico: recuperar solo tamano_pagina documentos
        # limitaría el re-ranking a los primeros N resultados BM25, perdiendo candidatos
        # que el modelo semántico podría rankear mejor. Con 100 docs, buscar_conceptual()
        # reordena por similitud coseno sobre un conjunto representativo de la búsqueda.
        resultado = elastic.buscar(
            index=ELASTIC_INDEX_DEFAULT,
            query=query_base,
            aggs=aggs,
            size=100
        )

        if resultado.get('success') and resultado.get('resultados'):
            reranked = pln_busqueda.buscar_conceptual(
                texto_buscar, resultado['resultados'], campo_texto='texto'
            )
            # Paginación en Python sobre el pool re-rankeado: el 'from' de Elasticsearch
            # ya no aplica porque el orden cambió tras el re-ranking semántico. Se pagina
            # sobre la lista reranked con aritmética de índice, preservando la semántica
            # de página/tamano_pagina. Límite real: pagina * tamano_pagina <= 100.
            inicio = (pagina - 1) * tamano_pagina
            resultado['resultados'] = reranked[inicio : inicio + tamano_pagina]

        return jsonify(resultado)
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
#--------------rutas del buscador en elastic-fin-------------

#--------------entrenar word2vec-inicio-------------
@app.route('/entrenar-word2vec')
def entrenar_word2vec_page():
    """Página de entrenamiento Word2Vec (requiere permiso admin_data_elastic)."""
    if not session.get('logged_in'):
        flash('Inicia sesión para acceder', 'warning')
        return redirect(url_for('login'))
    if not session.get('permisos', {}).get('admin_data_elastic'):
        flash('Sin permiso para esta acción', 'danger')
        return redirect(url_for('admin'))
    return render_template('entrenar_w2v.html', version=VERSION_APP,
                           modelo_existe=os.path.exists(_W2V_PATH))


@app.route('/entrenar-word2vec/stream')
def entrenar_word2vec_stream():
    """SSE: tokeniza corpus desde ES, entrena Word2Vec y recarga en pln_busqueda."""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    if not session.get('permisos', {}).get('admin_data_elastic'):
        return jsonify({'success': False, 'error': 'Sin permiso'}), 403

    modo = request.args.get('modo', 'incremental')

    def generate():
        def evento(tipo, mensaje):
            return f"data: {json.dumps({'tipo': tipo, 'mensaje': mensaje})}\n\n"

        yield evento('info', 'Consultando Elasticsearch...')
        resultado = elastic.buscar(
            index=ELASTIC_INDEX_DEFAULT,
            query={"query": {"match_all": {}}, "_source": ["texto"]},
            size=500,
        )
        if not resultado.get('success'):
            yield evento('error', f"Error al consultar ES: {resultado.get('error', '')}")
            yield f"data: {json.dumps({'tipo': 'fin', 'success': False})}\n\n"
            return

        hits   = resultado.get('resultados', [])
        n_docs = len(hits)
        if not hits:
            yield evento('error', 'No hay documentos en el índice.')
            yield f"data: {json.dumps({'tipo': 'fin', 'success': False})}\n\n"
            return

        yield evento('info', f'{n_docs} documentos encontrados. Tokenizando con spaCy (puede tardar)...')

        corpus = []
        for i, hit in enumerate(hits, 1):
            texto  = (hit.get('_source') or {}).get('texto', '')
            if not texto:
                continue
            procesado = pln_busqueda.preprocesar_texto(texto)
            tokens    = procesado.split() if procesado else []
            if tokens:
                corpus.append(tokens)
            if i % 50 == 0:
                yield evento('info', f'  Tokenizados {i}/{n_docs} ({len(corpus)} con tokens)...')

        if not corpus:
            yield evento('error', 'Sin tokens válidos tras preprocesar. Abortando.')
            yield f"data: {json.dumps({'tipo': 'fin', 'success': False})}\n\n"
            return

        yield evento('info', f'Corpus listo: {len(corpus)} documentos. Iniciando entrenamiento...')

        modelo_existente = None
        if modo == 'incremental' and os.path.exists(_W2V_PATH):
            yield evento('info', 'Modo incremental → cargando modelo existente...')
            modelo_existente = vector_search.cargar_modelo_completo(_W2V_PATH)
        else:
            if modo == 'desde_cero':
                yield evento('info', 'Modo desde cero → el modelo existente será reemplazado.')
            else:
                yield evento('info', 'Sin modelo previo → entrenando desde cero.')
            os.makedirs('models', exist_ok=True)

        modelo = vector_search.entrenar_word2vec(corpus, modelo_existente=modelo_existente)
        if modelo is None:
            yield evento('error', 'Entrenamiento fallido (gensim no disponible).')
            yield f"data: {json.dumps({'tipo': 'fin', 'success': False})}\n\n"
            return

        ruta_guardado = vector_search.guardar_modelo(modelo, _W2V_PATH)
        yield evento('ok', f'Modelo guardado en: {ruta_guardado}')

        pln_busqueda.cargar_word2vec(_W2V_PATH)
        yield evento('ok', 'Modelo recargado en memoria.')

        yield f"data: {json.dumps({'tipo': 'fin', 'success': True, 'documentos_usados': len(corpus), 'mensaje': f'Completado con {len(corpus)} documentos.'})}\n\n"

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})
#--------------entrenar word2vec-fin-------------

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
    
    return render_template('login.html', version=VERSION_APP, creador=CREATOR_APP)

@app.route('/listar-usuarios')
def listar_usuarios():
    """API que retorna todos los usuarios registrados en MongoDB."""
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
        
        # Si password viene vacío, no sobreescribir el hash existente
        if not datos_usuario.get('password'):
            datos_usuario.pop('password', None)

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
    """API para ejecutar operaciones DML (crear, actualizar, eliminar) en Elasticsearch."""
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
    
    # Lee el nombre de display de cada modelo para pasarlo al template; el HTML no tiene acceso directo a la configuración JSON.
    cfg = pipeline.cargar_config_modelos()
    cfg_activa = cfg.get('configuracion_activa', {})
    summarizers = {m['id']: m['nombre'] for m in cfg.get('summarizer', [])}
    modelo_fase1_nombre = summarizers.get(cfg_activa.get('modelo_fase1', ''), 'Fase 1')
    modelo_fase2_nombre = summarizers.get(cfg_activa.get('modelo_fase2', ''), 'Fase 2')

    return render_template('documentos_elastic.html',
                           usuario=session.get('usuario'), permisos=permisos,
                           version=VERSION_APP, creador=CREATOR_APP,
                           modelo_fase1_nombre=modelo_fase1_nombre,
                           modelo_fase2_nombre=modelo_fase2_nombre)

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
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    if not session.get('permisos', {}).get('admin_data_elastic'):
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    data = request.get_json()
    archivos = data.get('archivos', [])
    index = data.get('index')
    metodo = data.get('metodo', 'zip')

    if not archivos or not index:
        return jsonify({'success': False,
                       'error': 'Archivos e índice son requeridos'}), 400

    documentos = []
    archivos_fallidos = 0

    if metodo == 'zip':
        for archivo in archivos:
            ruta = archivo.get('ruta')
            if ruta and os.path.exists(ruta):
                doc = Funciones.leer_json(ruta)
                if doc:
                    documentos.append(doc)

    elif metodo == 'webscraping':
        modelo_resumen = pipeline.obtener_modelo_resumen_activo()
        archivos_nuevos = pipeline.filtrar_archivos_nuevos(
            archivos, index, elastic
        )
        if not archivos_nuevos:
            return jsonify({'success': True, 'indexados': 0,
                           'duplicados': len(archivos) - len(archivos_nuevos),
                           'fallidos': 0})

        total = len(archivos_nuevos)
        print(f"\nProcesando {total} archivo(s) con modelo: {modelo_resumen}")

        for i, archivo in enumerate(archivos_nuevos, 1):
            print(f"\n[{i}/{total}] {archivo.get('nombre', '')}")
            doc, _ = pipeline.procesar_documento(
                ruta=archivo['ruta'],
                nombre=archivo.get('nombre', ''),
                hash_archivo=archivo['hash_archivo'],
                pln=pln_busqueda,
                modelo_resumen=modelo_resumen
            )
            if doc:
                documentos.append(doc)
            else:
                archivos_fallidos += 1

    if not documentos:
        return jsonify({'success': True, 'indexados': 0,
                       'fallidos': archivos_fallidos})

    resultado = elastic.indexar_bulk(index, documentos)
    return jsonify({
        'success': resultado['success'],
        'indexados': resultado.get('indexados', 0),
        'fallidos': resultado.get('fallidos', 0) + archivos_fallidos
    })

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

@app.route('/subir-pdfs-carpeta', methods=['POST'])
def subir_pdfs_carpeta():
    """Recibe PDFs del cliente y los guarda en uploads/carpeta_local/ para procesarlos."""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    if not session.get('permisos', {}).get('admin_data_elastic'):
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403
    if 'archivos' not in request.files:
        return jsonify({'success': False, 'error': 'No se recibieron archivos'}), 400

    carpeta_destino = os.path.join('static', 'uploads', 'carpeta_local')
    os.makedirs(carpeta_destino, exist_ok=True)
    for f in os.listdir(carpeta_destino):           # limpiar subidas anteriores
        os.remove(os.path.join(carpeta_destino, f))

    guardados = []
    for archivo in request.files.getlist('archivos'):
        if archivo.filename.lower().endswith('.pdf'):
            # Extraer solo el nombre del archivo sin ruta de carpeta
            # archivo.filename puede venir como "carpeta/nombre.pdf"
            # desde el navegador cuando se selecciona desde subcarpeta
            nombre_base = os.path.basename(archivo.filename.replace('\\', '/'))
            nombre = secure_filename(nombre_base)
            ruta_completa = os.path.join(carpeta_destino, nombre)
            archivo.save(ruta_completa)
            guardados.append({'nombre': nombre, 'ruta': ruta_completa,
                              'extension': 'pdf', 'tamaño': os.path.getsize(ruta_completa)})

    return jsonify({'success': True, 'archivos': guardados, 'ruta': carpeta_destino})


@app.route('/listar-carpeta-local', methods=['POST'])
def listar_carpeta_local():
    """Lista los PDFs encontrados en una carpeta local del servidor."""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    if not session.get('permisos', {}).get('admin_data_elastic'):
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    ruta = (request.get_json() or {}).get('ruta', '').strip()
    if not ruta:
        return jsonify({'success': False, 'error': 'Ruta no especificada'}), 400
    if not os.path.isdir(ruta):
        return jsonify({'success': False, 'error': f'La ruta no existe o no es una carpeta válida'}), 400

    archivos = []
    for nombre in sorted(os.listdir(ruta)):
        if nombre.lower().endswith('.pdf'):
            ruta_completa = os.path.join(ruta, nombre)
            archivos.append({
                'nombre': nombre,
                'ruta': ruta_completa,
                'extension': 'pdf',
                'tamaño': os.path.getsize(ruta_completa)
            })

    return jsonify({'success': True, 'archivos': archivos,
                    'mensaje': f'Se encontraron {len(archivos)} archivos PDF'})


@app.route('/indexar-carpeta-local')
def indexar_carpeta_local():
    """SSE: procesa e indexa PDFs de una carpeta local con progreso en tiempo real."""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    if not session.get('permisos', {}).get('admin_data_elastic'):
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    ruta    = request.args.get('ruta', '').strip()
    index   = request.args.get('index', '').strip()
    nombres = [n for n in request.args.get('archivos', '').split('|') if n]

    if not ruta or not os.path.isdir(ruta) or not index:
        return jsonify({'error': 'Parámetros inválidos'}), 400

    def evento(tipo, **kwargs):
        import json as _json
        return f"data: {_json.dumps({'tipo': tipo, **kwargs})}\n\n"

    def generate():
        archivos_validos = [n for n in nombres if os.path.exists(os.path.join(ruta, n))]
        total = len(archivos_validos)
        yield evento('inicio', total=total)

        if not archivos_validos:
            yield evento('fin', indexados=0, errores=0, omitidos=0)
            return

        modelo_resumen = pipeline.obtener_modelo_resumen_activo()
        indexados = errores = omitidos = 0

        for i, nombre in enumerate(archivos_validos, 1):
            ruta_archivo = os.path.join(ruta, nombre)

            # ── Deduplicación por hash
            yield evento('progreso', archivo=nombre, num=i, total=total, fase='Verificando duplicado')
            hash_archivo = Funciones.calcular_hash_archivo(ruta_archivo)
            if elastic.existe_hash(hash_archivo, index):
                omitidos += 1
                yield evento('omitido', archivo=nombre, num=i, total=total)
                continue

            # ── Pipeline PLN
            yield evento('progreso', archivo=nombre, num=i, total=total, fase='Procesando con PLN')
            try:
                doc, _ = pipeline.procesar_documento(
                    ruta=ruta_archivo,
                    nombre=nombre,
                    hash_archivo=hash_archivo,
                    pln=pln_busqueda,
                    modelo_resumen=modelo_resumen
                )

                if doc is None:
                    errores += 1
                    yield evento('error', archivo=nombre, num=i, total=total, razon='Sin texto extraíble')
                    continue

                # ── Indexar
                yield evento('progreso', archivo=nombre, num=i, total=total, fase='Indexando en Elastic')
                res = elastic.indexar_bulk(index, [doc])
                if res['success']:
                    indexados += 1
                    yield evento('ok', archivo=nombre, num=i, total=total)
                else:
                    errores += 1
                    yield evento('error', archivo=nombre, num=i, total=total, razon='Error al indexar')

            except Exception as e:
                errores += 1
                yield evento('error', archivo=nombre, num=i, total=total, razon=str(e)[:120])

        yield evento('fin', indexados=indexados, errores=errores, omitidos=omitidos)

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})


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




@app.route('/configuracion')
def configuracion():
    """Página de configuración de modelos PLN"""
    config = pipeline.cargar_config_modelos()
    return render_template('configuracion.html', config=config,
                           version=VERSION_APP, creador=CREATOR_APP)


@app.route('/configuracion/guardar', methods=['POST'])
def guardar_configuracion():
    """API para actualizar campos de configuracion_activa"""
    data = request.get_json()

    config = pipeline.cargar_config_modelos()
    config_activa = config.setdefault('configuracion_activa', {})
    modelo_anterior = config_activa.get('summarizer_activo')

    campos_validos = ('summarizer_activo', 'modo_comparacion', 'modelo_fase1', 'modelo_fase2')
    for campo in campos_validos:
        if campo in data:
            config_activa[campo] = data[campo]

    summarizer_activo = config_activa.get('summarizer_activo')
    # Resuelve el modelo_hf del summarizer activo para devolverlo al frontend; el panel muestra el nombre real del modelo, no solo su ID interno.
    modelo_hf = next(
        (m.get('modelo_hf', 'google/mt5-small') for m in config.get('summarizer', [])
         if m.get('id') == summarizer_activo),
        'google/mt5-small'
    )

    pipeline.guardar_config_modelos(config)

    if modelo_anterior != summarizer_activo:
        pipeline.liberar_modelo_resumen(pln_busqueda)

    return jsonify({'success': True, 'modelo_activo': modelo_hf})


_EVALUACIONES_PATH = 'static/metrics/evaluaciones_precision.json'


@app.route('/metricas')
def metricas_vista():
    """Panel de métricas operacionales del pipeline PLN"""
    resumen = metrics.calcular_resumen_comparativo()
    todas   = metrics.cargar_todas_las_metricas()

    evaluaciones_precision = []
    if os.path.exists(_EVALUACIONES_PATH):
        try:
            with open(_EVALUACIONES_PATH, 'r', encoding='utf-8') as f:
                evaluaciones_precision = json.load(f)
        except Exception:
            evaluaciones_precision = []

    # Promedios globales de P@5 para el panel; diferencia positiva indica cuánto mejora la búsqueda semántica sobre BM25 puro.
    ev_bm25_avg = ev_sem_avg = ev_diff_avg = 0.0
    if evaluaciones_precision:
        n_ev        = len(evaluaciones_precision)
        ev_bm25_avg = round(sum(e.get('bm25_p5', 0) for e in evaluaciones_precision) / n_ev, 2)
        ev_sem_avg  = round(sum(e.get('semantico_p5', 0) for e in evaluaciones_precision) / n_ev, 2)
        ev_diff_avg = round(ev_sem_avg - ev_bm25_avg, 2)

    return render_template('metricas.html', resumen=resumen, metricas=todas,
                           evaluaciones_precision=evaluaciones_precision,
                           ev_bm25_avg=ev_bm25_avg, ev_sem_avg=ev_sem_avg,
                           ev_diff_avg=ev_diff_avg,
                           version=VERSION_APP, creador=CREATOR_APP)


@app.route('/metricas/datos')
def metricas_datos():
    """API JSON con el resumen comparativo de métricas para consumo desde JavaScript"""
    return jsonify(metrics.calcular_resumen_comparativo())


@app.route('/metricas/precision-datos')
def metricas_precision_datos():
    """API JSON con historial de evaluaciones Precisión@5"""
    evaluaciones = []
    if os.path.exists(_EVALUACIONES_PATH):
        try:
            with open(_EVALUACIONES_PATH, 'r', encoding='utf-8') as f:
                evaluaciones = json.load(f)
        except Exception:
            evaluaciones = []
    return jsonify(evaluaciones)


@app.route('/evaluar-precision', methods=['POST'])
def evaluar_precision():
    """Retorna top-5 BM25 puro y top-5 BM25+Semántico para una consulta."""
    try:
        data  = request.get_json()
        texto = (data.get('texto') or '').strip()
        n     = int(data.get('n', 5))
        if not texto:
            return jsonify({'success': False, 'error': 'Consulta vacía'}), 400

        query_base = {
            "query": {
                "bool": {
                    "must": [{
                        "multi_match": {
                            "query": texto,
                            "type": "best_fields",
                            "minimum_should_match": "60%",
                            "fields": [
                                "titulo_norma^5", "resumen^4", "texto^3",
                                "entidades.personas^2", "entidades.lugares^2",
                                "entidades.organizaciones^2", "entidades.leyes^2",
                                "entidades.otros", "tipo_norma^3", "entidad_emisora^3",
                                "temas.palabra^4"
                            ]
                        }
                    }]
                }
            }
        }

        resultado = elastic.buscar(
            index=ELASTIC_INDEX_DEFAULT,
            query=query_base,
            size=100
        )
        if not resultado.get('success'):
            return jsonify({'success': False, 'error': resultado.get('error', 'Error ES')}), 500

        hits_raw = resultado.get('resultados', [])

        def extraer_campos(hits):
            return [h.get('_source') or {} for h in hits]

        bm25_hits      = extraer_campos(hits_raw[:n])
        sem_list       = pln_busqueda.buscar_conceptual(texto, list(hits_raw), campo_texto='texto')
        semantico_hits = extraer_campos(sem_list[:n])

        return jsonify({'success': True, 'bm25': bm25_hits, 'semantico': semantico_hits})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/guardar-evaluacion', methods=['POST'])
def guardar_evaluacion():
    """Calcula P@5 y persiste la evaluación en evaluaciones_precision.json."""
    try:
        data     = request.get_json()
        consulta = (data.get('consulta') or '').strip()
        bm25_rel = data.get('bm25_relevantes', [])
        sem_rel  = data.get('semantico_relevantes', [])

        if not consulta:
            return jsonify({'success': False, 'error': 'Consulta vacía'}), 400

        # P@5: fracción de los primeros 5 resultados marcados como relevantes por el usuario (True/False); máximo 1.0.
        bm25_p5 = round(sum(1 for r in bm25_rel if r) / 5, 2)
        sem_p5  = round(sum(1 for r in sem_rel  if r) / 5, 2)

        evaluacion = {
            'consulta':             consulta,
            'timestamp':            datetime.now().isoformat(),
            'bm25_p5':              bm25_p5,
            'semantico_p5':         sem_p5,
            'bm25_relevantes':      bm25_rel,
            'semantico_relevantes': sem_rel,
        }

        evaluaciones = []
        if os.path.exists(_EVALUACIONES_PATH):
            try:
                with open(_EVALUACIONES_PATH, 'r', encoding='utf-8') as f:
                    evaluaciones = json.load(f)
            except Exception:
                evaluaciones = []

        evaluaciones.append(evaluacion)
        os.makedirs('static/metrics', exist_ok=True)
        with open(_EVALUACIONES_PATH, 'w', encoding='utf-8') as f:
            json.dump(evaluaciones, f, ensure_ascii=False, indent=2)

        return jsonify({'success': True, 'bm25_p5': bm25_p5, 'semantico_p5': sem_p5})

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/procesar-fase1')
def procesar_fase1():
    """Ejecuta fase 1 del pipeline con progreso SSE."""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    if not session.get('permisos', {}).get('admin_data_elastic'):
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    # request.args debe leerse FUERA de generate(): dentro del generator SSE el
    # contexto de petición Flask puede no estar activo, causando RuntimeError.
    archivos_json = request.args.get('archivos', '[]')
    index         = request.args.get('index', '')

    try:
        archivos = json.loads(archivos_json)
    except Exception:
        archivos = []

    if not archivos or not index:
        return jsonify({'success': False,
                       'error': 'Archivos e índice son requeridos'}), 400

    # Patrón SSE (Server-Sent Events): generate() es un generator que yield-ea eventos
    # JSON con formato "data: {...}\n\n". Flask hace streaming de cada yield al cliente
    # (EventSource en JS) sin esperar al final del procesamiento, mostrando progreso
    # en tiempo real durante el pipeline PLN (extracción, NER, resumen, etc.).
    def generate():
        def evento(tipo, mensaje):
            yield f"data: {json.dumps({'tipo': tipo, 'mensaje': mensaje})}\n\n"

        resultados    = []
        tiempos_fase1 = []

        # Deduplicación
        eventos_omitidos = []
        omitidos = []
        def on_omitido(nombre):
            omitidos.append(nombre)
            eventos_omitidos.append(
                f"data: {json.dumps({'tipo': 'omitido', 'mensaje': f'{nombre} → ya indexado, omitido'})}\n\n"
            )

        archivos_nuevos = pipeline.filtrar_archivos_nuevos(
            archivos, index, elastic, on_omitido=on_omitido
        )
        for ev in eventos_omitidos:
            yield ev

        if not archivos_nuevos:
            yield from evento('fin', json.dumps({
                'success': True, 'resultados': [],
                'omitidos': omitidos,
                'mensaje': f'{len(omitidos)} archivo(s) ya indexados.'
            }))
            return

        total = len(archivos_nuevos)
        for i, archivo in enumerate(archivos_nuevos, 1):
            ruta         = archivo.get('ruta', '')
            nombre       = archivo.get('nombre', '')
            hash_archivo = archivo.get('hash_archivo', '')

            yield from evento('archivo', f'[{i}/{total}] {nombre}')
            print(f'[Fase 1] [{i}/{total}] {nombre}')

            doc, metricas_doc = pipeline.procesar_fase1(
                ruta, nombre, hash_archivo, pln_busqueda
            )

            ext               = metricas_doc.get('extraccion_texto') or {}
            meta              = metricas_doc.get('metadatos') or {}
            res               = metricas_doc.get('resumen') or {}
            ext_metodo        = ext.get('metodo', '?')
            ext_longitud      = ext.get('longitud_caracteres', 0)
            num_chunks        = res.get('num_chunks', 0)
            completitud       = meta.get('completitud_porcentaje')
            tiempo_small      = res.get('tiempo_segundos')
            perplexidad_small = res.get('perplexidad')
            resumen_small     = doc.get('resumen', '') if doc else ''

            yield from evento('ok', f'  → Texto: {ext_metodo} ({ext_longitud} chars)')
            yield from evento('ok', f'  → Metadatos: {completitud}%')
            yield from evento('ok',
                f'  → Resumen: {num_chunks} segmentos, '
                f'{tiempo_small}s, perpl: {perplexidad_small}')

            if tiempo_small is not None:
                tiempos_fase1.append(tiempo_small)

            resultados.append({
                'nombre':                        nombre,
                'hash_archivo':                  hash_archivo,
                'resumen_small':                 resumen_small,
                'perplexidad_small':             perplexidad_small,
                'tiempo_small':                  tiempo_small,
                'completitud_metadatos':         completitud,
                'completitud_metadatos_detalle': meta,
                'documento':                     doc,
            })

        tiempo_promedio = (sum(tiempos_fase1) / len(tiempos_fase1)) \
                          if tiempos_fase1 else 0
        estimacion = pipeline.estimar_tiempo_fase2(
            len(resultados), tiempo_promedio
        )

        yield from evento('fin', json.dumps({
            'success':          True,
            'resultados':       resultados,
            'estimacion_fase2': estimacion,
            'omitidos':         omitidos,
        }))

    return Response(generate(),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache',
                             'X-Accel-Buffering': 'no'})


@app.route('/procesar-fase2')
def procesar_fase2():
    """Ejecuta fase 2 del pipeline con el modelo de Fase 2 configurado, con progreso SSE."""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    if not session.get('permisos', {}).get('admin_data_elastic'):
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    archivos_json = request.args.get('archivos', '[]')
    try:
        archivos = json.loads(archivos_json)
    except Exception:
        archivos = []

    cfg = pipeline.cargar_config_modelos()
    # Nombre de display del modelo de fase 2 para los mensajes SSE; se resuelve antes de generate() para que quede capturado en el cierre.
    _nombre_fase2 = next(
        (m['nombre'] for m in cfg.get('summarizer', [])
         if m['id'] == cfg.get('configuracion_activa', {}).get('modelo_fase2')),
        'Fase 2'
    )

    def generate():
        def evento(tipo, mensaje):
            yield f"data: {json.dumps({'tipo': tipo, 'mensaje': mensaje})}\n\n"

        resultados = []
        total      = len(archivos)

        for i, archivo in enumerate(archivos, 1):
            nombre        = archivo.get('nombre', '')
            hash_archivo  = archivo.get('hash_archivo', '')
            metricas_meta = archivo.get('completitud_metadatos') or {}

            yield from evento('archivo', f'[{i}/{total}] {nombre}')
            print(f'[Fase 2] [{i}/{total}] {nombre}')
            yield from evento('info', '  → Cargando texto temporal...')

            texto = pipeline.cargar_texto_temporal(hash_archivo)
            if not texto:
                yield from evento('error',
                    f'  → Sin texto temporal para {nombre}, omitido')
                continue

            yield from evento('ok',
                f'  → Texto cargado ({len(texto)} chars)')
            yield from evento('info', f'  → Generando resumen con {_nombre_fase2} (puede tardar)...')

            resumen_base, metricas_doc = pipeline.procesar_fase2(
                texto, nombre, hash_archivo, pln_busqueda,
                completitud_metadatos=metricas_meta
            )

            res              = metricas_doc.get('resumen') or {}
            num_chunks       = res.get('num_chunks', 0)
            tiempo_base      = res.get('tiempo_segundos', 0)
            perplexidad_base = res.get('perplexidad', '?')

            yield from evento('ok',
                f'  → {_nombre_fase2}: {num_chunks} segmentos, '
                f'{tiempo_base}s, perpl: {perplexidad_base}')

            resultados.append({
                'nombre':           nombre,
                'hash_archivo':     hash_archivo,
                'resumen_base':     resumen_base,
                'perplexidad_base': res.get('perplexidad'),
                'tiempo_base':      res.get('tiempo_segundos'),
            })

        yield from evento('fin', json.dumps({
            'success':    True,
            'resultados': resultados,
        }))

    return Response(generate(),
                    mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache',
                             'X-Accel-Buffering': 'no'})


@app.route('/indexar-seleccionados', methods=['POST'])
def indexar_seleccionados():
    """API que indexa documentos usando el resumen elegido (fase1 o fase2)."""
    if not session.get('logged_in'):
        return jsonify({'success': False, 'error': 'No autorizado'}), 401
    if not session.get('permisos', {}).get('admin_data_elastic'):
        return jsonify({'success': False, 'error': 'Sin permisos'}), 403

    data       = request.get_json()
    documentos = data.get('documentos', [])
    index      = data.get('index', '')

    if not documentos or not index:
        return jsonify({'success': False, 'error': 'Documentos e índice son requeridos'}), 400

    cfg = pipeline.cargar_config_modelos()
    cfg_activa = cfg.get('configuracion_activa', {})
    summarizers_hf = {m['id']: m.get('modelo_hf', '') for m in cfg.get('summarizer', [])}
    # Mapea fase1/fase2 al modelo_hf real para registrarlo en el documento indexado: permite saber qué modelo generó el resumen en cada versión.
    _MODELO_HF = {
        'fase1': summarizers_hf.get(cfg_activa.get('modelo_fase1', ''), 'google/mt5-small'),
        'fase2': summarizers_hf.get(cfg_activa.get('modelo_fase2', ''), 'google/mt5-base'),
    }
    docs_a_indexar = []

    for item in documentos:
        doc           = item.get('documento') or {}
        eleccion      = item.get('resumen_elegido', 'fase1')
        resumen_small = item.get('resumen_small', '')
        resumen_base  = item.get('resumen_base', '')

        doc['resumen']        = resumen_base if eleccion == 'fase2' else resumen_small
        doc['modelo_resumen'] = _MODELO_HF.get(eleccion, _MODELO_HF['fase1'])
        docs_a_indexar.append(doc)

    resultado = elastic.indexar_bulk(index, docs_a_indexar)

    # Elimina los JSONs de texto en static/temp/ ya que el documento fue indexado y el texto puede ocupar varios MB por archivo.
    for doc_data in documentos:
        hash_a = (doc_data.get('documento') or {}).get('hash_archivo')
        if hash_a:
            pipeline.eliminar_texto_temporal(hash_a)

    return jsonify({
        'success':   resultado.get('success', False),
        'indexados': resultado.get('indexados', 0),
        'errores':   resultado.get('fallidos', 0),
    })


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