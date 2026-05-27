"""
Registro y persistencia de métricas operacionales del pipeline PLN.

Centraliza la captura de tiempos, calidad de extracción, completitud de
metadatos y métricas de resumen para comparación entre modelos.

Cada documento procesado genera un JSON en static/metrics/ con cuatro secciones:
  extraccion_texto → método (pymupdf/ocr), tiempo, longitud, calidad_ok
  ner              → tiempo de inferencia, conteo de entidades por categoría
  metadatos        → campos completos/vacíos y completitud porcentual
  resumen          → modelo usado, tiempo, chunks, longitud y perplejidad

Usar calcular_resumen_comparativo() para agregar métricas de todos los
documentos y comparar el rendimiento entre modelos de resumen.
"""

import json
import os
from datetime import datetime
from typing import Dict, List, Optional

METRICAS_DIR = 'static/metrics'

os.makedirs(METRICAS_DIR, exist_ok=True)


def inicializar_metricas_documento(nombre_archivo: str, hash_archivo: str) -> Dict:
    """
    Crea y retorna el diccionario base de métricas para un documento.

    Todos los campos de secciones internas se inicializan en None y se
    rellenan progresivamente con las funciones registrar_*() conforme
    avanza el pipeline.

    Args:
        nombre_archivo: Nombre del archivo procesado.
        hash_archivo:   Hash SHA-256 con prefijo "sha256:".

    Returns:
        Diccionario de métricas inicializado.
    """
    return {
        "nombre_archivo": nombre_archivo,
        "hash_archivo": hash_archivo,
        "fecha_procesamiento": datetime.now().isoformat(),
        "extraccion_texto": {
            "metodo": None,
            "tiempo_segundos": None,
            "longitud_caracteres": None,
            "calidad_ok": None,
        },
        "ner": {
            "tiempo_ner_segundos": None,
            "entidades_por_categoria": None,
        },
        "metadatos": {
            "campos_completos": None,
            "campos_vacios": None,
            "completitud_porcentaje": None,
            "detalle_campos": None,
        },
        "resumen": {
            "modelo": None,
            "tiempo_segundos": None,
            "num_chunks": None,
            "longitud_resumen": None,
            "longitud_texto": None,
            "perplexidad": None,
        },
    }


def registrar_extraccion_texto(metricas: Dict, metodo: str, tiempo: float,
                               longitud: int, calidad_ok: bool) -> Dict:
    """
    Rellena la sección 'extraccion_texto' del diccionario de métricas.

    Args:
        metricas:   Diccionario de métricas del documento.
        metodo:     Método de extracción usado: "pymupdf" o "ocr".
        tiempo:     Tiempo de extracción en segundos.
        longitud:   Número de caracteres extraídos.
        calidad_ok: True si la extracción superó el control de calidad.

    Returns:
        Diccionario de métricas actualizado.
    """
    metricas["extraccion_texto"] = {
        "metodo": metodo,
        "tiempo_segundos": tiempo,
        "longitud_caracteres": longitud,
        "calidad_ok": calidad_ok,
    }
    return metricas


def registrar_ner(metricas: Dict, metricas_ner: Dict) -> Dict:
    """
    Rellena la sección 'ner' con el dict de métricas de extraer_entidades_mejorado().

    Args:
        metricas:     Diccionario de métricas del documento.
        metricas_ner: Segundo elemento de la tupla retornada por
                      extraer_entidades_mejorado().

    Returns:
        Diccionario de métricas actualizado.
    """
    metricas["ner"] = {
        "tiempo_ner_segundos": metricas_ner.get("tiempo_ner_segundos"),
        "entidades_por_categoria": metricas_ner.get("entidades_por_categoria"),
    }
    return metricas


def registrar_metadatos(metricas: Dict, metricas_meta: Dict) -> Dict:
    """
    Rellena la sección 'metadatos' con el dict de métricas de extraer_metadatos_mejorado().

    Args:
        metricas:      Diccionario de métricas del documento.
        metricas_meta: Segundo elemento de la tupla retornada por
                       extraer_metadatos_mejorado().

    Returns:
        Diccionario de métricas actualizado.
    """
    metricas["metadatos"] = {
        "campos_completos": metricas_meta.get("campos_completos"),
        "campos_vacios": metricas_meta.get("campos_vacios"),
        "completitud_porcentaje": metricas_meta.get("completitud_porcentaje"),
        "detalle_campos": metricas_meta.get("detalle_campos"),
    }
    return metricas


def registrar_resumen(metricas: Dict, metricas_resumen: Dict) -> Dict:
    """
    Rellena la sección 'resumen' con el dict de métricas de generar_resumen_con_metricas().

    Args:
        metricas:         Diccionario de métricas del documento.
        metricas_resumen: Segundo elemento de la tupla retornada por
                          generar_resumen_con_metricas().

    Returns:
        Diccionario de métricas actualizado.
    """
    metricas["resumen"] = {
        "modelo": metricas_resumen.get("modelo"),
        "tiempo_segundos": metricas_resumen.get("tiempo_segundos"),
        "num_chunks": metricas_resumen.get("num_chunks"),
        "longitud_resumen": metricas_resumen.get("longitud_resumen"),
        "longitud_texto": metricas_resumen.get("longitud_texto"),
        "perplexidad": metricas_resumen.get("perplexidad"),
    }
    return metricas


