"""
Capa de abstracción de modelos NLP para NormaSearch.

Encapsula y gestiona el estado de los modelos de ML (spaCy, Word2Vec, mT5)
y expone métodos de alto nivel para procesamiento lingüístico. Es una fachada
orientada a objetos sobre los módulos especializados de Helpers/PLN:
  text_preprocessing → normalización y tokenización
  entity_extractor   → NER, metadatos, detección de fechas
  vector_search      → Word2Vec, vectorización, búsqueda conceptual
  summarizer         → resumen abstractivo con mT5

Su responsabilidad es gestionar el ciclo de vida de los modelos: carga, uso
y liberación de memoria. No conoce ni gestiona documentos, archivos, métricas
ni persistencia — esas responsabilidades pertenecen a pipeline.py.
"""

import spacy
from typing import Any, Dict, List, Optional, Tuple

from Helpers.PLN.text_preprocessing import (
    preprocesar_texto as _prep_texto,
    preprocesar_para_transformer,
    dividir_en_chunks as _dividir,
)
from Helpers.PLN.entity_extractor import (
    normalizar_fecha as _normalizar_fecha,
    extraer_temas as _extraer_temas,
    extraer_entidades_mejorado as _extraer_entidades,
    extraer_metadatos_mejorado as _extraer_meta,
)
from Helpers.PLN.vector_search import (
    cargar_modelo_word2vec,
    vectorizar_texto,
    buscar_documentos_conceptuales,
)
from Helpers.PLN.summarizer import (
    cargar_pipeline_resumen,
    generar_resumen_con_metricas as _gen_resumen,
)


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
            self.nlp = optimizar_nlp_pipeline(self.nlp)  # deshabilita 'parser' y 'senter' para reducir latencia
            construir_entity_ruler(self.nlp)              # debe llamarse después de optimizar: agrega ORG al pipeline ya reducido
            print(f"  ✓ '{self.modelo_spacy_nombre}' cargado")
        except OSError:
            print(f"  ✗ Modelo '{self.modelo_spacy_nombre}' no encontrado.")
            print(f"    Ejecuta: python -m spacy download {self.modelo_spacy_nombre}")
            try:
                self.nlp = spacy.load('es_core_news_sm')
                self.nlp = optimizar_nlp_pipeline(self.nlp)  # deshabilita 'parser' y 'senter' para reducir latencia
                construir_entity_ruler(self.nlp)              # debe llamarse después de optimizar: agrega ORG al pipeline ya reducido
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
        entidades, _ = _extraer_entidades(self.nlp, texto)
        return entidades

    def normalizar_fecha(self, texto: str) -> Optional[str]:
        """Convierte expresión de fecha en español a YYYY-MM-DD."""
        return _normalizar_fecha(texto)

    def extraer_metadatos_norma(self, texto: str, nombre_archivo: str = '') -> Dict:
        """Extrae tipo, número, fecha, entidad emisora y título de una norma colombiana."""
        metadatos, _ = _extraer_meta(self.nlp, texto, nombre_archivo=nombre_archivo)
        return metadatos

    def extraer_temas(self, texto: str, top_n: int = 10) -> List[Tuple[str, float]]:
        """Palabras clave por frecuencia de lemas filtradas por POS tag."""
        return _extraer_temas(self.nlp, texto, top_n)

    # ── Resumen abstractivo ───────────────────────────────────────────────

    def generar_resumen_abstractivo(self, texto: str,
                                    max_length: int = 300,
                                    min_length: int = 30,
                                    chunk_chars: int = 4000) -> str:
        """Resumen mT5 con map-reduce. Carga el pipeline al primer uso."""
        if self._pipeline_resumen is None:
            self._pipeline_resumen = cargar_pipeline_resumen()
        resumen, _ = _gen_resumen(self._pipeline_resumen, texto, max_length, min_length, chunk_chars)
        return resumen

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

