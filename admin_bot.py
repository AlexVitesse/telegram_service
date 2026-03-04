#!/usr/bin/env python3
"""
Bot de Administración (Admin Monitor Bot)
==========================================
Bot de Telegram separado para tareas de administración del sistema:
- Visualizar logs y alertas
- Ejecutar git pull
- Reiniciar/pausar/reanudar el servicio principal

Uso:
    python admin_bot.py
"""
import asyncio
import logging
import os
import signal
import subprocess
import sys
import time

from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# Agregar directorio actual al path para imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config, BASE_DIR

# --- Paths ---
PID_FILE = os.path.join(BASE_DIR, ".service.pid")
PAUSE_FLAG = os.path.join(BASE_DIR, ".pause_flag")
LOG_FILE = os.path.join(BASE_DIR, config.log_file)
PROJECT_DIR = os.path.dirname(BASE_DIR)  # raíz del repo git

# --- Logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("admin_bot")

# --- Admin check ---
ADMIN_CHAT_ID = config.telegram.admin_chat_id


def is_admin(update: Update) -> bool:
    """Verifica que el mensaje viene del admin autorizado."""
    if not ADMIN_CHAT_ID:
        return False
    return str(update.effective_chat.id) == str(ADMIN_CHAT_ID)


# =============================================
# Handlers
# =============================================

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return
    await update.message.reply_text(
        "🛠 *Admin Monitor Bot*\n\n"
        "Comandos disponibles:\n"
        "/logs — Últimas 50 líneas del log\n"
        "/logs\\_full — Archivo .log completo\n"
        "/alerts — Últimos errores/warnings\n"
        "/status — Estado del servicio\n"
        "/pull — Ejecutar git pull\n"
        "/restart — Reiniciar servicio principal\n"
        "/pause — Pausar procesamiento MQTT\n"
        "/resume — Reanudar procesamiento MQTT",
        parse_mode="Markdown",
    )


