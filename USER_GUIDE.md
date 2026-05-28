# Manual de Usuario — NormaSearch

**Versión 3.0.0 · Contraloría Delegada para el Sector Agropecuario**

---

## 1. ¿Qué es NormaSearch?

NormaSearch es un motor de búsqueda especializado en normatividad colombiana del sector agropecuario. Permite consultar decretos, leyes, resoluciones, acuerdos, circulares y documentos CONPES mediante búsqueda en lenguaje natural, con filtros por tipo de norma, año y entidad emisora. Cada resultado incluye un resumen automático generado por inteligencia artificial y las entidades identificadas en el texto.

---

## 2. Acceso al sistema

| Dato | Valor |
|------|-------|
| URL local | `http://localhost:5000/buscador` |
| URL en red (si está publicado) | La suministra el administrador del sistema |

El buscador es de **acceso público** — no requiere iniciar sesión para realizar consultas. El login (`/login`) es exclusivo para administradores del sistema.

---

## 3. Cómo realizar una búsqueda

### 3.1 Campo de búsqueda

Escriba su consulta en el campo central de la pantalla y presione **Buscar** o la tecla `Enter`.

### 3.2 Tipos de consulta recomendados

| Tipo | Ejemplo | Cuándo usarlo |
|------|---------|---------------|
| **Palabras clave** | `subsidios rurales` | Cuando conoce términos técnicos del tema |
| **Frases cortas (2–4 palabras)** | `crédito agropecuario FINAGRO` | Para acotar el tema a una entidad o programa concreto |
| **Lenguaje natural** | `¿Qué normas regulan los incentivos para pequeños productores cafeteros?` | Cuando no conoce los términos exactos |
| **Nombre de la norma** | `Decreto 1071 de 2015` | Para localizar una norma específica |

### 3.3 Ejemplos concretos del dominio agropecuario colombiano

```
incentivos producción agrícola
reforma agraria adjudicación tierras baldías
fondo nacional agropecuario crédito
sanidad vegetal ICA certificación
seguro agropecuario catástrofe natural
agua riego distritos ley
subsidio vivienda rural campesino
comercialización productos agrícolas precio mínimo
CONPES seguridad alimentaria
resolución ICA plaguicidas registro
```

> **Consejo:** Prefiera 2 a 4 palabras representativas del tema. Consultas demasiado cortas (`agua`, `ley`) devuelven demasiados resultados; consultas muy largas pueden reducir los resultados relevantes.

---

## 4. Cómo interpretar los resultados

Cada tarjeta de resultado muestra los siguientes campos:

| Campo | Descripción |
|-------|-------------|
| **Tipo de norma** | Clasificación del documento: Decreto, Ley, Resolución, CONPES, Circular, Acuerdo, Ordenanza, Directiva |
| **Número** | Número oficial de la norma |
| **Año** | Año de expedición |
| **Entidad emisora** | Organismo que expidió la norma (ej.: Ministerio de Agricultura y Desarrollo Rural, ICA, FINAGRO) |
| **Resumen** | Resumen automático generado por el modelo de inteligencia artificial. **No es el texto oficial** — véase la sección de limitaciones |
| **Entidades detectadas** | Personas, organizaciones, lugares, leyes y fechas identificadas automáticamente en el texto |
| **Temas** | Palabras clave extraídas del contenido con su peso relativo |
| **Puntuación semántica** | Indicador interno de relevancia respecto a su consulta (no se muestra directamente, pero afecta el orden de los resultados) |

Los resultados aparecen ordenados por **relevancia combinada**: primero el motor BM25 de Elasticsearch recupera los 100 documentos más relacionados con su consulta, y luego se reordena por similitud semántica con su pregunta usando vectores Word2Vec.

---

## 5. Cómo usar los filtros

En el panel lateral izquierdo (o desplegable en pantallas pequeñas) encontrará tres filtros:

