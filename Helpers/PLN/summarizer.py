"""
Resumen abstractivo con mT5 para NormaSearch.

El modelo concreto se configura desde pipeline.py (default: google/mt5-small,
multilingüe, 101 idiomas). Todos los modelos mT5 tienen un contexto de entrada
de ~512 tokens; la estrategia map-reduce sobre chunks de 4 000 chars maneja
documentos de cualquier longitud.

La entrada recibe solo limpieza de nivel 1 (preprocesar_para_transformer):
los modelos seq2seq necesitan la sintaxis completa para generar texto coherente.
Eliminar stopwords antes del encoder degrada la calidad del resumen.

Función principal: generar_resumen_con_metricas()
"""

import math
import time
import torch
from typing import Dict, Optional, Tuple

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
        tokenizer.model_max_length = 512
        pipe = pipeline("summarization", model=modelo_nombre, tokenizer=tokenizer, device=device,
                        max_new_tokens=None)
        print(f"  ✓ '{modelo_nombre}' cargado")
        return pipe
    except Exception as exc:
        print(f"  ✗ No se pudo cargar '{modelo_nombre}': {exc}")
        return False


def _resumir_fragmento(pipeline_resumen, fragmento: str,
                        max_length: int, min_length: int) -> str:
    """
    Aplica el pipeline de resumen a un único fragmento.

    mT5 requiere el prefijo "summarize: " (modelo text-to-text, familia T5).
    Se usa max_length (no max_new_tokens): el pipeline de summarization reenvía
    max_length a model.generate() en todas las versiones de HuggingFace;
    max_new_tokens no siempre se forwarda, lo que hace que generate() use su
    default max_length=20 y provoca "min_length must be inferior than max_length"
    cuando min_length > 20.

    min_length se ajusta dinámicamente: no puede superar el 50% de los
    tokens estimados del fragmento ni max_length - 1, para evitar el
    error "min_length must be inferior than max_length" en fragmentos cortos.

    Args:
        pipeline_resumen: Pipeline cargado.
        fragmento:        Texto limpio (nivel 1) a resumir.
        max_length:       Máximo de tokens a generar.
        min_length:       Mínimo de tokens generados (se ajusta si es necesario).

    Returns:
        String con el resumen generado.
    """
    modelo_id = pipeline_resumen.model.config.name_or_path.lower()
    entrada = f"summarize: {fragmento}" if 't5' in modelo_id else fragmento

    # Estimar tokens del fragmento (aproximación: 1 token ≈ 4 chars)
    tokens_estimados = len(fragmento) // 4
    # min_length no puede superar el 50% de los tokens de entrada ni max_length - 1
    min_length_seguro = min(min_length,
                            max(1, tokens_estimados // 2),
                            max_length - 1)

    # Ajustar max_length si el fragmento es más corto que el límite configurado
    tokens_entrada = len(entrada) // 4
    if tokens_entrada < max_length:
        max_length = max(min_length_seguro + 1, tokens_entrada // 2)

    resultado = pipeline_resumen(
        entrada,
        max_length=max_length,
        min_length=min_length_seguro,
        do_sample=False,   # decodificación greedy: determinista y más rápida
        truncation=True,
    )
    return resultado[0]['summary_text']


def calcular_perplexidad(pipeline_resumen, texto: str) -> float:
    """
    Calcula la perplejidad del texto usando el modelo mT5 del pipeline.

    La perplejidad mide qué tan predecible es el texto para el modelo.
    Un valor más bajo indica texto más fluido y coherente.
    Fórmula: PP = exp(loss_promedio), donde loss_promedio es el promedio
    de cross-entropy losses por token obtenido del forward pass del modelo.

    Se ejecuta en torch.no_grad() para no acumular gradientes ni
    modificar los pesos durante la evaluación.

    Args:
        pipeline_resumen: Pipeline de HuggingFace cargado.
        texto:            Texto a evaluar (normalmente el resumen generado).

    Returns:
        Perplejidad como float redondeado a 4 decimales,
        o -1.0 si el texto está vacío, el pipeline no está disponible,
        o si ocurre cualquier error durante el cálculo.
    """
    if not pipeline_resumen or not texto or not texto.strip():
        return -1.0
    try:
        device = pipeline_resumen.model.device
        inputs = pipeline_resumen.tokenizer(
            texto, return_tensors='pt', truncation=True, max_length=512
        )
        input_ids = inputs['input_ids'].to(device)
        with torch.no_grad():
            outputs = pipeline_resumen.model(input_ids=input_ids, labels=input_ids)
        return round(math.exp(outputs.loss.item()), 4)
    except Exception as exc:
        print(f"  ✗ Error al calcular perplejidad: {exc}")
        return -1.0


def generar_resumen_con_metricas(pipeline_resumen,
                                  texto: str,
                                  max_length: int = 300,
                                  min_length: int = 30,
                                  chunk_chars: int = 4000) -> Tuple[str, Dict]:
    """
    Genera un resumen abstractivo con métricas de ejecución usando estrategia map-reduce.

    MAP:    preprocesa y divide el texto en chunks → resumen parcial por chunk.
    REDUCE: si hay múltiples resúmenes → concatenar; si el concatenado supera
            chunk_chars → aplicar un paso adicional de resumen.

    Captura tiempo total, número estimado de chunks, longitudes de entrada y salida,
    y perplejidad del resumen. La perplejidad se calcula sobre el resumen generado
    para medir la calidad lingüística de la salida del modelo.

    Args:
        pipeline_resumen: Pipeline de HuggingFace (None/False → retorna ("", {})).
        texto:            Texto de la norma en español.
        max_length:       Máximo de tokens a generar por fragmento.
        min_length:       Mínimo de tokens generados.
        chunk_chars:      Tamaño máximo de cada chunk en caracteres.

    Returns:
        Tupla (resumen, metricas). metricas contiene modelo, tiempo_segundos,
        num_chunks, longitud_resumen, longitud_texto y perplexidad.
        Retorna ("", {}) si el pipeline no está disponible o el texto es demasiado corto.
    """
    if not pipeline_resumen:
        return "", {}

    inicio = time.time()
    num_chunks = max(1, math.ceil(len(texto) / chunk_chars))

    texto_limpio = preprocesar_para_transformer(texto)
    if not texto_limpio or len(texto_limpio.strip()) < 50:
        return "", {}

    chunks_validos = [
        c for c in (texto_limpio[i:i + chunk_chars]
                    for i in range(0, len(texto_limpio), chunk_chars))
        if len(c.strip()) >= 100
    ]
    if not chunks_validos:
        return "", {}

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
        resumen = ""
    elif len(resumenes) == 1:
        resumen = resumenes[0]
    else:
        combinado = ' '.join(resumenes)
        if len(combinado) <= chunk_chars:
            resumen = combinado
        else:
            print(f"     Reduce final ({len(combinado)} chars)...", end='', flush=True)
            t0 = time.time()
            try:
                resumen = _resumir_fragmento(pipeline_resumen, combinado[:chunk_chars], max_length, min_length)
                print(f" ✓ {time.time() - t0:.1f}s")
            except Exception as exc:
                print(f" ✗ {exc}")
                resumen = combinado

    perplexidad = calcular_perplexidad(pipeline_resumen, resumen)
    tiempo_total = round(time.time() - inicio, 3)

    metricas: Dict = {
        'modelo': pipeline_resumen.model.config.name_or_path,
        'tiempo_segundos': tiempo_total,
        'num_chunks': num_chunks,
        'longitud_resumen': len(resumen),
        'longitud_texto': len(texto),
        'perplexidad': perplexidad,
    }

    return resumen, metricas