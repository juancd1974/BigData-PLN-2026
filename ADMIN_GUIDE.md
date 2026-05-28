# Manual del Administrador — NormaSearch

**Versión 3.0.0**

---

## 1. Requisitos previos

Antes de iniciar el sistema verifique que los siguientes servicios y dependencias estén operativos:

| Componente | Estado requerido |
|------------|-----------------|
| **MongoDB 7.x** | Servicio en ejecución en `localhost:27017` |
| **Elasticsearch 9.x** | Proceso activo en `localhost:9200` |
| **Python 3.11** | Instalado y accesible en PATH |
| **Entorno virtual** | Activado (`venv\Scripts\activate`) |
| **Modelo spaCy** | `es_core_news_lg` instalado (`python -m spacy download es_core_news_lg`) |
| **Tesseract OCR** | Instalado y accesible en PATH (requerido para PDFs escaneados) |
| **Poppler** | Instalado y en PATH (requerido para conversión PDF→imagen en OCR) |

Para la instalación completa de cada componente, consulte [`INSTALLATION_GUIDE.md`](INSTALLATION_GUIDE.md).

---

## 2. Cómo iniciar el sistema

```powershell
# 1. Activar el entorno virtual (desde la raíz del proyecto)
venv\Scripts\activate

# 2. Iniciar la aplicación Flask
python app.py
```

La aplicación queda disponible en `http://localhost:5000`. En la consola verá la secuencia de inicialización:

```
Cargando modelo spaCy 'es_core_news_lg'...
  Componentes activos: ['tok2vec', 'ner', 'entity_ruler']
  ✓ 'es_core_news_lg' cargado
Cargando modelo Word2Vec (si existe)...
  ✓ Vocabulario: X palabras
```

Si Elasticsearch no está disponible al arrancar, la aplicación espera hasta 120 segundos (configurable con `ELASTIC_STARTUP_TIMEOUT` en `.env`) antes de lanzar error.

Para detener el sistema: `Ctrl + C` en la consola.

---

## 3. Panel de Administración

Acceda desde `http://localhost:5000/login` con sus credenciales de administrador. Tras el login llega a `/admin`, que centraliza las siguientes secciones:

| Sección | Ruta | Descripción |
|---------|------|-------------|
| **Cargar documentos** | `/cargar_doc_elastic` | Indexar PDFs nuevos mediante tres métodos |
| **Gestionar usuarios** | `/gestor_usuarios` | Crear, editar y eliminar cuentas y permisos |
| **Gestionar índices** | `/gestor_elastic` | Visualizar estado de Elasticsearch, ejecutar queries |
| **Configuración PLN** | `/configuracion` | Cambiar modelos de resumen y modo de comparación |
| **Entrenar Word2Vec** | `/entrenar-word2vec` | Reentrenar el modelo semántico con el corpus actual |
| **Métricas** | `/metricas` | Panel de estadísticas operacionales y evaluaciones P@5 |

---

## 4. Cargar documentos

### 4.1 Tres métodos disponibles

#### Método 1 — Carpeta local (PDFs desde el servidor o subidos desde el navegador)

1. En la pantalla de carga, seleccione la pestaña **Carpeta local**.
2. Haga clic en **Seleccionar archivos PDF** y elija uno o varios PDFs desde su equipo. El sistema los sube temporalmente a `static/uploads/carpeta_local/`.
3. Haga clic en **Verificar archivos** para ver la lista de PDFs detectados.
4. Seleccione el índice de Elasticsearch de destino.
5. Haga clic en **Iniciar Fase 1**.

#### Método 2 — Web scraping MinAgricultura

1. Seleccione la pestaña **Web Scraping**.
2. Pegue la URL del portal del Ministerio de Agricultura que desea scrapear.
3. Haga clic en **Descargar archivos**. El sistema usa Playwright para extraer todos los enlaces a PDFs y descargarlos a `static/uploads/`.
4. Una vez completada la descarga, haga clic en **Iniciar Fase 1**.

> **Nota:** Este método requiere conexión a internet y que Playwright esté instalado con los navegadores (`playwright install chromium`).

