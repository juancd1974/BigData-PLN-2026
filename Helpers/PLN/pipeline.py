"""
Pipeline de procesamiento de documentos normativos para NormaSearch.

Orquesta las etapas de extracción de texto, NER, metadatos, temas y resumen
sobre archivos PDF y TXT, coordinando PLN.py, entity_extractor, summarizer y
metrics. Expone dos flujos de procesamiento:

  procesar_fase1()  → pipeline completo con el modelo liviano (mT5-small)
  procesar_fase2()  → solo resumen con el modelo de mayor calidad (mT5-base)

Diseño de dos fases:
  La fase 1 usa mT5-small (rápido, ~30 s/doc en CPU) para generar un resumen
  provisional. La fase 2, opcional, usa mT5-base (más lento, mejor calidad)
  sobre el mismo texto ya extraído. El texto se persiste en static/temp/ entre
  fases porque ambas ocurren en peticiones HTTP separadas (EventSource) y el
  texto puede superar varios MB — demasiado grande para enviarlo al browser y
  de vuelta.

  Cada fase genera su propio archivo de métricas en static/metrics/:
    {hash}_{modelo_fase1}.json  → extracción + NER + metadatos + resumen fase 1
    {hash}_{modelo_fase2}.json  → solo resumen fase 2 (sin datos de extracción)

Los errores por etapa se registran en consola sin interrumpir el pipeline:
el documento se indexa con los campos que se pudieron extraer correctamente.

Configuración de modelos: config/models_config.json
Métricas por documento:   static/metrics/<hash>_<modelo>.json
"""

import gc
import json
import os
import torch
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from Helpers.PLN import entity_extractor, metrics, summarizer
from Helpers.Utils.funciones import Funciones

_CONFIG_PATH = 'config/models_config.json'


