"""
Bootstrap de inicializacion para el proyecto.

Ejecuta en orden:
1) Inicializacion de MongoDB (usuario admin)
2) Inicializacion de Elasticsearch (indice principal)

Uso:
    python init_all.py

Opcional (recrear indice de Elasticsearch):
    python init_all.py --recreate-elastic
"""

import argparse
import subprocess
import sys


def run_step(title: str, command: list[str]) -> None:
    print(f"\n[init_all] {title}")
    print(f"[init_all] Ejecutando: {' '.join(command)}")

    completed = subprocess.run(command)
    if completed.returncode != 0:
        print(f"[init_all] ERROR: Fallo en paso '{title}' con codigo {completed.returncode}")
        sys.exit(completed.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inicializa MongoDB y Elasticsearch")
    parser.add_argument(
        "--recreate-elastic",
        action="store_true",
        help="Elimina y vuelve a crear el indice de Elasticsearch",
    )
    args = parser.parse_args()

    python_exec = sys.executable

    run_step(
        "Inicializando MongoDB (init_db.py)",
        [python_exec, "init_db.py"],
    )

    elastic_cmd = [python_exec, "init_elastic.py"]
    if args.recreate_elastic:
        elastic_cmd.append("--recreate")

    run_step(
        "Inicializando Elasticsearch (init_elastic.py)",
        elastic_cmd,
    )

    print("\n[init_all] Proceso completado correctamente.")


if __name__ == "__main__":
    main()
