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
                data = json.load(f)
            if isinstance(data, dict):
                resultado.append(data)
        except (json.JSONDecodeError, OSError):
            pass

    return resultado


def calcular_resumen_comparativo() -> Dict:
    """
    Lee todas las métricas guardadas y calcula estadísticas en tres secciones:

    extraccion → conteo de intentos exitosos (pymupdf/ocr), fallidos y tasa.
    metadatos  → completitud por campo (tipo_norma, numero_norma, anio_norma,
                 entidad_emisora, fecha_documento) sobre documentos con
                 detalle_campos disponible.
    resumen    → perplejidad y tiempo promedio agrupados por modelo. Los
                 documentos con perplexidad == -1.0 se excluyen del promedio
                 de perplejidad pero cuentan para total_documentos y tiempo.

    Returns:
        Dict con tres secciones: 'extraccion', 'metadatos' y 'resumen'.
    """
    todas = cargar_todas_las_metricas()

    # ── Acumuladores extracción ──────────────────────────────────────────────
    exitosos_pymupdf = 0
    exitosos_ocr = 0
    fallidos = 0

    # ── Acumuladores metadatos ───────────────────────────────────────────────
    _campos_objetivo = [
        'tipo_norma', 'numero_norma', 'anio_norma',
        'entidad_emisora', 'fecha_documento',
    ]
    _campo_counts: Dict[str, Dict] = {c: {'total': 0, 'completos': 0} for c in _campos_objetivo}
    total_docs_meta = 0
    _completitudes: List[float] = []

    # ── Acumuladores resumen por modelo ─────────────────────────────────────
    # Las claves con prefijo '_' son acumuladores temporales; se reemplazan
    # por valores calculados en resumen_por_modelo al finalizar.
    por_modelo: Dict[str, Dict] = {}

    for m in todas:
        # Extracción
        extraccion = m.get("extraccion_texto", {})
        calidad_ok = extraccion.get("calidad_ok")
        metodo = extraccion.get("metodo")
        if calidad_ok:
            if metodo == "pymupdf":
                exitosos_pymupdf += 1
            elif metodo == "ocr":
                exitosos_ocr += 1
        else:
            fallidos += 1

        # Metadatos
        meta = m.get("metadatos", {})
        detalle = meta.get("detalle_campos")
        if detalle is not None:
            total_docs_meta += 1
            for campo in _campos_objetivo:
                _campo_counts[campo]['total'] += 1
                if detalle.get(campo):
                    _campo_counts[campo]['completos'] += 1
            completitud = meta.get("completitud_porcentaje")
            if completitud is not None:
                _completitudes.append(completitud)

        # Resumen por modelo
        res = m.get("resumen", {})
        modelo = res.get("modelo") or "sin_modelo"
        if modelo not in por_modelo:
            por_modelo[modelo] = {
                "_tiempos": [],
                "_perplexidades": [],
                "total_documentos": 0,
            }
        por_modelo[modelo]["total_documentos"] += 1
        tiempo = res.get("tiempo_segundos")
        if tiempo is not None:
            por_modelo[modelo]["_tiempos"].append(tiempo)
        perp = res.get("perplexidad")
        if perp is not None and perp != -1.0:
            por_modelo[modelo]["_perplexidades"].append(perp)

    # ── Calcular resultados ──────────────────────────────────────────────────
    total_intentos = exitosos_pymupdf + exitosos_ocr + fallidos
    tasa_exito = round(
        ((exitosos_pymupdf + exitosos_ocr) / total_intentos) * 100, 1
    ) if total_intentos else 0.0

    por_campo: Dict[str, Dict] = {}
    for campo, counts in _campo_counts.items():
        total = counts['total']
        completos = counts['completos']
        por_campo[campo] = {
            "total": total,
            "completos": completos,
            "porcentaje": round((completos / total) * 100, 1) if total else 0.0,
        }

    resumen_por_modelo: Dict[str, Dict] = {}
    for modelo, datos in por_modelo.items():
        perps = datos["_perplexidades"]
        tiempos = datos["_tiempos"]
        resumen_por_modelo[modelo] = {
            "total_documentos": datos["total_documentos"],
            "perplexidad_promedio": round(sum(perps) / len(perps), 4) if perps else None,
            "perplexidad_min": round(min(perps), 4) if perps else None,
            "perplexidad_max": round(max(perps), 4) if perps else None,
            "tiempo_promedio_segundos": round(sum(tiempos) / len(tiempos), 3) if tiempos else None,
        }

    return {
        "extraccion": {
            "total_intentos": total_intentos,
            "exitosos_pymupdf": exitosos_pymupdf,
            "exitosos_ocr": exitosos_ocr,
            "fallidos": fallidos,
            "tasa_exito": tasa_exito,
        },
        "metadatos": {
            "total_documentos": total_docs_meta,
            "completitud_promedio": round(
                sum(_completitudes) / len(_completitudes), 1
            ) if _completitudes else 0.0,
            "por_campo": por_campo,
        },
        "resumen": {
            "por_modelo": resumen_por_modelo,
        },
    }
