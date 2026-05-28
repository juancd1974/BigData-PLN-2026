# NormaSearch

![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.x-000000?logo=flask&logoColor=white)
![Elasticsearch](https://img.shields.io/badge/Elasticsearch-8.x-005571?logo=elasticsearch&logoColor=white)
![spaCy](https://img.shields.io/badge/spaCy-es__core__news__lg-09A3D5?logoColor=white)
![HuggingFace](https://img.shields.io/badge/HuggingFace-mT5-FF9D00?logo=huggingface&logoColor=white)

Motor de búsqueda semántica para normatividad colombiana (decretos, leyes, resoluciones, CONPES, circulares).
Combina recuperación léxica BM25 con re-ranking semántico por similitud coseno, un pipeline PLN completo de
extracción, NER y resumen abstractivo, y un panel de administración web. Desarrollado como proyecto académico de
la **Maestría en Analítica de Datos** — Universidad Central, Bogotá, 2026.

---

## Características y módulos

### Ingesta de documentos
Carga de documentos normativos mediante scraping automatizado del portal MinAgricultura o desde carpeta local / archivo ZIP.
**Tecnologías:** Playwright, PyMuPDF, Tesseract OCR

### Pipeline PLN
Extracción de texto PDF con fallback automático a OCR, normalización y lematización, reconocimiento de entidades
con `EntityRuler` configurado para el dominio normativo colombiano (leyes, organizaciones, personas, lugares),
y deduplicación por hash SHA-256.
**Tecnologías:** spaCy `es_core_news_lg`, PyMuPDF, Tesseract

### Resumen abstractivo
Generación de resúmenes con dos modelos comparables y cálculo de perplejidad como métrica de calidad.
**Tecnologías:** `google/mT5-small`, `ELiRF/mt5-base-dacsa-es` (Hugging Face Transformers)

### Búsqueda híbrida
Búsqueda léxica BM25 sobre Elasticsearch con re-ranking semántico por similitud coseno sobre vectores Word2Vec
entrenados en el corpus propio, o GloVe 300d como fallback. Soporta filtros por tipo de norma, año y entidad.
**Tecnologías:** Elasticsearch, Word2Vec (gensim), GloVe 300d (spaCy)

### Entrenamiento Word2Vec
Entrenamiento desde cero o reentrenamiento incremental sobre el corpus normativo, con progreso en tiempo real vía SSE.
**Tecnologías:** gensim Word2Vec (Skip-gram / CBOW)

### Panel de administración
Gestión de usuarios y permisos por rol, administración de índices Elasticsearch, carga y procesamiento de documentos.
**Tecnologías:** Flask, MongoDB, Bootstrap 5

### Panel de métricas
Estadísticas de extracción (PyMuPDF vs. OCR), completitud de metadatos por campo, comparación de modelos de
resumen y evaluación Precisión@5 de BM25 puro vs. búsqueda semántica con historial acumulado.
**Tecnologías:** Bootstrap 5, JSON acumulativo en `static/metrics/`

---

## Arquitectura

### Módulos principales

| Módulo | Archivo | Descripción |
|---|---|---|
| Aplicación web | `app.py` | Rutas Flask, API REST, Server-Sent Events |
| Orquestador pipeline | `Helpers/PLN/pipeline.py` | Coordina fases de extracción, NER y resumen |
| Interfaz PLN | `Helpers/PLN/PLN.py` | Clase unificada para consumir el pipeline |
| Preprocesamiento | `Helpers/PLN/text_preprocessing.py` | Tokenización, lematización, stopwords |
| Entidades | `Helpers/PLN/entity_extractor.py` | NER con EntityRuler dominio colombiano |
| Resumen | `Helpers/PLN/summarizer.py` | mT5 con chunking y cálculo de perplejidad |
| Búsqueda vectorial | `Helpers/PLN/vector_search.py` | Word2Vec / GloVe, similitud coseno |
| Métricas | `Helpers/PLN/metrics.py` | Registro y agregación de métricas operacionales |
| Elasticsearch | `Helpers/BasesDatos/elastic.py` | Indexación bulk y búsqueda BM25 |
| MongoDB | `Helpers/BasesDatos/mongoDB.py` | Usuarios, roles y permisos |
| Scraping | `Helpers/Ingesta/webScrapingMinAgricultura.py` | Playwright + descarga de PDFs |

### Árbol de directorios

```
BigData-PLN-2026/
├── app.py                      # Aplicación Flask principal
├── Helpers/
│   ├── PLN/                    # Pipeline PLN completo
│   ├── BasesDatos/             # Elasticsearch · MongoDB
│   ├── Ingesta/                # Web scraping
│   └── Utils/                  # Utilidades generales
├── templates/                  # Plantillas Jinja2
├── static/
│   ├── css/                    # Estilos (paleta azul institucional)
│   ├── metrics/                # JSON de métricas acumuladas por documento
│   └── uploads/                # Archivos temporales de procesamiento
├── models/                     # Modelos Word2Vec entrenados (.model)
├── .env.example                # Plantilla de variables de entorno
├── requirements.lock           # Dependencias fijadas
├── README.md
└── INSTALLATION_GUIDE.md       # Guía completa de instalación
```

---

## Tecnologías

| Capa | Tecnología | Versión |
|---|---|---|
| Backend | Python · Flask | 3.11 · 3.x |
| Base de datos documental | MongoDB | 7.x |
| Motor de búsqueda | Elasticsearch | 8.x |
| PLN principal | spaCy `es_core_news_lg` | 3.x |
| Vectores semánticos | Word2Vec (gensim) · GloVe 300d | 4.x |
| Resumen abstractivo | `google/mT5-small` · `ELiRF/mt5-base-dacsa-es` | Hugging Face |
| Extracción PDF | PyMuPDF · Tesseract OCR · Poppler | — |
| Web scraping | Playwright | — |
| Autenticación | Werkzeug (hashing seguro) | — |
| Frontend | Bootstrap 5 · Jinja2 | 5.3 |

---

## Instalación rápida

```bash
# 1. Clonar el repositorio
git clone https://github.com/jdiazg14/BigData-PLN-2026.git
cd BigData-PLN-2026

# 2. Crear y activar entorno virtual
python -m venv venv
venv\Scripts\activate          # Windows

# 3. Instalar dependencias
pip install -r requirements.lock

# 4. Configurar variables de entorno
copy .env.example .env
# Editar .env: MONGO_URI, ELASTIC_URL, ELASTIC_PASSWORD, SECRET_KEY

# 5. Ejecutar
python app.py
```

> **Para instalación completa** incluyendo MongoDB, Elasticsearch, Tesseract, Poppler, modelo spaCy y
> configuración con GPU, ver [`INSTALLATION_GUIDE.md`](INSTALLATION_GUIDE.md).

---

## Documentación

- [Guía de instalación](INSTALLATION_GUIDE.md)
- [Manual de usuario](USER_GUIDE.md)
- [Manual de administrador](ADMIN_GUIDE.md)

---

## Flujo de uso

1. **Autenticación** — Iniciar sesión con un usuario administrador desde `/login`.
2. **Ingesta** — En el panel de administración, cargar documentos desde el portal MinAgricultura (scraping), carpeta local o archivo ZIP.
3. **Pipeline PLN** — El sistema extrae texto (PyMuPDF o Tesseract con fallback automático), identifica entidades, extrae metadatos estructurados y genera resúmenes con mT5.
4. **Indexación** — Los documentos procesados se indexan en Elasticsearch con metadatos, entidades y temas PLN.
5. **Búsqueda** — Desde `/buscador`, realizar consultas en lenguaje natural con filtros; el sistema aplica BM25 y re-rankea con similitud coseno sobre vectores Word2Vec o GloVe.
6. **Evaluación P@5** — En la pestaña "Evaluación P@5", comparar la precisión de BM25 puro vs. semántico marcando documentos relevantes entre los top-5 de cada método.
7. **Métricas** — En `/metricas`, consultar estadísticas de extracción, completitud de metadatos, comparación de modelos de resumen y el historial de evaluaciones Precisión@5.

---

## Métricas implementadas

El panel `/metricas` registra cuatro dimensiones: **extracción de texto** (tasa de éxito PyMuPDF vs. OCR por
documento), **completitud de metadatos** (porcentaje de campos estructurados sobre el total indexado),
**comparación de modelos de resumen** (perplejidad promedio, mínima y máxima agrupada por modelo) y
**Precisión@5** (P@5 de BM25 puro vs. BM25 con re-ranking semántico, acumulada a partir de evaluaciones
manuales realizadas desde el buscador). Todas las métricas se persisten en `static/metrics/` como JSON.

---

## Autor

**Juan Carlos Díaz González**  
Maestría en Analítica de Datos — Universidad Central, Bogotá  
[jdiazg14@ucentral.edu.co](mailto:jdiazg14@ucentral.edu.co)

---

## Versión

`3.0.0` — 2026
