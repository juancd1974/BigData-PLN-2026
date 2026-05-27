"""
Extracción de entidades nombradas y metadatos normativos para NormaSearch.

Combina NER con spaCy (es_core_news_lg) y dateparser para producir estructuras
de metadatos sobre documentos del corpus normativo colombiano. Los documentos
que superan 800 000 caracteres se procesan automáticamente por chunks.

Funciones principales:
  extraer_entidades_mejorado()  → NER con normalización de encabezado, chunking y métricas
  extraer_metadatos_mejorado()  → tipo, número, fecha, emisor y título con métricas de completitud
  construir_entity_ruler()      → extiende spaCy con entidades jurídicas colombianas
  optimizar_nlp_pipeline()      → deshabilita componentes no necesarios para NER
  normalizar_fecha()            → convierte expresiones de fecha a ISO 8601
  extraer_temas()               → palabras clave por frecuencia de lemas POS-filtrados

Requisito: python -m spacy download es_core_news_lg
"""

import os
import re
import time
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
_RE_TITULO = re.compile(
    r'^["\']?\s*por\s+'
    r'(?:el\s+cual|la\s+cual|medio\s+de\s+la\s+cual|medio\s+del\s+cual'
    r'|el\s+que|la\s+que|el\s+presente|la\s+presente)',
    re.IGNORECASE,
)
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
    r'(CONPES|DECRETO[\s_]*LEGISLATIVO|DECRETO|RESOLUCI[OÓ]N'
    r'|LEY|CIRCULAR|ACUERDO|DIRECTIVA|ORDENANZA)'
    r'[\s_]+(?:N[oO°]?\.?|N[uú]m\.?)?[\s_]*'
    r'(\d{2,6})'
    r'[\s_]+DEL?[\s_]+'
    r'(?:\d{1,2}[\s_]+DE[\s_]+\w+[\s_]+DE[\s_]+)?'
    r'(\d{4})',
    re.IGNORECASE,
)

_RE_FECHA_EN_NOMBRE = re.compile(
    r'(\d{1,2})[\s_]+DE[\s_]+'
    r'(ENERO|FEBRERO|MARZO|ABRIL|MAYO|JUNIO|JULIO|AGOSTO'
    r'|SEPTIEMBRE|OCTUBRE|NOVIEMBRE|DICIEMBRE)'
    r'[\s_]+DE[\s_]+(\d{4})',
    re.IGNORECASE,
)


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


def optimizar_nlp_pipeline(nlp: Any) -> Any:
    """
    Desactiva 'parser' y 'senter' del pipeline si existen, manteniendo
    'ner' y 'tok2vec' activos para reducir tiempo de procesamiento.

    Args:
        nlp: Modelo spaCy cargado.

    Returns:
        Modelo spaCy con pipeline optimizado.
    """
    for componente in ('parser', 'senter'):
        if componente in nlp.pipe_names:
            nlp.disable_pipe(componente)
    print(f"  Componentes activos: {list(nlp.pipe_names)}")
    return nlp


def construir_entity_ruler(nlp: Any) -> Any:
    """
    Agrega un EntityRuler al final del pipeline con patrones mínimos de ORG
    para entidades jurídicas colombianas que spaCy frecuentemente omite.

    Con overwrite_ents=False el ruler añade entidades solo donde NER no
    encontró nada, preservando los resultados del modelo estadístico.

    Args:
        nlp: Modelo spaCy cargado.

    Returns:
        Modelo spaCy con EntityRuler agregado.
    """
    ruler = nlp.add_pipe('entity_ruler', last=True, config={'overwrite_ents': False})
    orgs = [
        "Ministerio de Agricultura y Desarrollo Rural",
        "Ministerio de Agricultura",
        "Ministerio de Hacienda y Crédito Público",
        "Ministerio de Comercio Industria y Turismo",
        "Presidencia de la República",
        "MADR",
        "Contraloría General de la República",
        "Contraloría Delegada para el Sector Agropecuario",
        "INVIMA",
        "ICA",
        "FINAGRO",
        "Banco Agrario",
        "DNP",
        "DANE",
        "Congreso de la República",
        "El Congreso de Colombia",
        "Congreso de Colombia",
        "CONGRESO DE LA REPÚBLICA",
        "CONGRESO DE COLOMBIA",
    ]
    ruler.add_patterns([{"label": "ORG", "pattern": org} for org in orgs])
    return nlp


def normalizar_encabezado_para_ner(texto: str) -> str:
    """
    Normaliza las primeras 30 líneas del texto para mejorar la detección NER.

    Convierte a Title Case únicamente las líneas donde más del 80 % de sus
    caracteres alfabéticos están en mayúsculas, ya que spaCy entrenado sobre
    noticias asigna mejor las etiquetas ORG/PER en texto con capitalización
    convencional que en texto completamente en mayúsculas.

    Args:
        texto: Texto completo del documento.

    Returns:
        String con las primeras 30 líneas normalizadas.
    """
    lineas = texto.split('\n')[:30]
    resultado = []
    for linea in lineas:
        chars_alfa = [c for c in linea if c.isalpha()]
        if chars_alfa:
            pct_mayus = sum(1 for c in chars_alfa if c.isupper()) / len(chars_alfa)
            if pct_mayus > 0.8:
                linea = linea.title()
        resultado.append(linea)
    return '\n'.join(resultado)


