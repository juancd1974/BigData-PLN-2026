"""
Pre-descarga y almacena en caché los modelos HuggingFace utilizados por la aplicación.
Ejecutar una vez antes del primer uso: python download_models.py
"""

from transformers import AutoTokenizer, AutoModelForSeq2SeqLM

MODELS = [
    {
        "id": "google/mt5-small",
        "model_class": AutoModelForSeq2SeqLM,
        "description": "Resumen abstractivo (ligero)",
    },
    {
        "id": "google/mt5-base",
        "model_class": AutoModelForSeq2SeqLM,
        "description": "Resumen abstractivo (mayor calidad)",
    },
    {
        "id": "ELiRF/mt5-base-dacsa-es",
        "model_class": AutoModelForSeq2SeqLM,
        "description": "mT5-base fine-tuned resumen español (DACSA)",
    },
]


def download_model(model_id: str, model_class, description: str) -> None:
    print(f"\n{'='*60}")
    print(f"Descargando: {model_id}")
    print(f"Uso: {description}")
    print(f"{'='*60}")
    try:
        print("  → Descargando tokenizer...", flush=True)
        AutoTokenizer.from_pretrained(model_id)
        print("  → Tokenizer descargado.")

        print("  → Descargando modelo (puede tomar varios minutos)...", flush=True)
        model_class.from_pretrained(model_id)
        print(f"  ✓ {model_id} almacenado en caché correctamente.")
    except Exception as e:
        print(f"  ✗ Error al descargar {model_id}: {e}")
        print("    Verifique su conexión a internet y vuelva a intentarlo.")


def main() -> None:
    print("Predescargar modelos HuggingFace — BigData-PLN-2026")
    print(f"Total de modelos: {len(MODELS)}\n")

    exitosos = 0
    for m in MODELS:
        download_model(m["id"], m["model_class"], m["description"])
        exitosos += 1

    print(f"\n{'='*60}")
    print(f"Proceso completado: {exitosos}/{len(MODELS)} modelos en caché.")
    print("Los modelos se guardan en:")
    print("  C:\\Users\\<usuario>\\.cache\\huggingface\\hub\\")
    print("No necesitan descargarse nuevamente en ejecuciones posteriores.")


if __name__ == "__main__":
    main()
