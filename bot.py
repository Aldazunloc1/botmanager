import json
import os
import logging
import asyncio
import re
from datetime import datetime
from typing import Dict, Optional, List
from urllib.parse import urlparse
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler, 
    ContextTypes, filters, CallbackQueryHandler, ConversationHandler
)
from telegram.error import TelegramError

# ═══════════════════════════════════════════════════════════════════
# 🔧 CONFIGURACIÓN
# ═══════════════════════════════════════════════════════════════════

class Config:
    """Configuración centralizada del bot"""
    DB_FILE = "archivos.json"
    REQUESTS_FILE = "solicitudes.json"
    LOG_FILE = "bot.log"
    TOKEN = os.getenv("TELEGRAM_TOKEN", "7988514338:AAGoHUn20VNko6sAC15xeBxBaTqLav4msR8")
    ADMIN_ID = int(os.getenv("ADMIN_ID", "7655366089"))
    CANAL_ID = int(os.getenv("CANAL_ID", "-1001518541809"))
    MAX_MESSAGE_LENGTH = 4000
    MAX_SEARCH_RESULTS = 10
    MAX_REQUEST_LENGTH = 500
    REQUEST_STATES = {
        'PENDIENTE': '⏳',
        'PROCESANDO': '🔄',
        'COMPLETADO': '✅',
        'RECHAZADO': '❌'
    }

# Estados para el ConversationHandler de publicaciones
POST_TEXT, POST_MEDIA = range(2)

