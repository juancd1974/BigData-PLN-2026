"""
Utilidades de I/O y procesamiento de archivos para NormaSearch.

Agrupa operaciones de sistema de archivos, extracción de texto desde PDF,
cálculo de hashes y persistencia de datos temporales. Es usado por pipeline.py
y las rutas de Flask en app.py.

La clase Funciones agrupa métodos estáticos por conveniencia; no mantiene estado.

Extracción de texto PDF (con fallback automático a OCR):
  extraer_texto_pdf_con_metricas() → intenta PyMuPDF; si la calidad es baja, usa Tesseract OCR
  _calidad_texto()                 → detecta PDFs con fuente mal decodificada

Archivos temporales en static/temp/ (texto extraído entre fase 1 y fase 2):
  guardar_texto_temporal()   → persiste texto extraído en JSON por hash de archivo
  cargar_texto_temporal()    → recupera el texto para la fase 2
  eliminar_texto_temporal()  → limpieza post-indexación
"""

import os
import re
import zipfile
import requests
import json
import fitz
from collections import Counter
from PIL import Image
import pytesseract
import time
from typing import Dict, List, Optional, Tuple
from werkzeug.utils import secure_filename
from datetime import datetime
import hashlib

MESES_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "setiembre": 9,
    "octubre": 10, "noviembre": 11, "diciembre": 12
}

TEMP_DIR = 'static/temp'