def guardar_metricas(metricas: Dict) -> Optional[str]:
    """
    Persiste el diccionario de métricas como JSON en static/metrics/.

    Nombre del archivo: <hash_limpio>_<modelo_resumen>.json
    donde hash_limpio es el hash sin el prefijo "sha256:" y
    modelo_resumen es el nombre del modelo con "/" reemplazado por "_".

    Args:
        metricas: Diccionario de métricas completo del documento.

    Returns:
        Ruta del archivo guardado, o None si falló.
    """
    try:
        hash_raw = metricas.get("hash_archivo", "sin_hash")
        hash_limpio = hash_raw.replace("sha256:", "")

        modelo_raw = metricas.get("resumen", {}).get("modelo") or "sin_modelo"
        modelo_nombre = modelo_raw.replace("/", "_")

        nombre_archivo = f"{hash_limpio}_{modelo_nombre}.json"
        ruta = os.path.join(METRICAS_DIR, nombre_archivo)

        with open(ruta, 'w', encoding='utf-8') as f:
            json.dump(metricas, f, indent=4, ensure_ascii=False)

        return ruta
    except Exception as exc:
        print(f"  ✗ Error al guardar métricas: {exc}")
        return None


def cargar_todas_las_metricas() -> List[Dict]:
    """
    Lee todos los archivos JSON de static/metrics/ y los retorna como lista.

    Ignora archivos que no sean JSON válidos. No lanza excepción si la
    carpeta no existe o está vacía.

    Returns:
        Lista de diccionarios de métricas. Vacía si no hay archivos o
        la carpeta no existe.
    """
    if not os.path.exists(METRICAS_DIR):
        return []

    resultado = []
    for nombre in os.listdir(METRICAS_DIR):
        if not nombre.lower().endswith('.json'):
            continue
        ruta = os.path.join(METRICAS_DIR, nombre)
        try:
            with open(ruta, 'r', encoding='utf-8') as f:
                resultado.append(json.load(f))
        except (json.JSONDecodeError, OSError):
            pass

    return resultado


def calcular_resumen_comparativo() -> Dict:
    """
    Lee todas las métricas guardadas y calcula estadísticas comparativas
    agrupadas por modelo de resumen y método de extracción de texto.

    Los documentos con perplexidad == -1.0 se excluyen de los promedios
    de perplejidad pero sí cuentan para total_documentos y tiempo_promedio.

    Returns:
        Dict con dos secciones: 'por_modelo' y 'extraccion'.
    """
    todas = cargar_todas_las_metricas()

    por_modelo: Dict[str, Dict] = {}
    total_docs = 0
    pymupdf_count = 0
    ocr_count = 0
    calidad_ok_count = 0
    docs_con_extraccion = 0

    # Las claves con prefijo '_' son acumuladores temporales dentro del dict de cada
    # modelo; se reemplazan por valores calculados en resumen_por_modelo al finalizar.
    for m in todas:
        total_docs += 1

        extraccion = m.get("extraccion_texto", {})
        metodo = extraccion.get("metodo")
        if metodo == "pymupdf":
            pymupdf_count += 1
        elif metodo == "ocr":
            ocr_count += 1
        if metodo is not None:
            docs_con_extraccion += 1
            if extraccion.get("calidad_ok"):
                calidad_ok_count += 1

        resumen = m.get("resumen", {})
        modelo = resumen.get("modelo") or "sin_modelo"
        if modelo not in por_modelo:
            por_modelo[modelo] = {
                "_tiempos": [],
                "_perplexidades": [],
                "_completitudes": [],
                "total_documentos": 0,
            }

        por_modelo[modelo]["total_documentos"] += 1

        tiempo = resumen.get("tiempo_segundos")
        if tiempo is not None:
            por_modelo[modelo]["_tiempos"].append(tiempo)

        perp = resumen.get("perplexidad")
        if perp is not None and perp != -1.0:
            por_modelo[modelo]["_perplexidades"].append(perp)

        completitud = m.get("metadatos", {}).get("completitud_porcentaje")
        if completitud is not None:
            por_modelo[modelo]["_completitudes"].append(completitud)

    resumen_por_modelo: Dict[str, Dict] = {}
    for modelo, datos in por_modelo.items():
        perps = datos["_perplexidades"]
        tiempos = datos["_tiempos"]
        completitudes = datos["_completitudes"]
        resumen_por_modelo[modelo] = {
            "total_documentos": datos["total_documentos"],
            "perplexidad_promedio": round(sum(perps) / len(perps), 4) if perps else None,
            "perplexidad_min": round(min(perps), 4) if perps else None,
            "perplexidad_max": round(max(perps), 4) if perps else None,
            "tiempo_promedio_segundos": round(sum(tiempos) / len(tiempos), 3) if tiempos else None,
            "completitud_metadatos_promedio": round(sum(completitudes) / len(completitudes), 1) if completitudes else None,
        }

    tasa_exitosa = round((calidad_ok_count / docs_con_extraccion) * 100, 1) if docs_con_extraccion else 0.0

    return {
        "por_modelo": resumen_por_modelo,
        "extraccion": {
            "total_documentos": total_docs,
            "pymupdf_count": pymupdf_count,
            "ocr_count": ocr_count,
            "tasa_extraccion_exitosa": tasa_exitosa,
        },
    }