# ═══════════════════════════════════════════════════════════════════
# 📝 CONFIGURACIÓN DE LOGGING
# ═══════════════════════════════════════════════════════════════════

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO,
    handlers=[
        logging.FileHandler(Config.LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════
# 🗄️ GESTOR DE BASE DE DATOS
# ═══════════════════════════════════════════════════════════════════

class DatabaseManager:
    """Manejo de la base de datos JSON para archivos y solicitudes"""
    
    @staticmethod
    def cargar_db() -> Dict:
        """Carga la base de datos desde el archivo JSON"""
        try:
            if os.path.exists(Config.DB_FILE):
                with open(Config.DB_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    data = DatabaseManager.migrar_datos(data)
                    return data
        except json.JSONDecodeError as e:
            logger.error(f"❌ Error al cargar DB: {e}")
        except Exception as e:
            logger.error(f"❌ Error inesperado al cargar DB: {e}")
        
        return {
            'archivos': {},
            'estadisticas': {'total_busquedas': 0, 'archivos_agregados': 0},
            'version': '1.3'
        }

    @staticmethod
    def cargar_solicitudes() -> Dict:
        """Carga las solicitudes desde el archivo JSON"""
        try:
            if os.path.exists(Config.REQUESTS_FILE):
                with open(Config.REQUESTS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
        except json.JSONDecodeError as e:
            logger.error(f"❌ Error al cargar solicitudes: {e}")
        except Exception as e:
            logger.error(f"❌ Error inesperado al cargar solicitudes: {e}")
        
        return {
            'solicitudes': {},
            'contador_solicitudes': 0,
            'estadisticas': {
                'total_solicitudes': 0,
                'solicitudes_completadas': 0,
                'solicitudes_pendientes': 0
            }
        }

    @staticmethod
    def migrar_datos(data: Dict) -> Dict:
        """Migra y limpia datos con formato incorrecto"""
        if isinstance(data, dict) and 'archivos' not in data:
            data = {
                'archivos': data,
                'estadisticas': {'total_busquedas': 0, 'archivos_agregados': len(data)},
                'version': '1.3'
            }
        
        # Limpiar URLs incorrectas de Telegram API
        archivos_limpios = {}
        for clave, info in data.get('archivos', {}).items():
            if isinstance(info, dict):
                enlace = info.get('enlace', '')
                if 'api.telegram.org/file/bot' in enlace and not enlace.startswith('file_id:'):
                    logger.warning(f"⚠️ URL incorrecta detectada para {clave}")
                    info['enlace'] = 'ENLACE_INVALIDO_MIGRAR'
                    info['enlace_original'] = enlace
                    info['requiere_migracion'] = True
                archivos_limpios[clave] = info
            else:
                archivos_limpios[clave] = info
        
        data['archivos'] = archivos_limpios
        data['version'] = '1.3'
        return data

    @staticmethod
    def guardar_db(data: Dict) -> bool:
        """Guarda la base de datos en el archivo JSON"""
        return DatabaseManager._guardar_archivo(Config.DB_FILE, data, "base de datos")

    @staticmethod
    def guardar_solicitudes(data: Dict) -> bool:
        """Guarda las solicitudes en el archivo JSON"""
        return DatabaseManager._guardar_archivo(Config.REQUESTS_FILE, data, "solicitudes")

    @staticmethod
    def _guardar_archivo(filename: str, data: Dict, tipo: str) -> bool:
        """Método interno para guardar archivos JSON con backup"""
        try:
            # Crear backup antes de guardar
            if os.path.exists(filename):
                backup_name = f"{filename}.backup"
                if os.path.exists(backup_name):
                    os.remove(backup_name)
                os.rename(filename, backup_name)
            
            with open(filename, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"✅ {tipo.capitalize()} guardada exitosamente")
            return True
        except Exception as e:
            logger.error(f"❌ Error al guardar {tipo}: {e}")
            # Restaurar backup si existe
            backup_name = f"{filename}.backup"
            if os.path.exists(backup_name):
                try:
                    os.rename(backup_name, filename)
                    logger.info(f"🔄 Backup de {tipo} restaurado")
                except:
                    pass
            return False

    @staticmethod
    def buscar_archivos(query: str, archivos: Dict) -> List[tuple]:
        """Busca archivos que coincidan con la consulta"""
        resultados = []
        query_lower = query.lower().strip()
        
        if not query_lower:
            return resultados
        
        for palabra, enlace in archivos.items():
            palabra_lower = palabra.lower()
            if query_lower == palabra_lower:
                resultados.insert(0, (palabra, enlace, 100))
            elif query_lower in palabra_lower:
                relevancia = min((len(query_lower) / len(palabra)) * 100, 99)
                resultados.append((palabra, enlace, relevancia))
        
        resultados.sort(key=lambda x: x[2], reverse=True)
        return resultados[:Config.MAX_SEARCH_RESULTS]

# ═══════════════════════════════════════════════════════════════════
# 🤖 CLASE PRINCIPAL DEL BOT
# ═══════════════════════════════════════════════════════════════════

class TelegramBot:
    """Bot principal de gestión de archivos con sistema de solicitudes"""
    
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.db = self.db_manager.cargar_db()
        self.solicitudes_db = self.db_manager.cargar_solicitudes()
        self.reportar_archivos_invalidos()

    def reportar_archivos_invalidos(self):
        """Reporta archivos con enlaces inválidos"""
        archivos_invalidos = [
            clave for clave, info in self.db['archivos'].items()
            if isinstance(info, dict) and info.get('enlace') == 'ENLACE_INVALIDO_MIGRAR'
        ]
        
        if archivos_invalidos:
            logger.warning(f"⚠️ {len(archivos_invalidos)} archivos necesitan reenvío:")
            for archivo in archivos_invalidos[:5]:  # Mostrar solo los primeros 5
                logger.warning(f"  📁 {archivo}")

    def es_admin(self, user_id: int) -> bool:
        """Verifica si el usuario es administrador"""
        return user_id == Config.ADMIN_ID

    def validar_url(self, url: str) -> bool:
        """Valida si una URL tiene formato correcto"""
        try:
            resultado = urlparse(url)
            return all([resultado.scheme, resultado.netloc])
        except:
            return False

    # ═══════════════════════════════════════════════════════════════
    # 📢 SISTEMA DE PUBLICACIONES PARA ADMIN
    # ═══════════════════════════════════════════════════════════════

    async def post_to_channel_start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Inicia el proceso de crear una publicación en el canal (admin)"""
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
            return ConversationHandler.END

        keyboard = [
            [InlineKeyboardButton("📝 Solo texto", callback_data="post_text_only")],
            [InlineKeyboardButton("📷 Con imagen/documento", callback_data="post_with_media")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="post_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.message.reply_text(
            "📢 *Crear publicación para el canal*\n\n"
            "🎯 *Opciones disponibles:*\n"
            "📝 Solo texto\n"
            "📷 Con imagen, video o documento\n\n"
            "💡 Elige el tipo de publicación:",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )
        
        return POST_TEXT

    async def post_button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja los botones del sistema de publicaciones"""
        query = update.callback_query
        await query.answer()

        if query.data == "post_text_only":
            await query.edit_message_text(
                "📝 *Escribir publicación de solo texto*\n\n"
                "✏️ Envía el texto que quieres publicar en el canal.\n"
                "📝 Puedes usar formato Markdown:\n"
                "• *texto en negrita*\n"
                "• _texto en cursiva_\n"
                "• `código`\n"
                "• [enlace](URL)\n\n"
                "💡 Envía /cancel para cancelar",
                parse_mode="Markdown"
            )
            context.user_data['post_type'] = 'text_only'
            return POST_TEXT
            
        elif query.data == "post_with_media":
            await query.edit_message_text(
                "📷 *Publicación con multimedia*\n\n"
                "📤 Primero envía el archivo (imagen, video, documento)\n"
                "📝 Después podrás agregar texto descriptivo\n\n"
                "📋 *Formatos soportados:*\n"
                "• 🖼️ Imágenes (JPG, PNG, GIF)\n"
                "• 🎥 Videos (MP4, AVI, MOV)\n"
                "• 📄 Documentos (PDF, DOC, ZIP, etc.)\n\n"
                "💡 Envía /cancel para cancelar",
                parse_mode="Markdown"
            )
            context.user_data['post_type'] = 'with_media'
            return POST_MEDIA
            
        elif query.data == "post_cancel":
            await query.edit_message_text("❌ Publicación cancelada.")
            return ConversationHandler.END

        return POST_TEXT

    async def handle_post_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja el texto de la publicación"""
        if update.message.text == "/cancel":
            await update.message.reply_text("❌ Publicación cancelada.")
            return ConversationHandler.END

        texto = update.message.text
        post_type = context.user_data.get('post_type', 'text_only')

        if post_type == 'text_only':
            # Publicar solo texto
            await self.confirmar_publicacion(update, context, texto=texto)
            return ConversationHandler.END
        else:
            # Guardar texto para publicación con multimedia
            context.user_data['post_caption'] = texto
            await update.message.reply_text(
                "✅ *Texto guardado*\n\n"
                "📤 Ahora envía el archivo (imagen, video o documento)\n"
                "💡 Envía /cancel para cancelar"
            )
            return POST_MEDIA

    async def handle_post_media(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja los archivos multimedia para la publicación"""
        if update.message.text == "/cancel":
            await update.message.reply_text("❌ Publicación cancelada.")
            return ConversationHandler.END

        # Verificar tipo de archivo
        file_info = None
        file_type = None
        
        if update.message.photo:
            file_info = update.message.photo[-1]  # La imagen de mayor resolución
            file_type = 'photo'
        elif update.message.video:
            file_info = update.message.video
            file_type = 'video'
        elif update.message.document:
            file_info = update.message.document
            file_type = 'document'
        elif update.message.animation:
            file_info = update.message.animation
            file_type = 'animation'
        else:
            await update.message.reply_text(
                "❌ *Tipo de archivo no soportado*\n\n"
                "📋 Envía uno de estos formatos:\n"
                "• 🖼️ Imagen\n"
                "• 🎥 Video\n"
                "• 📄 Documento\n"
                "• 🎞️ GIF/Animación"
            )
            return POST_MEDIA

        # Guardar información del archivo
        context.user_data['file_id'] = file_info.file_id
        context.user_data['file_type'] = file_type
        context.user_data['file_name'] = getattr(file_info, 'file_name', f'{file_type}.file')

        caption = context.user_data.get('post_caption', '')
        
        await self.confirmar_publicacion(
            update, 
            context, 
            texto=caption, 
            file_id=file_info.file_id, 
            file_type=file_type,
            file_name=context.user_data['file_name']
        )
        
        return ConversationHandler.END

    async def confirmar_publicacion(self, update: Update, context: ContextTypes.DEFAULT_TYPE, 
                                  texto: str = None, file_id: str = None, file_type: str = None, 
                                  file_name: str = None):
        """Confirma y publica el contenido en el canal"""
        try:
            # Preparar el mensaje de confirmación
            if file_id:
                tipo_emoji = {
                    'photo': '🖼️',
                    'video': '🎥', 
                    'document': '📄',
                    'animation': '🎞️'
                }.get(file_type, '📎')
                
                confirmacion = (
                    f"✅ *Publicación lista para enviar*\n\n"
                    f"{tipo_emoji} *Archivo:* {file_name}\n"
                )
                
                if texto:
                    confirmacion += f"📝 *Texto:*\n{texto[:200]}{'...' if len(texto) > 200 else ''}\n\n"
                
                # Publicar en el canal
                if file_type == 'photo':
                    await context.bot.send_photo(
                        chat_id=Config.CANAL_ID,
                        photo=file_id,
                        caption=texto,
                        parse_mode="Markdown"
                    )
                elif file_type == 'video':
                    await context.bot.send_video(
                        chat_id=Config.CANAL_ID,
                        video=file_id,
                        caption=texto,
                        parse_mode="Markdown"
                    )
                elif file_type == 'animation':
                    await context.bot.send_animation(
                        chat_id=Config.CANAL_ID,
                        animation=file_id,
                        caption=texto,
                        parse_mode="Markdown"
                    )
                else:  # document
                    await context.bot.send_document(
                        chat_id=Config.CANAL_ID,
                        document=file_id,
                        caption=texto,
                        parse_mode="Markdown"
                    )
            else:
                # Solo texto
                confirmacion = (
                    f"✅ *Publicación de texto lista*\n\n"
                    f"📝 *Contenido:*\n{texto[:300]}{'...' if len(texto) > 300 else ''}\n\n"
                )
                
                await context.bot.send_message(
                    chat_id=Config.CANAL_ID,
                    text=texto,
                    parse_mode="Markdown"
                )

            confirmacion += (
                f"📺 *Canal:* `{Config.CANAL_ID}`\n"
                f"📅 *Enviado:* {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
                f"🎉 ¡Publicación enviada exitosamente!"
            )

            await update.message.reply_text(confirmacion, parse_mode="Markdown")
            logger.info(f"📢 Publicación enviada al canal por admin {update.effective_user.id}")

        except TelegramError as e:
            error_msg = f"❌ Error al enviar publicación: {str(e)}"
            logger.error(f"❌ Error al publicar en canal: {e}")
            await update.message.reply_text(error_msg)
        except Exception as e:
            error_msg = f"❌ Error inesperado: {str(e)}"
            logger.error(f"❌ Error inesperado en publicación: {e}")
            await update.message.reply_text(error_msg)

    async def cancel_post(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Cancela el proceso de publicación"""
        await update.message.reply_text("❌ Publicación cancelada.")
        return ConversationHandler.END

    # ═══════════════════════════════════════════════════════════════
    # 📨 SISTEMA DE SOLICITUDES DE ARCHIVOS
    # ═══════════════════════════════════════════════════════════════

    async def request_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /request para solicitar archivos"""
        user_id = update.effective_user.id
        user_name = update.effective_user.first_name or "Usuario"
        
        if not context.args:
            await update.message.reply_text(
                "📋 *Cómo solicitar archivos:*\n\n"
                "🔗 *Con enlace:*\n"
                "`/request https://ejemplo.com/archivo.zip`\n\n"
                "📝 *Con descripción:*\n"
                "`/request Necesito la ROM de Xiaomi Mi 11`\n\n"
                "💡 *Ejemplos:*\n"
                "• `/request https://drive.google.com/file/d/...`\n"
                "• `/request ROM global MIUI 14 para Redmi Note 12`\n"
                "• `/request Firmware Samsung Galaxy S23`\n\n"
                "⏱️ Las solicitudes son revisadas por los administradores",
                parse_mode="Markdown"
            )
            return

        contenido = " ".join(context.args).strip()
        
        if len(contenido) > Config.MAX_REQUEST_LENGTH:
            await update.message.reply_text(
                f"❌ La solicitud es muy larga. Máximo {Config.MAX_REQUEST_LENGTH} caracteres.\n"
                f"📊 Actual: {len(contenido)} caracteres"
            )
            return

        # Generar ID único para la solicitud
        self.solicitudes_db['contador_solicitudes'] += 1
        solicitud_id = f"REQ_{self.solicitudes_db['contador_solicitudes']:04d}"
        
        # Determinar tipo de solicitud
        es_enlace = self.validar_url(contenido)
        tipo_solicitud = "ENLACE" if es_enlace else "DESCRIPCION"
        
        # Crear solicitud
        nueva_solicitud = {
            'id': solicitud_id,
            'usuario_id': user_id,
            'usuario_nombre': user_name,
            'contenido': contenido,
            'tipo': tipo_solicitud,
            'estado': 'PENDIENTE',
            'fecha_creacion': datetime.now().isoformat(),
            'fecha_actualizacion': datetime.now().isoformat(),
            'respuesta_admin': None,
            'archivo_respuesta': None
        }
        
        # Guardar solicitud
        self.solicitudes_db['solicitudes'][solicitud_id] = nueva_solicitud
        self.solicitudes_db['estadisticas']['total_solicitudes'] += 1
        self.solicitudes_db['estadisticas']['solicitudes_pendientes'] += 1
        
        if self.db_manager.guardar_solicitudes(self.solicitudes_db):
            # Mensaje de confirmación para el usuario
            icono_tipo = "🔗" if es_enlace else "📝"
            await update.message.reply_text(
                f"✅ *Solicitud enviada exitosamente*\n\n"
                f"🆔 *ID:* `{solicitud_id}`\n"
                f"{icono_tipo} *Tipo:* {tipo_solicitud.capitalize()}\n"
                f"⏳ *Estado:* Pendiente\n"
                f"📅 *Fecha:* {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
                f"💬 *Contenido:*\n{contenido[:200]}{'...' if len(contenido) > 200 else ''}\n\n"
                f"🔔 Recibirás una notificación cuando sea procesada.\n"
                f"📊 Usa `/mystatus` para ver tus solicitudes.",
                parse_mode="Markdown"
            )
            
            # Notificar al admin
            try:
                await self.notificar_admin_nueva_solicitud(context, nueva_solicitud)
            except Exception as e:
                logger.error(f"❌ Error al notificar admin: {e}")
                
        else:
            await update.message.reply_text("❌ Error al procesar la solicitud. Inténtalo de nuevo.")

    async def notificar_admin_nueva_solicitud(self, context: ContextTypes.DEFAULT_TYPE, solicitud: Dict):
        """Notifica al admin sobre nueva solicitud"""
        icono_tipo = "🔗" if solicitud['tipo'] == "ENLACE" else "📝"
        
        keyboard = [
            [
                InlineKeyboardButton("✅ Aprobar", callback_data=f"aprobar_{solicitud['id']}"),
                InlineKeyboardButton("❌ Rechazar", callback_data=f"rechazar_{solicitud['id']}")
            ],
            [InlineKeyboardButton("📋 Ver todas", callback_data="admin_requests")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        mensaje = (
            f"🔔 *Nueva Solicitud de Archivo*\n\n"
            f"🆔 *ID:* `{solicitud['id']}`\n"
            f"👤 *Usuario:* {solicitud['usuario_nombre']} (`{solicitud['usuario_id']}`)\n"
            f"{icono_tipo} *Tipo:* {solicitud['tipo']}\n"
            f"📅 *Fecha:* {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
            f"💬 *Contenido:*\n`{solicitud['contenido']}`"
        )
        
        await context.bot.send_message(
            chat_id=Config.ADMIN_ID,
            text=mensaje,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

    async def my_requests_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /mystatus - Ver estado de solicitudes del usuario"""
        user_id = update.effective_user.id
        
        # Filtrar solicitudes del usuario
        mis_solicitudes = [
            sol for sol in self.solicitudes_db['solicitudes'].values()
            if sol['usuario_id'] == user_id
        ]
        
        if not mis_solicitudes:
            await update.message.reply_text(
                "📭 *No tienes solicitudes registradas*\n\n"
                "💡 Usa `/request <enlace o descripción>` para solicitar archivos.",
                parse_mode="Markdown"
            )
            return
        
        # Ordenar por fecha (más recientes primero)
        mis_solicitudes.sort(key=lambda x: x['fecha_creacion'], reverse=True)
        
        mensaje = f"📊 *Mis Solicitudes ({len(mis_solicitudes)}):*\n\n"
        
        for i, solicitud in enumerate(mis_solicitudes[:10], 1):  # Mostrar máximo 10
            estado_icono = Config.REQUEST_STATES.get(solicitud['estado'], '❓')
            tipo_icono = "🔗" if solicitud['tipo'] == "ENLACE" else "📝"
            fecha = datetime.fromisoformat(solicitud['fecha_creacion']).strftime('%d/%m/%Y')
            
            mensaje += f"{estado_icono} *{i}. {solicitud['id']}*\n"
            mensaje += f"{tipo_icono} {solicitud['tipo']} • 📅 {fecha}\n"
            mensaje += f"💬 {solicitud['contenido'][:80]}{'...' if len(solicitud['contenido']) > 80 else ''}\n"
            
            if solicitud.get('respuesta_admin'):
                mensaje += f"👨‍💼 *Admin:* {solicitud['respuesta_admin'][:60]}{'...' if len(solicitud['respuesta_admin']) > 60 else ''}\n"
            
            mensaje += "────────────────────\n"
        
        if len(mis_solicitudes) > 10:
            mensaje += f"\n... y {len(mis_solicitudes) - 10} solicitudes más\n"
        
        mensaje += (
            f"\n📊 *Resumen:*\n"
            f"⏳ Pendientes: {sum(1 for s in mis_solicitudes if s['estado'] == 'PENDIENTE')}\n"
            f"✅ Completadas: {sum(1 for s in mis_solicitudes if s['estado'] == 'COMPLETADO')}\n"
            f"❌ Rechazadas: {sum(1 for s in mis_solicitudes if s['estado'] == 'RECHAZADO')}"
        )
        
        await self.enviar_mensaje_largo(update, mensaje, "Markdown", context)

    # ═══════════════════════════════════════════════════════════════
    # 👨‍💼 COMANDOS DE ADMINISTRADOR PARA SOLICITUDES
    # ═══════════════════════════════════════════════════════════════

    async def admin_requests(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /adminrequests - Ver todas las solicitudes (admin)"""
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
            return

        todas_solicitudes = list(self.solicitudes_db['solicitudes'].values())
        
        if not todas_solicitudes:
            await update.message.reply_text("📭 No hay solicitudes registradas.")
            return

        # Filtros por estado si se especifica
        if context.args and context.args[0].upper() in ['PENDIENTE', 'COMPLETADO', 'RECHAZADO']:
            estado_filtro = context.args[0].upper()
            todas_solicitudes = [s for s in todas_solicitudes if s['estado'] == estado_filtro]
            titulo_extra = f" - {estado_filtro}S"
        else:
            titulo_extra = ""

        # Ordenar por fecha (más recientes primero)
        todas_solicitudes.sort(key=lambda x: x['fecha_creacion'], reverse=True)
        
        mensaje = f"📋 *Todas las Solicitudes{titulo_extra} ({len(todas_solicitudes)}):*\n\n"
        
        for i, solicitud in enumerate(todas_solicitudes[:15], 1):  # Mostrar máximo 15
            estado_icono = Config.REQUEST_STATES.get(solicitud['estado'], '❓')
            tipo_icono = "🔗" if solicitud['tipo'] == "ENLACE" else "📝"
            fecha = datetime.fromisoformat(solicitud['fecha_creacion']).strftime('%d/%m')
            
            mensaje += f"{estado_icono} *{solicitud['id']}* • {tipo_icono} • 📅 {fecha}\n"
            mensaje += f"👤 {solicitud['usuario_nombre']} (`{solicitud['usuario_id']}`)\n"
            mensaje += f"💬 {solicitud['contenido'][:70]}{'...' if len(solicitud['contenido']) > 70 else ''}\n"
            mensaje += "────────────────────\n"
        
        if len(todas_solicitudes) > 15:
            mensaje += f"\n... y {len(todas_solicitudes) - 15} solicitudes más\n"
        
        stats = self.solicitudes_db['estadisticas']
        mensaje += (
            f"\n📊 *Estadísticas:*\n"
            f"📊 Total: {stats['total_solicitudes']}\n"
            f"⏳ Pendientes: {stats['solicitudes_pendientes']}\n"
            f"✅ Completadas: {stats['solicitudes_completadas']}\n\n"
            f"💡 Usa `/adminrequests PENDIENTE` para filtrar"
        )
        
        await self.enviar_mensaje_largo(update, mensaje, "Markdown", context)

    async def respond_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /respond - Responder a una solicitud (admin)"""
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
            return

        if len(context.args) < 2:
            await update.message.reply_text(
                "📝 *Uso del comando de respuesta:*\n\n"
                "`/respond <ID_SOLICITUD> <respuesta>`\n\n"
                "*Ejemplos:*\n"
                "• `/respond REQ_0001 Archivo subido al canal`\n"
                "• `/respond REQ_0002 No disponible actualmente`\n"
                "• `/respond REQ_0003 Enlace roto, proporciona otro`\n\n"
                "💡 Usa `/adminrequests` para ver todas las solicitudes",
                parse_mode="Markdown"
            )
            return

        solicitud_id = context.args[0]
        respuesta = " ".join(context.args[1:])

        if solicitud_id not in self.solicitudes_db['solicitudes']:
            await update.message.reply_text(f"❌ No se encontró la solicitud `{solicitud_id}`.")
            return

        solicitud = self.solicitudes_db['solicitudes'][solicitud_id]
        
        # Actualizar solicitud
        solicitud['respuesta_admin'] = respuesta
        solicitud['estado'] = 'COMPLETADO'
        solicitud['fecha_actualizacion'] = datetime.now().isoformat()
        
        # Actualizar estadísticas
        if solicitud['estado'] != 'COMPLETADO':  # Solo si no estaba completada antes
            self.solicitudes_db['estadisticas']['solicitudes_completadas'] += 1
            if solicitud['estado'] == 'PENDIENTE':
                self.solicitudes_db['estadisticas']['solicitudes_pendientes'] -= 1

        if self.db_manager.guardar_solicitudes(self.solicitudes_db):
            # Confirmar al admin
            await update.message.reply_text(
                f"✅ *Respuesta enviada exitosamente*\n\n"
                f"🆔 *Solicitud:* `{solicitud_id}`\n"
                f"👤 *Usuario:* {solicitud['usuario_nombre']}\n"
                f"📝 *Tu respuesta:* {respuesta}",
                parse_mode="Markdown"
            )
            
            # Notificar al usuario
            try:
                await context.bot.send_message(
                    chat_id=solicitud['usuario_id'],
                    text=(
                        f"📬 *Respuesta a tu solicitud*\n\n"
                        f"🆔 *ID:* `{solicitud_id}`\n"
                        f"✅ *Estado:* Completado\n"
                        f"💬 *Tu solicitud:* {solicitud['contenido'][:100]}{'...' if len(solicitud['contenido']) > 100 else ''}\n\n"
                        f"👨‍💼 *Respuesta del administrador:*\n{respuesta}\n\n"
                        f"📊 Usa `/mystatus` para ver todas tus solicitudes"
                    ),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"❌ Error al notificar usuario: {e}")
                await update.message.reply_text(f"⚠️ Respuesta guardada, pero no se pudo notificar al usuario.")
        else:
            await update.message.reply_text("❌ Error al guardar la respuesta.")

    # ═══════════════════════════════════════════════════════════════
    # 🔧 MÉTODOS AUXILIARES
    # ═══════════════════════════════════════════════════════════════

    async def obtener_enlace_descarga(self, file_id: str, context: ContextTypes.DEFAULT_TYPE) -> Optional[str]:
        """Obtiene el enlace de descarga real de un file_id de Telegram"""
        try:
            file = await context.bot.get_file(file_id)
            return file.file_path
        except Exception as e:
            logger.error(f"❌ Error al obtener enlace de descarga para file_id {file_id}: {e}")
            return None

    async def enviar_mensaje_largo(self, update: Update, mensaje: str, parse_mode: str = None, context: ContextTypes.DEFAULT_TYPE = None):
        """Envía mensajes largos dividiéndolos si es necesario"""
        try:
            if len(mensaje) <= Config.MAX_MESSAGE_LENGTH:
                if hasattr(update, 'callback_query') and update.callback_query:
                    await update.callback_query.edit_message_text(mensaje, parse_mode=parse_mode)
                else:
                    await update.message.reply_text(mensaje, parse_mode=parse_mode)
            else:
                lines = mensaje.split('\n')
                current_chunk = ""
                chunks = []
                
                for line in lines:
                    if len(current_chunk + line + '\n') <= Config.MAX_MESSAGE_LENGTH:
                        current_chunk += line + '\n'
                    else:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        current_chunk = line + '\n'
                
                if current_chunk:
                    chunks.append(current_chunk.strip())
                
                for i, chunk in enumerate(chunks):
                    if i == 0:
                        if hasattr(update, 'callback_query') and update.callback_query:
                            await update.callback_query.edit_message_text(chunk, parse_mode=parse_mode)
                        else:
                            await update.message.reply_text(chunk, parse_mode=parse_mode)
                    else:
                        if context:
                            await context.bot.send_message(
                                chat_id=update.effective_chat.id,
                                text=chunk,
                                parse_mode=parse_mode
                            )
                        else:
                            await update.message.reply_text(chunk, parse_mode=parse_mode)
                    
                    if i < len(chunks) - 1:
                        await asyncio.sleep(0.5)
                        
        except Exception as e:
            logger.error(f"❌ Error al enviar mensaje largo: {e}")
            error_msg = "❌ Error al enviar el mensaje. Inténtalo de nuevo."
            try:
                if hasattr(update, 'callback_query') and update.callback_query:
                    await update.callback_query.edit_message_text(error_msg)
                else:
                    await update.message.reply_text(error_msg)
            except:
                pass

    async def publicar_en_canal(self, context: ContextTypes.DEFAULT_TYPE, texto: str = None, file_id: str = None):
        """Publica contenido en el canal configurado"""
        try:
            if file_id:
                await context.bot.send_document(
                    chat_id=Config.CANAL_ID, 
                    document=file_id,
                    caption=texto,
                    parse_mode="Markdown"
                )
            else:
                await context.bot.send_message(
                    chat_id=Config.CANAL_ID,
                    text=texto,
                    parse_mode="Markdown"
                )
            logger.info("✅ Mensaje enviado al canal exitosamente")
        except TelegramError as e:
            logger.error(f"❌ Error al enviar mensaje al canal: {e}")
            raise

    # ═══════════════════════════════════════════════════════════════
    # 🚀 COMANDOS PRINCIPALES
    # ═══════════════════════════════════════════════════════════════

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /start mejorado"""
        user_info = f"Usuario: {update.effective_user.first_name} (ID: {update.effective_user.id})"
        logger.info(f"🚀 Comando /start ejecutado por {user_info}")
        
        keyboard = []
        
        # Botones para usuarios regulares
        keyboard.extend([
            [InlineKeyboardButton("🔍 Mis solicitudes", callback_data="my_requests")],
            [InlineKeyboardButton("📚 Ver estadísticas", callback_data="stats")],
            [InlineKeyboardButton("ℹ️ Ayuda", callback_data="help")]
        ])
        
        # Botones adicionales para admin
        if self.es_admin(update.effective_user.id):
            keyboard.insert(0, [InlineKeyboardButton("📋 Lista de archivos", callback_data="list")])
            keyboard.insert(1, [InlineKeyboardButton("📥 Solicitudes pendientes", callback_data="admin_requests")])
            keyboard.insert(2, [InlineKeyboardButton("📢 Crear publicación", callback_data="create_post")])
            keyboard.insert(3, [InlineKeyboardButton("🔧 Ver archivos inválidos", callback_data="invalid")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Estadísticas rápidas
        total_archivos = len(self.db['archivos'])
        total_solicitudes = self.solicitudes_db['estadisticas']['total_solicitudes']
        solicitudes_pendientes = self.solicitudes_db['estadisticas']['solicitudes_pendientes']
        
        mensaje = (
            "🤖 *Bot de Gestión de Archivos v1.3*\n\n"
            "🔍 *Buscar archivos:* `/search <palabra>`\n"
            "📥 *Solicitar archivo:* `/request <enlace o descripción>`\n"
            "📊 *Mis solicitudes:* `/mystatus`\n"
            "📁 *Enviar archivo:* Arrastra y suelta\n"
        )
        
        # Comandos adicionales para admin
        if self.es_admin(update.effective_user.id):
            mensaje += "📢 *Crear publicación:* `/post`\n"
        
        mensaje += (
            f"\n👥 *Rol:* {'Administrador' if self.es_admin(update.effective_user.id) else 'Usuario'}\n"
            f"📁 *Archivos almacenados:* {total_archivos}\n"
            f"📋 *Total solicitudes:* {total_solicitudes}\n"
        )
        
        if self.es_admin(update.effective_user.id) and solicitudes_pendientes > 0:
            mensaje += f"🔔 *Solicitudes pendientes:* {solicitudes_pendientes}\n"
        
        mensaje += "\n💡 Usa los botones para navegar"
        
        await update.message.reply_text(
            mensaje,
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

    async def search(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /search mejorado para buscar archivos"""
        if not context.args:
            await update.message.reply_text(
                "🔍 *Cómo buscar archivos:*\n\n"
                "`/search <palabra_clave>`\n\n"
                "*Ejemplos:*\n"
                "• `/search honor`\n"
                "• `/search magic_5`\n"
                "• `/search infinix`\n"
                "• `/search samsung galaxy`\n\n"
                "💡 *Tips de búsqueda:*\n"
                "• Usa palabras clave específicas\n"
                "• Puedes usar palabras parciales\n"
                "• No distingue mayúsculas/minúsculas\n\n"
                "📥 ¿No encuentras lo que buscas? Usa `/request` para solicitarlo",
                parse_mode="Markdown"
            )
            return

        texto = " ".join(context.args).strip()
        if not texto:
            await update.message.reply_text("❌ Por favor proporciona una palabra clave para buscar.")
            return
            
        logger.info(f"🔍 Búsqueda: '{texto}' por usuario {update.effective_user.id}")
        
        # Actualizar estadísticas
        self.db['estadisticas']['total_busquedas'] += 1
        self.db_manager.guardar_db(self.db)
        
        resultados = self.db_manager.buscar_archivos(texto, self.db['archivos'])
        
        if not resultados:
            await update.message.reply_text(
                f"❌ *No encontré resultados para '{texto}'*\n\n"
                "💡 *¿Qué puedes hacer?*\n"
                "• Intenta con palabras más cortas\n"
                "• Revisa la ortografía\n"
                "• Usa palabras clave diferentes\n"
                "• Solicítalo con `/request {texto}`\n\n"
                f"📋 Usa `/request` para solicitar este archivo",
                parse_mode="Markdown"
            )
            return

        mensaje = f"🔍 *Resultados para '{texto}' ({len(resultados)}):*\n\n"
        
        for i, (palabra, info, relevancia) in enumerate(resultados, 1):
            if isinstance(info, dict):
                enlace = info.get('enlace', 'No disponible')
                fecha = info.get('fecha_agregado', '')[:10] if info.get('fecha_agregado') else ''
                nombre_original = info.get('nombre_original', palabra)
                tamaño = info.get('tamaño', 0)
                tamaño_mb = tamaño / 1024 / 1024 if tamaño > 0 else 0
            else:
                enlace = info
                fecha = ''
                nombre_original = palabra
                tamaño_mb = 0
            
            # Icono de estado
            if enlace.startswith("file_id:"):
                estado_icono = "✅"
            elif enlace == 'ENLACE_INVALIDO_MIGRAR':
                estado_icono = "⚠️"
            else:
                estado_icono = "🔗"
            
            mensaje += f"{estado_icono} *{i}. 📁 {nombre_original}*\n"
            mensaje += f"🔑 `{palabra}`\n"
            
            if enlace.startswith("file_id:"):
                file_id = enlace.replace("file_id:", "")
                enlace_descarga = await self.obtener_enlace_descarga(file_id, context)
                if enlace_descarga:
                    mensaje += f"📎 [⬇️ Descargar archivo]({enlace_descarga})\n"
                else:
                    mensaje += "📎 Archivo disponible (contacta admin si hay problemas)\n"
            elif enlace == 'ENLACE_INVALIDO_MIGRAR':
                mensaje += "⚠️ Archivo requiere reenvío\n"
            elif enlace.startswith("http"):
                mensaje += f"🔗 [🌐 Enlace directo]({enlace})\n"
            else:
                mensaje += f"🔗 {enlace}\n"
            
            if fecha:
                mensaje += f"📅 {fecha}"
            if tamaño_mb > 0:
                mensaje += f" • 💾 {tamaño_mb:.1f} MB"
            mensaje += f" • 🎯 {relevancia:.1f}%\n"
            mensaje += "─────────────────────\n"

        mensaje += f"\n💡 ¿No encontraste lo que buscas? Usa `/request {texto}`"

        await self.enviar_mensaje_largo(update, mensaje, "Markdown", context)

    async def list_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /list mejorado para mostrar archivos (admin)"""
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
            return

        archivos = self.db['archivos']
        
        if not archivos:
            await update.message.reply_text("📁 No hay archivos almacenados en la base de datos.")
            return

        # Filtros por estado si se especifica
        filtro = context.args[0].upper() if context.args and context.args[0].upper() in ['VALIDOS', 'INVALIDOS', 'ANTIGUOS'] else None
        
        archivos_ordenados = []
        for clave, info in archivos.items():
            if isinstance(info, dict):
                fecha = info.get('fecha_agregado', '1900-01-01T00:00:00')
                nombre_original = info.get('nombre_original', clave)
                enlace = info.get('enlace', '')
                
                if enlace.startswith('file_id:'):
                    estado = "VALIDO"
                    estado_icono = "✅"
                elif enlace == 'ENLACE_INVALIDO_MIGRAR':
                    estado = "INVALIDO"
                    estado_icono = "⚠️"
                else:
                    estado = "ANTIGUO"
                    estado_icono = "❓"
                    
                # Aplicar filtro si existe
                if filtro and not (
                    (filtro == 'VALIDOS' and estado == 'VALIDO') or
                    (filtro == 'INVALIDOS' and estado == 'INVALIDO') or
                    (filtro == 'ANTIGUOS' and estado == 'ANTIGUO')
                ):
                    continue
                    
                archivos_ordenados.append((fecha, clave, nombre_original, estado_icono, estado))
            else:
                if filtro and filtro != 'ANTIGUOS':
                    continue
                archivos_ordenados.append(('1900-01-01T00:00:00', clave, clave, "❓", "ANTIGUO"))
        
        archivos_ordenados.sort(key=lambda x: x[0], reverse=True)
        
        filtro_texto = f" - {filtro}S" if filtro else ""
        mensaje = f"📋 *Lista de archivos{filtro_texto} ({len(archivos_ordenados)}):*\n\n"
        
        # Contadores por estado
        contadores = {"VALIDO": 0, "INVALIDO": 0, "ANTIGUO": 0}
        
        for i, (fecha, clave, nombre_original, estado_icono, estado) in enumerate(archivos_ordenados[:20], 1):
            contadores[estado] += 1
            fecha_corta = fecha[:10] if len(fecha) >= 10 else "Sin fecha"
            
            mensaje += f"{estado_icono} *{i}. {nombre_original}*\n"
            mensaje += f"🔑 `{clave}` • 📅 {fecha_corta}\n"
            mensaje += "─────────────────────\n"
        
        if len(archivos_ordenados) > 20:
            mensaje += f"\n... y {len(archivos_ordenados) - 20} archivos más\n"
        
        mensaje += (
            f"\n📊 *Resumen por estado:*\n"
            f"✅ Válidos: {contadores['VALIDO']}\n"
            f"⚠️ Inválidos: {contadores['INVALIDO']}\n"
            f"❓ Antiguos: {contadores['ANTIGUO']}\n\n"
            f"💡 Filtros: `/list VALIDOS` `/list INVALIDOS` `/list ANTIGUOS`"
        )

        await self.enviar_mensaje_largo(update, mensaje, "Markdown", context)

    async def recibir_archivo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Procesar archivos enviados - mejorado"""
        documento = update.message.document
        if not documento:
            return

        user_info = f"{update.effective_user.first_name} (ID: {update.effective_user.id})"
        logger.info(f"📁 Archivo recibido: {documento.file_name} de {user_info}")

        nombre_archivo = documento.file_name or "archivo_sin_nombre"
        file_id = documento.file_id
        tamaño = documento.file_size or 0
        
        # Generar clave única mejorada
        clave = re.sub(r'[^a-zA-Z0-9_.]', '_', nombre_archivo.lower())
        clave = re.sub(r'_+', '_', clave)
        clave = clave.strip('_')
        
        # Remover extensión para la clave si es muy larga
        if len(clave) > 50:
            clave_sin_ext = os.path.splitext(clave)[0][:45]
            extension = os.path.splitext(clave)[1]
            clave = clave_sin_ext + extension
        
        contador = 1
        clave_original = clave
        
        while clave in self.db['archivos']:
            base_name = os.path.splitext(clave_original)[0]
            extension = os.path.splitext(clave_original)[1]
            clave = f"{base_name}_{contador}{extension}"
            contador += 1

        # Almacenar información completa del archivo
        self.db['archivos'][clave] = {
            'enlace': f"file_id:{file_id}",
            'fecha_agregado': datetime.now().isoformat(),
            'agregado_por': update.effective_user.id,
            'agregado_por_nombre': update.effective_user.first_name,
            'nombre_original': nombre_archivo,
            'tamaño': tamaño,
            'file_id': file_id,
            'tipo_mime': documento.mime_type or 'application/octet-stream'
        }
        self.db['estadisticas']['archivos_agregados'] += 1

        if self.db_manager.guardar_db(self.db):
            tamaño_mb = tamaño / 1024 / 1024
            
            # Mensaje de confirmación mejorado
            await update.message.reply_text(
                f"✅ *Archivo guardado exitosamente*\n\n"
                f"📁 *Nombre:* {nombre_archivo}\n"
                f"🔑 *Clave:* `{clave}`\n"
                f"💾 *Tamaño:* {tamaño_mb:.2f} MB\n"
                f"📅 *Fecha:* {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
                f"🔍 Busca con: `/search {clave.split('_')[0]}`\n"
                f"🆔 File ID: `{file_id}`",
                parse_mode="Markdown"
            )

            # Publicar en canal con información adicional
            try:
                caption = (
                    f"📂 *Nuevo archivo agregado*\n\n"
                    f"📁 *Nombre:* {nombre_archivo}\n"
                    f"🔑 *Clave de búsqueda:* `{clave}`\n"
                    f"💾 *Tamaño:* {tamaño_mb:.2f} MB\n"
                    f"👤 *Subido por:* {update.effective_user.first_name}\n"
                    f"📅 *Fecha:* {datetime.now().strftime('%d/%m/%Y %H:%M')}"
                )
                
                await self.publicar_en_canal(context, caption, file_id)
                
            except Exception as e:
                logger.error(f"❌ Error al publicar en canal: {e}")
                await update.message.reply_text(
                    f"✅ Archivo guardado correctamente\n"
                    f"⚠️ Error al publicar en el canal: {str(e)}"
                )
        else:
            await update.message.reply_text("❌ Error al guardar el archivo en la base de datos.")

    async def show_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None):
        """Mostrar estadísticas completas del bot"""
        db_stats = self.db['estadisticas']
        req_stats = self.solicitudes_db['estadisticas']
        total_archivos = len(self.db['archivos'])
        
        # Contadores detallados de archivos
        archivos_validos = 0
        archivos_invalidos = 0
        archivos_antiguos = 0
        tamaño_total = 0
        
        for info in self.db['archivos'].values():
            if isinstance(info, dict):
                enlace = info.get('enlace', '')
                tamaño_total += info.get('tamaño', 0)
                
                if enlace.startswith('file_id:'):
                    archivos_validos += 1
                elif enlace == 'ENLACE_INVALIDO_MIGRAR':
                    archivos_invalidos += 1
                else:
                    archivos_antiguos += 1
            else:
                archivos_antiguos += 1
        
        tamaño_total_mb = tamaño_total / 1024 / 1024
        
        mensaje = (
            "📊 *Estadísticas Completas del Bot*\n\n"
            "🗄️ *ARCHIVOS:*\n"
            f"📁 Total: {total_archivos}\n"
            f"✅ Válidos: {archivos_validos}\n"
            f"⚠️ Requieren reenvío: {archivos_invalidos}\n"
            f"❓ Formato antiguo: {archivos_antiguos}\n"
            f"💾 Tamaño total: {tamaño_total_mb:.1f} MB\n\n"
            "📥 *SOLICITUDES:*\n"
            f"📋 Total enviadas: {req_stats['total_solicitudes']}\n"
            f"⏳ Pendientes: {req_stats['solicitudes_pendientes']}\n"
            f"✅ Completadas: {req_stats['solicitudes_completadas']}\n"
            f"❌ Rechazadas: {req_stats['total_solicitudes'] - req_stats['solicitudes_pendientes'] - req_stats['solicitudes_completadas']}\n\n"
            "🔍 *BÚSQUEDAS:*\n"
            f"🔍 Total realizadas: {db_stats['total_busquedas']}\n"
            f"📤 Archivos agregados: {db_stats['archivos_agregados']}\n\n"
            f"🤖 *SISTEMA:*\n"
            f"📅 Base de datos: v{self.db.get('version', '1.0')}\n"
            f"⏰ Última actualización: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
        )
        
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")
        else:
            await update.message.reply_text(mensaje, parse_mode="Markdown")

    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None):
        """Mostrar ayuda completa del bot"""
        mensaje = (
            "ℹ️ *Guía Completa del Bot v1.3*\n\n"
            "🔍 *BÚSQUEDA DE ARCHIVOS:*\n"
            "• `/search <palabra>` - Buscar archivos\n"
            "• Ejemplo: `/search xiaomi redmi`\n\n"
            "📥 *SOLICITAR ARCHIVOS:*\n"
            "• `/request <enlace>` - Con enlace directo\n"
            "• `/request <descripción>` - Describir archivo\n"
            "• `/mystatus` - Ver mis solicitudes\n\n"
            "📤 *ENVIAR ARCHIVOS:*\n"
            "• Arrastra y suelta cualquier archivo\n"
            "• Se asignará automáticamente una clave\n"
            "• Se publicará en el canal\n\n"
            "🎯 *COMANDOS ÚTILES:*\n"
            "• `/start` - Menú principal\n"
            "• Botones interactivos para navegación\n\n"
        )
        
        if self.es_admin(update.effective_user.id if hasattr(update, 'effective_user') else (update.callback_query.from_user.id if hasattr(update, 'callback_query') else 0)):
            mensaje += (
                "👨‍💼 *COMANDOS DE ADMINISTRADOR:*\n"
                "• `/list [filtro]` - Lista archivos\n"
                "• `/adminrequests [estado]` - Ver solicitudes\n"
                "• `/respond <ID> <respuesta>` - Responder solicitud\n"
                "• `/delete <clave>` - Eliminar archivo\n"
                "• `/fixfiles` - Ver archivos inválidos\n"
                "• `/post` - Crear publicación en el canal\n\n"
            )
        
        mensaje += (
            "📋 *FORMATOS SOPORTADOS:*\n"
            "• Documentos (PDF, DOC, etc.)\n"
            "• Imágenes (JPG, PNG, etc.)\n"
            "• Videos y audio\n"
            "• Archivos comprimidos\n"
            "• ROMs y firmwares\n\n"
            "💡 *CONSEJOS:*\n"
            "• Usa palabras clave específicas\n"
            "• Las búsquedas no distinguen mayúsculas\n"
            "• Solicita archivos si no los encuentras\n"
            "• Revisa regularmente tus solicitudes"
        )
        
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")
        else:
            await update.message.reply_text(mensaje, parse_mode="Markdown")

    # ═══════════════════════════════════════════════════════════════
    # 🎛️ MANEJADOR DE BOTONES
    # ═══════════════════════════════════════════════════════════════

    async def button_handler(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja todos los botones inline del bot"""
        query = update.callback_query
        await query.answer()

        try:
            data = query.data
            user_id = query.from_user.id
            
            # Botones de información general
            if data == "stats":
                await self.show_stats(update, context)
            elif data == "help":
                await self.show_help(update, context)
            elif data == "my_requests":
                await self.handle_my_requests_button(update, context)
            
            # Botones de administrador
            elif data == "list" and self.es_admin(user_id):
                await self.handle_list_button(update, context)
            elif data == "admin_requests" and self.es_admin(user_id):
                await self.handle_admin_requests_button(update, context)
            elif data == "invalid" and self.es_admin(user_id):
                await self.handle_invalid_files_button(update, context)
            elif data == "create_post" and self.es_admin(user_id):
                await self.handle_create_post_button(update, context)
            
            # Botones de gestión de solicitudes
            elif data.startswith("aprobar_") and self.es_admin(user_id):
                await self.handle_approve_request(update, context, data)
            elif data.startswith("rechazar_") and self.es_admin(user_id):
                await self.handle_reject_request(update, context, data)
            
            # Botones del sistema de publicaciones
            elif data in ["post_text_only", "post_with_media", "post_cancel"] and self.es_admin(user_id):
                await self.post_button_handler(update, context)
            
            else:
                await query.edit_message_text("❌ Acción no válida o sin permisos suficientes.")
                
        except Exception as e:
            logger.error(f"❌ Error en button_handler: {e}")
            await query.edit_message_text("❌ Error al procesar la solicitud.")

    async def handle_create_post_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja el botón de crear publicación"""
        keyboard = [
            [InlineKeyboardButton("📝 Solo texto", callback_data="post_text_only")],
            [InlineKeyboardButton("📷 Con imagen/documento", callback_data="post_with_media")],
            [InlineKeyboardButton("❌ Cancelar", callback_data="post_cancel")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await update.callback_query.edit_message_text(
            "📢 *Crear publicación para el canal*\n\n"
            "🎯 *Opciones disponibles:*\n"
            "📝 Solo texto\n"
            "📷 Con imagen, video o documento\n\n"
            "💡 Elige el tipo de publicación:",
            parse_mode="Markdown",
            reply_markup=reply_markup
        )

    async def handle_my_requests_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja el botón de mis solicitudes"""
        user_id = update.callback_query.from_user.id
        
        mis_solicitudes = [
            sol for sol in self.solicitudes_db['solicitudes'].values()
            if sol['usuario_id'] == user_id
        ]
        
        if not mis_solicitudes:
            await update.callback_query.edit_message_text(
                "📭 *No tienes solicitudes registradas*\n\n"
                "💡 Usa `/request <enlace o descripción>` para solicitar archivos.\n\n"
                "*Ejemplos:*\n"
                "• `/request https://ejemplo.com/archivo.zip`\n"
                "• `/request ROM para Xiaomi Mi 11`",
                parse_mode="Markdown"
            )
            return
        
        # Mostrar resumen de solicitudes
        mis_solicitudes.sort(key=lambda x: x['fecha_creacion'], reverse=True)
        
        pendientes = sum(1 for s in mis_solicitudes if s['estado'] == 'PENDIENTE')
        completadas = sum(1 for s in mis_solicitudes if s['estado'] == 'COMPLETADO')
        rechazadas = sum(1 for s in mis_solicitudes if s['estado'] == 'RECHAZADO')
        
        mensaje = (
            f"📊 *Resumen de tus solicitudes ({len(mis_solicitudes)}):*\n\n"
            f"⏳ *Pendientes:* {pendientes}\n"
            f"✅ *Completadas:* {completadas}\n"
            f"❌ *Rechazadas:* {rechazadas}\n\n"
        )
        
        if mis_solicitudes:
            mensaje += "*🕒 Últimas 5 solicitudes:*\n\n"
            
            for i, sol in enumerate(mis_solicitudes[:5], 1):
                estado_icono = Config.REQUEST_STATES.get(sol['estado'], '❓')
                fecha = datetime.fromisoformat(sol['fecha_creacion']).strftime('%d/%m')
                
                mensaje += f"{estado_icono} *{sol['id']}* • {fecha}\n"
                mensaje += f"💬 {sol['contenido'][:60]}{'...' if len(sol['contenido']) > 60 else ''}\n"
                
                if sol.get('respuesta_admin'):
                    mensaje += f"👨‍💼 {sol['respuesta_admin'][:50]}{'...' if len(sol['respuesta_admin']) > 50 else ''}\n"
                
                mensaje += "─────────────────────\n"
        
        mensaje += "\n💡 Usa `/mystatus` para ver detalles completos"
        
        await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")

    async def handle_list_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja el botón de lista de archivos (admin)"""
        archivos = self.db['archivos']
        
        if not archivos:
            await update.callback_query.edit_message_text("📁 No hay archivos almacenados.")
            return

        # Contar archivos por estado
        validos = sum(1 for info in archivos.values() 
                     if isinstance(info, dict) and info.get('enlace', '').startswith('file_id:'))
        invalidos = sum(1 for info in archivos.values() 
                       if isinstance(info, dict) and info.get('enlace') == 'ENLACE_INVALIDO_MIGRAR')
        antiguos = len(archivos) - validos - invalidos
        
        # Obtener archivos más recientes
        archivos_recientes = []
        for clave, info in archivos.items():
            if isinstance(info, dict):
                fecha = info.get('fecha_agregado', '1900-01-01T00:00:00')
                nombre = info.get('nombre_original', clave)
                archivos_recientes.append((fecha, nombre, clave))
        
        archivos_recientes.sort(key=lambda x: x[0], reverse=True)
        
        mensaje = (
            f"📋 *Resumen de archivos ({len(archivos)} total):*\n\n"
            f"✅ *Válidos:* {validos}\n"
            f"⚠️ *Inválidos:* {invalidos}\n"
            f"❓ *Formato antiguo:* {antiguos}\n\n"
        )
        
        if archivos_recientes:
            mensaje += "*📁 Últimos 8 archivos:*\n\n"
            for i, (fecha, nombre, clave) in enumerate(archivos_recientes[:8], 1):
                fecha_corta = fecha[:10] if len(fecha) >= 10 else "Sin fecha"
                mensaje += f"{i}. *{nombre}*\n   `{clave}` • 📅 {fecha_corta}\n"
        
        mensaje += "\n💡 Usa `/list` para ver la lista completa"
        
        await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")

    async def handle_admin_requests_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja el botón de solicitudes de admin"""
        todas_solicitudes = list(self.solicitudes_db['solicitudes'].values())
        
        if not todas_solicitudes:
            await update.callback_query.edit_message_text("📭 No hay solicitudes registradas.")
            return

        # Filtrar solicitudes pendientes
        pendientes = [s for s in todas_solicitudes if s['estado'] == 'PENDIENTE']
        
        mensaje = f"📥 *Solicitudes pendientes ({len(pendientes)}):*\n\n"
        
        if not pendientes:
            mensaje += "✅ No hay solicitudes pendientes\n\n"
        else:
            for i, sol in enumerate(pendientes[:8], 1):
                tipo_icono = "🔗" if sol['tipo'] == "ENLACE" else "📝"
                fecha = datetime.fromisoformat(sol['fecha_creacion']).strftime('%d/%m')
                
                mensaje += f"{tipo_icono} *{sol['id']}* • 📅 {fecha}\n"
                mensaje += f"👤 {sol['usuario_nombre']}\n"
                mensaje += f"💬 {sol['contenido'][:70]}{'...' if len(sol['contenido']) > 70 else ''}\n"
                mensaje += "─────────────────────\n"
        
        stats = self.solicitudes_db['estadisticas']
        mensaje += (
            f"📊 *Estadísticas generales:*\n"
            f"📋 Total: {stats['total_solicitudes']}\n"
            f"✅ Completadas: {stats['solicitudes_completadas']}\n\n"
            f"💡 Usa `/adminrequests` para ver todas las solicitudes"
        )
        
        await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")

    async def handle_invalid_files_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja el botón de archivos inválidos"""
        archivos_invalidos = []
        for clave, info in self.db['archivos'].items():
            if isinstance(info, dict) and info.get('enlace') == 'ENLACE_INVALIDO_MIGRAR':
                archivos_invalidos.append((clave, info))

        if not archivos_invalidos:
            await update.callback_query.edit_message_text("✅ No hay archivos con enlaces inválidos.")
            return

        mensaje = f"🚨 *Archivos inválidos ({len(archivos_invalidos)}):*\n\n"
        
        for i, (clave, info) in enumerate(archivos_invalidos[:10], 1):
            nombre = info.get('nombre_original', clave)
            fecha = info.get('fecha_agregado', '')[:10] if info.get('fecha_agregado') else 'Sin fecha'
            
            mensaje += f"⚠️ *{i}. {nombre}*\n"
            mensaje += f"🔑 `{clave}` • 📅 {fecha}\n"
            mensaje += "─────────────────────\n"
        
        if len(archivos_invalidos) > 10:
            mensaje += f"\n... y {len(archivos_invalidos) - 10} archivos más\n"
        
        mensaje += (
            "\n💡 *Para solucionarlo:*\n"
            "1. Reenvía los archivos al bot\n"
            "2. Usa `/delete <clave>` para eliminar inválidos\n"
            "3. Usa `/fixfiles` para ver detalles completos"
        )
        
        await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")

    async def handle_approve_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
        """Maneja la aprobación de solicitudes"""
        solicitud_id = data.replace("aprobar_", "")
        
        if solicitud_id not in self.solicitudes_db['solicitudes']:
            await update.callback_query.edit_message_text(f"❌ Solicitud `{solicitud_id}` no encontrada.")
            return

        solicitud = self.solicitudes_db['solicitudes'][solicitud_id]
        
        # Actualizar solicitud
        solicitud['estado'] = 'PROCESANDO'
        solicitud['fecha_actualizacion'] = datetime.now().isoformat()
        
        if self.db_manager.guardar_solicitudes(self.solicitudes_db):
            # Actualizar el mensaje con nueva información
            mensaje = (
                f"🔄 *Solicitud en proceso*\n\n"
                f"🆔 *ID:* `{solicitud_id}`\n"
                f"👤 *Usuario:* {solicitud['usuario_nombre']}\n"
                f"📝 *Contenido:* {solicitud['contenido'][:100]}{'...' if len(solicitud['contenido']) > 100 else ''}\n\n"
                f"✅ Estado cambiado a: *PROCESANDO*\n\n"
                f"💡 Usa `/respond {solicitud_id} <mensaje>` para completar la solicitud"
            )
            
            await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")
            
            # Notificar al usuario
            try:
                await context.bot.send_message(
                    chat_id=solicitud['usuario_id'],
                    text=(
                        f"🔄 *Solicitud en proceso*\n\n"
                        f"🆔 *ID:* `{solicitud_id}`\n"
                        f"📝 *Tu solicitud:* {solicitud['contenido'][:150]}{'...' if len(solicitud['contenido']) > 150 else ''}\n\n"
                        f"✅ Un administrador está procesando tu solicitud.\n"
                        f"🔔 Recibirás una notificación cuando esté lista."
                    ),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"❌ Error al notificar usuario sobre aprobación: {e}")
        else:
            await update.callback_query.edit_message_text("❌ Error al procesar la solicitud.")

    async def handle_reject_request(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data: str):
        """Maneja el rechazo de solicitudes"""
        solicitud_id = data.replace("rechazar_", "")
        
        if solicitud_id not in self.solicitudes_db['solicitudes']:
            await update.callback_query.edit_message_text(f"❌ Solicitud `{solicitud_id}` no encontrada.")
            return

        solicitud = self.solicitudes_db['solicitudes'][solicitud_id]
        
        # Actualizar solicitud
        solicitud['estado'] = 'RECHAZADO'
        solicitud['fecha_actualizacion'] = datetime.now().isoformat()
        solicitud['respuesta_admin'] = 'Solicitud rechazada por el administrador'
        
        # Actualizar estadísticas
        if solicitud['estado'] == 'PENDIENTE':
            self.solicitudes_db['estadisticas']['solicitudes_pendientes'] -= 1
        
        if self.db_manager.guardar_solicitudes(self.solicitudes_db):
            # Actualizar el mensaje
            mensaje = (
                f"❌ *Solicitud rechazada*\n\n"
                f"🆔 *ID:* `{solicitud_id}`\n"
                f"👤 *Usuario:* {solicitud['usuario_nombre']}\n"
                f"📝 *Contenido:* {solicitud['contenido'][:100]}{'...' if len(solicitud['contenido']) > 100 else ''}\n\n"
                f"❌ Estado: *RECHAZADO*\n"
                f"📅 Fecha de rechazo: {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            )
            
            await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")
            
            # Notificar al usuario
            try:
                await context.bot.send_message(
                    chat_id=solicitud['usuario_id'],
                    text=(
                        f"❌ *Solicitud rechazada*\n\n"
                        f"🆔 *ID:* `{solicitud_id}`\n"
                        f"📝 *Tu solicitud:* {solicitud['contenido'][:150]}{'...' if len(solicitud['contenido']) > 150 else ''}\n\n"
                        f"❌ Tu solicitud ha sido rechazada por un administrador.\n"
                        f"💡 Puedes enviar una nueva solicitud con `/request` si deseas."
                    ),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"❌ Error al notificar usuario sobre rechazo: {e}")
        else:
            await update.callback_query.edit_message_text("❌ Error al procesar el rechazo.")

    # ═══════════════════════════════════════════════════════════════
    # 🗑️ COMANDO DE ELIMINACIÓN Y OTROS UTILITARIOS
    # ═══════════════════════════════════════════════════════════════

    async def delete_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando para eliminar archivos (solo admin)"""
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
            return

        if not context.args:
            await update.message.reply_text(
                "🗑️ *Uso del comando de eliminación:*\n\n"
                "`/delete <clave_archivo>`\n\n"
                "*Ejemplos:*\n"
                "• `/delete honor_magic_5.zip`\n"
                "• `/delete xiaomi_redmi_note_12`\n\n"
                "⚠️ *Advertencia:* Esta acción es irreversible\n"
                "💡 Usa `/list` para ver las claves de archivos",
                parse_mode="Markdown"
            )
            return

        clave = " ".join(context.args).strip()
        
        if clave not in self.db['archivos']:
            await update.message.reply_text(
                f"❌ *Archivo no encontrado*\n\n"
                f"🔍 No existe el archivo con clave: `{clave}`\n"
                f"💡 Usa `/list` para ver archivos disponibles"
            )
            return

        # Obtener información del archivo antes de eliminarlo
        info_archivo = self.db['archivos'][clave]
        if isinstance(info_archivo, dict):
            nombre_original = info_archivo.get('nombre_original', clave)
            fecha_agregado = info_archivo.get('fecha_agregado', '')[:10]
            tamaño = info_archivo.get('tamaño', 0)
        else:
            nombre_original = clave
            fecha_agregado = 'Desconocida'
            tamaño = 0

        # Eliminar archivo
        del self.db['archivos'][clave]
        
        if self.db_manager.guardar_db(self.db):
            tamaño_mb = tamaño / 1024 / 1024 if tamaño > 0 else 0
            
            await update.message.reply_text(
                f"🗑️ *Archivo eliminado exitosamente*\n\n"
                f"📁 *Nombre:* {nombre_original}\n"
                f"🔑 *Clave:* `{clave}`\n"
                f"📅 *Fecha agregado:* {fecha_agregado}\n"
                f"💾 *Tamaño:* {tamaño_mb:.2f} MB\n\n"
                f"✅ El archivo ha sido eliminado permanentemente",
                parse_mode="Markdown"
            )
            logger.info(f"🗑️ Archivo eliminado: {clave} por admin {update.effective_user.id}")
        else:
            await update.message.reply_text("❌ Error al eliminar el archivo de la base de datos.")

    async def fix_invalid_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando para admin: mostrar archivos inválidos con detalles"""
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
            return

        archivos_invalidos = []
        for clave, info in self.db['archivos'].items():
            if isinstance(info, dict) and info.get('enlace') == 'ENLACE_INVALIDO_MIGRAR':
                archivos_invalidos.append((clave, info))

        if not archivos_invalidos:
            await update.message.reply_text("✅ No hay archivos con enlaces inválidos.")
            return

        mensaje = f"🚨 *Archivos inválidos - Detalles ({len(archivos_invalidos)}):*\n\n"
        
        for i, (clave, info) in enumerate(archivos_invalidos[:15], 1):
            nombre = info.get('nombre_original', clave)
            fecha = info.get('fecha_agregado', '')[:10] if info.get('fecha_agregado') else 'Sin fecha'
            agregado_por = info.get('agregado_por_nombre', 'Desconocido')
            enlace_original = info.get('enlace_original', 'No disponible')
            
            mensaje += f"⚠️ *{i}. {nombre}*\n"
            mensaje += f"🔑 `{clave}`\n"
            mensaje += f"📅 {fecha} • 👤 {agregado_por}\n"
            mensaje += f"🔗 {enlace_original[:50]}{'...' if len(enlace_original) > 50 else ''}\n"
            mensaje += "─────────────────────\n"

        if len(archivos_invalidos) > 15:
            mensaje += f"\n... y {len(archivos_invalidos) - 15} archivos más\n"

        mensaje += (
            "\n📋 *Acciones recomendadas:*\n"
            "1. 🔄 Reenvía los archivos originales al bot\n"
            "2. 🗑️ Elimina archivos inválidos: `/delete <clave>`\n"
            "3. 📞 Contacta a los usuarios para que reenvíen\n"
            "4. 🔍 Verifica regularmente con este comando\n\n"
            "💡 *Causa:* URLs temporales de Telegram API que expiraron"
        )

        await self.enviar_mensaje_largo(update, mensaje, "Markdown", context)

    # ═══════════════════════════════════════════════════════════════
    # 🚨 MANEJADOR DE ERRORES
    # ═══════════════════════════════════════════════════════════════

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Maneja errores del bot de forma elegante"""
        logger.error("❌ Excepción en el manejo de actualización:", exc_info=context.error)
        
        # Intentar enviar mensaje de error al usuario si es posible
        try:
            if isinstance(update, Update) and update.effective_message:
                await update.effective_message.reply_text(
                    "❌ *Error inesperado*\n\n"
                    "🔄 Por favor, inténtalo de nuevo en unos momentos.\n"
                    "💡 Si el problema persiste, contacta al administrador.\n\n"
                    f"🆔 Error ID: {datetime.now().strftime('%Y%m%d_%H%M%S')}",
                    parse_mode="Markdown"
                )
        except Exception:
            # Si no se puede enviar el mensaje de error, solo registrar
            logger.error("❌ No se pudo enviar mensaje de error al usuario")
            pass

# ═══════════════════════════════════════════════════════════════════
# 🚀 FUNCIÓN PRINCIPAL
# ═══════════════════════════════════════════════════════════════════

def main():
    """Función principal del bot con configuración completa"""
    print("🤖 Iniciando Bot de Gestión de Archivos v1.3...")
    
    if not Config.TOKEN:
        logger.error("❌ TOKEN no configurado. Define TELEGRAM_TOKEN en variables de entorno")
        print("❌ Error: TOKEN no configurado")
        return

    try:
        bot = TelegramBot()
        app = ApplicationBuilder().token(Config.TOKEN).build()

        # ═══════════════════════════════════════════════════════════
        # 📋 REGISTRO DE COMANDOS Y CONVERSATION HANDLERS
        # ═══════════════════════════════════════════════════════════
        
        # ConversationHandler para el sistema de publicaciones
        post_handler = ConversationHandler(
            entry_points=[CommandHandler("post", bot.post_to_channel_start)],
            states={
                POST_TEXT: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_post_text),
                    CallbackQueryHandler(bot.post_button_handler, pattern="^post_")
                ],
                POST_MEDIA: [
                    MessageHandler(filters.ALL & ~filters.COMMAND, bot.handle_post_media),
                    MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_post_media)
                ]
            },
            fallbacks=[CommandHandler("cancel", bot.cancel_post)],
            allow_reentry=True
        )
        
        app.add_handler(post_handler)
        
        # Comandos principales
        app.add_handler(CommandHandler("start", bot.start))
        app.add_handler(CommandHandler("search", bot.search))
        app.add_handler(CommandHandler("help", bot.show_help))
        
        # Comandos de solicitudes
        app.add_handler(CommandHandler("request", bot.request_file))
        app.add_handler(CommandHandler("mystatus", bot.my_requests_status))
        
        # Comandos de administrador - archivos
        app.add_handler(CommandHandler("list", bot.list_files))
        app.add_handler(CommandHandler("delete", bot.delete_file))
        app.add_handler(CommandHandler("fixfiles", bot.fix_invalid_files))
        
        # Comandos de administrador - solicitudes
        app.add_handler(CommandHandler("adminrequests", bot.admin_requests))
        app.add_handler(CommandHandler("respond", bot.respond_request))
        
        # Manejadores de contenido
        app.add_handler(CallbackQueryHandler(bot.button_handler))
        app.add_handler(MessageHandler(filters.Document.ALL, bot.recibir_archivo))
        
        # Manejador de errores
        app.add_error_handler(bot.error_handler)

        # ═══════════════════════════════════════════════════════════
        # 📊 INFORMACIÓN DE INICIO
        # ═══════════════════════════════════════════════════════════
        
        logger.info("🤖 Bot iniciado exitosamente")
        print("✅ Bot en ejecución correctamente")
        print("\n" + "═" * 60)
        print("📋 COMANDOS DISPONIBLES:")
        print("═" * 60)
        print("👥 USUARIOS:")
        print("   🚀 /start - Menú principal con botones")
        print("   🔍 /search <palabra> - Buscar archivos")
        print("   📥 /request <enlace|descripción> - Solicitar archivo")
        print("   📊 /mystatus - Ver estado de mis solicitudes")
        print("   ℹ️  /help - Ayuda completa")
        print("\n👨‍💼 ADMINISTRADORES:")
        print("   📋 /list [filtro] - Lista todos los archivos")
        print("   📥 /adminrequests [estado] - Gestionar solicitudes")
        print("   📝 /respond <ID> <respuesta> - Responder solicitud")
        print("   🗑️ /delete <clave> - Eliminar archivo")
        print("   🔧 /fixfiles - Ver archivos inválidos")
        print("   📢 /post - Crear publicación en el canal")
        print("═" * 60)
        print(f"🆔 Admin ID: {Config.ADMIN_ID}")
        print(f"📺 Canal ID: {Config.CANAL_ID}")
        print(f"📊 Archivos en BD: {len(bot.db['archivos'])}")
        print(f"📋 Solicitudes: {bot.solicitudes_db['estadisticas']['total_solicitudes']}")
        print("═" * 60)
        
        # Iniciar el bot
        app.run_polling(drop_pending_updates=True)
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot detenido por el usuario")
        print("\n🛑 Bot detenido manualmente")
    except Exception as e:
        logger.error(f"❌ Error crítico al iniciar el bot: {e}")
        print(f"❌ Error crítico: {e}")

if __name__ == "__main__":
    main()