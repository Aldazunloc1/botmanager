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

    @staticmethod
    def acortar_nombre(nombre: str, max_chars: int = 25) -> str:
        """Acorta nombres largos manteniendo información importante"""
        if len(nombre) <= max_chars:
            return nombre
        
        # Extraer extensión
        nombre_base, extension = os.path.splitext(nombre)
        
        # Si la extensión es muy larga, recortarla también
        if len(extension) > 8:
            extension = extension[:8] + "..."
        
        # Calcular espacio disponible para el nombre base
        espacio_disponible = max_chars - len(extension) - 3  # 3 para "..."
        
        if espacio_disponible > 0:
            nombre_cortado = nombre_base[:espacio_disponible] + "..." + extension
        else:
            nombre_cortado = nombre[:max_chars-3] + "..."
        
        return nombre_cortado

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
    # 📢 SISTEMA DE PUBLICACIONES PARA ADMIN - CORREGIDO
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
                "💡 Envía /cancel para cancelar",
                parse_mode="Markdown"
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
        elif update.message.audio:
            file_info = update.message.audio
            file_type = 'audio'
        elif update.message.voice:
            file_info = update.message.voice
            file_type = 'voice'
        else:
            await update.message.reply_text(
                "❌ *Tipo de archivo no soportado*\n\n"
                "📋 Envía uno de estos formatos:\n"
                "• 🖼️ Imagen\n"
                "• 🎥 Video\n"
                "• 📄 Documento\n"
                "• 🎞️ GIF/Animación\n"
                "• 🎵 Audio",
                parse_mode="Markdown"
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
        """Confirma y publica el contenido en el canal - CORREGIDO"""
        try:
            # Preparar el mensaje de confirmación
            if file_id:
                tipo_emoji = {
                    'photo': '🖼️',
                    'video': '🎥', 
                    'document': '📄',
                    'animation': '🎞️',
                    'audio': '🎵',
                    'voice': '🎤'
                }.get(file_type, '📎')
                
                confirmacion = (
                    f"✅ *Publicación lista para enviar*\n\n"
                    f"{tipo_emoji} *Archivo:* {file_name}\n"
                )
                
                if texto:
                    confirmacion += f"📝 *Texto:*\n{texto[:200]}{'...' if len(texto) > 200 else ''}\n\n"
                
                # Publicar en el canal con manejo de errores mejorado
                success = await self.publicar_multimedia_en_canal(
                    context, file_id, file_type, texto
                )
                
                if not success:
                    await update.message.reply_text(
                        "❌ *Error al enviar al canal*\n\n"
                        "🔍 *Posibles causas:*\n"
                        "• Bot no es administrador del canal\n"
                        "• Canal ID incorrecto\n"
                        "• Archivo demasiado grande\n"
                        "• Permisos insuficientes\n\n"
                        f"📺 *Canal configurado:* `{Config.CANAL_ID}`\n"
                        "💡 Verifica la configuración del bot en el canal",
                        parse_mode="Markdown"
                    )
                    return ConversationHandler.END
                
            else:
                # Solo texto
                confirmacion = (
                    f"✅ *Publicación de texto lista*\n\n"
                    f"📝 *Contenido:*\n{texto[:300]}{'...' if len(texto) > 300 else ''}\n\n"
                )
                
                # Dividir texto largo si es necesario
                if len(texto) > 4000:
                    chunks = [texto[i:i+4000] for i in range(0, len(texto), 4000)]
                    for i, chunk in enumerate(chunks):
                        try:
                            await context.bot.send_message(
                                chat_id=Config.CANAL_ID,
                                text=chunk,
                                parse_mode="Markdown"
                            )
                            if i < len(chunks) - 1:
                                await asyncio.sleep(1)  # Pausa entre mensajes
                        except TelegramError as e:
                            logger.error(f"❌ Error enviando chunk {i+1}: {e}")
                            raise
                else:
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
            error_msg = f"❌ *Error de Telegram:* {str(e)}"
            if "chat not found" in str(e).lower():
                error_msg += "\n\n🔍 *Solución:*\nVerifica que el bot sea administrador del canal"
            elif "forbidden" in str(e).lower():
                error_msg += "\n\n🔍 *Solución:*\nEl bot necesita permisos de administrador"
            elif "bad request" in str(e).lower():
                error_msg += "\n\n🔍 *Solución:*\nRevisa el formato del mensaje o archivo"
            
            logger.error(f"❌ Error al publicar en canal: {e}")
            await update.message.reply_text(error_msg, parse_mode="Markdown")
        except Exception as e:
            error_msg = f"❌ *Error inesperado:* {str(e)}"
            logger.error(f"❌ Error inesperado en publicación: {e}")
            await update.message.reply_text(error_msg, parse_mode="Markdown")

    async def publicar_multimedia_en_canal(self, context: ContextTypes.DEFAULT_TYPE, 
                                         file_id: str, file_type: str, caption: str = None) -> bool:
        """Publica multimedia en el canal con manejo robusto de errores"""
        try:
            # Limitar caption a 1024 caracteres (límite de Telegram)
            if caption and len(caption) > 1024:
                caption = caption[:1021] + "..."
            
            # Enviar según el tipo de archivo
            if file_type == 'photo':
                await context.bot.send_photo(
                    chat_id=Config.CANAL_ID,
                    photo=file_id,
                    caption=caption,
                    parse_mode="Markdown"
                )
            elif file_type == 'video':
                await context.bot.send_video(
                    chat_id=Config.CANAL_ID,
                    video=file_id,
                    caption=caption,
                    parse_mode="Markdown"
                )
            elif file_type == 'animation':
                await context.bot.send_animation(
                    chat_id=Config.CANAL_ID,
                    animation=file_id,
                    caption=caption,
                    parse_mode="Markdown"
                )
            elif file_type == 'audio':
                await context.bot.send_audio(
                    chat_id=Config.CANAL_ID,
                    audio=file_id,
                    caption=caption,
                    parse_mode="Markdown"
                )
            elif file_type == 'voice':
                await context.bot.send_voice(
                    chat_id=Config.CANAL_ID,
                    voice=file_id,
                    caption=caption,
                    parse_mode="Markdown"
                )
            else:  # document
                await context.bot.send_document(
                    chat_id=Config.CANAL_ID,
                    document=file_id,
                    caption=caption,
                    parse_mode="Markdown"
                )
            
            logger.info(f"✅ {file_type} enviado al canal exitosamente")
            return True
            
        except TelegramError as e:
            logger.error(f"❌ Error al enviar {file_type} al canal: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Error inesperado al enviar multimedia: {e}")
            return False

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
            
            # Formato mejorado y compacto
            contenido_corto = DatabaseManager.acortar_nombre(solicitud['contenido'], 60)
            
            mensaje += f"{estado_icono} `{solicitud['id']}` • {tipo_icono} • 📅 {fecha}\n"
            mensaje += f"💬 {contenido_corto}\n"
            
            if solicitud.get('respuesta_admin'):
                respuesta_corta = DatabaseManager.acortar_nombre(solicitud['respuesta_admin'], 50)
                mensaje += f"👨‍💼 {respuesta_corta}\n"
            
            mensaje += "──────────────────\n"
        
        if len(mis_solicitudes) > 10:
            mensaje += f"\n📄 *Mostrando 10 de {len(mis_solicitudes)} solicitudes*\n"
        
        # Resumen estadístico
        pendientes = sum(1 for s in mis_solicitudes if s['estado'] == 'PENDIENTE')
        completadas = sum(1 for s in mis_solicitudes if s['estado'] == 'COMPLETADO')
        rechazadas = sum(1 for s in mis_solicitudes if s['estado'] == 'RECHAZADO')
        
        mensaje += (
            f"\n📈 *Resumen:*\n"
            f"⏳ Pendientes: {pendientes} | ✅ Completadas: {completadas} | ❌ Rechazadas: {rechazadas}"
        )
        
        await self.enviar_mensaje_largo(update, mensaje, "Markdown", context)

    # ═══════════════════════════════════════════════════════════════
    # 👨‍💼 COMANDOS DE ADMINISTRADOR PARA SOLICITUDES
    # ═══════════════════════════════════════════════════════════════

    async def admin_requests(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /adminrequests - Ver todas las solicitudes (admin) - MEJORADO"""
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
            titulo_extra = f" {estado_filtro}S"
        else:
            titulo_extra = ""

        # Ordenar por fecha (más recientes primero)
        todas_solicitudes.sort(key=lambda x: x['fecha_creacion'], reverse=True)
        
        mensaje = f"📋 *Solicitudes{titulo_extra} ({len(todas_solicitudes)}):*\n\n"
        
        for i, solicitud in enumerate(todas_solicitudes[:12], 1):  # Mostrar máximo 12
            estado_icono = Config.REQUEST_STATES.get(solicitud['estado'], '❓')
            tipo_icono = "🔗" if solicitud['tipo'] == "ENLACE" else "📝"
            fecha = datetime.fromisoformat(solicitud['fecha_creacion']).strftime('%d/%m')
            
            # Nombres cortos para mejor visualización
            usuario_corto = DatabaseManager.acortar_nombre(solicitud['usuario_nombre'], 15)
            contenido_corto = DatabaseManager.acortar_nombre(solicitud['contenido'], 45)
            
            mensaje += f"{estado_icono} `{solicitud['id']}` • {tipo_icono} • 📅 {fecha}\n"
            mensaje += f"👤 {usuario_corto} • 💬 {contenido_corto}\n"
            mensaje += "──────────────────\n"
        
        if len(todas_solicitudes) > 12:
            mensaje += f"\n📄 *Mostrando 12 de {len(todas_solicitudes)} solicitudes*\n"
        
        stats = self.solicitudes_db['estadisticas']
        mensaje += (
            f"\n📊 *Estadísticas:*\n"
            f"📊 Total: {stats['total_solicitudes']} | "
            f"⏳ Pendientes: {stats['solicitudes_pendientes']} | "
            f"✅ Completadas: {stats['solicitudes_completadas']}\n\n"
            f"💡 Filtros: `/adminrequests PENDIENTE` • `/adminrequests COMPLETADO`"
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
                        f"💬 *Tu solicitud:* {DatabaseManager.acortar_nombre(solicitud['contenido'], 80)}\n\n"
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
    # 🔧 MÉTODOS AUXILIARES - MEJORADOS
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

    async def publicar_en_canal(self, context: ContextTypes.DEFAULT_TYPE, texto: str = None, file_id: str = None, file_type: str = None) -> bool:
        """Publica contenido en el canal configurado - CORREGIDO"""
        try:
            # Verificar que el canal esté configurado
            if not Config.CANAL_ID:
                logger.error("❌ ID del canal no configurado")
                return False
            
            if file_id and file_type:
                # Limitar caption a 1024 caracteres
                caption = texto[:1021] + "..." if texto and len(texto) > 1024 else texto
                
                # Enviar según el tipo de archivo
                if file_type == 'photo':
                    await context.bot.send_photo(
                        chat_id=Config.CANAL_ID, 
                        photo=file_id,
                        caption=caption,
                        parse_mode="Markdown"
                    )
                elif file_type == 'video':
                    await context.bot.send_video(
                        chat_id=Config.CANAL_ID, 
                        video=file_id,
                        caption=caption,
                        parse_mode="Markdown"
                    )
                elif file_type == 'animation':
                    await context.bot.send_animation(
                        chat_id=Config.CANAL_ID, 
                        animation=file_id,
                        caption=caption,
                        parse_mode="Markdown"
                    )
                elif file_type == 'audio':
                    await context.bot.send_audio(
                        chat_id=Config.CANAL_ID, 
                        audio=file_id,
                        caption=caption,
                        parse_mode="Markdown"
                    )
                elif file_type == 'voice':
                    await context.bot.send_voice(
                        chat_id=Config.CANAL_ID, 
                        voice=file_id,
                        caption=caption,
                        parse_mode="Markdown"
                    )
                else:  # document por defecto
                    await context.bot.send_document(
                        chat_id=Config.CANAL_ID, 
                        document=file_id,
                        caption=caption,
                        parse_mode="Markdown"
                    )
            elif texto:
                # Solo texto - dividir si es muy largo
                if len(texto) > 4000:
                    chunks = [texto[i:i+4000] for i in range(0, len(texto), 4000)]
                    for i, chunk in enumerate(chunks):
                        await context.bot.send_message(
                            chat_id=Config.CANAL_ID,
                            text=chunk,
                            parse_mode="Markdown"
                        )
                        if i < len(chunks) - 1:
                            await asyncio.sleep(1)
                else:
                    await context.bot.send_message(
                        chat_id=Config.CANAL_ID,
                        text=texto,
                        parse_mode="Markdown"
                    )
            else:
                logger.error("❌ No hay contenido para publicar")
                return False
                
            logger.info("✅ Mensaje enviado al canal exitosamente")
            return True
            
        except TelegramError as e:
            error_type = str(e).lower()
            if "chat not found" in error_type:
                logger.error(f"❌ Canal no encontrado (ID: {Config.CANAL_ID})")
            elif "forbidden" in error_type:
                logger.error(f"❌ Bot sin permisos en el canal (ID: {Config.CANAL_ID})")
            elif "bad request" in error_type:
                logger.error(f"❌ Solicitud incorrecta: {e}")
            else:
                logger.error(f"❌ Error de Telegram al enviar al canal: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Error inesperado al publicar en canal: {e}")
            return False

    # ═══════════════════════════════════════════════════════════════
    # 🚀 COMANDOS PRINCIPALES - MEJORADOS
    # ═══════════════════════════════════════════════════════════════

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /start mejorado"""
        user_info = f"Usuario: {update.effective_user.first_name} (ID: {update.effective_user.id})"
        logger.info(f"🚀 Comando /start ejecutado por {user_info}")
        
        keyboard = []
        
        # Botones para usuarios regulares
        keyboard.extend([
            [InlineKeyboardButton("🔍 Mis solicitudes", callback_data="my_requests")],
            [InlineKeyboardButton("📚 Estadísticas", callback_data="stats"), 
             InlineKeyboardButton("ℹ️ Ayuda", callback_data="help")]
        ])
        
        # Botones adicionales para admin en layout compacto
        if self.es_admin(update.effective_user.id):
            keyboard.insert(0, [
                InlineKeyboardButton("📋 Archivos", callback_data="list"),
                InlineKeyboardButton("📥 Solicitudes", callback_data="admin_requests")
            ])
            keyboard.insert(1, [
                InlineKeyboardButton("📢 Publicar", callback_data="create_post"),
                InlineKeyboardButton("🔧 Inválidos", callback_data="invalid")
            ])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Estadísticas rápidas
        total_archivos = len(self.db['archivos'])
        total_solicitudes = self.solicitudes_db['estadisticas']['total_solicitudes']
        solicitudes_pendientes = self.solicitudes_db['estadisticas']['solicitudes_pendientes']
        
        mensaje = (
            "🤖 *Bot de Gestión de Archivos v1.3*\n\n"
            "🔍 *Buscar:* `/search <palabra>`\n"
            "📥 *Solicitar:* `/request <enlace o descripción>`\n"
            "📊 *Estado:* `/mystatus`\n"
            "📁 *Enviar:* Arrastra cualquier archivo\n"
        )
        
        # Comandos adicionales para admin
        if self.es_admin(update.effective_user.id):
            mensaje += "📢 *Publicar:* `/post`\n"
        
        mensaje += (
            f"\n👥 *Rol:* {'🔧 Administrador' if self.es_admin(update.effective_user.id) else '👤 Usuario'}\n"
            f"📁 *Archivos:* {total_archivos} | 📋 *Solicitudes:* {total_solicitudes}\n"
        )
        
        if self.es_admin(update.effective_user.id) and solicitudes_pendientes > 0:
            mensaje += f"🔔 *Pendientes:* {solicitudes_pendientes}\n"
        
        mensaje += "\n💡 Usa los botones para navegar rápidamente"
        
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
            
            # Icono de estado y nombres cortos
            if enlace.startswith("file_id:"):
                estado_icono = "✅"
            elif enlace == 'ENLACE_INVALIDO_MIGRAR':
                estado_icono = "⚠️"
            else:
                estado_icono = "🔗"
            
            nombre_corto = DatabaseManager.acortar_nombre(nombre_original, 30)
            clave_corta = DatabaseManager.acortar_nombre(palabra, 25)
            
            mensaje += f"{estado_icono} *{i}. {nombre_corto}*\n"
            mensaje += f"🔑 `{clave_corta}`"
            
            # Información adicional en línea
            info_extra = []
            if fecha:
                info_extra.append(f"📅 {fecha}")
            if tamaño_mb > 0:
                info_extra.append(f"💾 {tamaño_mb:.1f}MB")
            if relevancia < 100:
                info_extra.append(f"🎯 {relevancia:.0f}%")
            
            if info_extra:
                mensaje += f" • {' • '.join(info_extra)}"
            mensaje += "\n"
            
            # Enlace de descarga
            if enlace.startswith("file_id:"):
                file_id = enlace.replace("file_id:", "")
                enlace_descarga = await self.obtener_enlace_descarga(file_id, context)
                if enlace_descarga:
                    mensaje += f"📎 [⬇️ Descargar]({enlace_descarga})\n"
                else:
                    mensaje += "📎 Disponible (contacta admin si hay problemas)\n"
            elif enlace == 'ENLACE_INVALIDO_MIGRAR':
                mensaje += "⚠️ Requiere reenvío\n"
            elif enlace.startswith("http"):
                mensaje += f"🔗 [🌐 Enlace directo]({enlace})\n"
            else:
                mensaje += f"🔗 {DatabaseManager.acortar_nombre(enlace, 40)}\n"
            
            mensaje += "──────────────────\n"

        mensaje += f"\n💡 ¿No encontraste lo que buscas? `/request {texto}`"

        await self.enviar_mensaje_largo(update, mensaje, "Markdown", context)

    async def list_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando /list MEJORADO con diseño compacto y ordenado"""
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
            return

        archivos = self.db['archivos']
        
        if not archivos:
            await update.message.reply_text("📁 No hay archivos almacenados en la base de datos.")
            return

        # Filtros mejorados
        filtro = None
        if context.args:
            arg = context.args[0].upper()
            if arg in ['VALIDOS', 'V']:
                filtro = 'VALIDOS'
            elif arg in ['INVALIDOS', 'I']:
                filtro = 'INVALIDOS'
            elif arg in ['ANTIGUOS', 'A']:
                filtro = 'ANTIGUOS'
        
        archivos_procesados = []
        contadores = {"VALIDO": 0, "INVALIDO": 0, "ANTIGUO": 0}
        
        for clave, info in archivos.items():
            if isinstance(info, dict):
                fecha = info.get('fecha_agregado', '1900-01-01T00:00:00')
                nombre_original = info.get('nombre_original', clave)
                enlace = info.get('enlace', '')
                tamaño = info.get('tamaño', 0)
                
                if enlace.startswith('file_id:'):
                    estado = "VALIDO"
                    estado_icono = "✅"
                elif enlace == 'ENLACE_INVALIDO_MIGRAR':
                    estado = "INVALIDO"
                    estado_icono = "⚠️"
                else:
                    estado = "ANTIGUO"
                    estado_icono = "🔗"
                
                contadores[estado] += 1
                
                # Aplicar filtro
                if filtro and not (
                    (filtro == 'VALIDOS' and estado == 'VALIDO') or
                    (filtro == 'INVALIDOS' and estado == 'INVALIDO') or
                    (filtro == 'ANTIGUOS' and estado == 'ANTIGUO')
                ):
                    continue
                    
                archivos_procesados.append({
                    'fecha': fecha,
                    'clave': clave,
                    'nombre': nombre_original,
                    'icono': estado_icono,
                    'estado': estado,
                    'tamaño': tamaño
                })
            else:
                contadores["ANTIGUO"] += 1
                if filtro and filtro != 'ANTIGUOS':
                    continue
                archivos_procesados.append({
                    'fecha': '1900-01-01T00:00:00',
                    'clave': clave,
                    'nombre': clave,
                    'icono': "🔗",
                    'estado': "ANTIGUO",
                    'tamaño': 0
                })
        
        # Ordenar por fecha (más recientes primero)
        archivos_procesados.sort(key=lambda x: x['fecha'], reverse=True)
        
        # Preparar mensaje con diseño mejorado
        filtro_texto = f" {filtro}S" if filtro else ""
        mensaje = f"📋 *Archivos{filtro_texto} ({len(archivos_procesados)} de {len(archivos)})*\n\n"
        
        # Mostrar estadísticas compactas
        mensaje += (
            f"📊 ✅ {contadores['VALIDO']} • ⚠️ {contadores['INVALIDO']} • 🔗 {contadores['ANTIGUO']}\n\n"
        )
        
        # Lista de archivos con formato compacto y elegante
        for i, archivo in enumerate(archivos_procesados[:15], 1):
            nombre_corto = DatabaseManager.acortar_nombre(archivo['nombre'], 28)
            clave_corta = DatabaseManager.acortar_nombre(archivo['clave'], 20)
            fecha_corta = archivo['fecha'][:10] if len(archivo['fecha']) >= 10 else "Sin fecha"
            tamaño_mb = archivo['tamaño'] / 1024 / 1024 if archivo['tamaño'] > 0 else 0
            
            mensaje += f"{archivo['icono']} *{i:02d}.* {nombre_corto}\n"
            mensaje += f"     🔑 `{clave_corta}`"
            
            # Información adicional en una sola línea
            info_items = [f"📅 {fecha_corta}"]
            if tamaño_mb > 0:
                if tamaño_mb >= 1024:
                    info_items.append(f"💾 {tamaño_mb/1024:.1f}GB")
                else:
                    info_items.append(f"💾 {tamaño_mb:.1f}MB")
            
            mensaje += f" • {' • '.join(info_items)}\n"
            mensaje += "──────────────────\n"
        
        if len(archivos_procesados) > 15:
            mensaje += f"\n📄 *Mostrando 15 de {len(archivos_procesados)} archivos*\n"
        
        mensaje += (
            f"\n💡 *Filtros rápidos:*\n"
            f"`/list V` (válidos) • `/list I` (inválidos) • `/list A` (antiguos)"
        )

        await self.enviar_mensaje_largo(update, mensaje, "Markdown", context)

    async def recibir_archivo(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Procesar archivos enviados - MEJORADO CON PUBLICACIÓN CORREGIDA"""
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
            
            # Mensaje de confirmación mejorado y compacto
            await update.message.reply_text(
                f"✅ *Archivo guardado exitosamente*\n\n"
                f"📁 {DatabaseManager.acortar_nombre(nombre_archivo, 35)}\n"
                f"🔑 `{clave}`\n"
                f"💾 {tamaño_mb:.2f} MB • 📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}\n\n"
                f"🔍 Busca con: `/search {clave.split('_')[0]}`",
                parse_mode="Markdown"
            )

            # Publicar en canal con formato mejorado y manejo de errores
            try:
                nombre_display = DatabaseManager.acortar_nombre(nombre_archivo, 40)
                
                caption = (
                    f"📂 *Nuevo archivo disponible*\n\n"
                    f"📁 `{nombre_display}`\n"
                    f"🔍 *Buscar con:* `{clave.split('_')[0]}`\n"
                    f"💾 {tamaño_mb:.1f} MB • 👤 {update.effective_user.first_name}\n"
                    f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
                )
                
                # Usar el método corregido de publicación
                success = await self.publicar_en_canal(
                    context, 
                    texto=caption, 
                    file_id=file_id, 
                    file_type='document'
                )
                
                if not success:
                    await update.message.reply_text(
                        f"⚠️ *Archivo guardado correctamente*\n"
                        f"❌ No se pudo publicar en el canal\n\n"
                        f"🔍 *Posibles causas:*\n"
                        f"• Bot sin permisos de administrador\n"
                        f"• Canal ID incorrecto: `{Config.CANAL_ID}`\n"
                        f"• Canal privado sin acceso\n\n"
                        f"💡 Contacta al administrador del canal"
                    )
                
            except Exception as e:
                logger.error(f"❌ Error al publicar en canal: {e}")
                await update.message.reply_text(
                    f"✅ Archivo guardado correctamente\n"
                    f"⚠️ Error al publicar en el canal: {str(e)}"
                )
        else:
            await update.message.reply_text("❌ Error al guardar el archivo en la base de datos.")

    async def show_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None):
        """Mostrar estadísticas completas del bot - DISEÑO MEJORADO"""
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
        
        tamaño_total_gb = tamaño_total / 1024 / 1024 / 1024
        tamaño_total_mb = tamaño_total / 1024 / 1024
        
        # Formato compacto y elegante
        mensaje = (
            "📊 *Estadísticas del Bot v1.3*\n"
            "═══════════════════════════\n\n"
            f"🗄️ *ARCHIVOS* ({total_archivos} total)\n"
            f"✅ Válidos: {archivos_validos} • ⚠️ Inválidos: {archivos_invalidos} • 🔗 Antiguos: {archivos_antiguos}\n"
            f"💾 Espacio: {tamaño_total_gb:.2f} GB ({tamaño_total_mb:.1f} MB)\n\n"
            f"📥 *SOLICITUDES*\n"
            f"📋 Total: {req_stats['total_solicitudes']} • ⏳ Pendientes: {req_stats['solicitudes_pendientes']}\n"
            f"✅ Completadas: {req_stats['solicitudes_completadas']} • ❌ Rechazadas: {req_stats['total_solicitudes'] - req_stats['solicitudes_pendientes'] - req_stats['solicitudes_completadas']}\n\n"
            f"🔍 *ACTIVIDAD*\n"
            f"🔍 Búsquedas: {db_stats['total_busquedas']} • 📤 Archivos agregados: {db_stats['archivos_agregados']}\n\n"
            f"🤖 *SISTEMA*\n"
            f"📅 Versión: v{self.db.get('version', '1.0')} • ⏰ {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
            f"📺 Canal: `{Config.CANAL_ID}`"
        )
        
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")
        else:
            await update.message.reply_text(mensaje, parse_mode="Markdown")

    async def show_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE = None):
        """Mostrar ayuda completa del bot - DISEÑO MEJORADO"""
        mensaje = (
            "ℹ️ *Guía del Bot v1.3*\n"
            "═══════════════════════\n\n"
            "🔍 *BÚSQUEDA*\n"
            "`/search <palabra>` - Buscar archivos\n"
            "Ejemplo: `/search xiaomi redmi`\n\n"
            "📥 *SOLICITUDES*\n"
            "`/request <enlace|descripción>` - Solicitar archivo\n"
            "`/mystatus` - Ver mis solicitudes\n\n"
            "📤 *ENVÍO*\n"
            "Arrastra cualquier archivo al chat\n"
            "Se publica automáticamente en el canal\n\n"
        )
        
        # Comandos de admin en sección separada
        if self.es_admin(update.effective_user.id if hasattr(update, 'effective_user') else (update.callback_query.from_user.id if hasattr(update, 'callback_query') else 0)):
            mensaje += (
                "👨‍💼 *ADMINISTRADOR*\n"
                "`/list [V|I|A]` - Lista archivos (Válidos|Inválidos|Antiguos)\n"
                "`/adminrequests [estado]` - Gestionar solicitudes\n"
                "`/respond <ID> <respuesta>` - Responder solicitud\n"
                "`/delete <clave>` - Eliminar archivo\n"
                "`/fixfiles` - Ver archivos inválidos\n"
                "`/post` - Crear publicación en canal\n\n"
            )
        
        mensaje += (
            "📋 *FORMATOS SOPORTADOS*\n"
            "🖼️ Imágenes • 🎥 Videos • 📄 Documentos\n"
            "🎵 Audio • 📦 Comprimidos • 📱 ROMs\n\n"
            "💡 *CONSEJOS*\n"
            "• Usa palabras clave específicas\n"
            "• Búsquedas no distinguen mayúsculas\n"
            "• Solicita si no encuentras algo\n"
            "• Revisa `/mystatus` regularmente"
        )
        
        if hasattr(update, 'callback_query') and update.callback_query:
            await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")
        else:
            await update.message.reply_text(mensaje, parse_mode="Markdown")

    # ═══════════════════════════════════════════════════════════════
    # 🎛️ MANEJADOR DE BOTONES - MEJORADO
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
            [InlineKeyboardButton("📷 Con multimedia", callback_data="post_with_media")],
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
        """Maneja el botón de mis solicitudes - DISEÑO MEJORADO"""
        user_id = update.callback_query.from_user.id
        
        mis_solicitudes = [
            sol for sol in self.solicitudes_db['solicitudes'].values()
            if sol['usuario_id'] == user_id
        ]
        
        if not mis_solicitudes:
            await update.callback_query.edit_message_text(
                "📭 *No tienes solicitudes*\n\n"
                "💡 Usa `/request <enlace o descripción>`\n\n"
                "*Ejemplos:*\n"
                "• `/request https://ejemplo.com/archivo.zip`\n"
                "• `/request ROM para Xiaomi Mi 11`",
                parse_mode="Markdown"
            )
            return
        
        # Estadísticas rápidas
        mis_solicitudes.sort(key=lambda x: x['fecha_creacion'], reverse=True)
        pendientes = sum(1 for s in mis_solicitudes if s['estado'] == 'PENDIENTE')
        completadas = sum(1 for s in mis_solicitudes if s['estado'] == 'COMPLETADO')
        rechazadas = sum(1 for s in mis_solicitudes if s['estado'] == 'RECHAZADO')
        
        mensaje = (
            f"📊 *Tus Solicitudes ({len(mis_solicitudes)})*\n"
            f"⏳ {pendientes} • ✅ {completadas} • ❌ {rechazadas}\n\n"
        )
        
        # Lista compacta de solicitudes
        for i, sol in enumerate(mis_solicitudes[:8], 1):
            estado_icono = Config.REQUEST_STATES.get(sol['estado'], '❓')
            fecha = datetime.fromisoformat(sol['fecha_creacion']).strftime('%d/%m')
            contenido_corto = DatabaseManager.acortar_nombre(sol['contenido'], 45)
            
            mensaje += f"{estado_icono} `{sol['id']}` • 📅 {fecha}\n"
            mensaje += f"💬 {contenido_corto}\n"
            
            if sol.get('respuesta_admin'):
                respuesta_corta = DatabaseManager.acortar_nombre(sol['respuesta_admin'], 40)
                mensaje += f"👨‍💼 {respuesta_corta}\n"
            
            mensaje += "──────────────────\n"
        
        if len(mis_solicitudes) > 8:
            mensaje += f"\n📄 *Mostrando 8 de {len(mis_solicitudes)} solicitudes*\n"
        
        mensaje += "\n💡 `/mystatus` para ver detalles completos"
        
        await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")

    async def handle_list_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja el botón de lista de archivos (admin) - DISEÑO MEJORADO"""
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
        
        # Obtener archivos más recientes con información completa
        archivos_recientes = []
        tamaño_total = 0
        
        for clave, info in archivos.items():
            if isinstance(info, dict):
                fecha = info.get('fecha_agregado', '1900-01-01T00:00:00')
                nombre = info.get('nombre_original', clave)
                tamaño = info.get('tamaño', 0)
                enlace = info.get('enlace', '')
                
                tamaño_total += tamaño
                
                estado = "✅" if enlace.startswith('file_id:') else ("⚠️" if enlace == 'ENLACE_INVALIDO_MIGRAR' else "🔗")
                
                archivos_recientes.append((fecha, nombre, clave, tamaño, estado))
        
        archivos_recientes.sort(key=lambda x: x[0], reverse=True)
        tamaño_total_gb = tamaño_total / 1024 / 1024 / 1024
        
        mensaje = (
            f"📋 *Resumen de Archivos*\n"
            f"═══════════════════════\n\n"
            f"📊 *Total:* {len(archivos)} archivos\n"
            f"✅ {validos} • ⚠️ {invalidos} • 🔗 {antiguos}\n"
            f"💾 *Espacio:* {tamaño_total_gb:.2f} GB\n\n"
        )
        
        if archivos_recientes:
            mensaje += "*📁 Últimos 10 archivos:*\n\n"
            for i, (fecha, nombre, clave, tamaño, estado) in enumerate(archivos_recientes[:10], 1):
                fecha_corta = fecha[:10] if len(fecha) >= 10 else "Sin fecha"
                nombre_corto = DatabaseManager.acortar_nombre(nombre, 25)
                clave_corta = DatabaseManager.acortar_nombre(clave, 20)
                tamaño_mb = tamaño / 1024 / 1024 if tamaño > 0 else 0
                
                mensaje += f"{estado} *{i:02d}.* {nombre_corto}\n"
                mensaje += f"     🔑 `{clave_corta}` • 📅 {fecha_corta}"
                
                if tamaño_mb > 0:
                    if tamaño_mb >= 1024:
                        mensaje += f" • 💾 {tamaño_mb/1024:.1f}GB"
                    else:
                        mensaje += f" • 💾 {tamaño_mb:.1f}MB"
                
                mensaje += "\n──────────────────\n"
        
        mensaje += "\n💡 `/list V` válidos • `/list I` inválidos • `/list A` antiguos"
        
        await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")

    async def handle_admin_requests_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja el botón de solicitudes de admin - DISEÑO MEJORADO"""
        todas_solicitudes = list(self.solicitudes_db['solicitudes'].values())
        
        if not todas_solicitudes:
            await update.callback_query.edit_message_text("📭 No hay solicitudes registradas.")
            return

        # Filtrar solicitudes pendientes
        pendientes = [s for s in todas_solicitudes if s['estado'] == 'PENDIENTE']
        completadas = [s for s in todas_solicitudes if s['estado'] == 'COMPLETADO']
        
        mensaje = (
            f"📥 *Panel de Solicitudes*\n"
            f"═══════════════════════\n\n"
            f"⏳ *Pendientes:* {len(pendientes)}\n"
            f"✅ *Completadas:* {len(completadas)}\n"
            f"📊 *Total histórico:* {len(todas_solicitudes)}\n\n"
        )
        
        if pendientes:
            mensaje += "*🔔 Solicitudes pendientes:*\n\n"
            for i, sol in enumerate(pendientes[:6], 1):
                tipo_icono = "🔗" if sol['tipo'] == "ENLACE" else "📝"
                fecha = datetime.fromisoformat(sol['fecha_creacion']).strftime('%d/%m')
                usuario_corto = DatabaseManager.acortar_nombre(sol['usuario_nombre'], 12)
                contenido_corto = DatabaseManager.acortar_nombre(sol['contenido'], 35)
                
                mensaje += f"{tipo_icono} `{sol['id']}` • 📅 {fecha}\n"
                mensaje += f"👤 {usuario_corto} • 💬 {contenido_corto}\n"
                mensaje += "──────────────────\n"
            
            if len(pendientes) > 6:
                mensaje += f"\n📄 *Mostrando 6 de {len(pendientes)} pendientes*\n"
        else:
            mensaje += "✅ *¡No hay solicitudes pendientes!*\n"
        
        mensaje += f"\n💡 `/adminrequests` para vista completa • `/adminrequests PENDIENTE` para filtrar"
        
        await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")

    async def handle_invalid_files_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Maneja el botón de archivos inválidos - DISEÑO MEJORADO"""
        archivos_invalidos = []
        for clave, info in self.db['archivos'].items():
            if isinstance(info, dict) and info.get('enlace') == 'ENLACE_INVALIDO_MIGRAR':
                archivos_invalidos.append((clave, info))

        if not archivos_invalidos:
            await update.callback_query.edit_message_text(
                "✅ *¡Excelente!*\n\n"
                "No hay archivos con enlaces inválidos.\n"
                "Todos los enlaces están funcionando correctamente."
            )
            return

        mensaje = (
            f"🚨 *Archivos Inválidos*\n"
            f"═══════════════════════\n\n"
            f"⚠️ *Total:* {len(archivos_invalidos)} archivos\n"
            f"🔧 *Acción requerida:* Reenvío manual\n\n"
        )
        
        for i, (clave, info) in enumerate(archivos_invalidos[:12], 1):
            nombre = info.get('nombre_original', clave)
            fecha = info.get('fecha_agregado', '')[:10] if info.get('fecha_agregado') else 'S/F'
            agregado_por = info.get('agregado_por_nombre', 'Desc.')
            
            nombre_corto = DatabaseManager.acortar_nombre(nombre, 25)
            clave_corta = DatabaseManager.acortar_nombre(clave, 18)
            usuario_corto = DatabaseManager.acortar_nombre(agregado_por, 10)
            
            mensaje += f"⚠️ *{i:02d}.* {nombre_corto}\n"
            mensaje += f"     🔑 `{clave_corta}` • 📅 {fecha} • 👤 {usuario_corto}\n"
            mensaje += "──────────────────\n"

        if len(archivos_invalidos) > 12:
            mensaje += f"\n📄 *Mostrando 12 de {len(archivos_invalidos)} archivos*\n"

        mensaje += (
            f"\n🔧 *Soluciones:*\n"
            f"1. 🔄 Reenvía archivos originales\n"
            f"2. 🗑️ `/delete <clave>` para eliminar\n"
            f"3. 📞 Contacta usuarios para reenvío\n"
            f"4. 🔍 `/fixfiles` para lista completa"
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
            # Mensaje compacto de confirmación
            contenido_corto = DatabaseManager.acortar_nombre(solicitud['contenido'], 80)
            
            mensaje = (
                f"🔄 *Solicitud en proceso*\n\n"
                f"🆔 `{solicitud_id}` • 👤 {solicitud['usuario_nombre']}\n"
                f"💬 {contenido_corto}\n\n"
                f"✅ Estado: *PROCESANDO*\n\n"
                f"💡 `/respond {solicitud_id} <mensaje>` para completar"
            )
            
            await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")
            
            # Notificar al usuario
            try:
                await context.bot.send_message(
                    chat_id=solicitud['usuario_id'],
                    text=(
                        f"🔄 *Solicitud en proceso*\n\n"
                        f"🆔 `{solicitud_id}`\n"
                        f"💬 {DatabaseManager.acortar_nombre(solicitud['contenido'], 100)}\n\n"
                        f"✅ Un administrador está procesando tu solicitud.\n"
                        f"🔔 Recibirás notificación cuando esté lista."
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
            # Mensaje compacto de confirmación
            contenido_corto = DatabaseManager.acortar_nombre(solicitud['contenido'], 80)
            
            mensaje = (
                f"❌ *Solicitud rechazada*\n\n"
                f"🆔 `{solicitud_id}` • 👤 {solicitud['usuario_nombre']}\n"
                f"💬 {contenido_corto}\n\n"
                f"❌ Estado: *RECHAZADO*\n"
                f"📅 {datetime.now().strftime('%d/%m/%Y %H:%M')}"
            )
            
            await update.callback_query.edit_message_text(mensaje, parse_mode="Markdown")
            
            # Notificar al usuario
            try:
                await context.bot.send_message(
                    chat_id=solicitud['usuario_id'],
                    text=(
                        f"❌ *Solicitud rechazada*\n\n"
                        f"🆔 `{solicitud_id}`\n"
                        f"💬 {DatabaseManager.acortar_nombre(solicitud['contenido'], 100)}\n\n"
                        f"❌ Tu solicitud ha sido rechazada.\n"
                        f"💡 Puedes enviar una nueva con `/request`"
                    ),
                    parse_mode="Markdown"
                )
            except Exception as e:
                logger.error(f"❌ Error al notificar usuario sobre rechazo: {e}")
        else:
            await update.callback_query.edit_message_text("❌ Error al procesar el rechazo.")

    # ═══════════════════════════════════════════════════════════════
    # 🗑️ COMANDO DE ELIMINACIÓN Y OTROS UTILITARIOS - MEJORADOS
    # ═══════════════════════════════════════════════════════════════

    async def delete_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando para eliminar archivos (solo admin) - MEJORADO"""
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
            return

        if not context.args:
            await update.message.reply_text(
                "🗑️ *Eliminar archivos*\n\n"
                "`/delete <clave_archivo>`\n\n"
                "*Ejemplos:*\n"
                "• `/delete honor_magic_5.zip`\n"
                "• `/delete xiaomi_redmi_note_12`\n\n"
                "⚠️ *Acción irreversible*\n"
                "💡 `/list` para ver claves disponibles",
                parse_mode="Markdown"
            )
            return

        clave = " ".join(context.args).strip()
        
        if clave not in self.db['archivos']:
            # Buscar claves similares
            claves_similares = [c for c in self.db['archivos'].keys() if clave.lower() in c.lower()]
            
            mensaje = f"❌ *Archivo no encontrado*\n\n🔍 No existe: `{clave}`\n"
            
            if claves_similares:
                mensaje += f"\n💡 *¿Quisiste decir?*\n"
                for similar in claves_similares[:5]:
                    similar_corto = DatabaseManager.acortar_nombre(similar, 30)
                    mensaje += f"• `{similar_corto}`\n"
            
            mensaje += f"\n📋 `/list` para ver todos los archivos"
            
            await update.message.reply_text(mensaje, parse_mode="Markdown")
            return

        # Obtener información del archivo antes de eliminarlo
        info_archivo = self.db['archivos'][clave]
        if isinstance(info_archivo, dict):
            nombre_original = info_archivo.get('nombre_original', clave)
            fecha_agregado = info_archivo.get('fecha_agregado', '')[:10]
            tamaño = info_archivo.get('tamaño', 0)
            agregado_por = info_archivo.get('agregado_por_nombre', 'Desconocido')
        else:
            nombre_original = clave
            fecha_agregado = 'Desconocida'
            tamaño = 0
            agregado_por = 'Desconocido'

        # Eliminar archivo
        del self.db['archivos'][clave]
        
        if self.db_manager.guardar_db(self.db):
            tamaño_mb = tamaño / 1024 / 1024 if tamaño > 0 else 0
            nombre_corto = DatabaseManager.acortar_nombre(nombre_original, 35)
            
            await update.message.reply_text(
                f"🗑️ *Archivo eliminado*\n\n"
                f"📁 {nombre_corto}\n"
                f"🔑 `{clave}`\n"
                f"📅 {fecha_agregado} • 👤 {agregado_por}\n"
                f"💾 {tamaño_mb:.2f} MB\n\n"
                f"✅ Eliminado permanentemente",
                parse_mode="Markdown"
            )
            logger.info(f"🗑️ Archivo eliminado: {clave} por admin {update.effective_user.id}")
        else:
            await update.message.reply_text("❌ Error al eliminar el archivo de la base de datos.")

    async def fix_invalid_files(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Comando para admin: mostrar archivos inválidos - DISEÑO MEJORADO"""
        if not self.es_admin(update.effective_user.id):
            await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
            return

        archivos_invalidos = []
        for clave, info in self.db['archivos'].items():
            if isinstance(info, dict) and info.get('enlace') == 'ENLACE_INVALIDO_MIGRAR':
                archivos_invalidos.append((clave, info))

        if not archivos_invalidos:
            await update.message.reply_text(
                "✅ *Estado perfecto*\n\n"
                "No hay archivos con enlaces inválidos.\n"
                "Todos los archivos están funcionando correctamente."
            )
            return

        mensaje = (
            f"🚨 *Archivos Inválidos*\n"
            f"═══════════════════════\n\n"
            f"⚠️ *Total:* {len(archivos_invalidos)} archivos\n"
            f"🔧 *Requieren:* Reenvío manual\n\n"
        )
        
        for i, (clave, info) in enumerate(archivos_invalidos[:15], 1):
            nombre = info.get('nombre_original', clave)
            fecha = info.get('fecha_agregado', '')[:10] if info.get('fecha_agregado') else 'S/F'
            agregado_por = info.get('agregado_por_nombre', 'Desc.')
            enlace_original = info.get('enlace_original', '')
            
            nombre_corto = DatabaseManager.acortar_nombre(nombre, 25)
            clave_corta = DatabaseManager.acortar_nombre(clave, 18)
            usuario_corto = DatabaseManager.acortar_nombre(agregado_por, 8)
            
            mensaje += f"⚠️ *{i:02d}.* {nombre_corto}\n"
            mensaje += f"     🔑 `{clave_corta}` • 📅 {fecha} • 👤 {usuario_corto}\n"
            
            if enlace_original and len(enlace_original) > 10:
                enlace_corto = DatabaseManager.acortar_nombre(enlace_original, 40)
                mensaje += f"     🔗 {enlace_corto}\n"
            
            mensaje += "──────────────────\n"

        if len(archivos_invalidos) > 15:
            mensaje += f"\n📄 *Mostrando 15 de {len(archivos_invalidos)} archivos*\n"

        mensaje += (
            f"\n🔧 *Plan de acción:*\n"
            f"1. 🔄 Reenvía archivos originales al bot\n"
            f"2. 🗑️ `/delete <clave>` para limpiar inválidos\n"
            f"3. 📞 Contacta usuarios para reenvío\n\n"
            f"💡 *Causa:* URLs temporales de Telegram que expiraron"
        )

        await self.enviar_mensaje_largo(update, mensaje, "Markdown", context)

    # ═══════════════════════════════════════════════════════════════
    # 🚨 MANEJADOR DE ERRORES MEJORADO
    # ═══════════════════════════════════════════════════════════════

    async def error_handler(self, update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Maneja errores del bot de forma elegante"""
        logger.error("❌ Excepción en el manejo de actualización:", exc_info=context.error)
        
        # Intentar enviar mensaje de error al usuario si es posible
        try:
            if isinstance(update, Update) and update.effective_message:
                error_id = datetime.now().strftime('%Y%m%d_%H%M%S')
                
                # Determinar tipo de error para mensaje específico
                error_str = str(context.error).lower()
                if "timeout" in error_str:
                    error_msg = (
                        "⏰ *Timeout - Conexión lenta*\n\n"
                        "🔄 Inténtalo de nuevo en unos segundos.\n"
                        f"🆔 Error ID: {error_id}"
                    )
                elif "forbidden" in error_str:
                    error_msg = (
                        "🚫 *Error de permisos*\n\n"
                        "🔧 Verifica que el bot tenga los permisos necesarios.\n"
                        f"🆔 Error ID: {error_id}"
                    )
                elif "bad request" in error_str:
                    error_msg = (
                        "❌ *Solicitud incorrecta*\n\n"
                        "🔄 Revisa el formato e inténtalo de nuevo.\n"
                        f"🆔 Error ID: {error_id}"
                    )
                else:
                    error_msg = (
                        "❌ *Error inesperado*\n\n"
                        "🔄 Inténtalo de nuevo en unos momentos.\n"
                        f"💡 Si persiste, contacta al administrador.\n"
                        f"🆔 Error ID: {error_id}"
                    )
                
                await update.effective_message.reply_text(error_msg, parse_mode="Markdown")
        except Exception:
            # Si no se puede enviar el mensaje de error, solo registrar
            logger.error("❌ No se pudo enviar mensaje de error al usuario")
            pass

# ═══════════════════════════════════════════════════════════════════
# 🚀 FUNCIÓN PRINCIPAL MEJORADA
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
                    MessageHandler(
                        (filters.PHOTO | filters.VIDEO | filters.ANIMATION | 
                         filters.AUDIO | filters.VOICE | filters.Document.ALL) & ~filters.COMMAND, 
                        bot.handle_post_media
                    ),
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
        
        # Manejadores de contenido mejorados
        app.add_handler(CallbackQueryHandler(bot.button_handler))
        app.add_handler(MessageHandler(filters.Document.ALL, bot.recibir_archivo))
        
        # Manejador de errores
        app.add_error_handler(bot.error_handler)

        # ═══════════════════════════════════════════════════════════
        # 📊 INFORMACIÓN DE INICIO MEJORADA
        # ═══════════════════════════════════════════════════════════
        
        logger.info("🤖 Bot iniciado exitosamente")
        print("✅ Bot en ejecución correctamente")
        print("\n" + "═" * 65)
        print("📋 COMANDOS DISPONIBLES:")
        print("═" * 65)
        print("👥 USUARIOS:")
        print("   🚀 /start      - Menú principal interactivo")
        print("   🔍 /search     - Buscar archivos por palabra clave")
        print("   📥 /request    - Solicitar archivo (enlace o descripción)")
        print("   📊 /mystatus   - Ver estado de mis solicitudes")
        print("   ℹ️  /help      - Guía completa de uso")
        print("\n👨‍💼 ADMINISTRADORES:")
        print("   📋 /list [V|I|A] - Lista archivos (Válidos|Inválidos|Antiguos)")
        print("   📥 /adminrequests [estado] - Gestionar todas las solicitudes")
        print("   📝 /respond <ID> <msg> - Responder a solicitud específica")
        print("   🗑️ /delete <clave> - Eliminar archivo permanentemente")
        print("   🔧 /fixfiles - Ver y gestionar archivos inválidos")
        print("   📢 /post - Sistema de publicaciones al canal")
        print("═" * 65)
        print("🔧 CONFIGURACIÓN:")
        print(f"   🆔 Admin ID: {Config.ADMIN_ID}")
        print(f"   📺 Canal ID: {Config.CANAL_ID}")
        print(f"   📁 Archivos en BD: {len(bot.db['archivos'])}")
        print(f"   📋 Total solicitudes: {bot.solicitudes_db['estadisticas']['total_solicitudes']}")
        print(f"   ⏳ Solicitudes pendientes: {bot.solicitudes_db['estadisticas']['solicitudes_pendientes']}")
        
        # Verificar archivos inválidos
        archivos_invalidos = sum(1 for info in bot.db['archivos'].values() 
                               if isinstance(info, dict) and info.get('enlace') == 'ENLACE_INVALIDO_MIGRAR')
        if archivos_invalidos > 0:
            print(f"   ⚠️ Archivos inválidos: {archivos_invalidos}")
        
        print("═" * 65)
        print("🚀 Bot listo para recibir comandos...")
        
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