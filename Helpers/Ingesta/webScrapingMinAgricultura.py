import os
import requests
from urllib.parse import urljoin
from requests.exceptions import SSLError
import urllib3


# Mapa rápido del flujo:
# 1) Se consulta el API de SharePoint por cada categoría (Conpes, Leyes, etc.).
# 2) Se recorren todos los items con paginación (__next).
# 3) Se filtran rutas válidas de Normatividad y extensión .pdf.
# 4) Se deduplican enlaces y luego se descargan con validaciones de integridad.
# 5) Si falla SSL en Windows, se hace un reintento controlado con verify=False.


# =============================================================================
# Clase principal: extracción de enlaces desde listas SharePoint de Normatividad
# =============================================================================
class WebScrapingMinAgricultura:

    # -------------------------------------------------------------------------
    # Inicialización de configuración base
    # -------------------------------------------------------------------------
    def __init__(self, base_url, headless=True):
        self.base_url = base_url.rstrip("/") + "/"                               # Normaliza slash final
        self.headless = headless                                                    # Se conserva por compatibilidad
        self.site_url = self.base_url.rstrip("/")                                   # URL base para API SharePoint
        self.base_domain = "https://www.minagricultura.gov.co"                     # Dominio para construir URLs absolutas
        self._ssl_verify = True                                                     # Intenta SSL estricto primero

        # Categorías del buscador y lista SharePoint asociada
        self.categorias = {
            1: {"nombre": "conpes", "lista": "Conpes"},
            2: {"nombre": "leyes", "lista": "Leyes"},
            3: {"nombre": "resoluciones", "lista": "Resoluciones"},
            4: {"nombre": "decretos", "lista": "Decretos"},
            10: {"nombre": "circulares", "lista": "Circulares"}
        }

    # -------------------------------------------------------------------------
    # Iterador de items en lista SharePoint (con paginación __next)
    # -------------------------------------------------------------------------
    def _iterar_items_lista(self, nombre_lista):
        """Obtiene todos los items de una lista SharePoint con paginación."""
        headers = {"Accept": "application/json;odata=verbose"}                    # Formato JSON clásico de SharePoint
        url = (
            f"{self.site_url}/_api/web/lists/getbytitle('{nombre_lista}')/Items"
            "?$select=FileRef,Anexos,Title&$top=5000"                                # Trae columnas necesarias y lote grande
        )

        while url:                                                                    # Recorre todas las páginas devueltas por API
            try:
                resp = requests.get(url, headers=headers, timeout=60, verify=self._ssl_verify)  # Solicitud principal
            except SSLError:
                if self._ssl_verify:
                    # Fallback para equipos sin cadena de certificados actualizada
                    print(" ⚠ SSL verify falló. Reintentando con verify=False...")
                    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)         # Evita ruido de warnings
                    self._ssl_verify = False                                                    # Desactiva verify para siguientes llamadas
                    resp = requests.get(url, headers=headers, timeout=60, verify=False)         # Reintento inmediato
                else:
                    raise                                                                    # Si ya estaba en False, propaga error real
            resp.raise_for_status()                                                         # Falla explícitamente si HTTP != 2xx
            data = resp.json().get("d", {})                                                # Estructura OData de SharePoint
            for item in data.get("results", []):                                           # Entrega item por item al consumidor
                yield item
            url = data.get("__next")                                                       # URL de siguiente página (si existe)

    # --------------------------------------------
    # Extraer enlaces PDF de una categoría del MinAgricultura
    # --------------------------------------------
    def _extraer_enlaces_categoria(self, tipo_id):
        if tipo_id not in self.categorias:                                                  # Valida categoría soportada
            print(f" ❌ ERROR: Categoría inválida: {tipo_id}")
            return []
        categoria = self.categorias[tipo_id]                                                # Obtiene metadata de categoría
        nombre_categoria = categoria["nombre"]                                              # Nombre amigable para logs
        nombre_lista = categoria["lista"]                                                   # Nombre exacto de lista SharePoint
        url = f"{self.base_url}SitePages/buscador-general-normas.aspx?t={tipo_id}"         # URL informativa para trazabilidad

        print(f"\n=== CATEGORÍA {tipo_id} ({nombre_categoria}) ===")
        print(f"Consultando lista SharePoint: {nombre_lista}")
        enlaces = []
        try:
            for item in self._iterar_items_lista(nombre_lista):                             # Lee todos los registros de la lista
                file_ref = item.get("FileRef")                                              # Ruta relativa del archivo en SharePoint
                if not file_ref:
                    continue

                pdf_url = urljoin(self.base_domain, file_ref)                               # Convierte a URL absoluta
                if "/Normatividad/" not in pdf_url:                                          # Evita archivos fuera del módulo
                    continue
                if ".pdf" not in pdf_url.lower():                                           # Restringe a documentos PDF
                    continue
                enlaces.append(pdf_url)                                                      # Agrega candidato válido
        except Exception as e:
            print(f" ❌ ERROR consultando API de lista '{nombre_lista}': {e}")
            return []

        print(f" → PDF encontrados por API: {len(enlaces)}")

        return enlaces

    # --------------------------------------------
    # Extraer enlaces de todas las categorías
    # --------------------------------------------
    def extraer_todos_los_enlaces(self):
        enlaces = []
        categorias_activas = ", ".join([f"{cid}:{cfg['nombre']}" for cid, cfg in self.categorias.items()])  # Resumen para logs
        print(f"\n===== CATEGORÍAS ACTIVAS (BUSCADOR) =====\n{categorias_activas}")

        # Iterar sobre todas las categorías
        for tipo_id in self.categorias.keys():                                               # Recorre 1,2,3,4,10
            encontrados = self._extraer_enlaces_categoria(tipo_id)                           # Extrae por API de la categoría
            print(f" → Enlaces agregados en categoría {tipo_id}: {len(encontrados)}")
            enlaces.extend(encontrados)                                                      # Acumula enlaces de todas las categorías

        # eliminar duplicados
        enlaces = list(set(enlaces))                                                         # Deduplicación final global
        print(f"\n===== EXTRACCIÓN FINALIZADA =====\nTotal enlaces únicos: {len(enlaces)}")

        return enlaces

    # --------------------------------------------
    # Descargar archivos PDF con requests
    # --------------------------------------------
    def descargar_archivos(self, enlaces, upload_dir):
        total = len(enlaces)                                                                 # Total a procesar
        descargados = 0
        errores = 0

        print("\n===== INICIANDO DESCARGAS =====")
        print(f"Total de enlaces a procesar: {total}\n")

        for i, url in enumerate(enlaces, start=1):                                           # Descarga secuencial para control de errores
            try:
                nombre_archivo = url.split("/")[-1].replace("%20", "_")                  # Normaliza espacios en nombre local
                ruta_destino = os.path.join(upload_dir, nombre_archivo)                     # Ruta de salida en uploads

                print(f"[Descargando archivo {i} / {total}]: {url}")
                print(f" → Guardar como: {nombre_archivo}")
                
                # --- DESCARGA ROBUSTA CON STREAM ---
                try:
                    r = requests.get(url, stream=True, timeout=180, verify=self._ssl_verify)  # Descarga principal
                except SSLError:
                    if self._ssl_verify:
                        print("   ⚠ SSL verify falló al descargar. Reintentando con verify=False...")
                        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)     # Evita ruido de warnings
                        self._ssl_verify = False                                                # Reutiliza fallback para descargas siguientes
                        r = requests.get(url, stream=True, timeout=180, verify=False)           # Reintento inmediato
                    else:
                        raise

                with r:                                                                       # Cierra conexión al finalizar
                    if r.status_code != 200:
                        print(f"   ✖ ERROR HTTP {r.status_code}")
                        errores += 1
                        continue

                    with open(ruta_destino, "wb") as f:
                        for chunk in r.iter_content(chunk_size=1024 * 32):                  # Escribe por bloques de 32KB
                            if chunk:
                                f.write(chunk)

                # --- VALIDAR TAMAÑO ---
                tamaño = os.path.getsize(ruta_destino)                                       # Validación rápida de integridad mínima
                if tamaño < 5000:
                    print(f"   ✖ Archivo demasiado pequeño ({tamaño} bytes). Posible descarga incompleta.")
                    errores += 1
                    continue

                # --- VALIDAR EOF MARKER ---
                with open(ruta_destino, "rb") as f:
                    f.seek(-2048, os.SEEK_END)                                               # Leer cola del archivo para firma EOF
                    final = f.read()

                if b"%%EOF" not in final:
                    print("   ✖ Archivo sin marcador EOF → descarga truncada.")
                    errores += 1
                    continue

                # --- OK ---
                print(f"   ✔ DESCARGADO ({tamaño} bytes)")
                descargados += 1                

            except Exception as e:
                print(f"   ✖ ERROR EXCEPCIÓN: {e}")
                errores += 1

        print("\n===== DESCARGAS FINALIZADAS =====")
        print(f"Total: {total}")
        print(f"Descargados: {descargados}")
        print(f"Errores: {errores}")

        # devolver conteos al backend
        return {
            "total": total,
            "descargados": descargados,
            "errores": errores
        }