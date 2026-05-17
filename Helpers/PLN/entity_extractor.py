"""
Extracción de entidades nombradas y metadatos para NormaSearch.

Combina NER con spaCy (es_core_news_lg) y dateparser para producir
estructuras de metadatos sobre documentos del corpus normativo colombiano.
Incluye procesamiento por chunks para documentos que superan 1 M de caracteres.

Requisito: python -m spacy download es_core_news_lg
"""

import os
import re
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

import dateparser
from dateparser.search import search_dates

from Helpers.PLN.text_preprocessing import dividir_en_chunks


# Ordenado de más a menos específico para evitar match parcial en el encabezado
_TIPOS_NORMA = [
    'DECRETO LEGISLATIVO', 'DECRETO', 'RESOLUCIÓN', 'RESOLUCION',
    'LEY', 'CIRCULAR', 'ACUERDO', 'DIRECTIVA', 'ORDENANZA', 'CONPES',
]

# Formato oficial colombiano: "26 de marzo de 2019"
_RE_FECHA_LARGA = re.compile(
    r'\b(\d{1,2}\s+de\s+[a-zA-ZÁÉÍÓÚáéíóú]+\s+de\s+\d{4})',
    re.IGNORECASE,
)

# Captura variantes de notación: "DECRETO 1234", "RESOLUCIÓN No. 567", "LEY N° 80"
_RE_NUMERO_NORMA = re.compile(
    r'(DECRETO\s+LEGISLATIVO|DECRETO|RESOLUCIÓN|RESOLUCION'
    r'|LEY|CIRCULAR|ACUERDO|DIRECTIVA|ORDENANZA|CONPES)'
    r'(?:\s+N[oO°]?\.?)?\s+(\d{2,5})',
    re.IGNORECASE,
)

_RE_ANIO   = re.compile(r'\b(19\d{2}|20\d{2})\b')
_RE_TITULO = re.compile(r'^por\s+(el|la)\s+cu[aáo][ls]?\b', re.IGNORECASE)
_RE_FECHA_MES_ANIO = re.compile(
    r'\b(enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre'
    r'|octubre|noviembre|diciembre)\s+(?:de\s+|del\s+)?(\d{4})\b',
    re.IGNORECASE,
)
_SKIP_ENTIDADES = frozenset({'REPÚBLICA DE', 'REPÚBLICA DE COLOMBIA', 'COLOMBIA'})
_ENTIDAD_POR_TIPO = {
    'CONPES': 'CONSEJO NACIONAL DE POLÍTICA ECONÓMICA Y SOCIAL',
}
_RE_NOMBRE_ARCHIVO = re.compile(
    r'(CONPES|DECRETO[\s_]*LEGISLATIVO|DECRETO|RESOLUCI[OÓ]N|LEY|CIRCULAR|ACUERDO|DIRECTIVA|ORDENANZA)'
    r'[_\s]+(\d{2,5})[_\s]+DE[_\s]+(\d{4})',
    re.IGNORECASE,
)


def extraer_entidades(nlp: Any, texto: str) -> Dict[str, List[str]]:
    """
    Extrae entidades nombradas con spaCy NER y las clasifica en seis categorías.

    Mapeo de etiquetas spaCy a categorías de salida:
      PER          → personas
      LOC, GPE     → lugares   (LOC = geografía física; GPE = entidades geopolíticas)
      ORG          → organizaciones
      DATE         → fechas    (texto crudo; usar normalizar_fecha para convertir)
      LAW / heurística textual → leyes
      Resto (MISC, TIME, MONEY…) → otros  (incluye la etiqueta para transparencia)

    Pasar el texto ORIGINAL sin preprocesamiento: la capitalización es la principal
    señal del modelo para distinguir "ministerio" (común) de "Ministerio" (ORG).
    La deduplicación preserva el orden de primera aparición con dict.fromkeys.

    Args:
        nlp:   Modelo spaCy cargado.
        texto: Texto en español en forma original.

    Returns:
        Dict con seis listas de strings únicos en orden de aparición.
    """
    if nlp is None:
        raise ValueError("Modelo spaCy no cargado. Ejecuta: python -m spacy download es_core_news_lg")

    doc = nlp(texto)
    entidades: Dict[str, List[str]] = {
        'personas': [], 'lugares': [], 'organizaciones': [],
        'fechas': [], 'leyes': [], 'otros': [],
    }

    for ent in doc.ents:
        texto_ent = ent.text.strip()
        etiqueta  = ent.label_

        if etiqueta == 'PER':
            entidades['personas'].append(texto_ent)
        elif etiqueta in ('LOC', 'GPE'):
            entidades['lugares'].append(texto_ent)
        elif etiqueta == 'ORG':
            entidades['organizaciones'].append(texto_ent)
        elif etiqueta == 'DATE':
            entidades['fechas'].append(texto_ent)
        elif (etiqueta == 'LAW'
              or 'ley' in texto_ent.lower()
              or 'decreto' in texto_ent.lower()
              or 'resolución' in texto_ent.lower()):
            entidades['leyes'].append(texto_ent)
        else:
            entidades['otros'].append(f"{texto_ent} ({etiqueta})")

    for key in entidades:
        entidades[key] = list(dict.fromkeys(entidades[key]))

    return entidades