class Funciones:
    @staticmethod
    def crear_carpeta(ruta: str) -> bool:
        """Crea una carpeta si no existe"""
        try:
            if not os.path.exists(ruta):
                os.makedirs(ruta)
            return True
        except Exception as e:
            print(f"Error al crear carpeta: {e}")
            return False
    
    @staticmethod
    def descomprimir_zip_local(ruta_file_zip: str, ruta_descomprimir: str) -> List[Dict]:
        """Descomprime un archivo ZIP y retorna info de archivos"""
        archivos = []
        try:
            with zipfile.ZipFile(ruta_file_zip, 'r') as zip_ref:
                for file_info in zip_ref.namelist():
                    if not file_info.endswith('/'):
                        # Extraer carpeta padre
                        carpeta = os.path.dirname(file_info)
                        nombre_archivo = os.path.basename(file_info)
                        extension = os.path.splitext(nombre_archivo)[1].lower()
                        
                        # Solo procesar txt, pdf y json
                        if extension in ['.txt', '.pdf', '.json']:
                            zip_ref.extract(file_info, ruta_descomprimir)
                            archivos.append({
                                'carpeta': carpeta if carpeta else 'raiz',
                                'nombre': nombre_archivo,
                                'ruta': os.path.join(ruta_descomprimir, file_info),
                                'extension': extension
                            })
            return archivos
        except Exception as e:
            print(f"Error al descomprimir ZIP: {e}")
            return []
    
    @staticmethod
    def descargar_y_descomprimir_zip(url: str, carpeta_destino: str, tipoArchivo: str = '') -> List[Dict]:
        """Descarga y descomprime un ZIP desde URL"""
        try:
            Funciones.crear_carpeta(carpeta_destino)
            
            # Descargar archivo
            response = requests.get(url, stream=True)
            zip_path = os.path.join(carpeta_destino, 'temp.zip')
            
            with open(zip_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            # Descomprimir
            archivos = Funciones.descomprimir_zip_local(zip_path, carpeta_destino)
            
            # Eliminar ZIP temporal
            os.remove(zip_path)
            
            return archivos
        except Exception as e:
            print(f"Error al descargar y descomprimir: {e}")
            return []
    
    @staticmethod
    def allowed_file(filename: str, extensions: List[str]) -> bool:
        """Verifica si un archivo tiene extensión permitida"""
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in extensions
    
    @staticmethod
    def borrar_contenido_carpeta(ruta: str) -> bool:
        """
        Borra el contenido de una carpeta sin eliminar la carpeta misma
        
        Args:
            ruta: Ruta de la carpeta a limpiar
            
        Returns:
            True si se borró correctamente, False en caso de error
        """
        try:
            if not os.path.exists(ruta):
                return True  # Si no existe, no hay nada que borrar
            
            if not os.path.isdir(ruta):
                return False  # No es una carpeta
            
            # Eliminar todos los archivos y subcarpetas dentro
            for item in os.listdir(ruta):
                item_path = os.path.join(ruta, item)
                try:
                    if os.path.isfile(item_path) or os.path.islink(item_path):
                        os.unlink(item_path)  # Eliminar archivo o enlace simbólico
                    elif os.path.isdir(item_path):
                        import shutil
                        shutil.rmtree(item_path)  # Eliminar directorio y su contenido
                        print(f"Eliminado directorio: {item_path}")
                except Exception as e:
                    print(f"Error al eliminar {item_path}: {e}")
                    return False
            
            return True
        except Exception as e:
            print(f"Error al borrar contenido de carpeta: {e}")
            return False
    
    @staticmethod
    def _calidad_texto(texto: str) -> bool:
        """True si el texto extraído no parece caracteres corruptos de fuente mal decodificada."""
        palabras = texto.lower().split()
        # Validación 1: mínimo de palabras para que el análisis estadístico sea significativo
        if len(palabras) < 20:
            return False
        freq = Counter(palabras)
        top_count = freq.most_common(1)[0][1]
        # Validación 2: una palabra dominante (>30% del total) indica texto repetitivo o corrupto
        if top_count / len(palabras) > 0.30:
            return False
        if len(freq) < min(30, len(palabras) // 3):
            return False

        # Validación 3: detectar caracteres sueltos repetidos
        # Textos con fuente mal codificada producen letras sueltas
        # como "a s a s" o "i i i i" que pasan los checks anteriores
        tokens_cortos = [p for p in palabras if len(p) == 1]
        if len(tokens_cortos) / len(palabras) > 0.20:
            return False

        # Validación 4: ratio mínimo de caracteres alfabéticos
        # Texto legible debe tener al menos 40% de letras
        chars_alpha = sum(1 for c in texto if c.isalpha())
        if chars_alpha / max(len(texto), 1) < 0.40:
            return False

        return True

    @staticmethod
    def extraer_texto_pdf(ruta_pdf: str) -> str:
        """Extrae texto con PyMuPDF. Retorna '' si la calidad es baja (fuente mal decodificada),
        para que el llamador active el OCR fallback."""
        try:
            paginas = []
            with fitz.open(ruta_pdf) as doc:
                for page in doc:
                    paginas.append(page.get_text())
            texto = "\n".join(paginas).strip()
            if Funciones._calidad_texto(texto):
                return texto
            print(f"  → PyMuPDF: calidad baja en {os.path.basename(ruta_pdf)}, se intentará OCR")
            return ""
        except Exception as e:
            print(f"Error al extraer texto del PDF {ruta_pdf}: {e}")
            return ""
    
    @staticmethod
    def extraer_texto_pdf_ocr(ruta_pdf: str) -> str:
        """
        Extrae texto de un PDF usando OCR (útil para PDFs escaneados)
        
        Args:
            ruta_pdf: Ruta del archivo PDF
            
        Returns:
            Texto extraído usando OCR
            
        Nota: Requiere que Poppler esté instalado en el sistema.
              Ver INSTALLATION_GUIDE.md sección 3.6 para instrucciones.
        """
        try:
            from pdf2image import convert_from_path
            
            # Convertir PDF a imágenes
            images = convert_from_path(ruta_pdf)
            
            texto = ""
            for i, image in enumerate(images):
                # Aplicar OCR a cada página
                texto += pytesseract.image_to_string(image, lang='spa') + "\n"
            
            return texto.strip()
        except Exception as e:
            error_msg = str(e)
            if "poppler" in error_msg.lower():
                print(f"Error al extraer texto con OCR del PDF {ruta_pdf}: Poppler no está instalado.")
                print(f"   → Instale Poppler según las instrucciones en INSTALLATION_GUIDE.md (sección 3.6)")
            else:
                print(f"Error al extraer texto con OCR del PDF {ruta_pdf}: {e}")
            return ""
    
    @staticmethod
    def listar_archivos_json(ruta_carpeta: str) -> List[Dict]:
        """
        Lista todos los archivos JSON en una carpeta
        
        Args:
            ruta_carpeta: Ruta de la carpeta a explorar
            
        Returns:
            Lista de diccionarios con información de cada archivo JSON
        """
        archivos_json = []
        try:
            if not os.path.exists(ruta_carpeta):
                return []
            
            for archivo in os.listdir(ruta_carpeta):
                if archivo.lower().endswith('.json'):
                    ruta_completa = os.path.join(ruta_carpeta, archivo)
                    archivos_json.append({
                        'nombre': archivo,
                        'ruta': ruta_completa,
                        'tamaño': os.path.getsize(ruta_completa)
                    })
            
            return archivos_json
        except Exception as e:
            print(f"Error al listar archivos JSON: {e}")
            return []
    
    @staticmethod
    def listar_archivos_carpeta(ruta_carpeta: str, extensiones: List[str] = None) -> List[Dict]:
        """
        Lista archivos en una carpeta con extensiones específicas
        
        Args:
            ruta_carpeta: Ruta de la carpeta
            extensiones: Lista de extensiones a filtrar (ej: ['pdf', 'txt'])
            
        Returns:
            Lista de diccionarios con información de archivos
        """
        archivos = []
        try:
            if not os.path.exists(ruta_carpeta):
                return []
            
            for archivo in os.listdir(ruta_carpeta):
                ruta_completa = os.path.join(ruta_carpeta, archivo)
                if os.path.isfile(ruta_completa):
                    extension = os.path.splitext(archivo)[1].lower().replace('.', '')
                    
                    if extensiones is None or extension in extensiones:
                        archivos.append({
                            'nombre': archivo,
                            'ruta': ruta_completa,
                            'extension': extension,
                            'tamaño': os.path.getsize(ruta_completa)
                        })
            
            return archivos
        except Exception as e:
            print(f"Error al listar archivos: {e}")
            return []
    
    @staticmethod
    def leer_json(ruta_json: str) -> Dict:
        """
        Lee un archivo JSON y retorna su contenido
        
        Args:
            ruta_json: Ruta del archivo JSON
            
        Returns:
            Diccionario con el contenido del JSON
        """
        try:
            with open(ruta_json, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error al leer JSON {ruta_json}: {e}")
            return {}
    
    @staticmethod
    def guardar_json(ruta_json: str, datos: Dict) -> bool:
        """
        Guarda datos en un archivo JSON
        
        Args:
            ruta_json: Ruta donde guardar el JSON
            datos: Datos a guardar
            
        Returns:
            True si se guardó correctamente
        """
        try:
            # Crear directorio si no existe
            directorio = os.path.dirname(ruta_json)
            if directorio:
                Funciones.crear_carpeta(directorio)
            
            with open(ruta_json, 'w', encoding='utf-8') as f:
                json.dump(datos, f, indent=4, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"Error al guardar JSON: {e}")
            return False
        
    @staticmethod
    def calcular_hash_archivo(ruta_archivo):
        """
        Calcula hash SHA-256 de un archivo en modo streaming, sin cargarlo a memoria.

        Devuelve:
            "sha256:<hash_hexadecimal>"
        """
        sha256 = hashlib.sha256()

        try:
            with open(ruta_archivo, "rb") as f:
                for bloque in iter(lambda: f.read(8192), b""):
                    sha256.update(bloque)

            hash_hex = sha256.hexdigest()
            return f"sha256:{hash_hex}"

        except Exception as e:
            print(f"Error calculando hash del archivo {ruta_archivo}: {e}")
            return None

    @staticmethod
    def extraer_texto_pdf_con_metricas(ruta_pdf: str) -> Tuple[str, Dict]:
        """
        Extrae texto de un PDF y retorna métricas del proceso.

        Intenta primero con PyMuPDF. Si la calidad es insuficiente,
        activa OCR con Tesseract como fallback.

        Args:
            ruta_pdf: Ruta del archivo PDF a procesar.

        Returns:
            Tupla (texto, metricas). metricas contiene metodo,
            tiempo_segundos, longitud_caracteres y calidad_ok.
            Si ambos métodos fallan retorna ("", metricas) con
            calidad_ok=False y longitud_caracteres=0.
        """
        inicio = time.time()

        texto = Funciones.extraer_texto_pdf(ruta_pdf)
        if texto and Funciones._calidad_texto(texto):
            metricas = {
                "metodo": "pymupdf",
                "tiempo_segundos": round(time.time() - inicio, 3),
                "longitud_caracteres": len(texto),
                "calidad_ok": True,
            }
            return texto, metricas

        texto = Funciones.extraer_texto_pdf_ocr(ruta_pdf)
        calidad_ok = len(texto.strip()) >= 50
        metricas = {
            "metodo": "ocr",
            "tiempo_segundos": round(time.time() - inicio, 3),
            "longitud_caracteres": len(texto),
            "calidad_ok": calidad_ok,
        }
        return texto, metricas

    @staticmethod
    def guardar_texto_temporal(hash_archivo: str, nombre_archivo: str,
                               texto: str) -> Optional[str]:
        """
        Guarda el texto extraído de un PDF en un JSON temporal en static/temp/.

        Args:
            hash_archivo:   Hash SHA-256 con prefijo "sha256:".
            nombre_archivo: Nombre del archivo PDF fuente.
            texto:          Texto extraído del documento.

        Returns:
            Ruta del archivo guardado, o None si falló.
        """
        try:
            Funciones.crear_carpeta(TEMP_DIR)
            hash_limpio = hash_archivo.replace("sha256:", "")
            ruta = os.path.join(TEMP_DIR, f"{hash_limpio}.json")
            datos = {
                "nombre_archivo": nombre_archivo,
                "hash_archivo": hash_archivo,
                "texto": texto,
                "fecha_extraccion": datetime.now().isoformat(),
            }
            with open(ruta, 'w', encoding='utf-8') as f:
                json.dump(datos, f, indent=4, ensure_ascii=False)
            return ruta
        except Exception as e:
            print(f"Error al guardar texto temporal: {e}")
            return None

    @staticmethod
    def cargar_texto_temporal(hash_archivo: str) -> Optional[str]:
        """
        Carga el texto desde el JSON temporal correspondiente al hash.

        Args:
            hash_archivo: Hash SHA-256 con prefijo "sha256:".

        Returns:
            Texto como string, o None si el archivo no existe o no se puede leer.
        """
        try:
            hash_limpio = hash_archivo.replace("sha256:", "")
            ruta = os.path.join(TEMP_DIR, f"{hash_limpio}.json")
            if not os.path.exists(ruta):
                return None
            with open(ruta, 'r', encoding='utf-8') as f:
                datos = json.load(f)
            return datos.get("texto")
        except Exception as e:
            print(f"Error al cargar texto temporal: {e}")
            return None

    @staticmethod
    def eliminar_texto_temporal(hash_archivo: str) -> bool:
        """
        Elimina el JSON temporal correspondiente al hash.

        Args:
            hash_archivo: Hash SHA-256 con prefijo "sha256:".

        Returns:
            True si se eliminó correctamente o el archivo no existía,
            False si hubo un error al eliminar.
        """
        try:
            hash_limpio = hash_archivo.replace("sha256:", "")
            ruta = os.path.join(TEMP_DIR, f"{hash_limpio}.json")
            if not os.path.exists(ruta):
                return True
            os.remove(ruta)
            return True
        except Exception as e:
            print(f"Error al eliminar texto temporal: {e}")
            return False