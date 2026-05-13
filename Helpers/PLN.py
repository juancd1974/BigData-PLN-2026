# PLN 2026-1S — S4: spaCy NER/POS + dateparser · S13: HuggingFace Transformers · S14: sentence-transformers
import numpy as np
import re
import time
import spacy
import dateparser
from collections import Counter
from sentence_transformers import SentenceTransformer
from typing import List, Dict, Tuple, Optional
import warnings
warnings.filterwarnings('ignore')

# Modelo de resumen abstractivo — S13, notebook tabla, multilingüe con soporte español
_MODELO_RESUMEN = 'google/mt5-small'


class PLN:
    """Procesamiento de lenguaje natural sobre normatividad en español."""

    def __init__(self, modelo_spacy: str = 'es_core_news_lg',
                 modelo_embeddings: str = 'paraphrase-multilingual-MiniLM-L12-v2',
                 cargar_modelos: bool = True):
        self.modelo_spacy_nombre = modelo_spacy
        self.modelo_embeddings_nombre = modelo_embeddings
        self.nlp = None
        self.model_embeddings = None
        self._pipeline_resumen = None       # carga lazy al primer uso
        self._modelo_resumen_activo = None  # nombre del modelo que cargó exitosamente

        if cargar_modelos:
            self._cargar_modelos()

    def _cargar_modelos(self):
        """Carga spaCy y sentence-transformers."""
        try:
            print("Cargando modelo de spaCy...")
            self.nlp = spacy.load(self.modelo_spacy_nombre)
            self.nlp.max_length = 3_000_000          # documentos legales superan el límite por defecto (1 M chars)
            print(f"Modelo spaCy '{self.modelo_spacy_nombre}' cargado correctamente")
        except OSError:
            print(f"Modelo '{self.modelo_spacy_nombre}' no encontrado. Ejecuta:")
            print(f"  python -m spacy download {self.modelo_spacy_nombre}")
            try:
                self.nlp = spacy.load('es_core_news_sm')
                print("Usando es_core_news_sm como alternativa")
            except OSError:
                print("Error: no se pudo cargar ningún modelo de spaCy")
                self.nlp = None

        print("Cargando modelo de embeddings...")
        try:
            self.model_embeddings = SentenceTransformer(self.modelo_embeddings_nombre)
            print(f"Modelo de embeddings '{self.modelo_embeddings_nombre}' cargado correctamente")
        except Exception as e:
            print(f"Error al cargar modelo de embeddings: {e}")
            self.model_embeddings = None

    # ── S4: NER con spaCy — extrae personas, lugares, orgs, fechas y leyes

    def extraer_entidades(self, texto: str) -> Dict[str, List[str]]:
        """Extrae entidades nombradas usando spaCy (S4)."""
        if not self.nlp:
            raise ValueError("Modelo spaCy no cargado.")

        doc = self.nlp(texto)
        entidades = {
            'personas': [],
            'lugares': [],
            'organizaciones': [],
            'fechas': [],
            'leyes': [],
            'otros': []
        }

        for ent in doc.ents:
            if ent.label_ == 'PER':
                entidades['personas'].append(ent.text)
            elif ent.label_ == 'LOC':
                entidades['lugares'].append(ent.text)
            elif ent.label_ == 'ORG':
                entidades['organizaciones'].append(ent.text)
            elif ent.label_ == 'DATE':
                entidades['fechas'].append(ent.text)
            elif ent.label_ == 'LAW' or 'ley' in ent.text.lower():
                entidades['leyes'].append(ent.text)
            else:
                entidades['otros'].append(f"{ent.text} ({ent.label_})")

        for key in entidades:
            entidades[key] = list(dict.fromkeys(entidades[key]))  # elimina duplicados conservando orden de aparición

        return entidades

    def normalizar_fecha(self, texto: str) -> Optional[str]:
        """Normaliza una fecha en español a formato YYYY-MM-DD usando dateparser (S4)."""
        if not texto:
            return None
        resultado = dateparser.parse(texto, languages=['es'],
                                     settings={'PREFER_DAY_OF_MONTH': 'first',
                                               'RETURN_AS_TIMEZONE_AWARE': False})
        if resultado:
            return resultado.strftime('%Y-%m-%d')
        return None

    def extraer_metadatos_norma(self, texto: str) -> Dict:
        """
        Extrae tipo, número, fecha, año y entidad emisora de una norma.
        Usa spaCy NER para organizaciones y dateparser para fechas (S4).
        """
        lineas = texto.split("\n")
        encabezado = "\n".join(lineas[:20]).upper()

        meta = {
            "tipo_norma": None,
            "numero_norma": None,
            "anio_norma": None,
            "entidad_emisora": None,
            "fecha_documento": None,
            "titulo_norma": None
        }

        # Entidad emisora via NER spaCy
        doc = self.nlp(encabezado)
        for ent in doc.ents:
            if ent.label_ == "ORG" and len(ent.text) > 5:
                meta["entidad_emisora"] = ent.text.upper()
                break

        # Fecha: buscar patrón "26 de marzo de 2019" y normalizar con dateparser
        patron_fecha = re.search(
            r'\b(\d{1,2}\s+de\s+[a-zA-ZÁÉÍÓÚáéíóú]+\s+de\s+\d{4})',
            texto, re.IGNORECASE
        )
        if patron_fecha:
            fecha_norm = self.normalizar_fecha(patron_fecha.group(1))
            if fecha_norm:
                meta["fecha_documento"] = fecha_norm
                meta["anio_norma"] = int(fecha_norm[:4])

        # Tipo de norma
        tipos = ["DECRETO", "RESOLUCIÓN", "RESOLUCION", "LEY", "CIRCULAR", "ACUERDO"]
        for t in tipos:
            if t in encabezado:
                meta["tipo_norma"] = "RESOLUCIÓN" if t == "RESOLUCION" else t
                break

        # Número de norma
        m = re.search(r"(DECRETO|RESOLUCIÓN|RESOLUCION|LEY)\s+N?O?\.?\s*(\d{2,5})", encabezado)
        if m:
            meta["numero_norma"] = int(m.group(2))
        else:
            m = re.search(r"\b(\d{2,5})\b", encabezado)
            if m:
                meta["numero_norma"] = int(m.group(1))

        # Año si no se obtuvo de la fecha
        if not meta["anio_norma"]:
            m = re.search(r"\b(19\d{2}|20\d{2})\b", encabezado)
            if m:
                meta["anio_norma"] = int(m.group(1))

        # Título
        for linea in lineas[:30]:
            if linea.strip().lower().startswith(("por el cual", "por la cual")):
                meta["titulo_norma"] = linea.strip()
                break

        return meta

    # ── S4: palabras clave por frecuencia de lemas filtrados por POS tag

    def extraer_temas(self, texto: str, top_n: int = 10) -> List[Tuple[str, float]]:
        """Extrae palabras clave por frecuencia de lemas relevantes (S4)."""
        if not self.nlp:
            raise ValueError("Modelo spaCy no cargado.")

        doc = self.nlp(texto)
        palabras_relevantes = [
            token.lemma_.lower()
            for token in doc
            if not token.is_stop
            and not token.is_punct
            and not token.is_space
            and len(token.text) > 3
            and token.pos_ in ['NOUN', 'PROPN', 'ADJ', 'VERB']
        ]

        contador = Counter(palabras_relevantes)
        temas = contador.most_common(top_n)
        total = len(palabras_relevantes)

        if total > 0:
            return [(palabra, (freq / total) * 100) for palabra, freq in temas]
        return [(palabra, 0.0) for palabra, _ in temas]

    # ── S13: resumen abstractivo con HuggingFace — map-reduce para documentos largos
    def generar_resumen_abstractivo(self, texto: str,
                                    max_length: int = 150,
                                    min_length: int = 10,
                                    chunk_chars: int = 3000) -> str:
        """Resumen abstractivo con HuggingFace Transformers (S13).

        Intenta cargar modelos en orden (_MODELOS_RESUMEN). Si ninguno está
        disponible cae a un resumen extractivo de las primeras oraciones.
        Documentos largos usan map-reduce: resume chunks y luego los resume.
        """
        if self._pipeline_resumen is None:
            from transformers import pipeline, AutoTokenizer
            import torch
            try:
                print(f"Cargando modelo de resumen '{_MODELO_RESUMEN}'...")
                # use_fast=False: tokenizador rust no existe para mT5
                # legacy=True: evita el aviso de comportamiento heredado de T5Tokenizer
                tokenizer = AutoTokenizer.from_pretrained(_MODELO_RESUMEN,
                                                          use_fast=False, legacy=True)
                if torch.cuda.is_available():
                    device = 0
                    print("  → GPU detectada: usando CUDA")
                elif torch.backends.mps.is_available():
                    device = 'mps'
                    print("  → GPU detectada: usando Apple MPS")
                else:
                    device = -1
                    print("  → Sin GPU — usando CPU (inferencia lenta)")
                self._pipeline_resumen = pipeline("summarization", model=_MODELO_RESUMEN,
                                                  tokenizer=tokenizer, device=device)
                self._modelo_resumen_activo = _MODELO_RESUMEN
                print(f"  ✓ Modelo '{_MODELO_RESUMEN}' cargado")
            except Exception as e:
                print(f"  ✗ Modelo de resumen no disponible: {e}")
                self._pipeline_resumen = False  # no reintentar en el mismo proceso

        if not self._pipeline_resumen:
            return ""  # modelo no disponible, sin resumen

        # mT5 usa formato text-to-text: requiere prefijo de tarea
        usa_prefijo = 't5' in _MODELO_RESUMEN.lower()

        def _resumir(fragmento: str) -> str:
            entrada = f"summarize: {fragmento}" if usa_prefijo else fragmento
            # max_new_tokens controla solo tokens generados; max_length controla total (entrada+salida)
            r = self._pipeline_resumen(entrada, max_new_tokens=max_length,
                                       min_length=min_length, do_sample=False)
            return r[0]['summary_text']

        # MAP: resumir cada chunk por separado
        chunks = [texto[i:i + chunk_chars] for i in range(0, len(texto), chunk_chars)]
        chunks_validos = [c for c in chunks if len(c.strip()) >= 100]
        total_chunks = len(chunks_validos)
        print(f"  → Resumiendo {total_chunks} segmento(s) (~{total_chunks * 30}–{total_chunks * 60}s en CPU)")

        resumenes = []
        for idx, chunk in enumerate(chunks_validos, 1):
            t0 = time.time()
            print(f"     Segmento {idx}/{total_chunks}...", end='', flush=True)
            resumenes.append(_resumir(chunk))
            print(f" ✓ {time.time() - t0:.1f}s")

        if not resumenes:
            return ""
        if len(resumenes) == 1:
            return resumenes[0]

        # REDUCE: resumir el texto combinado de los resúmenes parciales
        texto_combinado = ' '.join(resumenes)
        if len(texto_combinado) > chunk_chars:
            print(f"     Reduce final...", end='', flush=True)
            t0 = time.time()
            resultado = _resumir(texto_combinado[:chunk_chars])
            print(f" ✓ {time.time() - t0:.1f}s")
            return resultado
        return texto_combinado

    # ── S14: embeddings semánticos (384 dims) — base para búsqueda RAG

    def obtener_embeddings(self, textos: List[str]) -> np.ndarray:
        """Genera embeddings de oraciones/documentos con sentence-transformers."""
        if not self.model_embeddings:
            raise ValueError("Modelo de embeddings no cargado.")
        return self.model_embeddings.encode(textos, convert_to_numpy=True, show_progress_bar=False)

    # ── S4: tokenización, lematización y filtrado de stopwords con spaCy

    def preprocesar_texto(self, texto: str,
                          remover_stopwords: bool = True,
                          lematizar: bool = True,
                          remover_numeros: bool = False,
                          min_longitud: int = 3) -> str:
        """Tokenización, stopwords y lematización con spaCy (S2)."""
        if not self.nlp:
            raise ValueError("Modelo spaCy no cargado.")

        doc = self.nlp(texto)
        palabras = []

        for token in doc:
            if len(token.text) < min_longitud:
                continue
            if remover_stopwords and token.is_stop:
                continue
            if token.is_punct or token.is_space:
                continue
            if remover_numeros and token.like_num:
                continue
            palabras.append(token.lemma_.lower() if lematizar else token.text.lower())

        return ' '.join(palabras)

    # ── chunking para documentos legales que superan el límite de spaCy

    def dividir_en_chunks(self, texto: str, max_chars: int = 800_000) -> List[str]:
        """Divide texto en bloques para no superar el límite de spaCy."""
        return [texto[i:i + max_chars] for i in range(0, len(texto), max_chars)]

    def procesar_texto_largo(self, texto: str) -> Dict:
        """Extrae entidades, temas y resumen de documentos extensos por chunks."""
        if len(texto) <= 900_000:
            return {
                "entidades": self.extraer_entidades(texto),
                "temas": self.extraer_temas(texto),
                "resumen": self.generar_resumen_abstractivo(texto)
            }

        print(f" → Texto largo ({len(texto)} chars). Dividiendo en chunks…")
        chunks = self.dividir_en_chunks(texto)

        entidades_total = {k: [] for k in ['personas', 'lugares', 'organizaciones',
                                            'fechas', 'leyes', 'otros']}
        resumen_total = []

        for i, parte in enumerate(chunks):
            print(f"   → Chunk {i + 1}/{len(chunks)}")
            ents = self.extraer_entidades(parte)
            for key in entidades_total:
                entidades_total[key].extend(ents[key])
            resumen_total.append(self.generar_resumen_abstractivo(parte, max_length=80, min_length=10))

        for key in entidades_total:
            entidades_total[key] = list(dict.fromkeys(entidades_total[key]))

        return {
            "entidades": entidades_total,
            "temas": self.extraer_temas(texto[:500_000]),
            "resumen": "\n".join(resumen_total)
        }

    def close(self):
        pass
