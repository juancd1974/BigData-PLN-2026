"""
Pipeline de preprocesamiento de texto para NormaSearch.

Implementa tres niveles de limpieza según el consumidor:
  preprocesar_para_transformer → normalización Unicode mínima para mT5/BERT.
    Preserva números, puntuación y capitalización que el AutoTokenizer necesita.
  limpiar_texto                → minúsculas + charset español para spaCy y Word2Vec.
  preprocesar_texto            → pipeline NLP completo (POS-filter + stopwords +
    lemas) para TF-IDF y búsqueda conceptual.
"""

import re
import unicodedata
from typing import Any, List, Optional

import nltk
from nltk.corpus import stopwords
from nltk.stem import SnowballStemmer

# Descargar recursos NLTK si no están en caché
for _recurso, _tipo in [('stopwords', 'corpora')]:
    try:
        nltk.data.find(f'{_tipo}/{_recurso}')
    except LookupError:
        nltk.download(_recurso, quiet=True)

# Stopwords NLTK español + términos legales sin carga semántica en el corpus normativo
_STOPWORDS_ES: set = set(stopwords.words('spanish')) | {
    'artículo', 'parágrafo', 'inciso', 'numeral', 'literal',
    'dicho', 'dichos', 'dicha', 'dichas',
    'mismo', 'mismos', 'misma', 'mismas',
    'mediante', 'respecto', 'cuanto',
    'cuya', 'cuyo', 'cuyos', 'cuyas',
    'ante', 'bajo', 'desde', 'hasta', 'hacia', 'entre', 'sobre', 'tras',
    'siguiente', 'presente', 'colombia',
}

_STEMMER_ES = SnowballStemmer("spanish")

# Caracteres válidos en español; se reemplaza por espacio (no vacío) para no
# fusionar tokens adyacentes: "Art.12" → "art  12", no "art12"
_RE_CHARS_VALIDOS = re.compile(r'[^a-záéíóúüñÁÉÍÓÚÜÑ\s]')
_RE_ESPACIOS      = re.compile(r'\s+')


def limpiar_texto(texto: str) -> str:
    """
    Normalización de nivel 1: minúsculas + charset español + espacios.

    No elimina palabras ni altera la estructura sintáctica.
    Apto para cualquier modelo que necesite contexto lingüístico completo.

    Args:
        texto: Cadena en español sin procesar.

    Returns:
        Cadena normalizada en minúsculas con un único espacio entre palabras.
    """
    texto = texto.lower()
    texto = _RE_CHARS_VALIDOS.sub(' ', texto)
    texto = _RE_ESPACIOS.sub(' ', texto).strip()
    return texto


def preprocesar_para_transformer(texto: str) -> str:
    """
    Normalización mínima para entrada a modelos transformer (mT5, BERT).

    Preserva números, puntuación y capitalización: el AutoTokenizer de mT5
    (SentencePiece) necesita el texto original para construir subword units
    coherentes. Aplicar limpiar_texto() antes degrada la calidad del resumen.

    Args:
        texto: Texto en español sin procesar.

    Returns:
        Texto con codificación normalizada (NFC), sin caracteres de control,
        espacios colapsados. Números, puntuación y mayúsculas intactos.
    """
    if not texto:
        return ''
    texto = unicodedata.normalize('NFC', texto)
    texto = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', texto)
    texto = re.sub(r'[ \t]+', ' ', texto)
    return texto.strip()


def aplicar_stemming(tokens: List[str]) -> List[str]:
    """
    Stemming morfológico con SnowballStemmer en español.

    Reduce tokens a su raíz morfológica. Usar solo como clave de agrupación;
    el stem no es una palabra real. Preferir lematización spaCy cuando esté disponible.

    Args:
        tokens: Lista de tokens ya filtrados.

    Returns:
        Lista de raíces morfológicas en minúsculas.
    """
    return [_STEMMER_ES.stem(t) for t in tokens]


def preprocesar_texto(nlp: Any,
                      texto: str,
                      remover_stopwords: bool = True,
                      lematizar: bool = True,
                      aplicar_stem: bool = False,
                      remover_numeros: bool = False,
                      min_longitud: int = 3,
                      pos_permitidos: Optional[List[str]] = None) -> str:
    """
    Pipeline NLP completo de preprocesamiento (nivel 2).

    Uso recomendado por tarea:
      TF-IDF / Word2Vec    → remover_stopwords=True, lematizar=True
      Extracción de temas  → remover_stopwords=True, lematizar=True, min_longitud=4
      Resumen mT5          → NO usar esta función; usar preprocesar_para_transformer

    Args:
        nlp:               Modelo spaCy cargado (es_core_news_lg).
        texto:             Texto en español sin procesar.
        remover_stopwords: Filtra stopwords NLTK + lista legal extendida.
        lematizar:         Devuelve lemas spaCy en lugar de formas crudas.
        aplicar_stem:      Aplica SnowballStemmer; solo si lematizar=False.
        remover_numeros:   Excluye tokens donde token.like_num es True.
        min_longitud:      Longitud mínima del token en caracteres.
        pos_permitidos:    POS tags a conservar. Default: NOUN, PROPN, ADJ, VERB.

    Returns:
        Cadena de tokens separados por espacio, lista para vectorización.
    """
    if pos_permitidos is None:
        # Categorías con carga semántica temática; excluye DET, ADP, CCONJ
        pos_permitidos = ['NOUN', 'PROPN', 'ADJ', 'VERB']

    texto_limpio = limpiar_texto(texto)
    doc = nlp(texto_limpio)
    tokens_finales: List[str] = []

    for token in doc:
        if len(token.text) < min_longitud:
            continue
        if token.is_punct or token.is_space:
            continue
        if remover_numeros and token.like_num:
            continue
        # Combina is_stop del modelo con nuestra lista legal extendida
        if remover_stopwords and (token.is_stop or token.lemma_.lower() in _STOPWORDS_ES):
            continue
        if token.pos_ not in pos_permitidos:
            continue

        forma = token.lemma_.lower() if lematizar else token.text.lower()
        tokens_finales.append(forma)

    # stem y lemma son mutuamente excluyentes; stem(lemma) produce raíces inválidas
    if aplicar_stem and not lematizar:
        tokens_finales = aplicar_stemming(tokens_finales)

    return ' '.join(tokens_finales)


def dividir_en_chunks(texto: str, max_chars: int = 800_000) -> List[str]:
    """
    Divide texto largo en segmentos seguros para spaCy (límite: 1 M chars).

    Corta en el último salto de línea antes del límite para no partir
    entidades multipalabra entre dos chunks.

    Args:
        texto:     Texto completo a dividir.
        max_chars: Tamaño máximo por chunk (default 800 000, margen 20 % sobre el límite).

    Returns:
        Lista de fragmentos. Si len(texto) <= max_chars devuelve [texto].
    """
    if len(texto) <= max_chars:
        return [texto]

    chunks: List[str] = []
    inicio = 0

    while inicio < len(texto):
        fin = inicio + max_chars
        if fin >= len(texto):
            chunks.append(texto[inicio:])
            break

        corte = texto.rfind('\n', inicio, fin)
        if corte <= inicio:
            corte = fin

        chunks.append(texto[inicio:corte])
        inicio = corte + 1

    return chunks