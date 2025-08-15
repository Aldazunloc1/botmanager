import sys
import os
import datetime
import logging
import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional, List
from pydantic import BaseModel
import requests
from fastapi import FastAPI, Request, HTTPException, Depends, Body, Query
from aiogram import Bot, Dispatcher, types
from aiogram.fsm.storage.memory import MemoryStorage

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import settings
from app.bot.bot_manager import IMEIBot
from app.models.webhook import WebhookUpdate
from app.models.user import User

# ----------------------------
# LOGGING CONFIGURATION
# ----------------------------
class TelegramLogsHandler(logging.Handler):
    def __init__(self, bot_token, chat_id):
        super().__init__()
        self.bot_token = bot_token
        self.chat_id = chat_id

    def emit(self, record):
        try:
            log_entry = self.format(record)
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
            requests.post(url, data={"chat_id": self.chat_id, "text": log_entry}, timeout=5)
        except Exception as e:
            print(f"Error enviando log a Telegram: {e}")

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO if not settings.debug else logging.DEBUG)

TELEGRAM_CHAT_ID = -1002860769422
tg_handler = TelegramLogsHandler(settings.bot_token, TELEGRAM_CHAT_ID)
tg_handler.setLevel(logging.INFO)
tg_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

console_handler = logging.StreamHandler()
console_handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))

file_handler = logging.FileHandler("app.log")
file_handler.setFormatter(logging.Formatter("[%(asctime)s] [%(levelname)s] %(message)s"))

logger.addHandler(tg_handler)
logger.addHandler(console_handler)
logger.addHandler(file_handler)

# ----------------------------
# GLOBAL BOT INSTANCE
# ----------------------------
bot_instance: IMEIBot = None

# ----------------------------
# Pydantic models
# ----------------------------
class AddCreditsRequest(BaseModel):
    user_id: int
    credits: float
    admin_key: str
    reason: Optional[str] = "Manual credit addition"

class SetCreditsRequest(BaseModel):
    user_id: int
    credits: float
    admin_key: str
    reason: Optional[str] = "Manual credit set"

class UserRegistrationRequest(BaseModel):
    user_id: int
    username: Optional[str] = None
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    initial_credits: float = 0.0
    admin_key: str

class BroadcastRequest(BaseModel):
    message: str
    admin_key: str

# ----------------------------
# FASTAPI LIFESPAN
# ----------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    global bot_instance
    logger.info("🚀 Starting IMEI Bot Manager...")

    try:
        bot_instance = IMEIBot(settings)

        if settings.webhook_url:
            webhook_url = f"{settings.webhook_url.rstrip('/')}{settings.webhook_path}"
            await bot_instance.bot.set_webhook(
                url=webhook_url,
                secret_token=settings.webhook_secret if settings.webhook_secret else None
            )
            logger.info(f"✅ Webhook set to: {webhook_url}")
        else:
            logger.info("🔄 Starting polling mode...")
            asyncio.create_task(bot_instance.start_polling())

        if settings.autopinger_enabled:
            await bot_instance.autopinger.start()
            logger.info("📡 AutoPinger started")

        yield

    except Exception as e:
        logger.error(f"❌ Error during startup: {e}")
        raise
    finally:
        logger.info("🛑 Shutting down...")
        if bot_instance:
            await bot_instance.autopinger.stop()
            await bot_instance.bot.session.close()
        logger.info("✅ Shutdown complete")

# ----------------------------
# CREATE APP
# ----------------------------
app = FastAPI(
    title="IMEI Bot Manager",
    description="FastAPI + aiogram IMEI Checker Bot with Credit Management",
    version="1.0.0",
    lifespan=lifespan
)

# ----------------------------
# ENDPOINTS
# ----------------------------
@app.get("/")
async def root():
    return {
        "status": "running",
        "bot": "IMEI Checker Pro",
        "version": "1.0.0",
        "webhook_mode": bool(settings.webhook_url),
        "autopinger": settings.autopinger_enabled
    }

@app.get("/ping")
async def ping():
    """Endpoint minimalista para verificaciones de actividad"""
    try:
        bot_active = bool(bot_instance) and await bot_instance.bot.get_me()
        return {
            "status": "active" if bot_active else "inactive",
            "bot_ready": bot_active,
            "timestamp": datetime.datetime.now().isoformat(),
            "version": "1.0.0",
            "response_size": "minimal"
        }
    except Exception as e:
        logger.error(f"Ping check failed: {e}")
        return {
            "status": "error",
            "error": str(e),
            "timestamp": datetime.datetime.now().isoformat()
        }

