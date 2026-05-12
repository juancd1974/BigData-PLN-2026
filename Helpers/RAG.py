# RAG 2026-1S — S14: TF-IDF + NearestNeighbors + respuesta extractiva con citación
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.neighbors import NearestNeighbors
from spacy.lang.es.stop_words import STOP_WORDS as STOPWORDS_ES
from typing import List, Dict


class RAG:
    """Recuperación semántica y respuesta extractiva sobre normatividad (S14)."""

    def __init__(self, n_vecinos: int = 6):
        self.vectorizer = TfidfVectorizer(lowercase=True, ngram_range=(1, 2),
                                          stop_words=list(STOPWORDS_ES))
        self.index = NearestNeighbors(n_neighbors=n_vecinos, metric='cosine')
        self.documentos: List[Dict] = []   # [{id, texto, fuente}]
        self._indexado = False

    # ── S14: construcción del índice TF-IDF sobre el corpus
    def indexar(self, documentos: List[Dict]) -> None:
        """Recibe lista de dicts {id, texto, fuente} y construye el índice."""
        self.documentos = documentos
        textos = [d['texto'] for d in documentos]
        matriz = self.vectorizer.fit_transform(textos)
        self.index.fit(matriz)
        self._indexado = True

    # ── S14: recuperación de los N documentos más cercanos a la consulta
    def recuperar(self, consulta: str, n: int = 3) -> List[Dict]:
        """Devuelve los n documentos más relevantes para la consulta."""
        if not self._indexado:
            raise RuntimeError("Llama a indexar() antes de recuperar().")
        vec = self.vectorizer.transform([consulta])
        distancias, indices = self.index.kneighbors(vec, n_neighbors=n)
        resultados = []
        for dist, idx in zip(distancias[0], indices[0]):
            doc = self.documentos[idx].copy()
            doc['similitud'] = round(1 - dist, 4)  # coseno: 1 - distancia
            resultados.append(doc)
        return resultados

    # ── S14: extrae las oraciones del documento más relevante como respuesta
    def responder(self, consulta: str, n_docs: int = 3,
                  n_oraciones: int = 3) -> Dict:
        """Genera respuesta extractiva con citas de las fuentes recuperadas."""
        docs = self.recuperar(consulta, n=n_docs)
        if not docs:
            return {'respuesta': 'Sin resultados.', 'fuentes': []}

        # Tomar oraciones del documento con mayor similitud
        mejor = docs[0]['texto']
        oraciones = [s.strip() for s in mejor.replace('\n', ' ').split('.')
                     if len(s.strip()) > 30]
        respuesta = '. '.join(oraciones[:n_oraciones]) + '.'

        fuentes = [{'id': d['id'], 'fuente': d['fuente'],
                    'similitud': d['similitud']} for d in docs]
        return {'respuesta': respuesta, 'fuentes': fuentes}
