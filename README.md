# NormaSearch

Motor de búsqueda semántica para normatividad colombiana mediante Procesamiento de Lenguaje Natural (PLN).

## Descripción

NormaSearch permite indexar, analizar y buscar documentos normativos colombianos (decretos, leyes, resoluciones, CONPES, circulares) combinando recuperación léxica BM25 con re-ranking semántico por similitud coseno (Word2Vec / GloVe).

El sistema aplica un pipeline PLN completo: extracción de texto PDF (PyMuPDF + OCR), normalización, NER con spaCy, extracción de metadatos estructurados, vectorización de documentos y resumen abstractivo con mT5.

## Tecnologías

| Capa | Tecnología |
|------|------------|
| Backend | Python · Flask |
| Motor de búsqueda | Elasticsearch (BM25 + Word2Vec) |
| PLN | spaCy `es_core_news_lg` · Word2Vec (gensim) |
| Resumen | Transformers mT5-small (Hugging Face) |
| Base de datos | MongoDB |
| Extracción PDF | PyMuPDF · Tesseract OCR |
| Frontend | Bootstrap 5 |

## Repositorio

[https://github.com/jdiazg14/BigData-PLN-2026](https://github.com/jdiazg14/BigData-PLN-2026)

## Autor

**Juan Carlos Díaz González**  
Maestría en Analítica de Datos — Universidad Central  
jdiazg14@ucentral.edu.co

## Versión

`3.0.0` — 2026
