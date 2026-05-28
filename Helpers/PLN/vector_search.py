"""
Búsqueda conceptual con Word2Vec para NormaSearch.

Similitud de coseno:
    cos(θ) = (u · v) / (‖u‖ · ‖v‖)

Vectorización de documentos (promedio de embeddings):
    vec(d) = (1/k) · Σᵢ w2v(tᵢ)   para tokens en vocabulario

CUMPLIMIENTO ENTREGA 1:
  ✓ Word2Vec gensim con CBOW (sg=0) y Skip-gram (sg=1)
  ✓ Hiperparámetros: vector_size, window, min_count, epochs
  ✓ Representación vectorial para búsqueda conceptual sin RAG ni sentence-transformers

TOLERANCIA A FALLOS — GENSIM EN PYTHON 3.14 / WINDOWS:
  gensim 4.x requiere extensiones C++ compiladas (Cython). En entornos sin
  Microsoft C++ Build Tools (ej. Python 3.14 en Windows), la compilación falla.
  Este módulo detecta el caso automáticamente con try/except y activa un fallback
  que usa los vectores GloVe de es_core_news_lg (token.vector, 300 dims).
  Ambas ramas resuelven la misma fórmula de promedio y el mismo calcular_similitud_coseno,
  garantizando resultados semánticamente coherentes en cualquier entorno.
"""

import multiprocessing
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from Helpers.PLN.text_preprocessing import preprocesar_texto

# ── Importación tolerante a fallos ────────────────────────────────────────────
# gensim 4.x requiere MSVC en Windows para compilar sus extensiones Cython.
# Si ImportError, GENSIM_DISPONIBLE=False activa la rama spaCy en vectorizar_texto.
try:
    from gensim.models import KeyedVectors, Word2Vec
    GENSIM_DISPONIBLE = True
except ImportError:
    KeyedVectors = None  # type: ignore[assignment,misc]
    Word2Vec = None      # type: ignore[assignment,misc]
    GENSIM_DISPONIBLE = False
    print("  [!] gensim no disponible. Fallback: vectores GloVe de spaCy (es_core_news_lg).")
    print("    Para activar Word2Vec: instala gensim>=4 con Python<=3.12 + MSVC Build Tools.")

# Raíz del proyecto: Helpers/PLN/ → Helpers/ → raíz
_DIRECTORIO_MODELOS  = Path(__file__).resolve().parent.parent.parent / 'models'
_RUTA_MODELO_DEFAULT = _DIRECTORIO_MODELOS / 'normasearch_w2v_sg_v100_w5.model'

_RE_TOKENIZER = re.compile(r'[^\w\s]')


def _tokenizar_simple(texto: str) -> List[str]:
    """Tokenizador regex sin dependencias; fallback de vectorizar_texto."""
    return _RE_TOKENIZER.sub('', texto.lower()).split()