@app.get("/health")
async def health_check():
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    try:
        bot_info = await bot_instance.bot.get_me()
        autopinger_status = bot_instance.autopinger.get_status()
        return {
            "status": "healthy",
            "bot_username": bot_info.username,
            "bot_id": bot_info.id,
            "total_users": len(bot_instance.db.users),
            "autopinger": autopinger_status,
            "webhook_mode": bool(settings.webhook_url)
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        raise HTTPException(status_code=503, detail=f"Health check failed: {str(e)}")

@app.post(settings.webhook_path)
async def webhook(request: Request):
    if not settings.webhook_url:
        raise HTTPException(status_code=404, detail="Webhook not configured")
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    try:
        if settings.webhook_secret:
            secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if secret_header != settings.webhook_secret:
                raise HTTPException(status_code=401, detail="Invalid secret token")
        update_data = await request.json()
        update = types.Update(**update_data)
        await bot_instance.dp.feed_update(bot_instance.bot, update)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=400, detail=f"Webhook processing failed: {str(e)}")

@app.get("/stats")
async def get_stats():
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    try:
        total_users = len(bot_instance.db.users)
        total_queries = sum(user.total_queries for user in bot_instance.db.users.values())
        total_balance = sum(user.balance for user in bot_instance.db.users.values())
        total_services = len(bot_instance.services_by_id)
        
        services_by_category = {cat: len(svc) for cat, svc in bot_instance.services_by_category.items()}
        autopinger_status = bot_instance.autopinger.get_status()
        
        return {
            "users": {"total": total_users, "total_queries": total_queries, "total_balance": round(total_balance,2)},
            "services": {"total": total_services, "by_category": services_by_category},
            "autopinger": autopinger_status
        }
    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")