def extraer_entidades_mejorado(nlp: Any, texto: str) -> Tuple[Dict, Dict]:
    """
    Extrae entidades nombradas con normalización de encabezado, soporte para
    documentos largos y métricas de ejecución.

    Pasos internos:
      1. Normaliza las primeras 30 líneas a Title Case para mejorar la detección NER
         (spaCy reconoce mejor ORG/PER con capitalización convencional).
      2. Si el texto supera 800 000 chars, lo divide en chunks y acumula resultados.
      3. Complementa las fechas de NER con búsqueda regex en las primeras 50 líneas
         para capturar fechas que NER frecuentemente omite en encabezados.

    Args:
        nlp:   Modelo spaCy cargado.
        texto: Texto completo del documento.

    Returns:
        Tupla (entidades, metricas). entidades es un dict con seis listas:
        personas, lugares, organizaciones, fechas, leyes, otros.
        metricas contiene tiempo_ner_segundos y entidades_por_categoria.
    """
    if nlp is None:
        raise ValueError("Modelo spaCy no cargado. Ejecuta: python -m spacy download es_core_news_lg")

    def _ner(t: str) -> Dict[str, List[str]]:
        doc = nlp(t)
        ents: Dict[str, List[str]] = {
            'personas': [], 'lugares': [], 'organizaciones': [],
            'fechas': [], 'leyes': [], 'otros': [],
        }
        for ent in doc.ents:
            texto_ent = ent.text.strip()
            etiqueta  = ent.label_
            if etiqueta == 'PER':
                ents['personas'].append(texto_ent)
            elif etiqueta in ('LOC', 'GPE'):
                ents['lugares'].append(texto_ent)
            elif etiqueta == 'ORG':
                ents['organizaciones'].append(texto_ent)
            elif etiqueta == 'DATE':
                ents['fechas'].append(texto_ent)
            elif (etiqueta == 'LAW'
                  or 'ley' in texto_ent.lower()
                  or 'decreto' in texto_ent.lower()
                  or 'resolución' in texto_ent.lower()):
                ents['leyes'].append(texto_ent)
            else:
                ents['otros'].append(f"{texto_ent} ({etiqueta})")
        for key in ents:
            ents[key] = list(dict.fromkeys(ents[key]))
        return ents

    inicio = time.time()

    lineas = texto.split('\n')
    encabezado_norm = normalizar_encabezado_para_ner(texto)
    texto_proc = encabezado_norm + '\n' + '\n'.join(lineas[30:])

    if len(texto_proc) <= 800_000:
        entidades = _ner(texto_proc)
    else:
        chunks = dividir_en_chunks(texto_proc, 800_000)
        entidades: Dict[str, List[str]] = {
            k: [] for k in ('personas', 'lugares', 'organizaciones', 'fechas', 'leyes', 'otros')
        }
        for chunk in chunks:
            for key, vals in _ner(chunk).items():
                entidades[key].extend(vals)

    primeras_50 = '\n'.join(lineas[:50])
    fechas_ner = set(entidades['fechas'])
    for m in _RE_FECHA_LARGA.finditer(primeras_50):
        if m.group(1) not in fechas_ner:
            entidades['fechas'].append(m.group(1))
    for m in _RE_FECHA_MES_ANIO.finditer(primeras_50):
        candidata = f"{m.group(1)} de {m.group(2)}"
        if candidata not in fechas_ner:
            entidades['fechas'].append(candidata)

    for key in entidades:
        entidades[key] = list(dict.fromkeys(entidades[key]))

    tiempo_total = round(time.time() - inicio, 3)
    metricas: Dict = {
        'tiempo_ner_segundos': tiempo_total,
        'entidades_por_categoria': {k: len(v) for k, v in entidades.items()},
    }

    return entidades, metricas


