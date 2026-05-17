"""
Orquestador PLN para NormaSearch.

Fachada sobre los cuatro módulos de Helpers:
  text_preprocessing → normalización y tokenización
  entity_extractor   → NER, metadatos, detección de fechas
  vector_search      → Word2Vec, vectorización, búsqueda conceptual
  summarizer         → resumen abstractivo con mT5-small
"""

import spacy
from typing import Dict, List, Optional, Tuple

from Helpers.PLN.text_preprocessing import (
    preprocesar_texto as _prep_texto,
    preprocesar_para_transformer,
    dividir_en_chunks as _dividir,
)
from Helpers.PLN.entity_extractor import (
    extraer_entidades_texto_largo,
    normalizar_fecha as _normalizar_fecha,
    extraer_metadatos_norma as _extraer_meta,
    extraer_temas as _extraer_temas,
)
from Helpers.PLN.vector_search import (
    cargar_modelo_word2vec,
    vectorizar_texto,
    buscar_documentos_conceptuales,
)
from Helpers.PLN.summarizer import (
    cargar_pipeline_resumen,
    generar_resumen_abstractivo as _gen_resumen,
)


class PLN:
    """Orquestador de NLP sobre normatividad colombiana en español."""

    def __init__(self, modelo_spacy: str = 'es_core_news_lg', cargar_modelos: bool = True):
        self.modelo_spacy_nombre = modelo_spacy
        self.nlp = None
        self._wv = None               # KeyedVectors; carga bajo demanda
        self._pipeline_resumen = None  # None = no intentado; False = falló

        if cargar_modelos:
            self._cargar_modelos()

    def _cargar_modelos(self):
        """Carga spaCy al inicio. Word2Vec y mT5 se cargan bajo demanda."""
        try:
            print(f"Cargando modelo spaCy '{self.modelo_spacy_nombre}'...")
            self.nlp = spacy.load(self.modelo_spacy_nombre)
            self.nlp.max_length = 3_000_000
            print(f"  ✓ '{self.modelo_spacy_nombre}' cargado")
        except OSError:
            print(f"  ✗ Modelo '{self.modelo_spacy_nombre}' no encontrado.")
            print(f"    Ejecuta: python -m spacy download {self.modelo_spacy_nombre}")
            try:
                self.nlp = spacy.load('es_core_news_sm')
                print("  ⚠ Usando es_core_news_sm como fallback")
            except OSError:
                print("  ✗ No se pudo cargar ningún modelo spaCy")
                self.nlp = None

    # ── Carga explícita de modelos opcionales ─────────────────────────────

    def cargar_word2vec(self, ruta: Optional[str] = None) -> bool:
        """Carga el modelo Word2Vec. Retorna True si tuvo éxito."""
        self._wv = cargar_modelo_word2vec(ruta)
        return self._wv is not None

    def cargar_resumen(self, modelo: str = 'google/mt5-small') -> bool:
        """Carga el pipeline mT5. Retorna True si tuvo éxito."""
        self._pipeline_resumen = cargar_pipeline_resumen(modelo)
        return bool(self._pipeline_resumen)

    # ── Preprocesamiento ──────────────────────────────────────────────────

    def preprocesar_texto(self, texto: str,
                          remover_stopwords: bool = True,
                          lematizar: bool = True,
                          remover_numeros: bool = False,
                          min_longitud: int = 3) -> str:
        """Nivel 2: POS-filter + stopwords + lematización spaCy."""
        return _prep_texto(self.nlp, texto,
                           remover_stopwords=remover_stopwords,
                           lematizar=lematizar,
                           remover_numeros=remover_numeros,
                           min_longitud=min_longitud)

    def preprocesar_para_transformer(self, texto: str) -> str:
        """Nivel 1: normalización mínima, sintaxis intacta para mT5/BERT."""
        return preprocesar_para_transformer(texto)

    def dividir_en_chunks(self, texto: str, max_chars: int = 800_000) -> List[str]:
        """Divide texto largo en segmentos seguros para spaCy."""
        return _dividir(texto, max_chars)

    # ── NER y metadatos ───────────────────────────────────────────────────

    def extraer_entidades(self, texto: str) -> Dict[str, List[str]]:
        """Extrae entidades nombradas con spaCy NER (6 categorías). Maneja textos > 800 K."""
        return extraer_entidades_texto_largo(self.nlp, texto)

    def normalizar_fecha(self, texto: str) -> Optional[str]:
        """Convierte expresión de fecha en español a YYYY-MM-DD."""
        return _normalizar_fecha(texto)

    def extraer_metadatos_norma(self, texto: str, nombre_archivo: str = '') -> Dict:
        """Extrae tipo, número, fecha, entidad emisora y título de una norma colombiana."""
        return _extraer_meta(self.nlp, texto, nombre_archivo=nombre_archivo)

    def extraer_temas(self, texto: str, top_n: int = 10) -> List[Tuple[str, float]]:
        """Palabras clave por frecuencia de lemas filtradas por POS tag."""
        return _extraer_temas(self.nlp, texto, top_n)

    # ── Resumen abstractivo ───────────────────────────────────────────────

    def generar_resumen_abstractivo(self, texto: str,
                                    max_length: int = 150,
                                    min_length: int = 10,
                                    chunk_chars: int = 3000) -> str:
        """Resumen mT5 con map-reduce. Carga el pipeline al primer uso."""
        if self._pipeline_resumen is None:
            self._pipeline_resumen = cargar_pipeline_resumen()
        return _gen_resumen(self._pipeline_resumen, texto, max_length, min_length, chunk_chars)

    # ── Búsqueda conceptual Word2Vec ──────────────────────────────────────

    def buscar_conceptual(self, query: str,
                          documentos_elastic: List[Dict],
                          campo_texto: str = 'contenido',
                          umbral_similitud: float = 0.0) -> List[Dict]:
        """Re-rankea hits de Elasticsearch por similitud coseno (Word2Vec o GloVe spaCy como fallback)."""
        if self._wv is None and self.nlp is None:
            return documentos_elastic
        return buscar_documentos_conceptuales(
            query, documentos_elastic, self._wv, self.nlp,
            campo_texto=campo_texto, umbral_similitud=umbral_similitud,
        )

    def vectorizar(self, texto: str) -> Optional[object]:
        """Vector promedio Word2Vec del texto. None si OOV o modelo no cargado."""
        if self._wv is None:
            return None
        return vectorizar_texto(texto, self._wv, self.nlp)

    # ── Procesamiento completo ────────────────────────────────────────────

    def procesar_texto_largo(self, texto: str) -> Dict:
        """Extrae entidades, temas y resumen. extraer_entidades maneja el chunking internamente."""
        return {
            "entidades": self.extraer_entidades(texto),
            "temas": self.extraer_temas(texto[:500_000]),
            "resumen": self.generar_resumen_abstractivo(texto),
        }

    def close(self):
        pass