#### Método 3 — Archivo ZIP

1. Seleccione la pestaña **ZIP**.
2. Haga clic en **Seleccionar ZIP** y elija un archivo ZIP que contenga PDFs o JSONs.
3. Haga clic en **Descomprimir y procesar**.
4. Seleccione el índice de destino y haga clic en **Cargar en Elasticsearch**.

---

### 4.2 Pantalla de procesamiento Fase 1

Durante la Fase 1 (pipeline completo) se muestra un log en tiempo real con el progreso por documento:

```
[1/12] DECRETO_1071_2015.pdf
  → Texto: pymupdf (42 580 chars)
  → Metadatos: 80%
  → Resumen: 3 segmentos, 94.2s, perpl: 312.4
```

Al finalizar, el sistema muestra el **panel de comparación de resúmenes** (si el modo comparación está activo) o pasa directamente a la indexación.

---

### 4.3 Pantalla de comparación de modelos (Fase 2)

Si el **modo comparación** está activo en Configuración, después de la Fase 1 aparece el botón **Iniciar Fase 2**. Al ejecutarla:

- El sistema genera un segundo resumen con el modelo de Fase 2 (más lento, mayor calidad) para cada documento.
- Se muestra una tabla comparativa con ambos resúmenes y sus métricas de perplejidad.

**Cómo elegir qué resumen indexar:**

Para cada documento, seleccione con el botón de radio:
- **Usar resumen Fase 1** (mT5-small): más rápido, adecuado para documentos extensos o cuando el tiempo es prioritario.
- **Usar resumen Fase 2** (mT5-base DACSA): mayor calidad lingüística, recomendado cuando la comprensión del resumen es crítica.

Una perplejidad más **baja** indica un resumen más fluido y coherente. Use este indicador como criterio secundario si duda entre ambas opciones.

Una vez elegido el resumen para cada documento, haga clic en **Indexar seleccionados**. El sistema indexa en Elasticsearch y limpia los archivos temporales de `static/temp/`.

---

### 4.4 Deduplicación automática

El sistema calcula un hash SHA-256 de cada archivo antes de procesarlo. Si el documento ya existe en el índice (mismo hash), se omite automáticamente y se notifica en el log. Esto evita duplicados al recargar un mismo lote de documentos.

---

## 5. Gestionar usuarios

Acceda a `/gestor_usuarios`. Requiere el permiso `admin_usuarios`.

### 5.1 Crear usuario

1. Haga clic en **Nuevo usuario**.
2. Complete usuario, contraseña y seleccione los permisos.
3. Haga clic en **Guardar**.

### 5.2 Editar usuario

1. Localice el usuario en la tabla.
2. Haga clic en el ícono de edición (lápiz).
3. Modifique los campos deseados. Si deja la contraseña vacía, **el hash existente no se sobreescribe**.
4. Haga clic en **Guardar cambios**.

### 5.3 Eliminar usuario

1. Localice el usuario en la tabla.
2. Haga clic en el ícono de eliminar (papelera).
3. Confirme la acción.

> **Restricción:** No puede eliminar su propia cuenta mientras tenga sesión activa.

### 5.4 Permisos disponibles

| Permiso | Acceso que otorga |
|---------|-------------------|
| `admin_data_elastic` | Cargar documentos, ejecutar Fase 1/Fase 2, entrenar Word2Vec, indexar desde carpeta o ZIP |
| `admin_elastic` | Gestionar índices de Elasticsearch (listar, consultar, ejecutar DML) |
| `admin_usuarios` | Crear, editar y eliminar usuarios |

Un usuario puede tener uno, varios o todos los permisos simultáneamente. Asigne solo los permisos necesarios para el rol de cada persona.

---

## 6. Gestionar índices Elasticsearch

Acceda a `/gestor_elastic`. Requiere el permiso `admin_elastic`.

### Visualizar estado

La pantalla lista todos los índices del cluster con su nombre, número de documentos y tamaño en disco. Use este panel para verificar que el índice principal (`index_minagricultura` por defecto) está activo y contiene documentos.

