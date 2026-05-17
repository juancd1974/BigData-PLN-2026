import os
import re
from werkzeug.utils import secure_filename 
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
from typing import List, Dict, Optional
import requests
from Helpers.Utils.funciones import Funciones

class WebScraping:
    """
    Web Scraping dinámico con Playwright y descargas con Requests.
    """

    def __init__(self, base_url: str, headless=True):
        self.base_url = base_url.rstrip("/") + "/"
        self.domain = urlparse(self.base_url).netloc
        self.dynamic_folder_name = secure_filename(self.domain).replace('.', '_')
        self.carpeta_pdfs = os.path.join('static', 'pdfs', self.dynamic_folder_name, 'descargas')
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.headless = headless

        # Archivos que se pueden descargar, extensible si se necesita
        self.DOWNLOAD_EXTENSIONS = ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.zip', 'txt', '.rtf')
        self.PDF_KEYWORDS_FILTER = ['Normatividad', 'Leyes', 'Decretos', 'Resoluciones', 'Conpes', 
                                    'Actos', 'Reglamentos', 'Circulares', 'Instructivos', 'Manuales',
                                    'Guías', 'Acuerdos', 'Contratos', 'Convenios']

    # INICIAR PLAYWRIGHT (una sola vez)
    def _start(self):
        """Inicia Playwright y abre un navegador Chromium."""
        if self.browser is None:
            self.playwright = sync_playwright().start()
            self.browser = self.playwright.chromium.launch(headless=self.headless)
            self.context = self.browser.new_context(accept_downloads=True)
            self.page = self.context.new_page()

    # DETENER PLAYWRIGHT (una sola vez)
    def _stop(self):
        try:
            if self.context:
                self.context.close()
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
        except:
            pass  # evitar error si ya está cerrado

    def _normalizar_url(self, url: str):
        """Normaliza la URL eliminando fragmentos (#) para la comparación en el set de visitados."""
        return url.split('#')[0].rstrip('/')
    
    def _find_in_page_or_iframe(self, selector: str):
        """
        Busca un selector en la página principal. Si no aparece, lo busca en los iframes.
        Retorna: (locator, frame)
        """
        # Buscar en página principal
        loc = self.page.locator(selector)
        if loc.count() > 0:
            return loc, None

        # Buscar en iframes
        for frame in self.page.frames:
            try:
                loc_iframe = frame.locator(selector)
                if loc_iframe.count() > 0:
                    return loc_iframe, frame
            except:
                pass

        return None, None

    def recorrer_dominio_recursivamente(
        self,
        initial_path: str,
        max_profundidad: int = 5,
        pdf_keywords: Optional[List[str]] = None,
        selector_contenedor: Optional[str] = None
    ) -> List[str]:

        self._start()

        start_url = urljoin(self.base_url, initial_path)
        queue = [(start_url, 0)]
        visited = {self._normalizar_url(start_url)}
        pdf_links = set()

        if pdf_keywords is None:
            pdf_keywords = self.PDF_KEYWORDS_FILTER

        print(f"[RASTREO] Iniciando BFS en {start_url} (Máx Prof: {max_profundidad})")
        print(f"[RASTREO] Selector usado: {selector_contenedor}")

        while queue:
            current_url, depth = queue.pop(0)
            if depth > max_profundidad:
                continue

            try:
                self.page.goto(current_url, timeout=30_000, wait_until='domcontentloaded')
                print(f"[{depth}/{max_profundidad}] Visitando: {current_url}")

                # ======================================================
                # 1. Seleccionar contenedor (página o iframe)
                # ======================================================
                if selector_contenedor:
                    contenedor, frame = self._find_in_page_or_iframe(selector_contenedor)

                    if contenedor is None:
                        print(f"[WARN] Selector '{selector_contenedor}' no encontrado en {current_url}. Usando página completa.")
                        enlaces_elementos = self.page.locator("a[href]").all()
                    else:
                        if frame is None:
                            enlaces_elementos = contenedor.locator("a[href]").all()
                        else:
                            enlaces_elementos = frame.locator(selector_contenedor + " a[href]").all()

                else:
                    enlaces_elementos = self.page.locator("a[href]").all()

                # ======================================================
                # 2. Procesar enlaces del contenedor
                # ======================================================
                for element in enlaces_elementos:
                    href = element.get_attribute("href")
                    if not href:
                        continue

                    full_url = urljoin(current_url, href)
                    normalized_url = self._normalizar_url(full_url)

                    is_internal = urlparse(full_url).netloc == self.domain
                    is_download_link = full_url.lower().endswith(self.DOWNLOAD_EXTENSIONS)

                    # -----------------------------------------
                    # 2.1 PDFs: aplicar filtros
                    # -----------------------------------------
                    if is_download_link:
                        is_relevant = any(k.lower() in full_url.lower() for k in pdf_keywords)

                        if is_relevant:
                            if full_url not in pdf_links:
                                pdf_links.add(full_url)
                                print(f"   -> [PDF ENCONTRADO] {full_url}")
                        else:
                            print(f"   -> [PDF IGNORADO] {full_url}")

                    # -----------------------------------------
                    # 2.2 Enlaces internos → BFS SEMILIMITADO
                    # Solo se siguen si provienen del contenedor
                    # -----------------------------------------
                    elif is_internal and normalized_url not in visited:

                        if selector_contenedor:
                            try:
                                inside = element.evaluate(
                                    "this.closest(arguments[0]) !== null",
                                    selector_contenedor
                                )
                            except:
                                inside = False

                            if not inside:
                                continue

                        # Agregar al BFS
                        visited.add(normalized_url)
                        queue.append((full_url, depth + 1))

            except Exception as e:
                print(f"[ERROR] Fallo en {current_url}: {e}")
                continue

        self._stop()
        print(f"[RASTREO FINALIZADO] Se encontraron {len(pdf_links)} enlaces de descarga.")
        return list(pdf_links)

    # FUNCIÓN DE DESCARGA RÁPIDA (con requests)
    def descargar_archivos_rapido(self, enlaces: List[str], carpeta_destino: str) -> Dict:
        """
        Descarga archivos PDF de forma rápida usando la librería requests.
        Implementa verificación de Content-Type e idempotencia.
        """
        Funciones.crear_carpeta(carpeta_destino)
        descargados, errores, saltados = 0, 0, 0
        total_enlaces = len(enlaces)
        
        print(f"[DESCARGA RÁPIDA] Iniciando descarga de {total_enlaces} archivos en {carpeta_destino}...")

        for i, url in enumerate(enlaces, 1):
            
            # 1. Deducir nombre del archivo desde la URL
            nombre_archivo = os.path.basename(urlparse(url).path)
            # Sanitizar nombre para evitar problemas de ruta
            nombre_archivo = secure_filename(nombre_archivo or f"descarga_{i}.pdf")
            
            ruta_destino = os.path.join(carpeta_destino, nombre_archivo)

            print(f"[{i}/{total_enlaces}] Procesando {url}")
            
            # 2. IDEMPOTENCIA: Saltar si el archivo ya existe localmente
            if os.path.exists(ruta_destino):
                saltados += 1
                print(f"   -> [SALTADO] Ya existe: {nombre_archivo}")
                continue

            try:
                # 3. Descarga con requests
                with requests.get(url, stream=True, timeout=15) as r:
                    r.raise_for_status() # Lanza excepción para códigos 4xx/5xx

                    # 4. VERIFICACIÓN DE CONTENT-TYPE (Evita descargar HTML de error/404)
                    content_type = r.headers.get('Content-Type', '').lower()
                    if 'application/pdf' not in content_type and not nombre_archivo.lower().endswith('.pdf'):
                         # Permitir otros tipos de descarga si no son HTML
                        if 'text/html' in content_type:
                            raise ValueError(f"URL no es PDF o archivo esperado (Content-Type: {content_type})")
                        
                    # 5. Guardar el archivo en modo binario
                    with open(ruta_destino, 'wb') as f:
                        for chunk in r.iter_content(chunk_size=8192):
                            f.write(chunk)
                    
                    descargados += 1
                    print(f"   -> [DESCARGADO] Guardado como: {nombre_archivo}")

            except requests.exceptions.Timeout:
                errores += 1
                print(f"   -> [ERROR TIMEOUT] Tiempo de espera agotado para {url}")
            except requests.exceptions.RequestException as e:
                errores += 1
                print(f"   -> [ERROR HTTP] Error en la solicitud {url}: {e}")
            except ValueError as e:
                errores += 1
                print(f"   -> [ERROR CONTENIDO] {e} en {url}")
            except Exception as e:
                errores += 1
                print(f"   -> [ERROR GENÉRICO] Fallo al descargar {url}: {e}")

        return {
            "descargados": descargados,
            "errores": errores,
            "saltados": saltados,
            "total": total_enlaces
        }

    # FUNCIÓN DE RASTREO CON PAGINACIÓN (para búsquedas específicas)

    def obtener_enlaces_con_paginacion(self, initial_path, selector_pagina='a[title="Siguiente"]', max_links=2000):
        """
        Extrae enlaces de una página con paginación, usando Playwright.
        """
        self._start()
        enlaces = set()
        current_url = urljoin(self.base_url, initial_path)

        print(f"[PAGINACIÓN] Iniciando extracción de enlaces desde: {current_url}")

        while True:
            try:
                self.page.goto(current_url, timeout=30_000, wait_until='domcontentloaded')
                print(f"Página actual: {current_url} | Enlaces recolectados: {len(enlaces)}")

                # Esperar a que los elementos de enlace (PDFs) estén presentes
                self.page.wait_for_selector('a[href$=".pdf"]', timeout=5000)

                # Extraer enlaces
                elementos_enlace = self.page.locator('a[href$=".pdf"]').all() # Solo busca enlaces que terminen en .pdf
                
                nuevos_enlaces_encontrados = 0
                for link_element in elementos_enlace:
                    href = link_element.get_attribute("href")
                    if href:
                        full_url = urljoin(current_url, href)
                        
                        # Aplicar filtro de palabras clave 
                        is_relevant = any(k.lower() in full_url.lower() for k in self.PDF_KEYWORDS_FILTER)
                        
                        if is_relevant:
                            if full_url not in enlaces:
                                enlaces.add(full_url)
                                nuevos_enlaces_encontrados += 1

                print(f"   -> Enlaces nuevos encontrados en esta página: {nuevos_enlaces_encontrados}")
                
                # Criterio de parada por límite
                if len(enlaces) >= max_links:
                    print(f"[LÍMITE ALCANZADO] Deteniendo rastreo por max_links={max_links}")
                    break

                # Navegar a la siguiente página
                siguiente_enlace = self.page.locator(selector_pagina)
                if siguiente_enlace.is_visible():
                    next_href = siguiente_enlace.get_attribute('href')
                    if next_href:
                        current_url = urljoin(self.base_url, next_href)
                    else:
                        print("[FIN] No se encontró URL para el botón 'Siguiente'.")
                        break
                else:
                    print("[FIN] Botón 'Siguiente' no visible.")
                    break

            except PlaywrightTimeoutError:
                print(f"[TIMEOUT] Error cargando o esperando elementos en {current_url}. Terminando.")
                break
            except Exception as e:
                print(f"[ERROR GENÉRICO] Fallo en la paginación: {e}")
                break

        self._stop()
        return list(enlaces)




    '''
    # EXTRAER ENLACES DINÁMICOS
    def extraer_links(self, url, extensiones=None, selector_contenedor = None,
                      espera_dom: int = 1500, max_links: int = 2000):
        """
        Extrae enlaces desde la página usando DOM dinámico. Normaliza URLs. Elimina duplicados

        Args:
            url: URL inicial
            selector_contenedor: CSS selector opcional
            extensiones: lista de extensiones válidas (ej: ["aspx","pdf"])
            espera_dom: tiempo para esperar carga del DOM
            max_links (int): Máximo de enlaces a capturar.
        Returns: 
            list: lista de enlaces únicos encontrados: { url: "...", type: "pdf" }
        """

        self._start()

        try:
            self.page.goto(url, timeout=40_000)
        except PlaywrightTimeoutError:
            print(f"[WARN] Timeout cargando {url}")
        except Exception as e:
            print(f"[ERROR] No se pudo abrir {url}: {e}")
            return []
        
        # Espera para cargar la página
        self.page.wait_for_timeout(espera_dom)

        # Encuentra todos los enlaces dentro del contenedor (o toda la página)
        if selector_contenedor:
            elementos = self.page.query_selector_all(selector_contenedor + " a")
        else:
            elementos = self.page.query_selector_all("a")

        # almacenar enlaces únicos
        enlaces = set()     
        # normalizar extensiones    
        extensiones_norm = [ext.lower().strip() for ext in extensiones] 

        for el in elementos:
            try:
                href = el.get_attribute("href")     # si no este atributo, salta
                if not href:
                    continue

                href_abs = urljoin(self.base_url, href) # normalizar URL

                for ext in extensiones_norm:
                    if href_abs.lower().endswith("." + ext):    # extensión válida
                        enlaces.add(href_abs)
                        break

                if len(enlaces) >= max_links:   # límite alcanzado
                    break

            except Exception:
                continue

        return list(enlaces)

    # DESCARGAR ARCHIVO DIRECTAMENTE CON PLAYWRIGHT
    def descargar_archivos(self, enlaces, carpeta_destino):
        """
        Descarga archivos encontrando eventos de descarga de Playwright.
        """

        self._start()
        os.makedirs(carpeta_destino, exist_ok=True)
        descargados, errores = 0, 0

        for url in enlaces:
            try:
                with self.page.expect_download() as download_info:
                    self.page.goto(url, timeout=35_000)
                download = download_info.value

                nombre = download.suggested_filename
                ruta = os.path.join(carpeta_destino, nombre)
                download.save_as(ruta)
                descargados += 1

            except PlaywrightTimeoutError:
                errores += 1
                print(f"[TIMEOUT] {url}")
            except Exception as e:
                errores += 1
                print(f"[ERROR] Error descargando {url}: {e}")

        return {
            "descargados": descargados,
            "errores": errores,
            "total": len(enlaces)
        }
    '''