def entrenar_word2vec(corpus_tokenizado: List[List[str]],
                      sg: int = 1,
                      vector_size: int = 100,
                      window: int = 5,
                      min_count: int = 2,
                      epochs: int = 50,
                      modelo_existente=None):
    """
    Entrena Word2Vec sobre el corpus normativo. Requiere gensim>=4.

    Si modelo_existente es un objeto Word2Vec cargado con cargar_modelo_completo(),
    realiza entrenamiento incremental (build_vocab update + train). Si es None,
    entrena desde cero con los hiperparámetros dados.

    Skip-gram (sg=1) es preferido para términos legales de baja frecuencia.
    Retorna None si GENSIM_DISPONIBLE es False.

    Args:
        corpus_tokenizado: Lista de documentos tokenizados.
        sg:               0 = CBOW, 1 = Skip-gram (solo aplica a entrenamiento desde cero).
        vector_size:      Dimensión de los embeddings (solo desde cero).
        window:           Tamaño de la ventana de contexto (solo desde cero).
        min_count:        Frecuencia mínima para incluir un token (solo desde cero).
        epochs:           Iteraciones de entrenamiento.
        modelo_existente: Objeto Word2Vec completo para entrenamiento incremental, o None.

    Returns:
        Modelo Word2Vec entrenado, o None si gensim no está disponible.
    """
    if not GENSIM_DISPONIBLE:
        print("  [!] gensim no disponible. entrenar_word2vec() no puede ejecutarse.")
        return None

    trabajadores = max(1, multiprocessing.cpu_count() - 1)
    arq = 'Skip-gram' if sg == 1 else 'CBOW'

    if modelo_existente is not None:
        print(f"  Entrenamiento incremental ({arq}): actualizando vocabulario con {len(corpus_tokenizado)} docs...")
        modelo_existente.build_vocab(corpus_tokenizado, update=True)
        modelo_existente.train(
            corpus_tokenizado,
            total_examples=len(corpus_tokenizado),
            epochs=epochs,
        )
        n = len(modelo_existente.wv)
        print(f"  ✓ Vocabulario actualizado: {n} palabras")
        return modelo_existente

    print(f"  Entrenando Word2Vec ({arq}): vector_size={vector_size}, "
          f"window={window}, min_count={min_count}, epochs={epochs}")
    modelo = Word2Vec(
        sentences=corpus_tokenizado,
        sg=sg, vector_size=vector_size, window=window,
        min_count=min_count, epochs=epochs, workers=trabajadores, seed=42,
    )
    n = len(modelo.wv)
    print(f"  ✓ Vocabulario: {n} palabras ({n * vector_size:,} parámetros)")
    return modelo


def guardar_modelo(modelo, ruta: Optional[str] = None) -> Optional[str]:
    """
    Guarda el modelo en formato nativo gensim (.model).
    Retorna None si gensim no está disponible o modelo es None.

    Args:
        modelo: Word2Vec entrenado.
        ruta:   Ruta de destino. Si None usa _RUTA_MODELO_DEFAULT.

    Returns:
        Ruta absoluta del archivo guardado, o None.
    """
    if not GENSIM_DISPONIBLE or modelo is None:
        return None
    destino = Path(ruta) if ruta else _RUTA_MODELO_DEFAULT
    destino.parent.mkdir(parents=True, exist_ok=True)
    modelo.save(str(destino))
    print(f"  ✓ Modelo guardado en: {destino}")
    return str(destino)


def cargar_modelo_word2vec(ruta: Optional[str] = None):
    """
    Carga un modelo Word2Vec y retorna sus KeyedVectors.

    Soporta .model (gensim nativo) y .bin/.txt/.vec (formato Google).
    Retorna None sin excepción si gensim no está disponible o el archivo no existe.
    En el primer caso, vectorizar_texto activará automáticamente el fallback spaCy.

    Args:
        ruta: Ruta al archivo. Si None usa _RUTA_MODELO_DEFAULT.

    Returns:
        KeyedVectors cargados, o None.
    """
    if not GENSIM_DISPONIBLE:
        print("  [!] gensim no disponible. vectorizar_texto usará vectores spaCy (GloVe 300-dim).")
        return None

    archivo = Path(ruta) if ruta else _RUTA_MODELO_DEFAULT

    if not archivo.exists():
        print(f"  [!] Modelo W2V no encontrado en: {archivo}")
        print("    Ejecuta entrenar_word2vec() o descarga vectores preentrenados.")
        return None

    try:
        ext = archivo.suffix.lower()
        if ext == '.model':
            print(f"  Cargando modelo gensim: {archivo.name} ...")
            wv = Word2Vec.load(str(archivo)).wv
        else:
            binario = ext == '.bin'
            print(f"  Cargando KeyedVectors ({'bin' if binario else 'txt'}): {archivo.name} ...")
            wv = KeyedVectors.load_word2vec_format(str(archivo), binary=binario)

        print(f"  ✓ Vocabulario: {len(wv):,} palabras | Dimensión: {wv.vector_size}")
        return wv

    except Exception as exc:
        print(f"  ✗ Error cargando '{archivo.name}': {exc}")
        return None


