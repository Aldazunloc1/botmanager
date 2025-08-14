import asyncio
import html
import re
import logging
import json
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

import httpx
from aiogram import Bot, Dispatcher
from aiogram.types import Message, KeyboardButton, ReplyKeyboardMarkup, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.config import Settings
from app.models.user import UserData
from app.services.database import UserDatabase
from app.services.imei_checker import IMEIChecker
from app.services.imei_validator import IMEIValidator
from app.services.response_formatter import ResponseFormatter
from app.services.autopinger import AutoPinger
from app.data.services_data import SERVICES_DATA

logger = logging.getLogger(__name__)


class IMEIStates(StatesGroup):
    waiting_for_service_category = State()
    waiting_for_service = State()
    waiting_for_imei = State()


class APIError(Exception):
    pass


class IMEIBot:
    def __init__(self, config: Settings):
        self.config = config
        self.bot = Bot(token=config.bot_token)
        self.dp = Dispatcher(storage=MemoryStorage())
        self.db = UserDatabase(config.users_db_path)
        self.autopinger = AutoPinger(config, self.bot)
        self.services_by_id = {s["id"]: s for s in SERVICES_DATA}
        self.services_by_category = {}
        
        # Load services from file if exists
        self._load_services()
        
        # Organize services by category
        for service in SERVICES_DATA:
            category = service["category"]
            if category not in self.services_by_category:
                self.services_by_category[category] = []
            self.services_by_category[category].append(service)
        
        self._setup_handlers()

    def _setup_handlers(self):
        """Setup bot handlers"""
        self.dp.message(CommandStart())(self.cmd_start)
        self.dp.message(Command("help"))(self.cmd_help)
        self.dp.message(Command("ping"))(self.cmd_ping)
        self.dp.message(Command("cancel"))(self.cmd_cancel)
        self.dp.message(Command("account"))(self.cmd_account)
        self.dp.message(Command("addbalance"))(self.cmd_add_balance)
        self.dp.message(Command("addservice"))(self.cmd_add_service)
        self.dp.message(Command("removeservice"))(self.cmd_remove_service)
        self.dp.message(Command("listservices"))(self.cmd_list_services)
        self.dp.message(Command("stats"))(self.cmd_stats)
        self.dp.message(Command("broadcast"))(self.cmd_broadcast)
        
        # AutoPinger commands
        self.dp.message(Command("autopinger"))(self.cmd_autopinger)
        self.dp.message(Command("autopingstart"))(self.cmd_autoping_start)
        self.dp.message(Command("autopingstop"))(self.cmd_autoping_stop)
        
        self.dp.callback_query()(self.handle_callback_query)
        
        # FSM handlers
        self.dp.message(IMEIStates.waiting_for_service_category)(self.handle_category_selection)
        self.dp.message(IMEIStates.waiting_for_service)(self.handle_category_selection)
        self.dp.message(IMEIStates.waiting_for_imei)(self.handle_imei_input)
        
        # Default handler
        self.dp.message()(self.handle_category_selection)

    def _is_owner(self, user_id: int) -> bool:
        return user_id == self.config.owner_id

    def _create_main_menu(self) -> ReplyKeyboardMarkup:
        buttons = [
            [KeyboardButton(text="🔍 Consultar IMEI")],
            [KeyboardButton(text="👤 Mi Cuenta"), KeyboardButton(text="❓ Ayuda")],
            [KeyboardButton(text="❌ Cancelar")]
        ]
        return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

    def _create_categories_keyboard(self) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        for category in self.services_by_category.keys():
            emoji = {"Apple": "🍎", "Android": "🤖", "General": "🔧"}.get(category, "📱")
            builder.button(text=f"{emoji} {category}", callback_data=f"cat_{category}")
        
        builder.button(text="❌ Cancelar", callback_data="cancel")
        builder.adjust(1)
        return builder.as_markup()

    def _create_services_keyboard(self, category: str) -> InlineKeyboardMarkup:
        builder = InlineKeyboardBuilder()
        
        services = self.services_by_category.get(category, [])
        for service in services[:15]:
            text = f"${service['price']} - {service['title']}"
            if len(text) > 64:
                text = f"${service['price']} - {service['title'][:50]}..."
            builder.button(text=text, callback_data=f"svc_{service['id']}")
        
        builder.button(text="🔙 Volver", callback_data="back_to_categories")
        builder.button(text="❌ Cancelar", callback_data="cancel")
        builder.adjust(1)
        return builder.as_markup()

    async def cmd_start(self, message: Message, state: FSMContext):
        await state.clear()
        
        user = message.from_user
        self.db.get_or_create_user(
            user_id=user.id, username=user.username,
            first_name=user.first_name, last_name=user.last_name
        )
        
        welcome_text = (
            "🤖 <b>¡Bienvenido al Bot IMEI Checker Pro!</b>\n\n"
            "Consulta información detallada de dispositivos móviles.\n\n"
            "📱 <b>Servicios disponibles:</b>\n"
            f"• 🍎 Apple ({len(self.services_by_category.get('Apple', []))} servicios)\n"
            f"• 🤖 Android ({len(self.services_by_category.get('Android', []))} servicios)\n"
            f"• 🔧 General ({len(self.services_by_category.get('General', []))} servicios)\n\n"
            "💡 <b>¿Qué deseas hacer?</b>"
        )
        
        await message.answer(welcome_text, reply_markup=self._create_main_menu(), parse_mode="HTML")

    async def cmd_help(self, message: Message):
        help_text = (
            "🆘 <b>Ayuda - Bot IMEI Checker Pro</b>\n\n"
            "<b>🔍 Cómo usar:</b>\n"
            "1️⃣ Selecciona 'Consultar IMEI'\n"
            "2️⃣ Elige categoría y servicio\n"
            "3️⃣ Envía el IMEI (8-17 dígitos)\n\n"
            "<b>💰 Precios:</b> Desde $0.01 hasta $3.50\n"
            "<b>📞 Soporte:</b> Contacta al administrador\n\n"
            "<b>📡 Sistema AutoPing activo</b> - Bot siempre en línea"
        )
        await message.answer(help_text, parse_mode="HTML")

    async def cmd_ping(self, message: Message):
        ping_status = "🟢 Activo" if self.autopinger.is_running else "🔴 Inactivo"
        await message.answer(
            f"🏓 ¡Pong! Bot funcionando ✅\n"
            f"📡 AutoPing: {ping_status}",
            parse_mode="HTML"
        )

    async def cmd_autopinger(self, message: Message):
        """Show AutoPinger status"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Sin permisos.")
            return
        
        status = self.autopinger.get_status()
        
        status_emoji = "🟢" if status["running"] else "🔴"
        enabled_emoji = "✅" if status["enabled"] else "❌"
        
        status_text = (
            f"📡 <b>Estado del AutoPinger</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"{enabled_emoji} <b>Habilitado:</b> {status['enabled']}\n"
            f"{status_emoji} <b>En ejecución:</b> {status['running']}\n"
            f"🔢 <b>Pings realizados:</b> {status['ping_count']}\n"
            f"⏰ <b>Intervalo:</b> {status['interval']}s\n"
            f"🌐 <b>URL externa:</b> {status['url']}\n"
        )
        
        if status["last_ping"]:
            last_ping_dt = datetime.fromisoformat(status["last_ping"])
            status_text += f"🕐 <b>Último ping:</b> {last_ping_dt.strftime('%H:%M:%S')}\n"
        
        await message.answer(status_text, parse_mode="HTML")

    async def cmd_autoping_start(self, message: Message):
        """Start AutoPinger"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Sin permisos.")
            return
        
        if not self.config.autopinger_enabled:
            await message.answer("❌ AutoPinger está deshabilitado en la configuración.")
            return
        
        if self.autopinger.is_running:
            await message.answer("⚠️ AutoPinger ya está en ejecución.")
            return
        
        try:
            await self.autopinger.start()
            await message.answer(
                f"✅ <b>AutoPinger iniciado</b>\n"
                f"⏰ Intervalo: {self.config.autopinger_interval}s\n"
                f"📡 Manteniendo bot activo...",
                parse_mode="HTML"
            )
        except Exception as e:
            await message.answer(f"❌ Error iniciando AutoPinger: {str(e)}")

    async def cmd_autoping_stop(self, message: Message):
        """Stop AutoPinger"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Sin permisos.")
            return
        
        if not self.autopinger.is_running:
            await message.answer("⚠️ AutoPinger no está en ejecución.")
            return
        
        try:
            await self.autopinger.stop()
            await message.answer(
                f"🛑 <b>AutoPinger detenido</b>\n"
                f"📊 Total pings realizados: {self.autopinger.ping_count}",
                parse_mode="HTML"
            )
        except Exception as e:
            await message.answer(f"❌ Error deteniendo AutoPinger: {str(e)}")

    async def cmd_cancel(self, message: Message, state: FSMContext):
        await state.clear()
        await message.answer("❌ Operación cancelada.\n\n💡 ¿Qué deseas hacer?", reply_markup=self._create_main_menu())

    async def cmd_account(self, message: Message):
        user = self.db.get_or_create_user(
            user_id=message.from_user.id, username=message.from_user.username,
            first_name=message.from_user.first_name, last_name=message.from_user.last_name
        )
        
        full_name = f"{user.first_name or ''} {user.last_name or ''}".strip()
        username_text = f"@{user.username}" if user.username else "No definido"
        
        account_text = (
            f"👤 <b>Mi Cuenta</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <b>ID:</b> <code>{user.user_id}</code>\n"
            f"👨‍💼 <b>Nombre:</b> {full_name or 'No definido'}\n"
            f"📱 <b>Usuario:</b> {username_text}\n"
            f"💰 <b>Balance:</b> ${user.balance:.2f}\n"
            f"📊 <b>Consultas:</b> {user.total_queries}\n"
        )
        
        if user.query_history:
            account_text += f"\n📋 <b>Historial reciente:</b>\n"
            for query in user.query_history[-3:]:
                status_emoji = "✅" if query["success"] else "❌"
                account_text += f"{status_emoji} ${query['price']} - IMEI: ...{query['imei']}\n"
        
        await message.answer(account_text, parse_mode="HTML")

    async def cmd_add_balance(self, message: Message):
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Sin permisos.")
            return
        
        try:
            parts = message.text.split()
            if len(parts) != 3:
                await message.answer("❌ Uso: /addbalance <user_id> <amount>")
                return
            
            target_user_id = int(parts[1])
            amount = float(parts[2])
            
            if target_user_id not in self.db.users:
                now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self.db.users[target_user_id] = UserData(
                    user_id=target_user_id, username=None, first_name="Usuario",
                    last_name=None, join_date=now, last_activity=now
                )
            
            user = self.db.users[target_user_id]
            old_balance = user.balance
            user.balance += amount
            self.db.save_users()
            
            await message.answer(
                f"✅ Balance actualizado\n"
                f"👤 Usuario: {target_user_id}\n" 
                f"💰 ${old_balance:.2f} → ${user.balance:.2f}",
                parse_mode="HTML"
            )
                
        except (ValueError, IndexError):
            await message.answer("❌ Formato inválido")

    async def cmd_add_service(self, message: Message):
        """Add new service - Owner only"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Sin permisos.")
            return
        
        try:
            parts = message.text.split(maxsplit=4)
            if len(parts) != 5:
                await message.answer(
                    "❌ Uso: /addservice <id> <title> <price> <category>\n"
                    "Ejemplo: /addservice 100 \"iPhone Info Pro\" 0.50 Apple\n"
                    "Categorías: Apple, Android, General"
                )
                return
            
            service_id = int(parts[1])
            title = parts[2].strip('"')
            price = parts[3]
            category = parts[4]
            
            if category not in ["Apple", "Android", "General"]:
                await message.answer("❌ Categoría debe ser: Apple, Android o General")
                return
            
            if service_id in self.services_by_id:
                await message.answer(f"❌ Ya existe un servicio con ID {service_id}")
                return
            
            new_service = {
                "id": service_id,
                "title": title,
                "price": price,
                "category": category
            }
            
            SERVICES_DATA.append(new_service)
            self.services_by_id[service_id] = new_service
            
            if category not in self.services_by_category:
                self.services_by_category[category] = []
            self.services_by_category[category].append(new_service)
            
            self._save_services()
            
            await message.answer(
                f"✅ <b>Servicio agregado</b>\n"
                f"🆔 ID: {service_id}\n"
                f"📝 Título: {title}\n"
                f"💰 Precio: ${price}\n"
                f"📂 Categoría: {category}",
                parse_mode="HTML"
            )
            
        except (ValueError, IndexError):
            await message.answer("❌ Formato inválido. Revisa la sintaxis.")

    async def cmd_remove_service(self, message: Message):
        """Remove service - Owner only"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Sin permisos.")
            return
        
        try:
            parts = message.text.split()
            if len(parts) != 2:
                await message.answer("❌ Uso: /removeservice <service_id>")
                return
            
            service_id = int(parts[1])
            
            if service_id not in self.services_by_id:
                await message.answer(f"❌ No existe servicio con ID {service_id}")
                return
            
            service = self.services_by_id[service_id]
            
            SERVICES_DATA[:] = [s for s in SERVICES_DATA if s["id"] != service_id]
            del self.services_by_id[service_id]
            
            category = service["category"]
            if category in self.services_by_category:
                self.services_by_category[category] = [
                    s for s in self.services_by_category[category] if s["id"] != service_id
                ]
                if not self.services_by_category[category]:
                    del self.services_by_category[category]
            
            self._save_services()
            
            await message.answer(
                f"✅ <b>Servicio eliminado</b>\n"
                f"🆔 ID: {service_id}\n"
                f"📝 Título: {service['title']}\n"
                f"📂 Categoría: {service['category']}",
                parse_mode="HTML"
            )
            
        except (ValueError, IndexError):
            await message.answer("❌ Formato inválido.")

    async def cmd_list_services(self, message: Message):
        """List all services - Owner only"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Sin permisos.")
            return
        
        if not SERVICES_DATA:
            await message.answer("📝 No hay servicios configurados.")
            return
        
        services_text = f"📋 <b>Lista de Servicios ({len(SERVICES_DATA)})</b>\n\n"
        
        for category in self.services_by_category:
            services_text += f"📂 <b>{category}:</b>\n"
            for service in self.services_by_category[category]:
                services_text += f"• ID {service['id']}: ${service['price']} - {service['title'][:40]}...\n"
            services_text += "\n"
        
        if len(services_text) > 4000:
            services_text = services_text[:4000] + "\n<i>... lista truncada</i>"
        
        await message.answer(services_text, parse_mode="HTML")

    async def cmd_stats(self, message: Message):
        """Show bot stats - Owner only"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Sin permisos.")
            return
        
        total_users = len(self.db.users)
        total_queries = sum(user.total_queries for user in self.db.users.values())
        total_balance = sum(user.balance for user in self.db.users.values())
        total_services = len(SERVICES_DATA)
        
        most_active = max(self.db.users.values(), key=lambda u: u.total_queries, default=None)
        
        cat_counts = {cat: len(services) for cat, services in self.services_by_category.items()}
        
        autopinger_status = self.autopinger.get_status()
        ping_status = "🟢 Activo" if autopinger_status["running"] else "🔴 Inactivo"
        
        stats_text = (
            f"📊 <b>Estadísticas del Bot</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"👥 <b>Total usuarios:</b> {total_users}\n"
            f"🔍 <b>Total consultas:</b> {total_queries}\n"
            f"💰 <b>Balance total:</b> ${total_balance:.2f}\n"
            f"🛠️ <b>Total servicios:</b> {total_services}\n"
            f"📡 <b>AutoPing:</b> {ping_status} ({autopinger_status['ping_count']} pings)\n\n"
            f"📂 <b>Por categoría:</b>\n"
        )
        
        for category, count in cat_counts.items():
            emoji = {"Apple": "🍎", "Android": "🤖", "General": "🔧"}.get(category, "📱")
            stats_text += f"• {emoji} {category}: {count} servicios\n"
        
        if most_active and most_active.total_queries > 0:
            stats_text += (
                f"\n🏆 <b>Usuario más activo:</b>\n"
                f"👤 {most_active.first_name or 'Sin nombre'} "
                f"({most_active.user_id})\n"
                f"📊 {most_active.total_queries} consultas\n"
            )
        
        await message.answer(stats_text, parse_mode="HTML")

    async def cmd_broadcast(self, message: Message):
        """Broadcast message - Owner only"""
        if not self._is_owner(message.from_user.id):
            await message.answer("❌ Sin permisos.")
            return
        
        try:
            parts = message.text.split(maxsplit=1)
            if len(parts) < 2:
                await message.answer("❌ Uso: /broadcast <mensaje>")
                return
            
            broadcast_msg = parts[1]
            confirm_text = (
                f"📢 <b>Confirmar Broadcast</b>\n\n"
                f"👥 Se enviará a {len(self.db.users)} usuarios\n\n"
                f"<b>Mensaje:</b>\n{broadcast_msg}\n\n"
                f"¿Continuar? Responde 'SI' para confirmar."
            )
            
            await message.answer(confirm_text, parse_mode="HTML")
            
        except Exception as e:
            await message.answer(f"❌ Error: {str(e)}")

    def _save_services(self):
        """Save services to JSON file"""
        try:
            services_file = Path(self.config.services_db_path)
            with open(services_file, 'w', encoding='utf-8') as f:
                json.dump(SERVICES_DATA, f, indent=2, ensure_ascii=False)
            logger.info("Services saved to file")
        except Exception as e:
            logger.error(f"Error saving services: {e}")

    def _load_services(self):
        """Load services from JSON file"""
        try:
            services_file = Path(self.config.services_db_path)
            if services_file.exists():
                with open(services_file, 'r', encoding='utf-8') as f:
                    loaded_services = json.load(f)
                    SERVICES_DATA.clear()
                    SERVICES_DATA.extend(loaded_services)
                    logger.info(f"Services loaded from file: {len(SERVICES_DATA)}")
        except Exception as e:
            logger.error(f"Error loading services: {e}")

    async def handle_category_selection(self, message: Message, state: FSMContext):
        text = message.text.strip()
        
        if text == "🔍 Consultar IMEI":
            await message.answer(
                "📱 <b>Selecciona una categoría:</b>",
                reply_markup=self._create_categories_keyboard(),
                parse_mode="HTML"
            )
            await state.set_state(IMEIStates.waiting_for_service_category)
            
        elif text == "👤 Mi Cuenta":
            await self.cmd_account(message)
            
        elif text == "❓ Ayuda":
            await self.cmd_help(message)
            
        elif text == "❌ Cancelar":
            await self.cmd_cancel(message, state)
            
        else:
            await message.answer("❌ Opción no válida", reply_markup=self._create_main_menu())

    async def handle_callback_query(self, callback_query, state: FSMContext):
        try:
            data = callback_query.data
            
            if data.startswith("cat_"):
                category = data[4:]
                await callback_query.message.edit_text(
                    f"📱 <b>Servicios de {category}:</b>\n\nSelecciona el servicio:",
                    reply_markup=self._create_services_keyboard(category),
                    parse_mode="HTML"
                )
                await state.update_data(selected_category=category)
                await state.set_state(IMEIStates.waiting_for_service)
                
            elif data.startswith("svc_"):
                service_id = int(data[4:])
                service = self.services_by_id.get(service_id)
                
                if service:
                    await state.update_data(selected_service=service)
                    await callback_query.message.edit_text(
                        f"✅ <b>Servicio:</b> {service['title']}\n"
                        f"💰 <b>Precio:</b> ${service['price']}\n\n"
                        f"📟 Envía el <b>número IMEI</b> (8-17 dígitos):",
                        parse_mode="HTML"
                    )
                    await state.set_state(IMEIStates.waiting_for_imei)
                
            elif data == "back_to_categories":
                await callback_query.message.edit_text(
                    "📱 <b>Selecciona una categoría:</b>",
                    reply_markup=self._create_categories_keyboard(),
                    parse_mode="HTML"
                )
                await state.set_state(IMEIStates.waiting_for_service_category)
                
            elif data == "cancel":
                await callback_query.message.delete()
                await callback_query.message.answer(
                    "❌ Cancelado. ¿Qué deseas hacer?",
                    reply_markup=self._create_main_menu()
                )
                await state.clear()
            
            await callback_query.answer()
            
        except Exception as e:
            logger.error(f"Error in callback: {e}")
            await callback_query.answer("❌ Error procesando solicitud")

    async def handle_imei_input(self, message: Message, state: FSMContext):
        imei_input = message.text.strip()
        
        is_valid, result = IMEIValidator.validate_imei(imei_input)
        if not is_valid:
            await message.answer(f"❌ {result}\n\nEnvía un IMEI válido:")
            return

        clean_imei = result
        data = await state.get_data()
        service = data.get("selected_service")
        
        if not service:
            await message.answer("❌ Error: No hay servicio seleccionado. Usa /start")
            await state.clear()
            return

        user = self.db.get_or_create_user(
            user_id=message.from_user.id, username=message.from_user.username,
            first_name=message.from_user.first_name, last_name=message.from_user.last_name
        )
        
        service_price = float(service["price"])
        if user.balance < service_price and not self._is_owner(message.from_user.id):
            await message.answer(
                f"❌ <b>Saldo insuficiente</b>\n\n"
                f"💰 Tu balance: ${user.balance:.2f}\n"
                f"💳 Precio: ${service_price:.2f}\n"
                f"📊 Necesitas: ${service_price - user.balance:.2f} más",
                parse_mode="HTML"
            )
            await state.clear()
            await message.answer("💡 ¿Qué deseas hacer?", reply_markup=self._create_main_menu())
            return

        processing_msg = await message.answer(
            f"🔄 <b>Procesando...</b>\n"
            f"📟 IMEI: ...{clean_imei[-4:]}\n"
            f"💰 Precio: ${service_price:.2f}",
            parse_mode="HTML"
        )

        try:
            async with IMEIChecker(self.config) as checker:
                response = await checker.check_imei(clean_imei, service["id"])
                
            formatted_response = ResponseFormatter.format_imei_response(response)
            await processing_msg.delete()
            await message.answer(formatted_response, parse_mode="HTML")
            
            self.db.update_user_query(
                user_id=message.from_user.id, service_title=service["title"],
                price=service_price, imei=clean_imei, success=True
            )
            
        except APIError as e:
            await processing_msg.delete()
            await message.answer(f"❌ <b>Error en la consulta:</b>\n{str(e)}", parse_mode="HTML")
            
            self.db.update_user_query(
                user_id=message.from_user.id, service_title=service["title"],
                price=0.0, imei=clean_imei, success=False
            )
            
        except Exception as e:
            await processing_msg.delete()
            await message.answer("❌ Error inesperado. Inténtalo más tarde.", parse_mode="HTML")
            logger.error(f"Unexpected error: {e}")

        await state.clear()
        await asyncio.sleep(1)
        await message.answer("✨ <b>¿Otra consulta?</b>", reply_markup=self._create_main_menu(), parse_mode="HTML")

    async def start_polling(self):
        """Start polling mode"""
        logger.info("🔄 Starting polling mode...")
        
        if self.config.autopinger_enabled:
            await self.autopinger.start()
        
        try:
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.error(f"Critical error: {e}")
            raise
        finally:
            await self.autopinger.stop()
            await self.bot.session.close()