def extraer_metadatos_mejorado(nlp: Any, texto: str,
                               nombre_archivo: str = '') -> Tuple[Dict, Dict]:
    """
    Extrae metadatos estructurados de una norma colombiana y calcula métricas de completitud.

    Estrategia por prioridad:
      1. Nombre de archivo (fuente primaria): tipo_norma, numero_norma, anio_norma, fecha_documento
      2. Texto del documento (fallback para campos aún en None)
      3. NER spaCy sobre primeras 20 líneas → entidad_emisora
      4. Patrón "Por el/la cual…" en primeras 50 líneas → titulo_norma

    Args:
        nlp:            Modelo spaCy cargado.
        texto:          Texto completo del documento.
        nombre_archivo: Nombre del archivo fuente (opcional, mejora extracción).

    Returns:
        Tupla (metadatos, metricas). metadatos contiene tipo_norma, numero_norma,
        anio_norma, entidad_emisora, fecha_documento, titulo_norma.
        metricas contiene campos_completos, campos_vacios, completitud_porcentaje
        y detalle_campos.
    """
    if nlp is None:
        raise ValueError("Modelo spaCy no cargado.")

    lineas              = texto.split('\n')
    encabezado          = '\n'.join(lineas[:20]).upper()
    encabezado_original = '\n'.join(lineas[:20])

    metadatos: Dict = {
        'tipo_norma': None, 'numero_norma': None, 'anio_norma': None,
        'entidad_emisora': None, 'fecha_documento': None, 'titulo_norma': None,
    }

    # PASO 1 — Nombre de archivo (fuente prioritaria)
    if nombre_archivo:
        nombre_sin_ext = os.path.splitext(nombre_archivo)[0]
        m = _RE_NOMBRE_ARCHIVO.match(nombre_sin_ext)
        if m:
            tipo_raw = m.group(1).upper()
            metadatos['tipo_norma']   = 'RESOLUCIÓN' if 'RESOLUCI' in tipo_raw else tipo_raw
            metadatos['numero_norma'] = int(m.group(2))
            metadatos['anio_norma']   = int(m.group(3))
        m_fecha = _RE_FECHA_EN_NOMBRE.search(nombre_sin_ext)
        if m_fecha:
            fecha_str = f"{m_fecha.group(1)} de {m_fecha.group(2)} de {m_fecha.group(3)}"
            fecha_norm = normalizar_fecha(fecha_str)
            if fecha_norm:
                metadatos['fecha_documento'] = fecha_norm
                metadatos['anio_norma']      = int(m_fecha.group(3))

    # PASO 2 — Texto (fallback solo para campos aún en None)
    if not metadatos['fecha_documento']:
        m = _RE_FECHA_LARGA.search(texto)
        if m:
            fecha = normalizar_fecha(m.group(1))
            if fecha:
                metadatos['fecha_documento'] = fecha
                metadatos['anio_norma']      = int(fecha[:4])

    if not metadatos['fecha_documento']:
        m = _RE_FECHA_MES_ANIO.search(texto)
        if m:
            fecha = normalizar_fecha(f"1 de {m.group(1)} de {m.group(2)}")
            if fecha:
                metadatos['fecha_documento'] = fecha
                metadatos['anio_norma']      = int(m.group(2))

    # _TIPOS_NORMA está ordenado: "DECRETO LEGISLATIVO" antes de "DECRETO"
    if not metadatos['tipo_norma']:
        for tipo in _TIPOS_NORMA:
            if tipo in encabezado:
                metadatos['tipo_norma'] = 'RESOLUCIÓN' if tipo == 'RESOLUCION' else tipo
                break

    if not metadatos['numero_norma']:
        m = _RE_NUMERO_NORMA.search(encabezado)
        if m:
            metadatos['numero_norma'] = int(m.group(2))
        else:
            m = re.search(r'\b(\d{2,5})\b', encabezado)
            if m:
                metadatos['numero_norma'] = int(m.group(1))

    if not metadatos['anio_norma']:
        m = _RE_ANIO.search(encabezado)
        if m:
            metadatos['anio_norma'] = int(m.group(1))

    # PASO 3 — Entidad emisora (siempre desde texto, no está en el nombre)
    mejor_org = None
    for ent in nlp(encabezado_original).ents:
        if ent.label_ == 'ORG':
            texto_ent = ent.text.strip().upper()
            if len(texto_ent) > 10 and texto_ent not in _SKIP_ENTIDADES:
                if mejor_org is None or len(texto_ent) > len(mejor_org):
                    mejor_org = texto_ent
    if mejor_org:
        metadatos['entidad_emisora'] = mejor_org

    if not metadatos['entidad_emisora'] and metadatos.get('tipo_norma') in _ENTIDAD_POR_TIPO:
        metadatos['entidad_emisora'] = _ENTIDAD_POR_TIPO[metadatos['tipo_norma']]

    # PASO 4 — Título (siempre desde texto)
    for linea in lineas[:50]:
        if _RE_TITULO.match(linea.strip()):
            metadatos['titulo_norma'] = linea.strip()
            break

    campos_clave = ('tipo_norma', 'numero_norma', 'anio_norma',
                    'entidad_emisora', 'fecha_documento')
    detalle = {campo: bool(metadatos.get(campo)) for campo in campos_clave}
    completos = sum(detalle.values())

    metricas: Dict = {
        'campos_completos': completos,
        'campos_vacios': len(campos_clave) - completos,
        'completitud_porcentaje': round((completos / len(campos_clave)) * 100, 1),
        'detalle_campos': detalle,
    }

    return metadatos, metricas