def cargar_modelo_completo(ruta: Optional[str] = None):
    """
    Carga el objeto Word2Vec completo (no solo KeyedVectors) para entrenamiento incremental.

    Retorna None si gensim no está disponible, el archivo no existe o no es .model.

    Args:
        ruta: Ruta al archivo .model. Si None usa _RUTA_MODELO_DEFAULT.

    Returns:
        Objeto Word2Vec completo, o None.
    """
    if not GENSIM_DISPONIBLE:
        return None
    archivo = Path(ruta) if ruta else _RUTA_MODELO_DEFAULT
    if not archivo.exists():
        return None
    if archivo.suffix.lower() != '.model':
        print(f"  [!] Entrenamiento incremental solo soportado para .model. Recibido: {archivo.suffix}")
        return None
    try:
        modelo = Word2Vec.load(str(archivo))
        print(f"  ✓ Modelo completo cargado para reentrenamiento: {archivo.name}")
        return modelo
    except Exception as exc:
        print(f"  ✗ Error cargando modelo completo '{archivo.name}': {exc}")
        return None


def vectorizar_texto(texto: str,
                     modelo: Any,
                     nlp: Any = None) -> Optional[np.ndarray]:
    """
    Vector representativo del texto como promedio de embeddings.

        vec(d) = (1/k) · Σ vec(tᵢ)   para tokens tᵢ vectorizables

    ── Rama gensim (GENSIM_DISPONIBLE=True, modelo=KeyedVectors) ──
        Vectores entrenados en el corpus normativo (Word2Vec, 100-dim).
        Aplica preprocesamiento nivel 2 si nlp está disponible.
        Tokens OOV se omiten; retorna None si todos son OOV.

    ── Rama spaCy / fallback (GENSIM_DISPONIBLE=False o modelo=None) ──
        Vectores GloVe preentrenados de es_core_news_lg (300-dim).
        Filtra stopwords, puntuación y tokens sin vector.
        Retorna None si nlp es None o no hay tokens con vector.

    Ambas ramas usan la misma fórmula de promedio. El resultado se
    pasa a calcular_similitud_coseno, que es invariante a la dimensión.

    Args:
        texto:  Texto en español.
        modelo: KeyedVectors (gensim) o None (activa fallback spaCy).
        nlp:    Modelo spaCy; obligatorio en rama fallback.

    Returns:
        np.ndarray de forma (vector_size,) o None si no hay tokens vectorizables.
    """
    # ── Rama spaCy / GloVe fallback ──────────────────────────────────────
    # Se activa en dos casos:
    # 1) GENSIM_DISPONIBLE=False: gensim no pudo compilar extensiones Cython (ej. Windows
    #    sin MSVC Build Tools). es_core_news_lg incluye vectores GloVe de 300 dim/token.
    # 2) modelo is None: Word2Vec aún no entrenado o no cargado en esta sesión.
    # Ambas ramas usan la misma fórmula de promedio y calcular_similitud_coseno,
    # que es invariante a la dimensión (100-dim W2V ó 300-dim GloVe).
    if not GENSIM_DISPONIBLE or modelo is None:
        if nlp is None:
            return None
        doc = nlp(texto)
        vectores = [
            token.vector for token in doc
            if not token.is_stop
            and not token.is_punct
            and token.has_vector
            and len(token.text) > 2
        ]
        return np.mean(vectores, axis=0) if vectores else None

    # ── Rama gensim ───────────────────────────────────────────────────────
    if nlp is not None:
        procesado = preprocesar_texto(nlp, texto, remover_stopwords=True, lematizar=True)
        tokens = procesado.split() if procesado else []
    else:
        tokens = _tokenizar_simple(texto)

    if not tokens:
        return None

    vectores = [modelo[t] for t in tokens if t in modelo.key_to_index]
    return np.mean(vectores, axis=0) if vectores else None