async def cmd_logs(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Envía las últimas 50 líneas del log como archivo."""
    if not is_admin(update):
        return
    if not os.path.exists(LOG_FILE):
        await update.message.reply_text("No se encontró el archivo de log.")
        return
    try:
        result = subprocess.run(
            ["tail", "-n", "50", LOG_FILE],
            capture_output=True, text=True, timeout=5,
        )
        lines = result.stdout
        if not lines.strip():
            await update.message.reply_text("El log está vacío.")
            return
        # Enviar como archivo de texto
        tmp = os.path.join(BASE_DIR, ".admin_tmp_log.txt")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(lines)
        await update.message.reply_document(
            document=open(tmp, "rb"),
            filename="last_50_lines.log",
            caption="Últimas 50 líneas del log",
        )
        os.remove(tmp)
    except Exception as e:
        await update.message.reply_text(f"Error leyendo log: {e}")


async def cmd_logs_full(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Envía el archivo .log completo."""
    if not is_admin(update):
        return
    if not os.path.exists(LOG_FILE):
        await update.message.reply_text("No se encontró el archivo de log.")
        return
    try:
        size_mb = os.path.getsize(LOG_FILE) / (1024 * 1024)
        if size_mb > 49:
            await update.message.reply_text(
                f"El log pesa {size_mb:.1f} MB, excede el límite de Telegram (50 MB)."
            )
            return
        await update.message.reply_document(
            document=open(LOG_FILE, "rb"),
            filename=os.path.basename(LOG_FILE),
            caption=f"Log completo ({size_mb:.2f} MB)",
        )
    except Exception as e:
        await update.message.reply_text(f"Error enviando log: {e}")


async def cmd_alerts(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Muestra últimos errores/warnings del log."""
    if not is_admin(update):
        return
    if not os.path.exists(LOG_FILE):
        await update.message.reply_text("No se encontró el archivo de log.")
        return
    try:
        result = subprocess.run(
            ["grep", "-E", "(ERROR|WARNING|CRITICAL)", LOG_FILE],
            capture_output=True, text=True, timeout=10,
        )
        lines = result.stdout.strip().split("\n")
        # Tomar las últimas 30 líneas
        recent = lines[-30:] if len(lines) > 30 else lines
        text = "\n".join(recent)
        if not text.strip():
            await update.message.reply_text("No se encontraron errores/warnings recientes.")
            return
        # Truncar a 4000 chars para Telegram
        if len(text) > 4000:
            text = text[-4000:]
        await update.message.reply_text(f"```\n{text}\n```", parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"Error buscando alertas: {e}")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Estado del servicio: PID, uptime, tamaño log, uso RAM."""
    if not is_admin(update):
        return

    lines = []

    # PID y estado del proceso
    pid = _read_pid()
    if pid and _pid_alive(pid):
        lines.append(f"🟢 Servicio ACTIVO  (PID {pid})")
        # Uptime via /proc en Debian
        try:
            stat = os.stat(f"/proc/{pid}")
            uptime_sec = time.time() - stat.st_mtime
            h, rem = divmod(int(uptime_sec), 3600)
            m, s = divmod(rem, 60)
            lines.append(f"⏱ Uptime: {h}h {m}m {s}s")
        except Exception:
            pass
        # RAM via /proc/PID/status
        try:
            with open(f"/proc/{pid}/status") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        ram_kb = int(line.split()[1])
                        lines.append(f"🧠 RAM: {ram_kb // 1024} MB")
                        break
        except Exception:
            pass
    else:
        lines.append("🔴 Servicio NO activo (sin PID o proceso muerto)")

    # Pause flag
    if os.path.exists(PAUSE_FLAG):
        lines.append("⏸ MQTT PAUSADO (flag presente)")
    else:
        lines.append("▶️ MQTT activo")

    # Tamaño log
    if os.path.exists(LOG_FILE):
        size_mb = os.path.getsize(LOG_FILE) / (1024 * 1024)
        lines.append(f"📄 Log: {size_mb:.2f} MB")
    else:
        lines.append("📄 Log: no encontrado")

    await update.message.reply_text("\n".join(lines))


async def cmd_pull(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Ejecuta git pull en el directorio del proyecto."""
    if not is_admin(update):
        return
    await update.message.reply_text("Ejecutando `git pull`...")
    try:
        result = subprocess.run(
            ["git", "pull"],
            cwd=PROJECT_DIR,
            capture_output=True, text=True, timeout=30,
        )
        output = (result.stdout + "\n" + result.stderr).strip()
        if not output:
            output = "(sin salida)"
        if len(output) > 4000:
            output = output[:4000]
        await update.message.reply_text(f"```\n{output}\n```", parse_mode="Markdown")
    except subprocess.TimeoutExpired:
        await update.message.reply_text("Timeout ejecutando git pull (>30s).")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")


async def cmd_restart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Reinicia el servicio principal (kill + relaunch)."""
    if not is_admin(update):
        return

    pid = _read_pid()
    if pid and _pid_alive(pid):
        await update.message.reply_text(f"Matando proceso {pid}...")
        try:
            os.kill(pid, signal.SIGTERM)
            # Esperar a que muera
            for _ in range(10):
                if not _pid_alive(pid):
                    break
                await asyncio.sleep(0.5)
            else:
                os.kill(pid, signal.SIGKILL)
        except Exception as e:
            await update.message.reply_text(f"Error matando proceso: {e}")
            return
    else:
        await update.message.reply_text("No hay proceso activo, iniciando nuevo...")

    # Limpiar pause flag si existe
    if os.path.exists(PAUSE_FLAG):
        os.remove(PAUSE_FLAG)

    # Relanzar
    try:
        main_py = os.path.join(BASE_DIR, "main.py")
        subprocess.Popen(
            [sys.executable, main_py],
            cwd=BASE_DIR,
            stdout=open(os.path.join(BASE_DIR, "restart_stdout.log"), "a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        await asyncio.sleep(2)
        new_pid = _read_pid()
        if new_pid and _pid_alive(new_pid):
            await update.message.reply_text(
                f"🟢 Servicio reiniciado (nuevo PID {new_pid})"
            )
        else:
            await update.message.reply_text(
                "⚠️ Proceso lanzado pero no se detectó PID. Revisa los logs."
            )
    except Exception as e:
        await update.message.reply_text(f"Error relanzando servicio: {e}")


async def cmd_pause(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Pausa el procesamiento MQTT del servicio principal."""
    if not is_admin(update):
        return
    if os.path.exists(PAUSE_FLAG):
        await update.message.reply_text("⏸ Ya estaba pausado.")
        return
    try:
        with open(PAUSE_FLAG, "w") as f:
            f.write(str(time.time()))
        await update.message.reply_text(
            "⏸ Servicio PAUSADO.\n"
            "El procesamiento MQTT se detendrá en segundos.\n"
            "Usa /resume para reanudar."
        )
    except Exception as e:
        await update.message.reply_text(f"Error creando flag: {e}")


async def cmd_resume(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Reanuda el procesamiento MQTT del servicio principal."""
    if not is_admin(update):
        return
    if not os.path.exists(PAUSE_FLAG):
        await update.message.reply_text("▶️ No estaba pausado.")
        return
    try:
        os.remove(PAUSE_FLAG)
        await update.message.reply_text("▶️ Servicio REANUDADO. MQTT se reconectará en segundos.")
    except Exception as e:
        await update.message.reply_text(f"Error eliminando flag: {e}")


# =============================================
# Utilidades
# =============================================

def _read_pid() -> int | None:
    """Lee el PID del servicio principal desde el archivo."""
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def _pid_alive(pid: int) -> bool:
    """Verifica si un proceso sigue vivo."""
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


# =============================================
# Main
# =============================================

def main():
    token = config.telegram.admin_bot_token
    if not token:
        logger.error("ADMIN_BOT_TOKEN no configurado en .env")
        sys.exit(1)
    if not ADMIN_CHAT_ID:
        logger.warning("TELEGRAM_ADMIN_CHAT_ID no configurado — el bot ignorará todos los mensajes")

    logger.info("Iniciando Admin Monitor Bot...")
    logger.info(f"Admin chat ID: {ADMIN_CHAT_ID}")
    logger.info(f"Log file: {LOG_FILE}")
    logger.info(f"Project dir: {PROJECT_DIR}")

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("logs", cmd_logs))
    app.add_handler(CommandHandler("logs_full", cmd_logs_full))
    app.add_handler(CommandHandler("alerts", cmd_alerts))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("pull", cmd_pull))
    app.add_handler(CommandHandler("restart", cmd_restart))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
