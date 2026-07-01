# NormaSearch — Informe Técnico de Procesamiento de Lenguaje Natural

**Motor de Búsqueda Semántica para Normatividad Colombiana**

Juan Carlos Díaz González  
Procesamiento de Lenguaje Natural  
Profesor: Miguel Ángel Rippe Espinosa  
Maestría en Analítica de Datos — Universidad Central  
Bogotá D.C., 2026 · Versión 3.0.0

---

## Tabla de contenidos

1. [Introducción](#1-introducción)
2. [Problema que resuelve](#2-problema-que-resuelve)
3. [Arquitectura general del sistema](#3-arquitectura-general-del-sistema)
4. [Corpus normativo](#4-corpus-normativo)
5. [Módulo 1 — Extracción de texto PDF](#5-módulo-1--extracción-de-texto-pdf)
6. [Módulo 2 — Preprocesamiento de texto](#6-módulo-2--preprocesamiento-de-texto)
7. [Módulo 3 — Reconocimiento de entidades nombradas y metadatos](#7-módulo-3--reconocimiento-de-entidades-nombradas-y-metadatos)
8. [Módulo 4 — Resumen abstractivo con Transformers](#8-módulo-4--resumen-abstractivo-con-transformers)
9. [Módulo 5 — Búsqueda semántica con Word2Vec](#9-módulo-5--búsqueda-semántica-con-word2vec)
10. [Módulo 6 — Orquestador del pipeline (pipeline.py)](#10-módulo-6--orquestador-del-pipeline)
11. [Módulo 7 — Fachada PLN (PLN.py)](#11-módulo-7--fachada-pln)
12. [Módulo 8 — Métricas operacionales (metrics.py)](#12-módulo-8--métricas-operacionales)
13. [Flujo completo de procesamiento](#13-flujo-completo-de-procesamiento)
14. [Métricas y resultados](#14-métricas-y-resultados)
15. [Desafíos técnicos y soluciones](#15-desafíos-técnicos-y-soluciones)
16. [Consideraciones éticas](#16-consideraciones-éticas)
17. [Limitaciones y trabajo futuro](#17-limitaciones-y-trabajo-futuro)
18. [Errores detectados en la presentación](#18-errores-detectados-en-la-presentación)
19. [Conclusiones](#19-conclusiones)

---

## 1. Introducción

NormaSearch es un motor de búsqueda semántica diseñado para normatividad colombiana del sector agropecuario. Permite a los funcionarios de la Contraloría Delegada para el Sector Agropecuario buscar decretos, leyes, resoluciones, acuerdos, circulares y documentos CONPES usando lenguaje natural en lugar de palabras clave exactas.

El sistema combina dos estrategias complementarias:

- **Recuperación léxica BM25** sobre Elasticsearch: encuentra documentos que contienen los términos de la consulta.
- **Re-ranking semántico por similitud coseno**: reordena esos documentos según qué tan parecido es su *significado* al de la consulta, usando vectores Word2Vec entrenados en el propio corpus normativo colombiano.

Además del buscador, NormaSearch incluye un pipeline completo de Procesamiento de Lenguaje Natural (PLN) que extrae automáticamente texto de los PDFs, identifica entidades (personas, organizaciones, fechas, leyes), extrae metadatos estructurados (tipo de norma, número, año, entidad emisora) y genera resúmenes automáticos con inteligencia artificial.

---

## 2. Problema que resuelve

El Ministerio de Agricultura y Desarrollo Rural emite constantemente decretos, resoluciones, leyes y documentos CONPES. Los funcionarios de la Contraloría que los auditan enfrentan tres problemas concretos:

### 2.1 La búsqueda por palabras clave es insuficiente

Si un funcionario busca "incentivos para pequeños productores" pero la norma habla de "subsidios para agricultores de economía campesina", una búsqueda por palabras clave no la encontrará. Los dos conceptos son semánticamente equivalentes pero léxicamente distintos. NormaSearch resuelve esto con re-ranking semántico: el sistema entiende que las palabras tienen significados relacionados y puede recuperar documentos relevantes aunque no usen exactamente los mismos términos.

### 2.2 La lectura manual de documentos extensos consume tiempo

Un decreto puede tener 50 páginas. Leerlo para extraer la fecha de expedición, la entidad que lo firmó o los artículos relacionados con un tema específico consume horas. NormaSearch extrae automáticamente metadatos estructurados y genera un resumen por inteligencia artificial.

### 2.3 La información no está estructurada

Sin un repositorio que organice automáticamente las normas por tipo, año, entidad emisora y tema, la trazabilidad de la política pública depende de la memoria del auditor. NormaSearch indexa cada documento con sus metadatos, entidades y palabras clave, y permite filtrar por cualquiera de esos campos.

---

## 3. Arquitectura general del sistema

NormaSearch está implementado en Python 3.11 con Flask como servidor web. Se organiza en dos flujos principales:

```
FLUJO DE CARGA (administrador)
  ① Ingesta de documentos
        ↓
  ② Extracción de texto (PyMuPDF → OCR fallback)
        ↓
  ③A Extracción de información
       - Entidades nombradas (NER spaCy)
       - Metadatos estructurados (cascada: archivo → NER → regex → diccionario)
       - Palabras clave (POS-tagging spaCy)
        ↓
  ③B Resumen abstractivo (mT5 — Transformers/HuggingFace)
        ↓
  ④ Indexación en Elasticsearch

FLUJO DE CONSULTA (usuario)
  consulta del usuario
        ↓
  ⑤ Recuperación BM25 (Elasticsearch, campo texto, pool configurable 5–200 docs)
        ↓
  ⑥ Re-ranking semántico (Word2Vec/GloVe, similitud coseno)
        ↓
  ⑦ Resultados al usuario
       - Normas reordenadas + resumen + entidades + metadatos
       - Filtros por tipo, año, entidad emisora
       - Evaluación Precisión@5 interactiva
```

### Módulos de código

| Módulo | Archivo | Qué hace |
|--------|---------|----------|
| Aplicación web | `app.py` | Rutas Flask, API REST, Server-Sent Events |
| Orquestador pipeline | `Helpers/PLN/pipeline.py` | Coordina las fases de extracción, NER y resumen |
| Fachada PLN | `Helpers/PLN/PLN.py` | Interfaz unificada que encapsula todos los módulos PLN |
| Preprocesamiento | `Helpers/PLN/text_preprocessing.py` | Limpieza, tokenización, lematización, stopwords |
| Entidades y metadatos | `Helpers/PLN/entity_extractor.py` | NER, extracción de metadatos, detección de fechas |
| Resumen abstractivo | `Helpers/PLN/summarizer.py` | mT5 con chunking y cálculo de perplejidad |
| Búsqueda vectorial | `Helpers/PLN/vector_search.py` | Word2Vec / GloVe, similitud coseno, re-ranking |
| Métricas | `Helpers/PLN/metrics.py` | Registro y agregación de métricas operacionales |
| Extracción PDF | `Helpers/Utils/funciones.py` | PyMuPDF, validación de calidad, OCR fallback |
| Elasticsearch | `Helpers/BasesDatos/elastic.py` | Indexación masiva y búsqueda BM25 |
| MongoDB | `Helpers/BasesDatos/mongoDB.py` | Usuarios, roles y permisos |
| Web scraping | `Helpers/Ingesta/webScrapingMinAgricultura.py` | Playwright + descarga de PDFs del MinAgricultura |

---

## 4. Corpus normativo

| Característica | Detalle |
|----------------|---------|
| Fuente | Portal normativo del Ministerio de Agricultura y Desarrollo Rural — minagricultura.gov.co |
| Tipos de documentos | Decretos, Resoluciones, Leyes, CONPES, Circulares, Acuerdos |
| Período cubierto | 1991 – 2025 |
| Documentos procesados | 121 documentos PDF |
| Documentos indexados exitosamente | 120 (1 fallido por PDF con estructura interna corrupta) |
| Formatos | PDFs digitales nativos y documentos escaneados |
| Idioma | Español colombiano |
| Deduplicación | Hash SHA-256 por archivo |

---

## 5. Módulo 1 — Extracción de texto PDF

**Archivo:** `Helpers/Utils/funciones.py`  
**Clase:** `Funciones`

### ¿Qué problema resuelve?

Los documentos del sector normativo son PDFs heterogéneos. Algunos tienen texto digital incrustado (PDFs nativos) y otros son fotografías de papel escaneado. Además, algunos PDFs nativos tienen fuentes con codificación no estándar que produce texto corrupto ("caracteres extraños").

### Estrategia: extracción con validación y fallback OCR

```
Paso 1: extraer_texto_pdf()
  - Abre el PDF con PyMuPDF (librería fitz)
  - Lee el texto de cada página: page.get_text()
  - PyMuPDF interpreta las tablas de fuente internas del PDF y devuelve texto Unicode
  - PyMuPDF NO necesita detectar encoding: opera sobre el binario del PDF directamente

Paso 2: _calidad_texto()
  - Evalúa si el texto extraído es legible aplicando 4 criterios estadísticos:
    1. Mínimo de 20 palabras (descarta documentos casi vacíos)
    2. Una sola palabra no supera el 30% del total (detecta texto repetitivo o corrupto)
    3. El vocabulario único no es excesivamente pequeño
    4. Al menos el 40% de los caracteres son letras (descarta texto binario)
    5. Máximo 20% de tokens de un solo carácter (detecta fuentes mal decodificadas)
  - Retorna True si el texto es aceptable, False si hay problemas

Paso 3 (si _calidad_texto() retornó False): extraer_texto_pdf_ocr()
  - Convierte cada página del PDF a imagen con Poppler (pdf2image)
  - Aplica reconocimiento óptico de caracteres con Tesseract en español
  - pytesseract.image_to_string(image, lang='spa')
  - Produce texto legible a partir de PDFs escaneados o con fuentes corruptas

Paso 4 (si ambos fallan): el documento se descarta y se registra en métricas
```

### Función principal

```python
extraer_texto_pdf_con_metricas(ruta_pdf: str) → Tuple[str, Dict]
```

Retorna el texto extraído más un diccionario con:
- `metodo`: `"pymupdf"` u `"ocr"`
- `tiempo_segundos`: cuánto tardó
- `longitud_caracteres`: tamaño del texto
- `calidad_ok`: True/False

### Librerías utilizadas

| Librería | Versión | Para qué |
|----------|---------|----------|
| `PyMuPDF` (fitz) | 1.27.x | Extracción de texto de PDFs digitales |
| `pytesseract` | — | Reconocimiento óptico de caracteres |
| `pdf2image` | — | Conversión PDF → imágenes para OCR |
| `Pillow` (PIL) | — | Manejo de imágenes |

### Nota técnica sobre encoding

PyMuPDF **no necesita detectar el encoding del archivo** porque opera sobre el stream interno del PDF, no sobre bytes de texto. El encoding solo es relevante para archivos `.txt`, donde el sistema usa UTF-8 como primera opción y latin-1 como fallback en `procesar_documento()` de `pipeline.py`.

---

## 6. Módulo 2 — Preprocesamiento de texto

**Archivo:** `Helpers/PLN/text_preprocessing.py`

### ¿Qué problema resuelve?

Antes de alimentar texto a un modelo de PLN hay que limpiarlo y adaptarlo al consumidor. Sin embargo, **distintos modelos necesitan distintos niveles de limpieza**: un modelo Transformer como mT5 necesita el texto lo más original posible (con puntuación, números y mayúsculas), mientras que Word2Vec se beneficia de texto completamente normalizado (solo palabras informativas en minúsculas, sin stopwords).

Por eso el módulo implementa **tres funciones con propósitos distintos**:

### Función 1: `preprocesar_para_transformer(texto)` — Nivel mínimo

**Cuándo se usa:** antes de enviar texto a mT5 para generar resúmenes.

**Qué hace:**
1. Normalización Unicode NFC: unifica variantes de caracteres (por ejemplo, la "é" puede representarse como un solo carácter o como "e" + acento combinado; NFC los unifica al primero).
2. Elimina caracteres de control invisibles (U+0000–U+001F) que pueden confundir al tokenizador.
3. Colapsa espacios múltiples en uno solo.
4. **Conserva:** números, puntuación, mayúsculas, acentos, signos de interrogación, etc.

**Por qué NO aplica limpieza fuerte:** el AutoTokenizer de mT5 usa SentencePiece para partir las palabras en subunidades ("sub-tokens"). Necesita el texto original para construir esas subunidades correctamente. Si se convierten las palabras a minúsculas antes, "Ministerio" y "ministerio" producen tokens diferentes y la calidad del resumen se degrada.

**Librería:** `unicodedata` (biblioteca estándar de Python), `re`

### Función 2: `limpiar_texto(texto)` — Nivel 1

**Cuándo se usa:** antes de Word2Vec y de cualquier modelo que necesite texto normalizado pero sin análisis lingüístico.

**Qué hace:**
1. Convierte todo a minúsculas.
2. Elimina todo carácter que no sea letra española (a-z, á, é, í, ó, ú, ü, ñ) ni espacio. Los reemplaza por espacio (no por vacío, para no fusionar tokens: "Art.12" → "art  12", no "art12").
3. Colapsa espacios múltiples.

**Librerías:** `re`

### Función 3: `preprocesar_texto(nlp, texto, ...)` — Nivel 2 (pipeline completo)

**Cuándo se usa:** para construir el corpus de entrenamiento de Word2Vec, para TF-IDF y para la extracción de palabras clave.

**Qué hace:**

```
texto crudo
    → limpiar_texto() (minúsculas + charset español)
    → spaCy NLP (tokenización + POS-tagging + lematización)
    → filtrar por longitud mínima (default: 3 caracteres)
    → eliminar puntuación y espacios
    → eliminar números (opcional, parámetro remover_numeros)
    → eliminar stopwords (lista NLTK + lista legal extendida)
    → filtrar por categoría gramatical POS (solo NOUN, PROPN, ADJ, VERB)
    → lematizar: devuelve el lema (forma base del diccionario)
      o la forma cruda (si lematizar=False)
```

**Ejemplo:**
```
Entrada: "El Ministerio de Agricultura expidió el Decreto 1071 de 2015"
Salida:  "ministerio agricultura expedir decreto"
```

**Lista de stopwords legal extendida:** además de las stopwords genéricas de NLTK en español, se eliminan palabras sin carga semántica en el corpus normativo: `artículo`, `parágrafo`, `inciso`, `numeral`, `literal`, `mediante`, `respecto`, `cuya`, `cuyo`, y preposiciones legales frecuentes.

### Función 4: `aplicar_stemming(tokens)` — Reducción morfológica

Alternativa a la lematización. Reduce cada token a su raíz morfológica usando SnowballStemmer en español. Por ejemplo: "agricultores" → "agricultor", "agrícola" → "agr". El stem no siempre es una palabra real; se usa solo como clave de agrupación.

### Función 5: `dividir_en_chunks(texto, max_chars=800_000)`

Divide textos muy largos en fragmentos para evitar el límite de 1 millón de caracteres de spaCy. Corta en el último salto de línea antes del límite para no partir entidades multipalabra.

### Librerías y modelos utilizados

| Librería | Para qué |
|----------|----------|
| `spaCy` con `es_core_news_lg` | Tokenización, POS-tagging, lematización, vectores GloVe 300d |
| `NLTK` (`stopwords`) | Lista base de stopwords en español |
| `NLTK` (`SnowballStemmer`) | Stemming morfológico en español |
| `unicodedata` | Normalización Unicode NFC |
| `re` | Expresiones regulares para limpieza de caracteres |

---

## 7. Módulo 3 — Reconocimiento de entidades nombradas y metadatos

**Archivo:** `Helpers/PLN/entity_extractor.py`

### ¿Qué problema resuelve?

Los documentos normativos contienen información estructurada (quién lo emitió, cuándo, qué tipo de norma es) pero está embebida en texto libre. El módulo la extrae automáticamente para poder indexarla y filtrar por ella en el buscador.

---

### 7.1 NER — Reconocimiento de entidades nombradas

**Función principal:** `extraer_entidades_mejorado(nlp, texto) → (entidades, metricas)`

El sistema extrae seis categorías de entidades:

| Categoría | Etiqueta spaCy | Ejemplos |
|-----------|---------------|---------|
| Personas | `PER` | Ministros, funcionarios firmantes |
| Lugares | `LOC`, `GPE` | Departamentos, municipios, regiones |
| Organizaciones | `ORG` | Entidades del Estado, gremios, ministerios |
| Fechas | `DATE` | Fechas de expedición y vigencia |
| Leyes | `LAW` + regex | Decretos, resoluciones y leyes citadas |
| Otros | cualquier otro | Entidades no clasificadas |

**Problema específico: encabezados en mayúsculas**

Los documentos normativos colombianos frecuentemente tienen el título y el tipo de norma completamente en mayúsculas (ej.: "MINISTERIO DE AGRICULTURA Y DESARROLLO RURAL"). El modelo `es_core_news_lg` de spaCy fue entrenado sobre noticias con capitalización convencional y pierde sensibilidad cuando el texto está todo en mayúsculas.

**Solución — `normalizar_encabezado_para_ner(texto)`:**

Se procesan solo las primeras 30 líneas del documento. Para cada línea donde más del 80% de los caracteres alfabéticos estén en mayúsculas, se aplica `title()` (convierte a "Ministerio De Agricultura Y Desarrollo Rural"). El resto del documento no se toca para no perder contexto semántico.

**Problema específico: documentos largos**

spaCy tiene un límite interno de ~1 millón de caracteres. Documentos muy extensos fallan si se procesan de golpe.

**Solución — chunking automático:** si el texto supera 800.000 caracteres, se divide con `dividir_en_chunks()` y se acumulan las entidades de cada chunk.

**Complemento de fechas con regex:** spaCy frecuentemente omite fechas en encabezados con formato poco común. Se complementa buscando con expresiones regulares en las primeras 50 líneas:
- Patrón 1: "26 de marzo de 2019" → `_RE_FECHA_LARGA`
- Patrón 2: "marzo de 2019" → `_RE_FECHA_MES_ANIO`

**EntityRuler personalizado — `construir_entity_ruler()` en `PLN.py`:**

Para entidades jurídicas colombianas que spaCy omite frecuentemente, se agrega un componente `EntityRuler` al pipeline con patrones explícitos para 17 entidades:
- Ministerio de Agricultura y Desarrollo Rural
- INVIMA, ICA, FINAGRO, Banco Agrario, DNP, DANE
- Contraloría General de la República
- Congreso de la República / Colombia
- Presidencia de la República
- etc.

Con `overwrite_ents=False` el ruler solo añade entidades donde NER estadístico no encontró nada, preservando los resultados del modelo.

**Deduplicación preservando orden:** `list(dict.fromkeys(lista))` elimina entidades duplicadas sin alterar el orden de primera aparición. `set()` también deduplicaría pero reordenaría aleatoriamente.

---

### 7.2 Extracción de metadatos

**Función principal:** `extraer_metadatos_mejorado(nlp, texto, nombre_archivo) → (metadatos, metricas)`

Extrae seis campos estructurados de cada norma:

| Campo | Ejemplo |
|-------|---------|
| `tipo_norma` | DECRETO, LEY, RESOLUCIÓN, CONPES |
| `numero_norma` | 1071 |
| `anio_norma` | 2015 |
| `entidad_emisora` | MINISTERIO DE AGRICULTURA Y DESARROLLO RURAL |
| `fecha_documento` | 2015-05-26 (formato ISO 8601) |
| `titulo_norma` | "Por el cual se expide el Decreto Único..." |

**Estrategia en cascada por prioridad:**

```
PRIORIDAD 1 — Nombre del archivo
  Si el archivo se llama "DECRETO_1071_DE_26_DE_MAYO_DE_2015.pdf",
  tipo, número, año y fecha se extraen directamente del nombre.
  Es el método más confiable porque el nombre del archivo es inmune
  a la calidad del texto extraído o al layout del documento.
  Regex: _RE_NOMBRE_ARCHIVO

PRIORIDAD 2 — Texto del documento (fallback)
  Para los campos que el nombre no contiene:
  - Fecha: _RE_FECHA_LARGA busca "26 de mayo de 2015"
  - Fecha alternativa: _RE_FECHA_MES_ANIO busca "mayo de 2015"
  - Tipo de norma: _TIPOS_NORMA busca en el encabezado (ordenado de más
    a menos específico: "DECRETO LEGISLATIVO" antes de "DECRETO")
  - Número: _RE_NUMERO_NORMA busca "DECRETO 1071" o "RESOLUCIÓN N° 567"

PRIORIDAD 3 — NER sobre el encabezado
  Para la entidad emisora, que casi nunca está en el nombre del archivo:
  - Se ejecuta NER spaCy sobre las primeras 20 líneas del documento
  - Se selecciona la ORG más larga encontrada (heurística: el nombre más
    largo suele ser el nombre completo de la entidad, más informativo que
    un acrónimo o nombre parcial)
  - Se excluyen falsos positivos conocidos: "COLOMBIA", "REPÚBLICA DE"

PRIORIDAD 4 — Diccionario por tipo de norma
  Para normas con entidad emisora estándar conocida:
  - CONPES → "CONSEJO NACIONAL DE POLÍTICA ECONÓMICA Y SOCIAL"

PRIORIDAD 5 — Título de la norma
  Se busca en las primeras 50 líneas una línea que comience con
  "Por el cual", "Por la cual", "Por medio del cual", etc.
  Regex: _RE_TITULO
```

### 7.3 Extracción de palabras clave

**Función:** `extraer_temas(nlp, texto, top_n=10) → List[Tuple[str, float]]`

**Estrategia:**
1. Se aplica POS-tagging con spaCy al texto.
2. Se conservan solo tokens de categorías informativas: `NOUN`, `PROPN`, `ADJ`, `VERB`.
3. Se eliminan stopwords y tokens de menos de 4 caracteres.
4. Se cuenta la frecuencia de cada lema.
5. El score de cada tema se calcula como porcentaje del total de tokens relevantes, lo que hace los resultados comparables entre documentos de diferente extensión.

**Ejemplo:**
```
Texto: decreto sobre subsidios para agricultura familiar campesina...
Temas: [("subsidio", 4.2%), ("agricultura", 3.8%), ("campesino", 3.1%), ...]
```

### 7.4 Normalización de fechas

**Función:** `normalizar_fecha(texto) → str` (formato "YYYY-MM-DD")

Convierte expresiones de fecha en español a formato ISO 8601 usando la librería `dateparser`. Ejemplos:
- "26 de marzo de 2019" → "2019-03-26"
- "enero 2018" → "2018-01-01" (día 1 cuando no hay día explícito)

**Por qué dateparser y no spaCy DATE:** el proyecto necesita el valor numérico parseado para indexación y filtrado en Elasticsearch, no solo el span de texto.

**Función:** `buscar_fechas_en_texto(texto) → List[Tuple[str, str]]`

Detecta y normaliza todas las fechas que aparecen en un texto usando `dateparser.search.search_dates`.

### Librerías y modelos utilizados

| Librería | Para qué |
|----------|----------|
| `spaCy` (`es_core_news_lg`) | NER estadístico, POS-tagging, lematización |
| `dateparser` | Conversión de fechas en español a ISO 8601 |
| `re` | Expresiones regulares para tipos, números, años y fechas |
| `collections.Counter` | Conteo de frecuencia de lemas para temas |
| `time` | Medición de tiempo de inferencia NER |

---

## 8. Módulo 4 — Resumen abstractivo con Transformers

**Archivo:** `Helpers/PLN/summarizer.py`

### ¿Qué problema resuelve?

Un decreto puede tener 40 páginas. El funcionario necesita saber rápidamente de qué trata sin leerlo completo. El módulo genera automáticamente un resumen en lenguaje natural usando un modelo de inteligencia artificial.

### Tecnología: modelos mT5 (Multilingual T5)

mT5 es una familia de modelos de lenguaje de la familia T5 (Text-to-Text Transfer Transformer) entrenados por Google sobre textos en 101 idiomas. Son modelos "texto a texto": reciben una instrucción y un texto de entrada, y generan texto de salida. Para resumen, la instrucción es `"summarize: {texto}"`.

Los modelos mT5 son **encoders-decoders**: el encoder lee el texto de entrada y el decoder genera el resumen token por token.

### Modelos comparados

| Modelo | Parámetros | Velocidad (CPU) | Naturaleza |
|--------|-----------|-----------------|------------|
| `google/mt5-small` | 300 M | ~31 s/doc | Multilingüe genérico (101 idiomas) |
| `ELiRF/mt5-base-dacsa-es` | 580 M | ~68 s/doc | Fine-tuned en español (1,8 M pares) |

El modelo `ELiRF/mt5-base-dacsa-es` fue ajustado específicamente sobre el dataset DACSA (Dataset for Automatic Content Summarization in Spanish), que contiene 1,8 millones de pares artículo-resumen en español. Esto lo hace mucho más apto para generar resúmenes fluidos en español.

### Estrategia map-reduce para documentos largos

Los modelos mT5 tienen un límite de contexto de ~512 tokens (~2.000 caracteres). Un decreto de 40 páginas puede tener 100.000 caracteres. Para manejarlo se usa una estrategia map-reduce:

```
MAP:
  Dividir el texto en chunks de ~4.000 caracteres
  Para cada chunk:
    1. Preprocesar con preprocesar_para_transformer() (normalización mínima)
    2. Añadir prefijo "summarize: " (necesario para T5/mT5)
    3. Generar resumen parcial con el modelo

REDUCE:
  Concatenar todos los resúmenes parciales
  Si la concatenación supera 4.000 caracteres:
    Aplicar un paso adicional de resumen sobre la concatenación
  Resultado: un único resumen del documento completo
```

### Función principal

```python
generar_resumen_con_metricas(
    pipeline_resumen,
    texto: str,
    max_length: int = 300,   # máximo de tokens a generar
    min_length: int = 30,    # mínimo de tokens generados
    chunk_chars: int = 4000  # tamaño de cada chunk
) → Tuple[str, Dict]
```

Retorna el resumen más un diccionario con: modelo usado, tiempo total, número de chunks, longitud del resumen y perplejidad.

### Perplejidad como métrica de calidad

**¿Qué es la perplejidad?**

La perplejidad (PP) mide qué tan predecible y fluido es el texto generado para el modelo:

```
PP = exp( promedio de cross-entropy loss por token )
```

- Un valor **cercano a 1** indica texto muy coherente y natural (el modelo "no se sorprende" de ninguna palabra).
- Un valor **alto** indica texto ruidoso, incoherente o con terminología que el modelo no comprende bien.

**Cálculo:**
```python
calcular_perplexidad(pipeline_resumen, resumen)
```
1. Se tokeniza el resumen generado.
2. Se hace un forward pass del modelo con los tokens de entrada y de salida iguales.
3. El modelo retorna la cross-entropy loss promedio por token.
4. `PP = exp(loss)`.

Se ejecuta en `torch.no_grad()` para no acumular gradientes (solo evaluación, sin entrenar).

### Carga del pipeline

```python
cargar_pipeline_resumen(modelo_nombre: str) → pipeline o False
```

- Usa `AutoTokenizer` con `use_fast=False` porque el tokenizador Rust no existe para mT5.
- `legacy=True` suprime el aviso de comportamiento de T5Tokenizer en HuggingFace >= 4.31.
- Detecta automáticamente GPU (CUDA), Apple Silicon (MPS) o CPU.
- Retorna `False` (no `None`) si falla, para que `PLN.py` pueda distinguir "no intentado" de "intentado y fallido".

### Librerías y modelos utilizados

| Librería | Para qué |
|----------|----------|
| `transformers` (HuggingFace) | Pipeline de summarization, AutoTokenizer |
| `torch` (PyTorch) | Backend de inferencia, cálculo de perplejidad, `no_grad()` |
| `math` | `math.exp()` para calcular PP desde la loss |
| `time` | Medición de tiempo de generación |

---

## 9. Módulo 5 — Búsqueda semántica con Word2Vec

**Archivo:** `Helpers/PLN/vector_search.py`

### ¿Qué problema resuelve?

La búsqueda BM25 de Elasticsearch encuentra documentos que contienen los términos exactos de la consulta. Pero si el usuario busca "incentivos para productores" y el documento habla de "subsidios para agricultores", BM25 lo puede perder. El re-ranking semántico convierte tanto la consulta como los documentos en vectores numéricos y los compara por su dirección geométrica en el espacio vectorial: si dos vectores apuntan en la misma dirección, los conceptos son similares.

### Concepto clave: Word Embeddings (vectores de palabras)

Un embedding es una representación numérica de una palabra. Por ejemplo, la palabra "subsidio" puede representarse como un vector de 100 números [0.21, -0.45, 0.87, ...]. Palabras con significados similares tienen vectores similares (apuntan en direcciones parecidas en el espacio de 100 dimensiones).

Word2Vec aprende estos vectores analizando qué palabras aparecen juntas frecuentemente en el corpus. Si "subsidio" y "incentivo" aparecen en contextos similares, sus vectores serán parecidos.

### Word2Vec entrenado en el corpus normativo colombiano

**Función:** `entrenar_word2vec(corpus_tokenizado, ...) → Word2Vec`

**Parámetros del modelo entrenado:**
- **Arquitectura:** Skip-gram (`sg=1`). Dado una palabra central, predice las palabras del contexto. Es preferido para términos legales de baja frecuencia.
- **vector_size:** 100 (cada palabra se representa en 100 dimensiones)
- **window:** 5 (considera las 5 palabras antes y después)
- **min_count:** 2 (ignora palabras que aparecen menos de 2 veces)
- **epochs:** 50 (itera 50 veces sobre el corpus)
- **workers:** núcleos de CPU disponibles - 1

**Entrenamiento incremental:** si ya existe un modelo previo, `entrenar_word2vec(corpus, modelo_existente=modelo)` actualiza el vocabulario y re-entrena sin perder el aprendizaje previo.

### Fallback automático con GloVe (vectores de spaCy)

Si gensim no está disponible (por incompatibilidad de compilación) o no se ha entrenado un modelo, el sistema usa automáticamente los vectores GloVe de 300 dimensiones incluidos en `es_core_news_lg` de spaCy.

Ambas ramas (Word2Vec y GloVe) usan la misma fórmula de promedio y similitud coseno, por lo que los resultados son comparables aunque la dimensionalidad sea diferente (100 vs 300).

### Vectorización de documentos y consultas

**Función:** `vectorizar_texto(texto, modelo, nlp) → np.ndarray`

Un documento completo se representa como el **promedio de los vectores de sus tokens**:

```
vec(documento) = (1/k) · Σ vec(token_i)   para todos los tokens en el vocabulario
```

Por ejemplo, si el documento tiene 5.000 palabras y 4.700 están en el vocabulario Word2Vec, el vector del documento es el promedio de esos 4.700 vectores.

### Similitud coseno

**Función:** `calcular_similitud_coseno(vector_a, vector_b) → float`

```
similitud = (a · b) / (‖a‖ · ‖b‖)
```

- Valor 1.0: vectores idénticos (mismo significado).
- Valor 0.0: vectores perpendiculares (sin relación semántica).
- Valor -1.0: vectores opuestos (significados contrarios).

La similitud coseno mide el ángulo entre vectores, no su magnitud. Esto hace que documentos largos y cortos sean comparables aunque sus vectores promedio tengan magnitudes diferentes.

### Re-ranking semántico

**Función:** `buscar_documentos_conceptuales(query, documentos_elastic, modelo, nlp, ...) → List[Dict]`

```
1. Vectorizar la consulta del usuario
2. Si la consulta es completamente fuera del vocabulario (OOV):
   - Conservar el orden BM25 original (no se puede hacer re-ranking sin vector)
3. Para cada documento del pool BM25:
   - Vectorizar el texto del documento
   - Calcular similitud coseno entre vector_consulta y vector_documento
4. Ordenar los documentos de mayor a menor similitud
5. Retornar la lista reordenada
```

**Pool de re-ranking configurable:** el tamaño del pool (cuántos documentos BM25 se re-rankean) es configurable desde `/configuracion` en el panel de administración, con rango 5–200 y valor por defecto 20.

### Palabras similares

**Función:** `buscar_similares(modelo, termino, top_n=10) → List[Tuple[str, float]]`

Devuelve las N palabras más similares semánticamente a un término dado usando `modelo.most_similar()` de gensim.

### Librerías utilizadas

| Librería | Para qué |
|----------|----------|
| `gensim` (Word2Vec, KeyedVectors) | Entrenamiento y carga de modelos Word2Vec |
| `numpy` | Promedio de vectores, norma L2, producto punto, clip |
| `spaCy` (`es_core_news_lg`) | Vectores GloVe 300d como fallback |
| `multiprocessing` | Detección de núcleos disponibles para entrenamiento paralelo |

### Tolerancia a fallos de compilación

gensim 4.x requiere extensiones compiladas con Cython (C++). En Windows sin las herramientas de compilación MSVC, la instalación falla. El módulo detecta esto en tiempo de importación:

```python
try:
    from gensim.models import KeyedVectors, Word2Vec
    GENSIM_DISPONIBLE = True
except ImportError:
    GENSIM_DISPONIBLE = False
    # → activar fallback GloVe spaCy
```

---

## 10. Módulo 6 — Orquestador del pipeline

**Archivo:** `Helpers/PLN/pipeline.py`

### ¿Qué hace?

Coordina todas las etapas de procesamiento para convertir un PDF en un documento listo para indexar en Elasticsearch. También gestiona la comunicación entre las dos fases del pipeline (que ocurren en peticiones HTTP separadas) y persiste los textos temporales entre fases.

### Diseño de dos fases

El pipeline opera en dos fases opcionales controladas por el administrador:

**Fase 1 — Pipeline completo:**
```
Extracción de texto (PyMuPDF/OCR)
    → NER (spaCy)
    → Metadatos (cascada)
    → Temas (POS-tagging)
    → Resumen con modelo Fase 1 (rápido: mT5-small)
    → Guardar métricas
    → Guardar texto temporal en static/temp/{hash}.json
```

**Fase 2 — Solo resumen con modelo alternativo (opcional):**
```
Cargar texto temporal desde static/temp/{hash}.json
    → Resumen con modelo Fase 2 (calidad superior: mT5-base-dacsa-es)
    → Guardar métricas del modelo 2
```

**¿Por qué archivos temporales?** Las fases 1 y 2 ocurren en dos peticiones HTTP separadas (el browser hace dos llamadas SSE distintas). El texto extraído puede tener varios MB — demasiado para enviarlo al browser y de vuelta. Los archivos en `static/temp/` sirven de canal entre fases sin pasar por el browser.

### Funciones principales

| Función | Qué hace |
|---------|----------|
| `procesar_documento(ruta, nombre, hash, pln, modelo)` | Ejecuta el pipeline completo sobre un archivo |
| `procesar_fase1(ruta, nombre, hash, pln)` | Alias de procesar_documento con modelo de fase 1 |
| `procesar_fase2(texto, nombre, hash, pln)` | Genera solo resumen con modelo de fase 2 |
| `filtrar_archivos_nuevos(archivos, index, elastic)` | Excluye documentos ya indexados (por hash SHA-256) |
| `guardar_texto_temporal(hash, nombre, texto)` | Persiste texto entre fases en static/temp/ |
| `cargar_texto_temporal(hash)` | Recupera el texto para la fase 2 |
| `eliminar_texto_temporal(hash)` | Limpia el archivo temporal tras indexar |
| `liberar_modelo_resumen(pln)` | Libera el modelo de memoria (anula referencia, vacía caché CUDA, llama gc.collect()) |
| `estimar_tiempo_fase2(n_docs, tiempo_fase1)` | Estima el tiempo total de la fase 2 (factor empírico 2.5×) |
| `cargar_config_modelos()` | Lee config/models_config.json |
| `obtener_modelo_fase(fase)` | Retorna el modelo_hf configurado para fase1 o fase2 |

### Progreso en tiempo real (SSE)

El procesamiento de documentos puede tardar minutos. Para mostrar progreso sin que el usuario espere sin retroalimentación, se usa **Server-Sent Events (SSE)**: el servidor va enviando mensajes JSON al browser a medida que avanza cada paso:

```
[Fase 1] [1/12] DECRETO_1071_2015.pdf
  → Texto: pymupdf (42.580 chars)
  → Metadatos: 80%
  → Resumen: 3 segmentos, 94.2s, perpl: 312.4
```

Los parámetros de `request.args` se leen **fuera** del generador SSE porque dentro del generador el contexto de petición Flask puede no estar activo.

### Métricas por documento

Cada documento procesado genera un archivo JSON en `static/metrics/`:
- Modo normal: `{hash}_{modelo_fase1}.json`
- Modo comparación: además `{hash}_{modelo_fase2}.json`

Esto permite comparar la perplejidad y el tiempo de ambos modelos en el panel de métricas.

---

## 11. Módulo 7 — Fachada PLN

**Archivo:** `Helpers/PLN/PLN.py`  
**Clase:** `PLN`

### ¿Qué hace?

Es la interfaz unificada que encapsula todos los módulos PLN. En lugar de que `app.py` y `pipeline.py` importen directamente de `text_preprocessing`, `entity_extractor`, `summarizer` y `vector_search`, usan `PLN` como punto de acceso único. Esto reduce el acoplamiento y simplifica el código de nivel superior.

### Ciclo de vida de los modelos

Los tres modelos tienen estrategias de carga diferentes:

| Modelo | Estrategia | Por qué |
|--------|-----------|---------|
| spaCy `es_core_news_lg` | Carga al inicio (`__init__`) | Siempre se necesita; carga una sola vez |
| Word2Vec / GloVe | Carga explícita bajo demanda (`cargar_word2vec()`) | Archivo grande; no siempre necesario |
| mT5 (pipeline resumen) | Carga lazy al primer uso | Muy pesado (~1-2 GB); no cargar si no se va a resumir |

**Estado del pipeline mT5:**
- `None` = no se ha intentado cargar todavía
- `False` = se intentó cargar pero falló (evita reintentos innecesarios)
- `objeto pipeline` = cargado y listo para usar

### Optimización del pipeline spaCy

Al cargar spaCy, se desactivan los componentes que no se necesitan para reducir latencia:

```python
optimizar_nlp_pipeline(nlp)
# Desactiva 'parser' y 'senter' — no se necesita análisis sintáctico completo
# Mantiene activos: 'tok2vec', 'ner'
```

El EntityRuler personalizado se agrega **después** de optimizar, para que funcione sobre el pipeline ya reducido.

### Métodos principales

| Método | Delegado a |
|--------|-----------|
| `preprocesar_texto(texto)` | `text_preprocessing.preprocesar_texto()` |
| `preprocesar_para_transformer(texto)` | `text_preprocessing.preprocesar_para_transformer()` |
| `extraer_entidades(texto)` | `entity_extractor.extraer_entidades_mejorado()` |
| `extraer_metadatos_norma(texto, nombre)` | `entity_extractor.extraer_metadatos_mejorado()` |
| `extraer_temas(texto, top_n)` | `entity_extractor.extraer_temas()` |
| `normalizar_fecha(texto)` | `entity_extractor.normalizar_fecha()` |
| `generar_resumen_abstractivo(texto)` | `summarizer.generar_resumen_con_metricas()` |
| `buscar_conceptual(query, docs)` | `vector_search.buscar_documentos_conceptuales()` |
| `vectorizar(texto)` | `vector_search.vectorizar_texto()` |
| `cargar_word2vec(ruta)` | `vector_search.cargar_modelo_word2vec()` |
| `cargar_resumen(modelo)` | `summarizer.cargar_pipeline_resumen()` |

---

## 12. Módulo 8 — Métricas operacionales

**Archivo:** `Helpers/PLN/metrics.py`

### ¿Qué hace?

Registra y agrega métricas de cada documento procesado para el panel de administración. Permite comparar el rendimiento del sistema a lo largo del tiempo y entre modelos.

### Estructura de métricas por documento

Cada documento genera un JSON con cuatro secciones:

```json
{
  "nombre_archivo": "DECRETO_1071_2015.pdf",
  "hash_archivo": "sha256:abc123...",
  "fecha_procesamiento": "2026-01-15T14:30:00",
  "extraccion_texto": {
    "metodo": "pymupdf",
    "tiempo_segundos": 0.45,
    "longitud_caracteres": 42580,
    "calidad_ok": true
  },
  "ner": {
    "tiempo_ner_segundos": 3.2,
    "entidades_por_categoria": {"personas": 2, "organizaciones": 5, ...}
  },
  "metadatos": {
    "campos_completos": 4,
    "campos_vacios": 1,
    "completitud_porcentaje": 80.0,
    "detalle_campos": {"tipo_norma": true, "numero_norma": true, ...}
  },
  "resumen": {
    "modelo": "ELiRF/mt5-base-dacsa-es",
    "tiempo_segundos": 67.72,
    "num_chunks": 3,
    "longitud_resumen": 412,
    "longitud_texto": 42580,
    "perplexidad": 1.18
  }
}
```

**Nombre del archivo:** `{hash_limpio}_{modelo_resumen}.json`

En modo comparación, el mismo documento genera **dos archivos** (uno por modelo), por lo que en `static/metrics/` hay más archivos que documentos.

### Deduplicación en el resumen comparativo

**Problema:** en modo comparación, los dos archivos de métricas del mismo documento (uno por modelo) serían contados dos veces al calcular totales de extracción y metadatos.

**Solución** en `calcular_resumen_comparativo()`:
- Se mantienen dos sets: `_hashes_extraccion` y `_hashes_metadatos`.
- Antes de incrementar cualquier contador, se verifica que el hash del documento no esté ya en el set.
- Los registros de **fase 2** se detectan porque `calidad_ok is None` (la fase 2 no ejecuta extracción de texto).

### Métricas calculadas

**Extracción de texto:**
- Total de documentos intentados
- Exitosos con PyMuPDF / con OCR / fallidos
- Tasa de éxito (%)

**Metadatos:**
- Completitud por campo (tipo, número, año, entidad, fecha)
- Completitud promedio global

**Resumen por modelo:**
- Total documentos resumidos
- Perplejidad promedio, mínima y máxima
- Tiempo promedio de generación

---

## 13. Flujo completo de procesamiento

Para entender cómo colaboran todos los módulos, aquí el recorrido completo de un documento desde que se sube hasta que aparece en el buscador:

```
ADMINISTRADOR sube un ZIP con PDFs
           ↓
app.py — /procesar-zip-elastic
  Descomprime el ZIP en static/uploads/
           ↓
app.py — /procesar-fase1 (SSE)
  pipeline.filtrar_archivos_nuevos()
    → Funciones.calcular_hash_archivo() ← hashlib SHA-256
    → elastic.existe_hash() ← Elasticsearch
    → Omite documentos ya indexados
           ↓
  pipeline.procesar_fase1() por cada documento nuevo
           ↓
  pipeline.procesar_documento()
    ↓
    a. Funciones.extraer_texto_pdf_con_metricas()
         → fitz.open() → page.get_text()
         → Funciones._calidad_texto()
         → si falla: pytesseract.image_to_string()
         → metrics.registrar_extraccion_texto()
         → pipeline.guardar_texto_temporal() ← static/temp/{hash}.json
    ↓
    b. entity_extractor.extraer_entidades_mejorado()
         → normalizar_encabezado_para_ner()
         → pln.nlp() ← spaCy NER
         → regex fechas complementario
         → metrics.registrar_ner()
    ↓
    c. entity_extractor.extraer_metadatos_mejorado()
         → cascada: nombre → NER → regex → diccionario
         → PLN.normalizar_fecha() ← dateparser
         → metrics.registrar_metadatos()
    ↓
    d. PLN.extraer_temas()
         → spaCy POS-tagging + Counter
    ↓
    e. summarizer.generar_resumen_con_metricas()
         → text_preprocessing.preprocesar_para_transformer()
         → dividir en chunks de 4.000 chars
         → pipeline_resumen("summarize: {chunk}") ← mT5 HuggingFace
         → estrategia map-reduce
         → calcular_perplexidad() ← forward pass mT5 + math.exp()
         → metrics.registrar_resumen()
    ↓
    f. metrics.guardar_metricas() ← static/metrics/{hash}_{modelo}.json
    ↓
    g. Construir documento_elastic (dict con todos los campos)

  SSE → browser (progreso por documento)
  print() → consola del servidor (log de progreso)
           ↓

ADMINISTRADOR: pantalla de comparación (si modo_comparacion=True)
           ↓
app.py — /procesar-fase2 (SSE)
  pipeline.cargar_texto_temporal() ← static/temp/{hash}.json
  pipeline.procesar_fase2()
    → liberar_modelo_resumen() ← gc.collect() + torch.cuda.empty_cache()
    → pln.cargar_resumen(modelo_fase2)
    → summarizer.generar_resumen_con_metricas() con modelo_fase2
    → metrics.guardar_metricas() ← archivo independiente
           ↓

ADMINISTRADOR elige resumen (fase 1 o fase 2) por documento
           ↓
app.py — /indexar-seleccionados
  elastic.indexar_bulk() ← Elasticsearch
  pipeline.eliminar_texto_temporal() ← limpia static/temp/
           ↓

USUARIO hace una consulta en /buscador
           ↓
app.py — /buscar-elastic
  query match simple → elastic.buscar(size=RERANK_POOL_SIZE)
  pool_bm25: top-N documentos por BM25
  PLN.buscar_conceptual()
    → text_preprocessing.limpiar_texto()
    → vector_search.vectorizar_texto() ← Word2Vec o GloVe
    → vector_search.calcular_similitud_coseno() ← numpy
    → ordenar por similitud descendente
  Paginación en Python sobre el pool reordenado
  → Resultados al usuario: norma + resumen + entidades + temas + metadatos
```

---

## 14. Métricas y resultados

### 14.1 Extracción de texto

Evaluado sobre 121 documentos PDF del Ministerio de Agricultura y Desarrollo Rural (1991–2025):

| Indicador | Valor |
|-----------|-------|
| Total documentos procesados | 121 |
| Exitosos con PyMuPDF | 103 (85,1 %) |
| Exitosos con fallback OCR | 17 (14,0 %) |
| Fallidos (ambos métodos) | 1 (0,8 %) |
| **Tasa de éxito global** | **99,2 %** |

El único documento fallido tenía estructura interna corrupta que ni PyMuPDF ni Tesseract pudieron procesar.

### 14.2 Completitud de metadatos

Medida sobre 120 documentos indexados. **Importante:** esta métrica mide *cobertura* (el campo tiene un valor), no *precisión* (el valor es correcto). Un campo puede estar completo con un valor extraído incorrectamente.

| Campo | Completos | Total | Porcentaje |
|-------|-----------|-------|-----------|
| Tipo de norma | 120 | 120 | **100,0 %** |
| Número | 120 | 120 | **100,0 %** |
| Año | 120 | 120 | **100,0 %** |
| Entidad emisora | 90 | 120 | 75,0 % |
| Fecha del documento | 91 | 120 | 75,8 % |

Los campos tipo, número y año alcanzan 100% porque se extraen del nombre del archivo (método robusto). Los campos entidad emisora y fecha dependen del texto y de patrones en el encabezado.

### 14.3 Comparación de modelos de resumen — Perplejidad

| Modelo | Total docs | Perpl. promedio | Perpl. mínima | T. promedio (s) |
|--------|-----------|-----------------|--------------|-----------------|
| ELiRF/mt5-base-dacsa-es | 120 | **1,18** | 1,054 | 67,72 |
| google/mt5-small | 120 | 2.928,5 | 1,338 | 31,31 |

La diferencia es aproximadamente **2.486 veces** a favor de ELiRF/mt5-base-dacsa-es. Esta brecha se explica porque mT5-small es multilingüe genérico (101 idiomas), mientras que mt5-base-dacsa-es fue ajustado específicamente sobre texto en español.

Los valores extremos de perplejidad en mT5-small (hasta 346.806 en algunos documentos) indican que el modelo falla completamente en documentos con terminología jurídica densa.

### 14.4 Precisión@5 — Evaluación humana de la búsqueda

La evaluación de búsqueda compara dos métodos sobre exactamente el mismo campo y tipo de consulta (match simple sobre `texto`), garantizando una comparación justa:

| Consulta | P@5 BM25 | P@5 Semántico | T. BM25 | T. Re-ranking |
|----------|----------|---------------|---------|---------------|
| plaguicidas registro control fitosanitario | 0,8 | 0,8 | 21 ms | 13.285 ms |
| subsidio vivienda rural campesino | 0,6 | 1,0 | 23 ms | 14.606 ms |
| comunidades negras territorios colectivos | 0,6 | 1,0 | 27 ms | 14.436 ms |
| comercialización productos agrícolas precio mínimo | 0,4 | 0,8 | 24 ms | 14.165 ms |
| seguro agropecuario catástrofe natural cosecha | 0,8 | 1,0 | 29 ms | 15.695 ms |
| distritos riego adecuación tierras | 0,8 | 0,8 | 32 ms | 14.456 ms |
| sanidad animal ICA certificación exportación | 0,4 | 0,6 | 22 ms | 8.327 ms |
| reforma agraria adjudicación tierras baldías | 0,6 | 1,0 | 26 ms | 14.327 ms |
| incentivos producción agrícola pequeños productores | 0,6 | 0,6 | 23 ms | 12.167 ms |
| crédito agropecuario FINAGRO tasa subsidiada | 0,8 | 0,8 | 423 ms | 11.078 ms |
| **PROMEDIO** | **0,64** | **0,84** | **65 ms** | **13.254 ms** |

**Conclusiones:**
- El método semántico supera a BM25 puro en **8 de 10 consultas** (+31% promedio).
- En ninguna consulta el re-ranking semántico **degrada** los resultados respecto a BM25.
- Los 4 casos de P@5 = 1,0 (semántico perfecto) corresponden a consultas temáticamente específicas.
- El costo del re-ranking es ~13 segundos en CPU con pool=20 — admisible para búsqueda documental donde la precisión es prioritaria.

---

## 15. Desafíos técnicos y soluciones

### 15.1 PDFs con fuente mal decodificada

**Problema:** algunos PDFs del portal normativo usan fuentes con codificación no estándar. PyMuPDF extrae texto, pero los caracteres son ilegibles ("VERSIàN" en lugar de "VERSIÓN").

**Solución:** validador `_calidad_texto()` con cuatro criterios estadísticos que detecta este tipo de texto corrupto y activa el fallback OCR automáticamente.

### 15.2 Incompatibilidad de gensim con Python 3.14 en Windows

**Problema:** gensim requiere extensiones C++ compiladas con Cython. En Windows sin Microsoft C++ Build Tools, la compilación falla para Python 3.13+ .

**Solución:** importación tolerante a fallos con `try/except ImportError`. Si gensim no está disponible, `GENSIM_DISPONIBLE = False` activa la rama GloVe de spaCy como fallback sin interrumpir el sistema.

### 15.3 NER no detectaba entidades en texto completamente en mayúsculas

**Problema:** `es_core_news_lg` fue entrenado sobre noticias con capitalización convencional. Los encabezados normativos en MAYÚSCULAS reducen su sensibilidad para detectar organizaciones.

**Solución:** `normalizar_encabezado_para_ner()` convierte a Title Case las líneas con más del 80% de caracteres en mayúsculas antes de ejecutar NER.

### 15.4 Doble conteo en métricas en modo comparación

**Problema:** en modo comparación, cada documento genera dos archivos JSON de métricas (uno por modelo). `cargar_todas_las_metricas()` carga ambos, y los acumuladores de extracción y metadatos los contaban dos veces.

**Solución:** sets de deduplicación `_hashes_extraccion` y `_hashes_metadatos` en `calcular_resumen_comparativo()`. Además, los registros de fase 2 tienen `calidad_ok = None`, lo que permite detectarlos y excluirlos del conteo de extracción.

### 15.5 Comparación injusta en Precisión@5

**Problema:** la implementación inicial de `/evaluar-precision` usaba multi_match sobre 11 campos con boosts para BM25, mientras que el re-ranking semántico solo vectorizaba el campo `texto`. Los métodos no competían sobre la misma información.

**Solución:** se cambió la query de BM25 en `/evaluar-precision` a `match` simple sobre el campo `texto` exclusivamente, garantizando que ambos métodos usen exactamente la misma fuente de información. El endpoint `/buscar-elastic` del buscador normal mantiene el multi_match con 11 campos para maximizar la relevancia de búsqueda.

### 15.6 Contexto Flask no disponible dentro del generador SSE

**Problema:** dentro del generador `generate()` de Flask (que produce los eventos SSE), el contexto de la petición HTTP puede no estar activo. Intentar leer `request.args` dentro del generador causa `RuntimeError`.

**Solución:** los parámetros de `request.args` se leen **antes** de crear el generador y se capturan en el cierre (closure) de la función `generate()`.

### 15.7 Memoria del modelo mT5 entre peticiones

**Problema:** cargar mT5 consume 1–2 GB de RAM/VRAM. Si el administrador cambia el modelo activo en configuración, el modelo anterior debe liberarse antes de cargar el nuevo.

**Solución:** `liberar_modelo_resumen(pln)` anula la referencia al pipeline, vacía la caché CUDA con `torch.cuda.empty_cache()` y llama `gc.collect()` del recolector de basura de Python.

---

## 16. Consideraciones éticas

NormaSearch es una herramienta de apoyo al análisis, no un sistema de interpretación jurídica autónoma. Los resúmenes generados automáticamente y los resultados de búsqueda son insumos para facilitar el trabajo del funcionario, quien mantiene en todo momento la responsabilidad del criterio jurídico.

**Sobre los datos:** los documentos procesados son actos administrativos de carácter público publicados en el portal oficial del Ministerio de Agricultura. Su descarga y procesamiento se realiza dentro del marco legal colombiano de acceso a la información pública (Ley 1712 de 2014). Los nombres de funcionarios extraídos como entidades se usan exclusivamente para indexación y búsqueda, sin construir perfiles individuales (Ley 1581 de 2012).

**Sobre los modelos:** spaCy `es_core_news_lg` y mT5 fueron entrenados sobre corpus generales en español, no sobre texto jurídico colombiano. Esto puede introducir sesgos en la extracción de entidades (el modelo puede confundir términos técnicos normativos con entidades de noticias) y en la calidad de los resúmenes con terminología muy específica del dominio.

---

## 17. Limitaciones y trabajo futuro

### 17.1 Limitaciones actuales

| Limitación | Detalle |
|------------|---------|
| Completitud ≠ precisión en metadatos | Un campo puede estar "completo" con un valor incorrecto. No se ha medido la tasa de exactitud del dato extraído. |
| Costo del re-ranking en CPU | ~13 segundos por consulta con pool=20. En producción con GPU sería < 1 segundo. |
| Caracteres corruptos en PDFs | Algunos PDFs del Ministerio tienen caracteres mal decodificados en el PDF original (ej. "VERSIàN"). No es un problema de encoding del sistema sino del archivo fuente. Afecta la extracción de metadatos por regex. |
| Corpus pequeño para Word2Vec | 121 documentos es representativo pero insuficiente para que Word2Vec capture relaciones semánticas ricas. Con 500+ documentos los vectores serían más precisos. |
| JavaScript embebido en HTML | Los templates incluyen JavaScript inline, lo que reduce la mantenibilidad del frontend. |

### 17.2 Trabajo futuro

- **Corrección de caracteres corruptos:** implementar un mapa de sustitución aplicado al texto extraído y al nombre del archivo antes de la extracción de metadatos.
- **Métrica de precisión de metadatos:** validación manual de una muestra para medir no solo cobertura sino exactitud del valor extraído.
- **Vectores pre-calculados en Elasticsearch:** almacenar `dense_vector` por documento para eliminar la latencia del re-ranking en tiempo de consulta (de ~13 s a < 100 ms).
- **Ampliar el corpus:** escalar a 500–1.000 documentos y re-entrenar Word2Vec.
- **Ajuste fino de mT5:** entrenar sobre resúmenes normativos etiquetados para mejorar la pertinencia jurídica de los resúmenes generados.
- **Separar JavaScript de HTML:** mover los scripts a archivos `.js` en `static/js/` para mejorar la mantenibilidad y permitir caché del browser.
- **Descubrimiento de modelos:** registro automático de nuevos modelos de resumen compatibles en `models_config.json`.

---

## 18. Errores detectados en la presentación

Se encontraron dos inexactitudes en `NormaSearch_Presentacion.pdf`:

### Error 1 — Errata tipográfica en el nombre de la librería (Slide 3)

| Ubicación | Texto en la presentación | Corrección |
|-----------|--------------------------|-----------|
| Slide 3, Flujo de Consulta, paso ⑤ | "Word2Vec **(genism)**" | "Word2Vec **(gensim)**" |

La librería se llama **gensim** (con s antes de la i). Es una errata tipográfica sin efecto en el contenido técnico.

### Error 2 — Rango del pool de re-ranking incompleto (Slide 3)

| Ubicación | Texto en la presentación | Corrección |
|-----------|--------------------------|-----------|
| Slide 3, Flujo de Consulta, paso ④ | "Recupera pool configurable **(20–200 docs)**" | "Recupera pool configurable **(5–200 docs, default 20)**" |

El valor **20** es el default del campo `pool_reranking`, no el mínimo del rango. El rango real implementado en el código es **5–200** (validado en `guardar_configuracion()` de `app.py`). Indicar "20–200" sugiere que 20 es el mínimo, lo cual es incorrecto.

---

## 19. Conclusiones

NormaSearch demuestra que es posible construir un motor de búsqueda semántica para normatividad colombiana aplicando técnicas modernas de PLN sobre documentos PDF heterogéneos con herramientas de código abierto.

Los resultados confirman las hipótesis de diseño:

1. **El re-ranking semántico mejora Precisión@5 en un 31 %** respecto a BM25 puro (0,84 vs 0,64), sin degradar los resultados en ninguna de las 10 consultas evaluadas. El análisis conceptual rescata documentos que BM25 omite por no usar los mismos términos exactos.

2. **El ajuste fino en español es determinante para el resumen.** ELiRF/mt5-base-dacsa-es logra una perplejidad promedio de 1,18 frente a 2.928,5 de mT5-small — una mejora de aproximadamente 2.486 veces. No se debe asumir suficiencia en modelos multilingüe generalistas para dominios especializados.

3. **El pipeline con fallback OCR logra el 99,2 % de éxito** sobre el corpus heterogéneo. La estrategia de validación estadística de calidad del texto (`_calidad_texto()`) es más robusta que una simple verificación de longitud.

4. **La extracción de metadatos por cascada de prioridades** logra 100% de cobertura en tipo, número y año aprovechando el nombre del archivo, método inmune a la calidad del texto extraído.

5. **El principal aprendizaje técnico:** la calidad del pipeline PLN depende críticamente de la calidad del texto extraído, tan importante como los propios modelos de lenguaje. La arquitectura modular permite que cada componente evolucione de forma independiente.

El sistema tiene potencial real para apoyar procesos de auditoría en entidades del Estado colombiano, reduciendo el tiempo de localización de normas relevantes y facilitando la síntesis de documentos extensos con resumen automático de alta calidad lingüística.

---

*NormaSearch v3.0.0 — Maestría en Analítica de Datos · Universidad Central · Bogotá D.C., 2026*
