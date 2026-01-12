#!/usr/bin/env python3
"""
Backup y Restauración de Firebase Realtime Database
====================================================
Crea backups automáticos y permite restaurar datos.

Uso:
    python backup_firebase.py backup      # Crear backup
    python backup_firebase.py restore     # Restaurar último backup
    python backup_firebase.py restore backup_2026-01-12.json  # Restaurar específico
    python backup_firebase.py list        # Listar backups disponibles

Configurar en cron para backup diario a las 3:00 AM:
    0 3 * * * cd /ruta/telegram_service && /ruta/venv/bin/python backup_firebase.py backup
"""

import json
import sys
import os
from datetime import datetime, timedelta
from pathlib import Path
import logging

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuración
BACKUP_DIR = Path(__file__).parent / "backups"
MAX_BACKUP_DAYS = 3  # Mantener backups de los últimos 3 días
FIREBASE_CREDENTIALS = Path(__file__).parent / "firebase_credentials.json"
DATABASE_URL = "https://sentinel-c028f-default-rtdb.firebaseio.com/"

# Nodos a respaldar (None = todo)
NODES_TO_BACKUP = [
    "ESP32",      # Dispositivos y configuración
    "Usuarios",   # Usuarios registrados
    "Horarios",   # Programaciones automáticas
]


def init_firebase():
    """Inicializa conexión con Firebase"""
    try:
        import firebase_admin
        from firebase_admin import credentials, db

        if not firebase_admin._apps:
            cred = credentials.Certificate(str(FIREBASE_CREDENTIALS))
            firebase_admin.initialize_app(cred, {
                'databaseURL': DATABASE_URL
            })
        return db
    except Exception as e:
        logger.error(f"Error inicializando Firebase: {e}")
        return None


def create_backup() -> str:
    """
    Crea un backup de Firebase.
    Retorna el nombre del archivo creado.
    """
    logger.info("Iniciando backup de Firebase...")

    db = init_firebase()
    if not db:
        logger.error("No se pudo conectar a Firebase")
        return None

    # Crear directorio de backups si no existe
    BACKUP_DIR.mkdir(exist_ok=True)

    # Obtener datos
    backup_data = {
        "metadata": {
            "created_at": datetime.now().isoformat(),
            "nodes": NODES_TO_BACKUP
        },
        "data": {}
    }

    for node in NODES_TO_BACKUP:
        try:
            ref = db.reference(node)
            data = ref.get()
            if data:
                backup_data["data"][node] = data
                logger.info(f"  - {node}: OK ({len(str(data))} bytes)")
            else:
                logger.info(f"  - {node}: vacío")
        except Exception as e:
            logger.error(f"  - {node}: ERROR - {e}")

    # Guardar backup
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    filename = f"backup_{timestamp}.json"
    filepath = BACKUP_DIR / filename

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(backup_data, f, indent=2, ensure_ascii=False)

    file_size = filepath.stat().st_size / 1024  # KB
    logger.info(f"Backup creado: {filename} ({file_size:.1f} KB)")

    # Limpiar backups antiguos
    cleanup_old_backups()

    return filename


def cleanup_old_backups():
    """Elimina backups más antiguos de MAX_BACKUP_DAYS días"""
    if not BACKUP_DIR.exists():
        return

    cutoff_date = datetime.now() - timedelta(days=MAX_BACKUP_DAYS)
    deleted_count = 0

    for backup_file in BACKUP_DIR.glob("backup_*.json"):
        try:
            # Extraer fecha del nombre: backup_2026-01-12_030000.json
            date_str = backup_file.stem.replace("backup_", "")[:10]
            file_date = datetime.strptime(date_str, "%Y-%m-%d")

            if file_date < cutoff_date:
                backup_file.unlink()
                logger.info(f"Backup antiguo eliminado: {backup_file.name}")
                deleted_count += 1
        except (ValueError, OSError) as e:
            logger.warning(f"No se pudo procesar {backup_file.name}: {e}")

    if deleted_count > 0:
        logger.info(f"Se eliminaron {deleted_count} backups antiguos")


def list_backups():
    """Lista todos los backups disponibles"""
    if not BACKUP_DIR.exists():
        print("No hay backups disponibles")
        return []

    backups = sorted(BACKUP_DIR.glob("backup_*.json"), reverse=True)

    if not backups:
        print("No hay backups disponibles")
        return []

    print(f"\nBackups disponibles ({len(backups)}):")
    print("-" * 50)

    for backup_file in backups:
        size = backup_file.stat().st_size / 1024
        mtime = datetime.fromtimestamp(backup_file.stat().st_mtime)

        # Leer metadata
        try:
            with open(backup_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                nodes = data.get("metadata", {}).get("nodes", [])
                nodes_str = ", ".join(nodes) if nodes else "desconocido"
        except:
            nodes_str = "error leyendo"

        print(f"  {backup_file.name}")
        print(f"    Fecha: {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"    Tamaño: {size:.1f} KB")
        print(f"    Nodos: {nodes_str}")
        print()

    return backups


def restore_backup(backup_name: str = None):
    """
    Restaura un backup a Firebase.
    Si no se especifica nombre, usa el más reciente.
    """
    if not BACKUP_DIR.exists():
        logger.error("No existe directorio de backups")
        return False

    # Determinar archivo a restaurar
    if backup_name:
        backup_file = BACKUP_DIR / backup_name
        if not backup_file.exists():
            # Intentar con prefijo backup_
            backup_file = BACKUP_DIR / f"backup_{backup_name}.json"
        if not backup_file.exists():
            logger.error(f"Backup no encontrado: {backup_name}")
            return False
    else:
        # Usar el más reciente
        backups = sorted(BACKUP_DIR.glob("backup_*.json"), reverse=True)
        if not backups:
            logger.error("No hay backups disponibles")
            return False
        backup_file = backups[0]

    logger.info(f"Restaurando desde: {backup_file.name}")

    # Confirmar restauración
    print(f"\n¿Restaurar {backup_file.name}?")
    print("ADVERTENCIA: Esto sobrescribirá los datos actuales en Firebase.")
    response = input("Escribe 'SI' para confirmar: ")

    if response.upper() != "SI":
        print("Restauración cancelada")
        return False

    # Leer backup
    try:
        with open(backup_file, 'r', encoding='utf-8') as f:
            backup_data = json.load(f)
    except Exception as e:
        logger.error(f"Error leyendo backup: {e}")
        return False

    # Conectar a Firebase
    db = init_firebase()
    if not db:
        logger.error("No se pudo conectar a Firebase")
        return False

    # Restaurar cada nodo
    data = backup_data.get("data", {})
    for node, node_data in data.items():
        try:
            ref = db.reference(node)
            ref.set(node_data)
            logger.info(f"  - {node}: restaurado")
        except Exception as e:
            logger.error(f"  - {node}: ERROR - {e}")
            return False

    logger.info("Restauración completada exitosamente")
    return True


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return

    command = sys.argv[1].lower()

    if command == "backup":
        create_backup()

    elif command == "list":
        list_backups()

    elif command == "restore":
        backup_name = sys.argv[2] if len(sys.argv) > 2 else None
        restore_backup(backup_name)

    elif command == "cleanup":
        cleanup_old_backups()

    else:
        print(f"Comando no reconocido: {command}")
        print("Usa: backup, list, restore, cleanup")


if __name__ == "__main__":
    main()
