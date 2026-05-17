"""
Resumen abstractivo con mT5 para NormaSearch.

Modelo: google/mt5-small (multilingüe, 101 idiomas, incluye español).
Estrategia para documentos largos: map-reduce sobre chunks de 3 000 chars,
dado que mT5-small tiene un contexto de entrada de ~512 tokens.

La entrada recibe solo limpieza de nivel 1 (preprocesar_para_transformer):
los modelos seq2seq necesitan la sintaxis completa para generar texto coherente.
Eliminar stopwords antes del encoder degrada la calidad del resumen.
"""

import time
from typing import Optional

from Helpers.PLN.text_preprocessing import preprocesar_para_transformer

_MODELO_RESUMEN = 'google/mt5-small'


def cargar_pipeline_resumen(modelo_nombre: str = _MODELO_RESUMEN):
    """
    Carga el pipeline de HuggingFace para summarization.

    Usa AutoTokenizer con use_fast=False (el tokenizador Rust no existe para mT5)
    y legacy=True (suprime el aviso de comportamiento de T5Tokenizer en HF >= 4.31).
    Detecta CUDA / Apple MPS / CPU automáticamente.

    Retorna False si el modelo no puede cargarse, en lugar de None, para
    que PLN pueda distinguir "no intentado" de "intentado y fallido" y evitar
    reintentos innecesarios en el mismo proceso.

    Args:
        modelo_nombre: Identificador HuggingFace. Default: google/mt5-small.

    Returns:
        Pipeline de HuggingFace listo para inferencia, o False si falló la carga.
    """
    from transformers import pipeline, AutoTokenizer
    import torch

    if torch.cuda.is_available():
        device = 0
        print("  → GPU: CUDA")
    elif hasattr(torch.backends, 'mps') and torch.backends.mps.is_available():
        device = 'mps'
        print("  → GPU: Apple MPS")
    else:
        device = -1
        print("  → CPU (inferencia lenta en documentos largos)")

    print(f"  Cargando modelo de resumen '{modelo_nombre}'...")
    try:
        tokenizer = AutoTokenizer.from_pretrained(modelo_nombre, use_fast=False, legacy=True)
        pipe = pipeline("summarization", model=modelo_nombre, tokenizer=tokenizer, device=device)
        print(f"  ✓ '{modelo_nombre}' cargado")
        return pipe
    except Exception as exc:
        print(f"  ✗ No se pudo cargar '{modelo_nombre}': {exc}")
        return False


def _resumir_fragmento(pipeline_resumen, fragmento: str,
                        max_new_tokens: int, min_length: int) -> str:
    """
    Aplica el pipeline de resumen a un único fragmento.

    mT5 requiere el prefijo "summarize: " (modelo text-to-text, familia T5).
    Se usa max_new_tokens en lugar de max_length para evitar el conflicto
    de parámetros que genera advertencia en HuggingFace.

    Args:
        pipeline_resumen: Pipeline cargado.
        fragmento:        Texto limpio (nivel 1) a resumir.
        max_new_tokens:   Máximo de tokens a generar.
        min_length:       Mínimo de tokens generados.

    Returns:
        String con el resumen generado.
    """
    modelo_id = pipeline_resumen.model.config.name_or_path.lower()
    entrada = f"summarize: {fragmento}" if 't5' in modelo_id else fragmento

    resultado = pipeline_resumen(
        entrada,
        max_new_tokens=max_new_tokens,
        min_length=min_length,
        do_sample=False,   # decodificación greedy: determinista y más rápida
        truncation=True,
    )
    return resultado[0]['summary_text']


def generar_resumen_abstractivo(pipeline_resumen,
                                 texto: str,
                                 max_length: int = 150,
                                 min_length: int = 10,
                                 chunk_chars: int = 3000) -> str:
    """
    Genera un resumen abstractivo usando estrategia map-reduce.

    MAP:    divide el texto en chunks de chunk_chars → resumen parcial por chunk.
    REDUCE: si hay múltiples resúmenes → concatenar; si el concatenado supera
            chunk_chars → aplicar un paso adicional de resumen.

    Retorna string vacío si el pipeline no está disponible o el texto es
    demasiado corto, sin lanzar excepción (degradación sin interrupción).

    Args:
        pipeline_resumen: Pipeline de HuggingFace (None/False → sin resumen).
        texto:            Texto de la norma en español (sin preprocesar).
        max_length:       Máximo de tokens a generar por fragmento.
        min_length:       Mínimo de tokens generados.
        chunk_chars:      Tamaño máximo de cada chunk en caracteres.

    Returns:
        Resumen como string, o "" si el pipeline no está disponible.
    """
    if not pipeline_resumen:
        return ""

    texto_limpio = preprocesar_para_transformer(texto)
    if not texto_limpio or len(texto_limpio.strip()) < 50:
        return ""

    chunks_validos = [
        c for c in (texto_limpio[i:i + chunk_chars]
                    for i in range(0, len(texto_limpio), chunk_chars))
        if len(c.strip()) >= 100
    ]
    if not chunks_validos:
        return ""

    total = len(chunks_validos)
    print(f"  → Resumiendo {total} segmento(s) (~{total * 30}–{total * 60}s en CPU)")

    resumenes: list = []
    for idx, chunk in enumerate(chunks_validos, 1):
        t0 = time.time()
        print(f"     Segmento {idx}/{total}...", end='', flush=True)
        try:
            resumenes.append(_resumir_fragmento(pipeline_resumen, chunk, max_length, min_length))
            print(f" ✓ {time.time() - t0:.1f}s")
        except Exception as exc:
            print(f" ✗ {exc}")

    if not resumenes:
        return ""
    if len(resumenes) == 1:
        return resumenes[0]

    combinado = ' '.join(resumenes)
    if len(combinado) <= chunk_chars:
        return combinado

    # Paso de reduce: resumir la concatenación de resúmenes parciales
    print(f"     Reduce final ({len(combinado)} chars)...", end='', flush=True)
    t0 = time.time()
    try:
        final = _resumir_fragmento(pipeline_resumen, combinado[:chunk_chars], max_length, min_length)
        print(f" ✓ {time.time() - t0:.1f}s")
        return final
    except Exception as exc:
        print(f" ✗ {exc}")
        return combinado   # fallback: devolver la concatenación sin reduce