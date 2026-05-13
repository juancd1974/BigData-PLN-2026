# Guía de Instalación — BigData-PLN-2026

Esta guía describe el proceso completo para configurar y ejecutar el proyecto en Windows.
Incluye configuración para desarrollo local y para despliegues en producción/cloud.

---

## Requisitos Previos

- Windows 10 / 11 (64 bits)
- Python 3.10 o superior
- Git

---

## 0. Requisitos del Sistema (Python)

Antes de continuar, verifique que tiene instalado **Python 3.10 o superior**.

Descarga oficial:
[https://www.python.org/downloads/](https://www.python.org/downloads/)

> **Importante (Windows):** Durante la instalación, marque obligatoriamente la casilla **"Add Python to PATH"**. Si no lo hace, los comandos `python` y `pip` no funcionarán en la terminal.

---

## 1. Requisitos de Software

### 1.1 MongoDB Community Server

1. Descargue el instalador MSI desde el sitio oficial:
   [https://www.mongodb.com/try/download/community](https://www.mongodb.com/try/download/community)
   - Seleccione: **Version → 7.x**, **Platform → Windows**, **Package → MSI**

2. Ejecute el instalador y siga el asistente de instalación.
   - En el paso de configuración, seleccione **"Install MongoD as a Service"**.
   - Deje el directorio de datos por defecto: `C:\Program Files\MongoDB\Server\7.0\data\`.

3. Confirme que **MongoDB Compass** se instale junto al servidor (opción incluida en el instalador).

### 1.2 Elasticsearch

1. Descargue el paquete ZIP desde el sitio oficial:
   [https://www.elastic.co/downloads/elasticsearch](https://www.elastic.co/downloads/elasticsearch)
   - Seleccione la versión **9.x** compatible con el cliente instalado (`elasticsearch==9.4.0`).

2. Extraiga el contenido del ZIP en un directorio de su elección, por ejemplo:
   ```
   C:\elasticsearch-9.x.x\
   ```

3. Elasticsearch no requiere instalación adicional. Se ejecuta directamente desde su directorio extraído.

---

## 2. Configuración de Bases de Datos

### 2.1 Iniciar MongoDB como Servicio

MongoDB queda registrado como servicio de Windows durante la instalación. Para verificar su estado e iniciarlo manualmente si es necesario, ejecute en PowerShell con privilegios de administrador:

```powershell
# Verificar el estado del servicio
Get-Service -Name MongoDB

# Iniciar el servicio si está detenido
Start-Service -Name MongoDB
```

Para configurar el inicio automático con Windows:

```powershell
Set-Service -Name MongoDB -StartupType Automatic
```

La instancia estará disponible en `mongodb://localhost:27017` por defecto.

### 2.2 Ejecutar Elasticsearch

Navegue al directorio donde extrajo Elasticsearch y ejecute el script de inicio:

```cmd
cd C:\elasticsearch-9.x.x\bin
elasticsearch.bat
```

Espere a que el proceso indique que el nodo está listo. Elasticsearch estará disponible en `http://localhost:9200` por defecto.

> **Nota de seguridad:** En la primera ejecución, Elasticsearch genera automáticamente credenciales y un token de enrollment. Guarde la contraseña del usuario `elastic` que se muestra en la consola, ya que se solicita una única vez. Configúrela en el archivo `.env` del proyecto.

Para deshabilitar la autenticación en un entorno estrictamente local y de desarrollo, edite `C:\elasticsearch-9.x.x\config\elasticsearch.yml` y agregue:

```yaml
xpack.security.enabled: false
```

---

## 3. Entorno de Python

Ejecute los siguientes comandos desde la raíz del proyecto en PowerShell.

### 3.1 Crear el entorno virtual

```powershell
python -m venv venv
```

### 3.2 Activar el entorno virtual

```powershell
.\venv\Scripts\activate
```

El prefijo `(venv)` en el prompt indica que el entorno está activo.

Para ejecutar desde una terminal en Visual Studio Code, primero se debe cambiar la política de ejecución:

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### 3.3 Actualizar pip

Antes de instalar dependencias, actualice `pip` para asegurar que el gestor de paquetes pueda resolver correctamente versiones y metadatos recientes.

```powershell
python -m pip install --upgrade pip
```

### 3.4 Instalar las dependencias

```powershell
pip install -r requirements.txt
```

> **Nota:** Los paquetes `torch` y los modelos de HuggingFace pueden tardar varios minutos en descargarse. Asegúrese de contar con conexión estable y al menos 8 GB de espacio libre en disco.

### 3.5 Instalar los navegadores de Playwright

El módulo `playwright` requiere un paso adicional para descargar los binarios de los navegadores:

```powershell
playwright install chromium
```

### 3.6 Poppler (Requerido para OCR de PDFs escaneados)

**¿Qué es Poppler?**
Poppler es una librería que convierte archivos PDF a imágenes. Es requerida para la funcionalidad de OCR en PDFs escaneados o sin texto digital.

**Instalación en Windows:**

1. **Opción A: Usar Chocolatey (recomendado)**
   ```powershell
   choco install poppler
   ```

2. **Opción B: Descarga manual**
   - Descargue desde: https://github.com/ossia/poppler-windows/releases/
   - Extraiga el contenido en: `C:\Program Files\poppler`
   - Agregue a PATH: `C:\Program Files\poppler\Library\bin`

3. **Verificación:**
   ```powershell
   pdftotext --version
   ```

### 3.7 Tesseract OCR (Requerido para OCR de PDFs escaneados)

**¿Qué es Tesseract?**
Motor de reconocimiento óptico de caracteres (OCR). Se usa como fallback cuando un PDF no contiene texto digital.

**Instalación en Windows:**

1. Descargue el instalador desde el repositorio oficial de UB-Mannheim:
   [https://github.com/UB-Mannheim/tesseract/wiki](https://github.com/UB-Mannheim/tesseract/wiki)
   - Descargue el archivo `tesseract-ocr-w64-setup-*.exe`

2. Durante la instalación, en el paso **"Additional language data"**, marque:
   - **Spanish** (`spa`) para activar el reconocimiento en español

3. Agregue Tesseract al PATH del usuario. Ejecute en PowerShell (no requiere administrador):
   ```powershell
   $p = [Environment]::GetEnvironmentVariable("PATH", "User")
   [Environment]::SetEnvironmentVariable("PATH", "$p;C:\Program Files\Tesseract-OCR", "User")
   ```
   Cierre y vuelva a abrir la terminal para que el cambio tome efecto.

4. **Verificación:**
   ```powershell
   tesseract --version
   ```

> **Nota:** Si Tesseract o Poppler no están instalados, la aplicación seguirá funcionando para PDFs con texto digital. Solo fallarán los PDFs puramente escaneados.

---

## 4. Modelos de NLP

### 4.1 Modelo de spaCy en Español

Con el entorno virtual activo, descargue el modelo grande en español:

```powershell
python -m spacy download es_core_news_lg
```

Este modelo ofrece mayor precisión en NER (reconocimiento de entidades) y POS tagging para documentos normativos en español.

Verifique la instalación:

```powershell
python -c "import spacy; nlp = spacy.load('es_core_news_lg'); print('Modelo cargado correctamente')"
```

### 4.2 Modelos de HuggingFace (descarga automática)

Los modelos de embeddings y resumen **no requieren instalación manual**. Se descargan automáticamente la primera vez que se usan y se guardan en caché local:

```
C:\Users\<usuario>\.cache\huggingface\hub\
```

A partir de la segunda ejecución, cargan desde la caché sin necesidad de internet.

| Modelo | Uso | Tamaño aprox. |
|--------|-----|---------------|
| `paraphrase-multilingual-MiniLM-L12-v2` | Embeddings semánticos (RAG) | ~470 MB |
| `google/mt5-small` | Resumen abstractivo de documentos | ~1.2 GB |

> **Primera ejecución:** La descarga de ambos modelos puede tomar 5–15 minutos según la velocidad de internet.

---

## 5. Variables de Entorno (.env)

Cree un archivo `.env` en la raíz del proyecto. Use uno de los siguientes perfiles según su entorno.

> **Nota de seguridad:** El archivo `.env` contiene credenciales y secretos. **Nunca** debe subirse al repositorio.

### 5.1 Configuración para Desarrollo Local

```env
# Flask
SECRET_KEY=<TU_LLAVE_SECRETA_ALEATORIA>
UPLOAD_DIR=static/uploads

# MongoDB local
MONGO_URI=mongodb://localhost:27017/
MONGO_DB=proyecto_bigData
MONGO_COLECCION=usuario_roles

# Elasticsearch local
ELASTIC_URL=http://localhost:9200
ELASTIC_USER=elastic
ELASTIC_PASSWORD=tu_password_local
ELASTIC_INDEX_DEFAULT=index_minagricultura
ELASTIC_REQUEST_TIMEOUT=20
ELASTIC_STARTUP_TIMEOUT=120

# Usuario administrador inicial
APP_USER_ADMIN=<TU_USUARIO>
APP_USER_ADMIN_PASSWORD=<TU_CONTRASEÑA>
```

### 5.2 Configuración para Producción/Cloud

```env
# Flask
SECRET_KEY=<TU_LLAVE_SECRETA_ALEATORIA>
UPLOAD_DIR=static/uploads

# MongoDB Atlas
MONGO_URI=mongodb+srv://usuario:password@cluster.mongodb.net/?retryWrites=true&w=majority
MONGO_DB=proyecto_bigData
MONGO_COLECCION=usuario_roles

# Elastic Cloud
ELASTIC_URL=https://cluster-id.region.provider.elastic-cloud.com:9243
ELASTIC_USER=elastic
ELASTIC_PASSWORD=tu_password_cloud
ELASTIC_INDEX_DEFAULT=index_minagricultura
ELASTIC_REQUEST_TIMEOUT=20
ELASTIC_STARTUP_TIMEOUT=120

# Usuario administrador inicial
APP_USER_ADMIN=<TU_USUARIO>
APP_USER_ADMIN_PASSWORD=<TU_CONTRASEÑA>
```

### 5.3 Detección automática de entorno

La aplicación detecta automáticamente el entorno en tiempo de ejecución usando las variables anteriores:

- Si `MONGO_URI` contiene `localhost` o `127.0.0.1`, mostrará `✅ MongoDB Local: Conectado`; en caso contrario, `✅ MongoDB Atlas (Cloud): Conectado`.
- Si `ELASTIC_URL` contiene `localhost` o `127.0.0.1`, mostrará `✅ Elasticsearch Local: Conectado (vX.Y.Z)`; en caso contrario, `✅ Elasticsearch Cloud: Conectado (vX.Y.Z)`.

No es necesario cambiar el código al pasar de local a cloud: basta con ajustar el `.env`.

---

## 6. Inicializar Bases de Datos

Antes del primer inicio de la aplicación, ejecute los scripts de inicialización.

### 6.0 Opción recomendada (un solo comando)

```powershell
python init_all.py
```

Este comando ejecuta en orden `init_db.py` y `init_elastic.py`.

Si necesita recrear el índice de Elasticsearch durante una migración o ajuste de mappings:

```powershell
python init_all.py --recreate-elastic
```

### 6.1 Inicializar MongoDB (usuario administrador)

```powershell
python init_db.py
```

El script leerá la configuración de `APP_USER_ADMIN` y `APP_USER_ADMIN_PASSWORD` desde el archivo `.env` y creará ese usuario con contraseña almacenada con hash seguro (`werkzeug.security`). Si el usuario ya existe, el script no realiza ningún cambio (es idempotente).

### 6.2 Inicializar Elasticsearch (índice principal)

```powershell
python init_elastic.py
```

Este script crea el índice definido en `ELASTIC_INDEX_DEFAULT` con settings y mappings base para la aplicación. Si el índice ya existe, no realiza cambios (idempotente).

Si necesita reconstruirlo desde cero:

```powershell
python init_elastic.py --recreate
```

> **Importante:** Use `--recreate` solo en ambientes de desarrollo o cuando tenga respaldo de los datos, porque elimina y vuelve a crear el índice.

---

## 7. Ejecutar la Aplicación

Con los servicios de MongoDB y Elasticsearch activos y el entorno virtual activado:

```powershell
python app.py
```

La aplicación estará disponible en `http://127.0.0.1:5000`.

---

## Resumen de Verificación

| Componente | Verificación rápida |
|---|---|
| MongoDB | `Get-Service -Name MongoDB` → estado `Running` |
| Elasticsearch | `Invoke-RestMethod http://localhost:9200` en PowerShell |
| Python / venv | `python --version` con prefijo `(venv)` activo |
| spaCy | `python -c "import spacy; spacy.load('es_core_news_lg')"` |
| Tesseract | `tesseract --version` |
| Poppler | `pdftotext --version` |
| Aplicación Flask | Acceder a `http://127.0.0.1:5000` en el navegador |