# ----------------------------
# ADMIN ENDPOINTS
# ----------------------------
@app.post("/admin/user/add_credits")
async def add_credits(request: AddCreditsRequest):
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    try:
        if request.admin_key != settings.admin_key:
            raise HTTPException(status_code=401, detail="Invalid admin key")
        if request.user_id not in bot_instance.db.users:
            raise HTTPException(status_code=404, detail="User not found")
        
        user = bot_instance.db.users[request.user_id]
        old_balance = user.balance
        user.balance += request.credits
        bot_instance.db.save()
        
        try:
            await bot_instance.bot.send_message(
                request.user_id,
                f"💰 <b>¡Créditos añadidos!</b>\n\n"
                f"• <b>Créditos recibidos:</b> +{request.credits}\n"
                f"• <b>Balance anterior:</b> {old_balance}\n"
                f"• <b>Nuevo balance:</b> {user.balance}\n"
                f"• <b>Motivo:</b> {request.reason}",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Failed to notify user {request.user_id}: {e}")
            
        logger.info(f"Added {request.credits} credits to user {request.user_id}. New balance: {user.balance}")
        return {
            "status": "success",
            "user_id": request.user_id,
            "credits_added": request.credits,
            "old_balance": old_balance,
            "new_balance": user.balance,
            "reason": request.reason
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Add credits error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to add credits: {str(e)}")

@app.post("/admin/user/set_credits")
async def set_credits(request: SetCreditsRequest):
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    try:
        if request.admin_key != settings.admin_key:
            raise HTTPException(status_code=401, detail="Invalid admin key")
        if request.user_id not in bot_instance.db.users:
            raise HTTPException(status_code=404, detail="User not found")
            
        user = bot_instance.db.users[request.user_id]
        old_balance = user.balance
        user.balance = request.credits
        bot_instance.db.save()
        
        try:
            await bot_instance.bot.send_message(
                request.user_id,
                f"💳 <b>Balance actualizado</b>\n\n"
                f"• <b>Balance anterior:</b> {old_balance}\n"
                f"• <b>Nuevo balance:</b> {user.balance}\n"
                f"• <b>Motivo:</b> {request.reason}",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.warning(f"Failed to notify user {request.user_id}: {e}")
            
        logger.info(f"Set credits for user {request.user_id} to {request.credits}. Old balance: {old_balance}")
        return {
            "status": "success",
            "user_id": request.user_id,
            "old_balance": old_balance,
            "new_balance": user.balance,
            "reason": request.reason
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Set credits error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to set credits: {str(e)}")

@app.post("/admin/user/register")
async def register_user(request: UserRegistrationRequest):
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    try:
        if request.admin_key != settings.admin_key:
            raise HTTPException(status_code=401, detail="Invalid admin key")
        if request.user_id in bot_instance.db.users:
            raise HTTPException(status_code=400, detail="User already exists")
            
        new_user = User(
            user_id=request.user_id,
            username=request.username,
            first_name=request.first_name or "Unknown",
            last_name=request.last_name,
            join_date=datetime.datetime.now(),
            balance=request.initial_credits
        )
        
        bot_instance.db.users[request.user_id] = new_user
        bot_instance.db.save()
        
        logger.info(f"Manually registered user {request.user_id} with {request.initial_credits} initial credits")
        return {
            "status": "success",
            "user_id": request.user_id,
            "username": request.username,
            "initial_credits": request.initial_credits,
            "message": "User registered successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Register user error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to register user: {str(e)}")

@app.get("/admin/user/{user_id}")
async def get_user_info(user_id: int, admin_key: str = Query(...)):
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    try:
        if admin_key != settings.admin_key:
            raise HTTPException(status_code=401, detail="Invalid admin key")
        if user_id not in bot_instance.db.users:
            raise HTTPException(status_code=404, detail="User not found")
            
        user = bot_instance.db.users[user_id]
        return {
            "user_id": user.user_id,
            "username": user.username,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "join_date": user.join_date,
            "last_activity": user.last_activity,
            "total_queries": user.total_queries,
            "balance": round(user.balance, 2),
            "is_active": hasattr(user, 'is_active') and user.is_active
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get user info error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get user info: {str(e)}")

@app.delete("/admin/user/{user_id}")
async def delete_user(user_id: int, admin_key: str = Body(..., embed=True)):
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    try:
        if admin_key != settings.admin_key:
            raise HTTPException(status_code=401, detail="Invalid admin key")
        if user_id not in bot_instance.db.users:
            raise HTTPException(status_code=404, detail="User not found")
            
        user = bot_instance.db.users[user_id]
        user_info = {
            "user_id": user.user_id,
            "username": user.username,
            "balance": user.balance,
            "total_queries": user.total_queries
        }
        
        del bot_instance.db.users[user_id]
        bot_instance.db.save()
        
        logger.info(f"Deleted user {user_id} with balance {user_info['balance']}")
        return {
            "status": "success",
            "message": "User deleted successfully",
            "deleted_user": user_info
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Delete user error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete user: {str(e)}")

@app.post("/admin/broadcast")
async def broadcast_message(request: BroadcastRequest):
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    try:
        if request.admin_key != settings.admin_key:
            raise HTTPException(status_code=401, detail="Invalid admin key")
        if not request.message:
            raise HTTPException(status_code=400, detail="Message is required")
            
        success_count, failed_count = 0, 0
        for user_id in bot_instance.db.users.keys():
            try:
                await bot_instance.bot.send_message(
                    user_id,
                    f"📢 <b>Mensaje del administrador:</b>\n\n{request.message}",
                    parse_mode="HTML"
                )
                success_count += 1
                await asyncio.sleep(0.05)  # Rate limiting
            except Exception as e:
                logger.warning(f"Failed to send to user {user_id}: {e}")
                failed_count += 1
                
        return {
            "status": "completed",
            "success_count": success_count,
            "failed_count": failed_count,
            "total_users": len(bot_instance.db.users)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Broadcast error: {e}")
        raise HTTPException(status_code=500, detail=f"Broadcast failed: {str(e)}")

@app.get("/admin/users")
async def get_users(
    limit: int = Query(50, gt=0, le=100),
    offset: int = Query(0, ge=0),
    admin_key: str = Query(...)
):
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    try:
        if admin_key != settings.admin_key:
            raise HTTPException(status_code=401, detail="Invalid admin key")
            
        users_list = list(bot_instance.db.users.values())
        users_slice = users_list[offset:offset + limit]
        
        users_data = []
        for user in users_slice:
            users_data.append({
                "user_id": user.user_id,
                "username": user.username,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "join_date": user.join_date,
                "last_activity": user.last_activity,
                "total_queries": user.total_queries,
                "balance": round(user.balance, 2)
            })
            
        return {
            "users": users_data,
            "total": len(users_list),
            "offset": offset,
            "limit": limit,
            "has_more": offset + limit < len(users_list)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Get users error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get users: {str(e)}")

# ----------------------------
# RUN APPLICATION
# ----------------------------
def run():
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
        log_level="debug" if settings.debug else "info"
    )

if __name__ == "__main__":
    run()