### Ejecutar query

El editor de queries permite enviar cualquier query JSON de Elasticsearch directamente. Útil para diagnóstico, limpieza de documentos concretos o verificación de campos.

Ejemplo — verificar que un documento fue indexado:
```json
{
  "query": {
    "term": { "hash_archivo": "sha256:<hash_del_archivo>" }
  }
}
```

### Ejecutar DML

Para operaciones de modificación (actualizar documentos, eliminar por query, etc.) use el editor DML. Ejemplo — eliminar todos los documentos de un año:
```json
{
  "query": { "term": { "anio_norma": 2010 } }
}
```

> **Precaución:** Las operaciones DML no son reversibles. Verifique siempre el alcance de la query antes de ejecutar.

---

## 7. Configuración

Acceda a `/configuracion`. No requiere permiso especial más allá del login.

### Modelo activo (modo simple)

Seleccione el modelo de resumen que se usa cuando el modo comparación está **desactivado**. Opciones disponibles:

| Modelo | Velocidad | Calidad |
|--------|-----------|---------|
| `google/mt5-small` | Rápido (~30–60 s/doc en CPU) | Aceptable |
| `ELiRF/mt5-base-dacsa-es` | Lento (~90–150 s/doc en CPU) | Superior para español jurídico |

### Modo comparación

Cuando está **activado**, el pipeline ejecuta Fase 1 y habilita el botón de Fase 2 para generar resúmenes con ambos modelos y comparar resultados antes de indexar. Recomendado para lotes pequeños donde se quiere máxima calidad.

Cuando está **desactivado**, solo se ejecuta Fase 1 con el modelo activo. Recomendado para lotes grandes.

### Modelos Fase 1 y Fase 2

En modo comparación, seleccione independientemente el modelo para cada fase. La combinación típica es:
- **Fase 1:** `google/mt5-small` (rápido, genera el resumen provisional)
- **Fase 2:** `ELiRF/mt5-base-dacsa-es` (más lento, genera el resumen de mayor calidad)

Los cambios se aplican al guardar. Si el modelo activo cambia respecto al anterior, el pipeline libera el modelo de memoria automáticamente para cargar el nuevo en el siguiente procesamiento.

---

## 8. Entrenar modelo Word2Vec

Acceda a `/entrenar-word2vec`. Requiere el permiso `admin_data_elastic`.

### ¿Cuándo reentrenar?

- Al agregar un lote significativo de documentos nuevos al índice (más de 20–30 documentos).
- Cuando las búsquedas semánticas devuelven resultados poco relacionados con la consulta.
- Después de indexar documentos de un subtema nuevo no cubierto por el corpus anterior.

### Modo incremental vs. desde cero

| Modo | Cuándo usarlo | Efecto |
|------|--------------|--------|
| **Incremental** | El modelo ya existe y solo se agregaron documentos nuevos | Actualiza el vocabulario y los vectores existentes sin perder el aprendizaje previo. Más rápido |
| **Desde cero** | Primera vez, o cuando el corpus cambió sustancialmente | Entrena un modelo completamente nuevo con todos los documentos del índice. Más lento pero más consistente |

### Pasos

1. Seleccione el modo (incremental recomendado si existe modelo previo).
2. Haga clic en **Iniciar entrenamiento**.
3. El log en tiempo real muestra: consulta a Elasticsearch → tokenización → entrenamiento → guardado → recarga en memoria.
4. Al finalizar, el modelo queda activo inmediatamente para las siguientes búsquedas.

El modelo se guarda en `models/normasearch_w2v_sg_v100_w5.model`. Si `models/` no existe, el sistema la crea automáticamente.

---

## 9. Panel de métricas

Acceda a `/metricas`. Visible para cualquier usuario con sesión activa.

### 9.1 Sección Extracción de texto

Muestra cuántos documentos fueron procesados exitosamente con PyMuPDF, cuántos requirieron OCR y cuántos fallaron, con la tasa de éxito global.