def extraer_entidades_texto_largo(nlp: Any,
                                  texto: str,
                                  max_chars: int = 800_000) -> Dict[str, List[str]]:
    """
    Extrae entidades de documentos que superan el límite de spaCy.

    Segmenta con dividir_en_chunks (corte en párrafos) para no partir entidades
    multipalabra entre fragmentos, agrega resultados y deduplica globalmente.

    Args:
        nlp:       Modelo spaCy cargado.
        texto:     Texto completo (puede superar 1 M de caracteres).
        max_chars: Tamaño máximo por chunk.

    Returns:
        Diccionario acumulado con la misma estructura que extraer_entidades.
    """
    if len(texto) <= max_chars:
        return extraer_entidades(nlp, texto)

    print(f"  → Documento largo ({len(texto):,} chars). Procesando NER en chunks...")

    chunks = dividir_en_chunks(texto, max_chars)
    entidades_total: Dict[str, List[str]] = {
        k: [] for k in ('personas', 'lugares', 'organizaciones', 'fechas', 'leyes', 'otros')
    }

    for i, chunk in enumerate(chunks, 1):
        print(f"     Chunk NER {i}/{len(chunks)} ({len(chunk):,} chars)...")
        for key, vals in extraer_entidades(nlp, chunk).items():
            entidades_total[key].extend(vals)

    for key in entidades_total:
        entidades_total[key] = list(dict.fromkeys(entidades_total[key]))

    return entidades_total


def normalizar_fecha(texto: str) -> Optional[str]:
    """
    Convierte una expresión de fecha en español a formato ISO 8601 (YYYY-MM-DD).

    Usa dateparser en lugar de spaCy DATE porque el proyecto necesita el valor
    numérico parseado para indexación en Elasticsearch, no solo el span de texto.

    Configuración:
      PREFER_DAY_OF_MONTH='first'   → "enero 2019" → 2019-01-01 (determinista)
      RETURN_AS_TIMEZONE_AWARE=False → datetime naive, compatible con Elasticsearch

    Args:
        texto: Expresión de fecha en español ("26 de marzo de 2019", "ayer", etc.).

    Returns:
        "YYYY-MM-DD" o None si dateparser no puede interpretar la expresión.
    """
    if not texto or not texto.strip():
        return None

    resultado = dateparser.parse(
        texto,
        languages=['es'],
        settings={'PREFER_DAY_OF_MONTH': 'first', 'RETURN_AS_TIMEZONE_AWARE': False},
    )
    return resultado.strftime('%Y-%m-%d') if resultado else None


def buscar_fechas_en_texto(texto: str) -> List[Tuple[str, str]]:
    """
    Detecta y normaliza todas las expresiones de fecha en un texto continuo.

    Retorna pares (texto_original, iso_normalizada) para mostrar la expresión
    original al usuario y filtrar por fecha en Elasticsearch simultáneamente.

    Args:
        texto: Texto en español con posibles expresiones de fecha.

    Returns:
        Lista de tuplas (texto_detectado, "YYYY-MM-DD"). Vacía si no hay fechas.
    """
    encontradas = search_dates(texto, languages=['es'])
    if not encontradas:
        return []
    return [(txt, dt.strftime('%Y-%m-%d')) for txt, dt in encontradas]