def calcular_similitud_coseno(vector_a: np.ndarray,
                               vector_b: np.ndarray) -> float:
    """
    Similitud de coseno entre dos vectores. Implementación NumPy pura.

        cos(θ) = dot(u, v) / (‖u‖ · ‖v‖)

    Válida para cualquier dimensión (100-dim W2V o 300-dim GloVe).
    Devuelve 0.0 si algún vector tiene norma L2 = 0. Aplica clip [-1, 1].

    Args:
        vector_a: np.ndarray de forma (n,).
        vector_b: np.ndarray de forma (n,).

    Returns:
        Float en [-1.0, 1.0].
    """
    na = np.linalg.norm(vector_a)
    nb = np.linalg.norm(vector_b)

    if na == 0.0 or nb == 0.0:
        return 0.0

    return float(np.clip(np.dot(vector_a, vector_b) / (na * nb), -1.0, 1.0))


def buscar_similares(modelo: Any,
                     termino: str,
                     top_n: int = 10) -> List[Tuple[str, float]]:
    """
    Palabras más similares a un término en el espacio W2V (solo gensim).

    En modo fallback spaCy, usa nlp.vocab[term].vector para explorar GloVe.

    Args:
        modelo:  KeyedVectors cargados (gensim).
        termino: Palabra a consultar.
        top_n:   Número de resultados.

    Returns:
        Lista de (palabra, similitud_coseno). Vacía si OOV o en modo fallback.
    """
    if not GENSIM_DISPONIBLE or modelo is None:
        if not GENSIM_DISPONIBLE:
            print("  [!] buscar_similares requiere gensim.")
        return []
    if termino not in modelo.key_to_index:
        print(f"  [!] '{termino}' no está en el vocabulario del modelo.")
        return []
    return modelo.most_similar(termino, topn=top_n)


def buscar_documentos_conceptuales(query: str,
                                    documentos_elastic: List[Dict],
                                    modelo: Any,
                                    nlp: Any = None,
                                    campo_texto: str = 'contenido',
                                    umbral_similitud: float = 0.0) -> List[Dict]:
    """
    Re-rankea hits de Elasticsearch por similitud coseno.

    Vectoriza la query y cada documento con vectorizar_texto (gensim o spaCy),
    ordena por similitud descendente. Si la query es OOV, retorna el orden BM25.
    En modo fallback, nlp es el único parámetro de vectorización necesario.

    Args:
        query:              Texto de la consulta del usuario.
        documentos_elastic: Hits de Elasticsearch ({_id, _score, _source}).
        modelo:             KeyedVectors (gensim) o None (fallback spaCy).
        nlp:                Modelo spaCy; obligatorio en modo fallback.
        campo_texto:        Campo de _source con el texto del documento.
        umbral_similitud:   Filtrar documentos con score < umbral.

    Returns:
        Lista de documentos con campo 'similitud_coseno', ordenados desc.
    """
    if not documentos_elastic:
        return documentos_elastic

    if not GENSIM_DISPONIBLE and nlp is None:
        return documentos_elastic

    vector_query = vectorizar_texto(query, modelo, nlp)

    # Si la query es completamente OOV (todos los tokens fuera del vocabulario), no hay
    # vector de referencia. Se conserva el orden BM25 original (orden Elasticsearch)
    # en lugar de retornar error, ya que BM25 sigue siendo un ranking útil.
    if vector_query is None:
        print(f"  [!] Query '{query[:60]}' sin tokens vectorizables. Usando orden BM25.")
        for doc in documentos_elastic:
            doc['similitud_coseno'] = 0.0
        return documentos_elastic

    for doc in documentos_elastic:
        texto_doc = doc.get('_source', {}).get(campo_texto, '')
        if not texto_doc or not isinstance(texto_doc, str):
            doc['similitud_coseno'] = 0.0
            continue

        vector_doc = vectorizar_texto(texto_doc, modelo, nlp)
        doc['similitud_coseno'] = (
            calcular_similitud_coseno(vector_query, vector_doc)
            if vector_doc is not None else 0.0
        )

    resultado = documentos_elastic
    if umbral_similitud > 0.0:
        resultado = [d for d in resultado if d['similitud_coseno'] >= umbral_similitud]

    resultado.sort(key=lambda d: d['similitud_coseno'], reverse=True)
    return resultado