- Una tasa de éxito PyMuPDF alta (>80 %) indica que el corpus tiene PDFs con texto digital (no escaneados).
- Si hay muchos documentos en OCR, el procesamiento será más lento y el texto puede tener más errores.

### 9.2 Sección Metadatos

Muestra la completitud porcentual de cada campo estructurado (tipo de norma, número, año, entidad emisora, fecha) sobre el total de documentos indexados.

- Un campo con baja completitud (<60 %) indica que ese atributo no está presente o es difícil de extraer del formato de los documentos.
- Esta información es útil para decidir si conviene mejorar los patrones de extracción en `entity_extractor.py`.

### 9.3 Sección Modelos de resumen

Comparación de perplejidad y tiempo de procesamiento agrupados por modelo. La perplejidad promedio más baja indica resúmenes más fluidos. Los documentos donde el cálculo de perplejidad falló (valor `-1.0`) se excluyen del promedio pero cuentan en el total.

### 9.4 Sección Precisión@5

Historial acumulado de evaluaciones manuales realizadas desde la pestaña "Evaluación P@5" del buscador. Muestra:

- **P@5 BM25 promedio**: precisión del método léxico sobre todas las consultas evaluadas.
- **P@5 Semántico promedio**: precisión con re-ranking semántico.
- **Diferencia**: ganancia o pérdida del método semántico respecto a BM25 puro. Un valor positivo confirma que el re-ranking mejora los resultados para el dominio normativo.

---

## 10. Publicar con ngrok

Para exponer el sistema a usuarios externos sin despliegue en la nube, use ngrok:

```powershell
# Instalar ngrok (solo la primera vez)
winget install ngrok

# Publicar el puerto 5000
ngrok http 5000
```

ngrok genera una URL pública (ej.: `https://abc123.ngrok-free.app`) que redirige al servidor local. Comparta esa URL con los usuarios mientras el tunnel esté activo. El tunnel se cierra al detener ngrok o cerrar la terminal.

> **Nota de seguridad:** ngrok expone el sistema públicamente. Use solo en sesiones controladas y cierre el tunnel al terminar. En producción, use un servidor con HTTPS y autenticación adecuada (ver `INSTALLATION_GUIDE.md`).

---

## 11. Recomendaciones de mantenimiento

### Limpiar métricas antiguas

Los archivos JSON de métricas se acumulan en `static/metrics/` con el tiempo. Si el panel de métricas se vuelve lento o desea reiniciar las estadísticas:

```powershell
# Eliminar todos los archivos de métricas (conserva el .gitkeep)
Get-ChildItem static\metrics -Exclude .gitkeep | Remove-Item -Force
```

> Esto borra también el historial de evaluaciones P@5 (`evaluaciones_precision.json`). Haga un respaldo si desea conservarlo.

### Reentrenar Word2Vec al agregar documentos

Cada vez que indexe un lote de documentos nuevos, reentrane el modelo Word2Vec en modo **incremental** para que los nuevos términos queden representados en el espacio semántico. Sin reentrenamiento, los documentos nuevos se rankeán con vectores GloVe de spaCy como fallback, que son menos específicos del dominio normativo.

### Verificar espacio en disco

Los modelos Word2Vec y los archivos temporales de texto (`static/temp/`) pueden ocupar espacio significativo:

| Ruta | Contenido | Tamaño aproximado |
|------|-----------|------------------|
| `models/` | Modelo Word2Vec entrenado | 10–100 MB según vocabulario |
| `static/temp/` | Texto temporal entre fases (se limpia al indexar) | Varía; limpiar manualmente si queda residuo |
| `static/metrics/` | JSON de métricas por documento | ~5–20 KB por documento |
| `static/uploads/` | PDFs descargados (se limpian automáticamente en cada carga) | Varía |

### Actualizar el corpus

Para mantener el corpus actualizado con las normas más recientes del Ministerio de Agricultura, se recomienda ejecutar una carga periódica (mensual o según la frecuencia de publicación de nuevas normas) usando el método de Web Scraping desde el panel de administración.

---

*Manual del Administrador — NormaSearch v3.0.0 · 2026*