def extraer_metadatos_norma(nlp: Any, texto: str, nombre_archivo: str = '') -> Dict:
    """
    Extrae metadatos estructurados del encabezado de una norma colombiana.

    Estrategia combinada:
      1. NER spaCy sobre las primeras 20 líneas (MAYÚSCULAS) → entidad emisora (ORG)
      2. Regex + dateparser sobre texto original → fecha del documento
      3. Búsqueda de palabras clave en el encabezado → tipo de norma
      4. Regex de número de norma con variantes de notación
      5. Fallback de año si no hay fecha completa
      6. Patrón "Por el/la cual…" en primeras 30 líneas → título

    Args:
        nlp:   Modelo spaCy cargado.
        texto: Texto completo de la norma (sin preprocesar).

    Returns:
        Dict con claves: tipo_norma, numero_norma, anio_norma,
        entidad_emisora, fecha_documento, titulo_norma. None si no se encontró.
    """
    if nlp is None:
        raise ValueError("Modelo spaCy no cargado.")

    lineas              = texto.split('\n')
    encabezado          = '\n'.join(lineas[:20]).upper()
    encabezado_original = '\n'.join(lineas[:20])

    meta: Dict = {
        'tipo_norma': None, 'numero_norma': None, 'anio_norma': None,
        'entidad_emisora': None, 'fecha_documento': None, 'titulo_norma': None,
    }

    # Nombre de archivo como fuente primaria de tipo/número/año (más fiable que texto en PDFs con codificación compleja)
    if nombre_archivo:
        m = _RE_NOMBRE_ARCHIVO.match(os.path.splitext(nombre_archivo)[0])
        if m:
            tipo_raw = m.group(1).upper()
            meta['tipo_norma']   = 'RESOLUCIÓN' if 'RESOLUCI' in tipo_raw else tipo_raw
            meta['numero_norma'] = int(m.group(2))
            meta['anio_norma']   = int(m.group(3))

    # NER sobre texto original (sin uppercase) — mejor sensibilidad del modelo para entidades
    mejor_org = None
    for ent in nlp(encabezado_original).ents:
        if ent.label_ == 'ORG':
            texto_ent = ent.text.strip().upper()
            if len(texto_ent) > 10 and texto_ent not in _SKIP_ENTIDADES:
                if mejor_org is None or len(texto_ent) > len(mejor_org):
                    mejor_org = texto_ent
    if mejor_org:
        meta['entidad_emisora'] = mejor_org

    if not meta['entidad_emisora'] and meta.get('tipo_norma') in _ENTIDAD_POR_TIPO:
        meta['entidad_emisora'] = _ENTIDAD_POR_TIPO[meta['tipo_norma']]

    # Buscar fecha en texto ORIGINAL: dateparser es sensible a mayúsculas en meses
    m = _RE_FECHA_LARGA.search(texto)
    if m:
        fecha = normalizar_fecha(m.group(1))
        if fecha:
            meta['fecha_documento'] = fecha
            meta['anio_norma']      = int(fecha[:4])

    if not meta['fecha_documento']:
        m = _RE_FECHA_MES_ANIO.search(texto)
        if m:
            fecha = normalizar_fecha(f"1 de {m.group(1)} de {m.group(2)}")
            if fecha:
                meta['fecha_documento'] = fecha
                meta['anio_norma']      = int(m.group(2))

    # _TIPOS_NORMA está ordenado: "DECRETO LEGISLATIVO" antes de "DECRETO"
    for tipo in _TIPOS_NORMA:
        if tipo in encabezado:
            meta['tipo_norma'] = 'RESOLUCIÓN' if tipo == 'RESOLUCION' else tipo
            break

    m = _RE_NUMERO_NORMA.search(encabezado)
    if m:
        meta['numero_norma'] = int(m.group(2))
    else:
        m = re.search(r'\b(\d{2,5})\b', encabezado)
        if m:
            meta['numero_norma'] = int(m.group(1))

    if not meta['anio_norma']:
        m = _RE_ANIO.search(encabezado)
        if m:
            meta['anio_norma'] = int(m.group(1))

    for linea in lineas[:30]:
        if _RE_TITULO.match(linea.strip()):
            meta['titulo_norma'] = linea.strip()
            break

    return meta


def extraer_temas(nlp: Any, texto: str, top_n: int = 10) -> List[Tuple[str, float]]:
    """
    Extrae palabras clave por frecuencia de lemas usando POS-tagging spaCy.

    Filtra por POS informativos (NOUN, PROPN, ADJ, VERB), elimina stopwords
    y cuenta lemas para agrupar variantes morfológicas. El score se normaliza
    como porcentaje del total de tokens relevantes, haciendo los resultados
    comparables entre documentos de diferente longitud.

    Args:
        nlp:    Modelo spaCy cargado.
        texto:  Texto original (sin preprocesar; la capitalización mejora POS).
        top_n:  Número de temas a devolver.

    Returns:
        Lista de tuplas (lema, porcentaje) ordenadas de mayor a menor frecuencia.
        Score = (frecuencia / total_relevantes) × 100.
    """
    if nlp is None:
        raise ValueError("Modelo spaCy no cargado.")

    palabras_relevantes: List[str] = [
        token.lemma_.lower()
        for token in nlp(texto)
        if not token.is_stop
        and not token.is_punct
        and not token.is_space
        and len(token.text) > 3
        and token.pos_ in ('NOUN', 'PROPN', 'ADJ', 'VERB')
    ]

    contador = Counter(palabras_relevantes)
    temas    = contador.most_common(top_n)
    total    = len(palabras_relevantes)

    if total > 0:
        return [(lema, (freq / total) * 100) for lema, freq in temas]
    return [(lema, 0.0) for lema, _ in temas]