| Filtro | Uso |
|--------|-----|
| **Tipo de norma** | Seleccione uno o varios tipos (Decreto, Ley, Resolución…). Útil cuando necesita solo leyes o solo resoluciones |
| **Año** | Filtre por uno o varios años de expedición. Útil para normas vigentes de un período concreto |
| **Entidad emisora** | Filtre por la entidad que expidió la norma. Útil para circunscribir resultados al Ministerio de Agricultura, ICA, FINAGRO, etc. |

Los filtros se aplican **dentro del conjunto de resultados ya recuperados**. Puede combinar los tres simultáneamente.

Para limpiar los filtros, haga clic en **Limpiar filtros** o vuelva a deseleccionar las opciones marcadas.

---

## 6. Ver el detalle completo de un documento

Haga clic en el botón **Ver detalle** (o sobre el título de la tarjeta) para abrir el panel de detalle completo del documento. Este panel muestra:

- Texto completo del resumen generado
- Metadatos estructurados completos (tipo, número, fecha, entidad, título oficial)
- Todas las entidades detectadas organizadas por categoría (personas, organizaciones, lugares, leyes, fechas)
- Lista completa de temas con su porcentaje de relevancia
- Ruta del archivo fuente

Para cerrar el panel, haga clic en **×** o fuera del área del detalle.

---

## 7. Pestaña "Evaluación P@5"

### ¿Qué es?

La pestaña **Evaluación P@5** es una herramienta de retroalimentación que le permite comparar la calidad de dos métodos de búsqueda:

- **BM25 puro**: recuperación léxica clásica por coincidencia de términos (el método estándar de Elasticsearch)
- **BM25 + Semántico**: los mismos resultados reordenados por similitud de significado usando vectores entrenados en el corpus normativo

La métrica **P@5** (Precisión en los primeros 5) mide cuántos de los 5 primeros resultados son realmente relevantes para su consulta.

### Cómo usarla

1. Escriba una consulta en el campo de la pestaña "Evaluación P@5" y haga clic en **Evaluar**.
2. Se mostrarán dos columnas con los 5 primeros resultados de cada método.
3. Para cada resultado, marque **Relevante** o deje sin marcar si no lo es, según su criterio profesional.
4. Haga clic en **Guardar evaluación**.

El sistema calculará P@5 para cada método y registrará el resultado en el historial acumulado. Con el tiempo, el historial permite comparar qué método es más útil para el dominio normativo agropecuario.

### Criterio de relevancia sugerido

Un resultado es **relevante** si el documento indexado trata directamente el tema de su consulta y le aportaría información útil para su trabajo en la Contraloría. No es necesario que sea la norma principal — una norma complementaria o relacionada también puede marcarse como relevante.

---

## 8. Limitaciones que debe conocer

| Limitación | Detalle |
|------------|---------|
| **Los resúmenes no son texto oficial** | Son generados automáticamente por un modelo de IA (mT5). Pueden contener simplificaciones, omisiones o imprecisiones. Para cualquier actuación oficial, consulte siempre el texto completo de la norma en la fuente primaria (Diario Oficial, SUIN-Juriscol) |
| **Los metadatos pueden requerir verificación** | El tipo de norma, número, fecha y entidad emisora se extraen automáticamente del texto. En documentos con formato atípico, un campo puede quedar vacío o con un valor incorrecto |
| **Documentos con OCR pueden tener texto imperfecto** | Los PDFs escaneados se procesan con reconocimiento óptico de caracteres (Tesseract). El texto resultante puede contener errores ortográficos, palabras fusionadas o caracteres incorrectos, lo que afecta la precisión de la búsqueda y del resumen |
| **El corpus es el cargado por el administrador** | NormaSearch solo busca en los documentos que han sido indexados en el sistema. La ausencia de una norma en los resultados no significa que no exista — puede que aún no haya sido cargada |
| **Los resultados son una ayuda de consulta, no una auditoría** | El sistema está diseñado para agilizar la búsqueda documental, no para reemplazar el análisis jurídico profesional |

---

*Manual elaborado para la Contraloría Delegada para el Sector Agropecuario · NormaSearch v3.0.0 · 2026*