def cargar_config_modelos() -> Dict:
    """
    Lee y retorna el contenido de config/models_config.json.

    Returns:
        Diccionario con la configuración de modelos, o {} si el archivo
        no existe o no es un JSON válido.
    """
    try:
        with open(_CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def guardar_config_modelos(config: Dict) -> bool:
    """
    Persiste el diccionario de configuración en config/models_config.json.

    Args:
        config: Diccionario completo de configuración de modelos.

    Returns:
        True si se guardó correctamente, False si hubo un error.
    """
    try:
        with open(_CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)
        return True
    except Exception as exc:
        print(f"  ✗ Error al guardar configuración: {exc}")
        return False


TEMP_DIR = 'static/temp'


def guardar_texto_temporal(hash_archivo: str, nombre_archivo: str,
                            texto: str) -> Optional[str]:
    """
    Guarda el texto extraído de un PDF en un JSON temporal en static/temp/.

    El texto se almacena en disco porque la fase 1 y la fase 2 ocurren en dos
    peticiones HTTP separadas (EventSource en el browser). El texto puede tener
    varios MB — demasiado grande para enviarlo en la respuesta SSE y de vuelta
    en la petición de fase 2. Los archivos en static/temp/ sirven de canal de
    comunicación entre fases sin pasar por el browser.

    Args:
        hash_archivo:   Hash SHA-256 con prefijo "sha256:".
        nombre_archivo: Nombre del archivo PDF fuente.
        texto:          Texto extraído del documento.

    Returns:
        Ruta del archivo guardado, o None si falló.
    """
    try:
        os.makedirs(TEMP_DIR, exist_ok=True)
        hash_limpio = hash_archivo.replace("sha256:", "")
        ruta = os.path.join(TEMP_DIR, f"{hash_limpio}.json")
        datos = {
            "nombre_archivo": nombre_archivo,
            "hash_archivo": hash_archivo,
            "texto": texto,
            "fecha_extraccion": datetime.now().isoformat(),
        }
        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(datos, f, indent=4, ensure_ascii=False)
        return ruta
    except Exception as exc:
        print(f"Error al guardar texto temporal: {exc}")
        return None


def cargar_texto_temporal(hash_archivo: str) -> Optional[str]:
    """
    Carga el texto desde el JSON temporal correspondiente al hash.

    Args:
        hash_archivo: Hash SHA-256 con prefijo "sha256:".

    Returns:
        Texto como string, o None si el archivo no existe o no se puede leer.
    """
    try:
        hash_limpio = hash_archivo.replace("sha256:", "")
        ruta = os.path.join(TEMP_DIR, f"{hash_limpio}.json")
        if not os.path.exists(ruta):
            return None
        with open(ruta, 'r', encoding='utf-8') as f:
            datos = json.load(f)
        return datos.get("texto")
    except Exception as exc:
        print(f"Error al cargar texto temporal: {exc}")
        return None


def eliminar_texto_temporal(hash_archivo: str) -> bool:
    """
    Elimina el JSON temporal correspondiente al hash.

    Args:
        hash_archivo: Hash SHA-256 con prefijo "sha256:".

    Returns:
        True si se eliminó correctamente o el archivo no existía,
        False si hubo un error al eliminar.
    """
    try:
        hash_limpio = hash_archivo.replace("sha256:", "")
        ruta = os.path.join(TEMP_DIR, f"{hash_limpio}.json")
        if not os.path.exists(ruta):
            return True
        os.remove(ruta)
        return True
    except Exception as exc:
        print(f"Error al eliminar texto temporal: {exc}")
        return False


def obtener_modelo_resumen_activo() -> str:
    """
    Retorna el modelo_hf del summarizer marcado como activo en la configuración.

    Returns:
        Identificador HuggingFace del modelo activo, o "google/mt5-small"
        si no se puede leer la configuración.
    """
    fallback = 'google/mt5-small'
    config = cargar_config_modelos()
    if not config:
        return fallback

    activo_id = config.get('configuracion_activa', {}).get('summarizer_activo')
    if not activo_id:
        return fallback

    for modelo in config.get('summarizer', []):
        if modelo.get('id') == activo_id:
            return modelo.get('modelo_hf', fallback)

    return fallback


def obtener_modelo_fase(fase: str) -> str:
    """
    Retorna el modelo_hf configurado para la fase indicada.

    Lee configuracion_activa.modelo_fase1 o modelo_fase2 según el parámetro
    y busca el modelo_hf correspondiente en el array summarizer.

    Args:
        fase: 'fase1' o 'fase2'.

    Returns:
        Identificador HuggingFace del modelo, o el fallback si no se puede
        leer la configuración ('google/mt5-small' para fase1,
        'ELiRF/mt5-base-dacsa-es' para fase2).
    """
    fallbacks = {
        'fase1': 'google/mt5-small',
        'fase2': 'ELiRF/mt5-base-dacsa-es',
    }
    fallback = fallbacks.get(fase, 'google/mt5-small')
    config = cargar_config_modelos()
    if not config:
        return fallback

    campo = 'modelo_fase1' if fase == 'fase1' else 'modelo_fase2'
    modelo_id = config.get('configuracion_activa', {}).get(campo)
    if not modelo_id:
        return fallback

    for modelo in config.get('summarizer', []):
        if modelo.get('id') == modelo_id:
            return modelo.get('modelo_hf', fallback)

    return fallback


def liberar_modelo_resumen(pln) -> None:
    """
    Libera la memoria del modelo de resumen cargado en el objeto PLN.

    Anula la referencia al pipeline, vacía la caché CUDA si está disponible
    y fuerza una pasada del recolector de basura.

    Args:
        pln: Instancia de PLN con _pipeline_resumen cargado.
    """
    pln._pipeline_resumen = None
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()
    print("  → Modelo de resumen liberado de memoria.")


def procesar_documento(ruta: str, nombre: str, hash_archivo: str,
                       pln, modelo_resumen: str,
                       callback=None) -> Tuple[Optional[Dict], Dict]:
    """
    Orquesta el pipeline completo para un documento normativo.

    Pasos: extracción de texto → NER → metadatos → temas → resumen.
    Cada paso registra sus métricas en el diccionario de métricas del
    documento. Los errores en NER, metadatos y resumen se registran en
    consola sin interrumpir el pipeline.

    Args:
        ruta:           Ruta absoluta o relativa al archivo.
        nombre:         Nombre del archivo (con extensión).
        hash_archivo:   Hash SHA-256 con prefijo "sha256:".
        pln:            Instancia de PLN con spaCy cargado.
        modelo_resumen: Identificador HuggingFace del modelo de resumen.
        callback:       Función opcional callback(tipo, mensaje) para
                        recibir mensajes de progreso en tiempo real.
                        tipo: 'info', 'ok', 'error', 'progreso'.

    Returns:
        Tupla (documento_elastic, metricas). documento_elastic es None si
        el texto extraído tiene menos de 50 caracteres.
    """
    metricas = metrics.inicializar_metricas_documento(nombre, hash_archivo)
    extension = os.path.splitext(nombre)[1].lower().lstrip('.')

    # ── a. Extracción de texto ────────────────────────────────────────────
    if callback: callback('info', 'Extrayendo texto...')
    texto = ''
    if extension == 'pdf':
        texto, metricas_ext = Funciones.extraer_texto_pdf_con_metricas(ruta)
    else:
        import time as _time
        t0 = _time.time()
        try:
            with open(ruta, 'r', encoding='utf-8') as f:
                texto = f.read()
        except UnicodeDecodeError:
            with open(ruta, 'r', encoding='latin-1') as f:
                texto = f.read()
        metricas_ext = {
            'metodo': 'txt',
            'tiempo_segundos': round(_time.time() - t0, 3),
            'longitud_caracteres': len(texto),
            'calidad_ok': len(texto.strip()) >= 50,
        }

    metricas = metrics.registrar_extraccion_texto(
        metricas,
        metodo=metricas_ext['metodo'],
        tiempo=metricas_ext['tiempo_segundos'],
        longitud=metricas_ext['longitud_caracteres'],
        calidad_ok=metricas_ext['calidad_ok'],
    )
    if callback: callback('ok', f"Texto extraído ({metricas_ext['metodo']}, {metricas_ext['longitud_caracteres']} chars, {metricas_ext['tiempo_segundos']}s)")
    guardar_texto_temporal(hash_archivo, nombre, texto)

    if not texto or len(texto.strip()) < 50:
        print(f"  ✗ Texto insuficiente en '{nombre}'. Se omite el documento.")
        if callback: callback('error', 'Texto insuficiente, documento omitido')
        metrics.guardar_metricas(metricas)
        return None, metricas

    # ── b. NER ────────────────────────────────────────────────────────────
    if callback: callback('info', 'Analizando entidades (NER)...')
    entidades: Dict = {}
    try:
        entidades, metricas_ner = entity_extractor.extraer_entidades_mejorado(
            pln.nlp, texto
        )
        metricas = metrics.registrar_ner(metricas, metricas_ner)
        if callback: callback('ok', f"NER completado ({metricas_ner.get('tiempo_ner_segundos', 0)}s)")
    except Exception as exc:
        print(f"  ✗ Error en NER para '{nombre}': {exc}")

    # ── c. Metadatos ──────────────────────────────────────────────────────
    if callback: callback('info', 'Extrayendo metadatos...')
    metadatos: Dict = {}
    try:
        metadatos, metricas_meta = entity_extractor.extraer_metadatos_mejorado(
            pln.nlp, texto, nombre_archivo=nombre
        )
        metricas = metrics.registrar_metadatos(metricas, metricas_meta)
        if callback: callback('ok', f"Metadatos: {metricas_meta.get('campos_completos', 0)}/5 campos ({metricas_meta.get('completitud_porcentaje', 0)}%)")
        if metadatos.get('fecha_documento'):
            fecha_norm = pln.normalizar_fecha(metadatos['fecha_documento'])
            if fecha_norm:
                metadatos['fecha_documento'] = fecha_norm
    except Exception as exc:
        print(f"  ✗ Error en metadatos para '{nombre}': {exc}")

    # ── d. Temas ──────────────────────────────────────────────────────────
    temas: List[Dict] = []
    try:
        temas_raw = pln.extraer_temas(texto[:500_000])
        temas = [{'palabra': p, 'relevancia': round(r, 4)} for p, r in temas_raw]
    except Exception as exc:
        print(f"  ✗ Error en extracción de temas para '{nombre}': {exc}")

    # ── e. Resumen ────────────────────────────────────────────────────────
    resumen = ''
    try:
        if callback: callback('info', f'Resumiendo con {modelo_resumen}...')
        if not pln._pipeline_resumen:
            pln.cargar_resumen(modelo_resumen)
        elif pln._pipeline_resumen.model.config.name_or_path != modelo_resumen:
            liberar_modelo_resumen(pln)
            pln.cargar_resumen(modelo_resumen)

        # generar_resumen_con_metricas() aplica preprocesar_para_transformer() internamente
        # (no limpiar_texto()): el AutoTokenizer de mT5 usa SentencePiece y necesita el
        # texto con puntuación, números y capitalización intactos para subword tokenization.
        # Aplicar limpiar_texto() antes degradaría la calidad del resumen generado.
        resumen, metricas_resumen = summarizer.generar_resumen_con_metricas(
            pln._pipeline_resumen, texto
        )
        metricas = metrics.registrar_resumen(metricas, metricas_resumen)
        if callback: callback('ok', f"Resumen generado ({metricas_resumen.get('num_chunks', 0)} segmentos, {metricas_resumen.get('tiempo_segundos', 0)}s, perpl: {metricas_resumen.get('perplexidad')})")
    except Exception as exc:
        print(f"  ✗ Error en resumen para '{nombre}': {exc}")

    # ── f. Persistencia ───────────────────────────────────────────────────
    metrics.guardar_metricas(metricas)

    # ── g. Documento para Elasticsearch ──────────────────────────────────
    documento_elastic = {
        'tipo_norma':      metadatos.get('tipo_norma'),
        'numero_norma':    metadatos.get('numero_norma'),
        'anio_norma':      metadatos.get('anio_norma'),
        'entidad_emisora': metadatos.get('entidad_emisora'),
        'fecha_documento': metadatos.get('fecha_documento'),
        'titulo_norma':    metadatos.get('titulo_norma'),
        'texto':           texto[:2_000_000],
        'resumen':         resumen,
        'entidades':       entidades,
        'temas':           temas,
        'ruta':            ruta,
        'nombre_archivo':  nombre,
        'hash_archivo':    hash_archivo,
        'fecha_carga':     datetime.now().isoformat(),
    }

    return documento_elastic, metricas


def filtrar_archivos_nuevos(archivos: List[Dict],
                             index: str, elastic,
                             on_omitido=None) -> List[Dict]:
    """
    Filtra de una lista de archivos los que ya están indexados en Elasticsearch.

    Para cada archivo calcula su hash SHA-256 y verifica si ya existe en el
    índice. Solo retorna los archivos cuyo hash no está presente.

    Args:
        archivos:   Lista de dicts con al menos la clave 'ruta'.
        index:      Nombre del índice de Elasticsearch.
        elastic:    Cliente Elasticsearch con método existe_hash().
        on_omitido: Callable opcional que recibe el nombre del archivo omitido.

    Returns:
        Lista de dicts de archivos nuevos, con la clave 'hash_archivo' agregada.
    """
    nuevos = []
    omitidos = 0

    for archivo in archivos:
        ruta = archivo.get('ruta', '')
        hash_archivo = Funciones.calcular_hash_archivo(ruta)
        if not hash_archivo:
            continue
        if elastic.existe_hash(hash_archivo, index):
            omitidos += 1
            if on_omitido:
                on_omitido(archivo.get('nombre', ''))
            continue
        archivo['hash_archivo'] = hash_archivo
        nuevos.append(archivo)

    if omitidos:
        print(f"  → {omitidos} archivo(s) omitido(s) por duplicado.")

    return nuevos


def procesar_fase1(ruta: str, nombre: str,
                   hash_archivo: str, pln,
                   callback=None) -> Tuple[Optional[Dict], Dict]:
    """
    Fase 1 del pipeline: extracción de texto, NER, metadatos, temas
    y resumen con el modelo configurado en fase 1.

    Alias semántico de procesar_documento(). El modelo de resumen se
    lee de config/models_config.json (configuracion_activa.modelo_fase1).

    Args:
        ruta:         Ruta absoluta o relativa al archivo.
        nombre:       Nombre del archivo (con extensión).
        hash_archivo: Hash SHA-256 con prefijo "sha256:".
        pln:          Instancia de PLN con spaCy cargado.
        callback:     Función opcional callback(tipo, mensaje) para
                      recibir mensajes de progreso en tiempo real.

    Returns:
        Tupla (documento_elastic, metricas) tal como la retorna
        procesar_documento().
    """
    return procesar_documento(ruta, nombre, hash_archivo, pln,
                              modelo_resumen=obtener_modelo_fase('fase1'),
                              callback=callback)


def procesar_fase2(texto: str, nombre: str,
                   hash_archivo: str, pln,
                   completitud_metadatos: dict = None,
                   callback=None) -> Tuple[str, Dict]:
    """
    Fase 2 del pipeline: resumen abstractivo con el modelo configurado
    en fase 2, sobre texto ya extraído en la fase 1.

    Carga el modelo indicado en config/models_config.json
    (configuracion_activa.modelo_fase2), liberando el anterior si es necesario.
    Registra métricas de resumen y las persiste en static/metrics/.

    Args:
        texto:                  Texto completo del documento (obtenido en fase 1).
        nombre:                 Nombre del archivo fuente.
        hash_archivo:           Hash SHA-256 con prefijo "sha256:".
        pln:                    Instancia de PLN con spaCy cargado.
        completitud_metadatos:  Dict de métricas de metadatos de fase 1 (opcional).
        callback:               Función opcional callback(tipo, mensaje) para
                                recibir mensajes de progreso en tiempo real.

    Returns:
        Tupla (resumen, metricas). Retorna ("", {}) si ocurre un error.
    """
    modelo_base = obtener_modelo_fase('fase2')
    try:
        # Nuevo dict de métricas independiente del de fase 1: el archivo resultante
        # ({hash}_{modelo_fase2}.json) coexiste con el de fase 1 en static/metrics/
        # y permite comparar perplejidad y tiempo de ambos modelos en el panel.
        # La sección extraccion_texto queda con calidad_ok=None (no hay extracción
        # en fase 2); calcular_resumen_comparativo() lo detecta y lo omite.
        metricas = metrics.inicializar_metricas_documento(nombre, hash_archivo)

        modelo_actual = (
            pln._pipeline_resumen.model.config.name_or_path
            if pln._pipeline_resumen else None
        )
        if pln._pipeline_resumen is None or modelo_actual != modelo_base:
            if callback: callback('info', f'Cargando {modelo_base}...')
            liberar_modelo_resumen(pln)
            pln.cargar_resumen(modelo_base)
            if callback: callback('ok', f'{modelo_base} listo')

        if callback: callback('info', f'Generando resumen con {modelo_base}...')
        resumen, metricas_resumen = summarizer.generar_resumen_con_metricas(
            pln._pipeline_resumen, texto
        )
        metricas = metrics.registrar_resumen(metricas, metricas_resumen)
        if callback: callback('ok', f"Resumen generado ({metricas_resumen.get('tiempo_segundos', 0)}s, perpl: {metricas_resumen.get('perplexidad')})")
        if completitud_metadatos:
            metricas = metrics.registrar_metadatos(metricas,
                                                   completitud_metadatos)
        metrics.guardar_metricas(metricas)

        return resumen, metricas
    except Exception as exc:
        print(f"  ✗ Error en fase 2 para '{nombre}': {exc}")
        return "", {}


def estimar_tiempo_fase2(num_documentos: int,
                          tiempo_promedio_fase1: float) -> Dict:
    """
    Estima el tiempo de procesamiento de la fase 2 con mT5-base.

    mT5-base tarda aproximadamente 2.5x más que mT5-small por documento.

    Args:
        num_documentos:        Número de documentos a procesar en fase 2.
        tiempo_promedio_fase1: Tiempo promedio por documento en fase 1
                               (segundos).

    Returns:
        Dict con segundos_estimados, minutos_estimados y mensaje legible.
    """
    # Factor 2.5: empírico, mT5-base tarda ~2.5× más que mT5-small por documento en las mismas condiciones de hardware.
    segundos = num_documentos * tiempo_promedio_fase1 * 2.5

    if segundos < 60:
        mensaje = "Menos de 1 minuto"
    elif segundos < 120:
        mensaje = "Aproximadamente 1 minuto"
    else:
        mensaje = f"Aproximadamente {round(segundos / 60)} minutos"

    return {
        'segundos_estimados': round(segundos, 1),
        'minutos_estimados':  round(segundos / 60, 2),
        'mensaje':            mensaje,
    }
