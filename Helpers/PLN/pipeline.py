"""
Orquestador del pipeline completo de procesamiento de documentos normativos.

Concentra la lógica de extracción, NER, metadatos, temas y resumen,
y delega el registro de métricas a Helpers.PLN.metrics.
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


def liberar_modelo_resumen(pln) -> None:
    """
    Libera la memoria del modelo de resumen cargado en el objeto PLN.

    Llama close(), anula la referencia al pipeline, vacía la caché CUDA
    si está disponible y fuerza una pasada del recolector de basura.

    Args:
        pln: Instancia de PLN con _pipeline_resumen cargado.
    """
    pln.close()
    pln._pipeline_resumen = None
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    gc.collect()
    print("  → Modelo de resumen liberado de memoria.")


def procesar_documento(ruta: str, nombre: str, hash_archivo: str,
                       pln, modelo_resumen: str) -> Tuple[Optional[Dict], Dict]:
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

    Returns:
        Tupla (documento_elastic, metricas). documento_elastic es None si
        el texto extraído tiene menos de 50 caracteres.
    """
    metricas = metrics.inicializar_metricas_documento(nombre, hash_archivo)
    extension = os.path.splitext(nombre)[1].lower().lstrip('.')

    # ── a. Extracción de texto ────────────────────────────────────────────
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
    Funciones.guardar_texto_temporal(hash_archivo, nombre, texto)

    if not texto or len(texto.strip()) < 50:
        print(f"  ✗ Texto insuficiente en '{nombre}'. Se omite el documento.")
        return None, metricas

    # ── b. NER ────────────────────────────────────────────────────────────
    entidades: Dict = {}
    try:
        entidades, metricas_ner = entity_extractor.extraer_entidades_mejorado(
            pln.nlp, texto
        )
        metricas = metrics.registrar_ner(metricas, metricas_ner)
    except Exception as exc:
        print(f"  ✗ Error en NER para '{nombre}': {exc}")

    # ── c. Metadatos ──────────────────────────────────────────────────────
    metadatos: Dict = {}
    try:
        metadatos, metricas_meta = entity_extractor.extraer_metadatos_mejorado(
            pln.nlp, texto, nombre_archivo=nombre
        )
        metricas = metrics.registrar_metadatos(metricas, metricas_meta)
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
        if not pln._pipeline_resumen:
            pln.cargar_resumen(modelo_resumen)
        elif pln._pipeline_resumen.model.config.name_or_path != modelo_resumen:
            liberar_modelo_resumen(pln)
            pln.cargar_resumen(modelo_resumen)

        resumen, metricas_resumen = summarizer.generar_resumen_con_metricas(
            pln._pipeline_resumen, texto
        )
        metricas = metrics.registrar_resumen(metricas, metricas_resumen)
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
                             index: str, elastic) -> List[Dict]:
    """
    Filtra de una lista de archivos los que ya están indexados en Elasticsearch.

    Para cada archivo calcula su hash SHA-256 y verifica si ya existe en el
    índice. Solo retorna los archivos cuyo hash no está presente.

    Args:
        archivos: Lista de dicts con al menos la clave 'ruta'.
        index:    Nombre del índice de Elasticsearch.
        elastic:  Cliente Elasticsearch con método existe_hash().

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
            continue
        archivo['hash_archivo'] = hash_archivo
        nuevos.append(archivo)

    if omitidos:
        print(f"  → {omitidos} archivo(s) omitido(s) por duplicado.")

    return nuevos


def procesar_fase1(ruta: str, nombre: str,
                   hash_archivo: str, pln) -> Tuple[Optional[Dict], Dict]:
    """
    Fase 1 del pipeline: extracción de texto, NER, metadatos, temas
    y resumen con mT5-small.

    Alias semántico de procesar_documento() con modelo fijo 'google/mt5-small'.
    Permite claridad en flujos que distinguen fase 1 (mT5-small) de
    fase 2 (mT5-base).

    Args:
        ruta:         Ruta absoluta o relativa al archivo.
        nombre:       Nombre del archivo (con extensión).
        hash_archivo: Hash SHA-256 con prefijo "sha256:".
        pln:          Instancia de PLN con spaCy cargado.

    Returns:
        Tupla (documento_elastic, metricas) tal como la retorna
        procesar_documento().
    """
    return procesar_documento(ruta, nombre, hash_archivo, pln,
                              modelo_resumen='google/mt5-small')


def procesar_fase2(texto: str, nombre: str,
                   hash_archivo: str, pln) -> Tuple[str, Dict]:
    """
    Fase 2 del pipeline: resumen abstractivo con mT5-base sobre texto
    ya extraído en la fase 1.

    Carga mT5-base liberando el modelo anterior si es necesario.
    Registra métricas de resumen y las persiste en static/metrics/.

    Args:
        texto:        Texto completo del documento (obtenido en fase 1).
        nombre:       Nombre del archivo fuente.
        hash_archivo: Hash SHA-256 con prefijo "sha256:".
        pln:          Instancia de PLN con spaCy cargado.

    Returns:
        Tupla (resumen, metricas). Retorna ("", {}) si ocurre un error.
    """
    modelo_base = 'google/mt5-base'
    try:
        metricas = metrics.inicializar_metricas_documento(nombre, hash_archivo)

        modelo_actual = (
            pln._pipeline_resumen.model.config.name_or_path
            if pln._pipeline_resumen else None
        )
        if pln._pipeline_resumen is None or modelo_actual != modelo_base:
            liberar_modelo_resumen(pln)
            pln.cargar_resumen(modelo_base)

        resumen, metricas_resumen = summarizer.generar_resumen_con_metricas(
            pln._pipeline_resumen, texto
        )
        metricas = metrics.registrar_resumen(metricas, metricas_resumen)
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
