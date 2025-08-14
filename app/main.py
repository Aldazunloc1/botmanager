import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import settings
import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Dict, Any, Optional
from pydantic import BaseModel

from fastapi import FastAPI, Request, HTTPException, Depends, Body
from aiogram import Bot, Dispatcher, types
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.fsm.storage.memory import MemoryStorage


from app.bot.bot_manager import IMEIBot
from app.models.webhook import WebhookUpdate

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.debug else logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global bot instance
bot_instance: IMEIBot = None

# Pydantic models for request validation
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

class AdminKeyDep:
    def __init__(self, admin_key: str = Body(..., embed=True)):
        if admin_key != getattr(settings, 'admin_key', 'your_admin_key_here'):
            raise HTTPException(status_code=401, detail="Invalid admin key")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan manager"""
    global bot_instance
    
    logger.info("🚀 Starting IMEI Bot Manager...")
    
    try:
        # Initialize bot
        bot_instance = IMEIBot(settings)
        
        # Set webhook if URL is provided
        if settings.webhook_url:
            webhook_url = f"{settings.webhook_url.rstrip('/')}{settings.webhook_path}"
            await bot_instance.bot.set_webhook(
                url=webhook_url,
                secret_token=settings.webhook_secret if settings.webhook_secret else None
            )
            logger.info(f"✅ Webhook set to: {webhook_url}")
        else:
            # Start polling in background
            logger.info("🔄 Starting polling mode...")
            asyncio.create_task(bot_instance.start_polling())
        
        # Start AutoPinger if enabled
        if settings.autopinger_enabled:
            await bot_instance.autopinger.start()
            logger.info("📡 AutoPinger started")
        
        yield
        
    except Exception as e:
        logger.error(f"❌ Error during startup: {e}")
        raise
    finally:
        # Cleanup
        logger.info("🛑 Shutting down...")
        if bot_instance:
            await bot_instance.autopinger.stop()
            await bot_instance.bot.session.close()
        logger.info("✅ Shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="IMEI Bot Manager",
    description="FastAPI + aiogram IMEI Checker Bot with Credit Management",
    version="1.0.0",
    lifespan=lifespan
)


@app.get("/")
async def root():
    """Health check endpoint"""
    return {
        "status": "running",
        "bot": "IMEI Checker Pro",
        "version": "1.0.0",
        "webhook_mode": bool(settings.webhook_url),
        "autopinger": settings.autopinger_enabled
    }


@app.get("/health")
async def health_check():
    """Detailed health check"""
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    
    try:
        # Test bot connection
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
    """Webhook endpoint for Telegram updates"""
    if not settings.webhook_url:
        raise HTTPException(status_code=404, detail="Webhook not configured")
    
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    
    try:
        # Verify secret token if configured
        if settings.webhook_secret:
            secret_header = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
            if secret_header != settings.webhook_secret:
                raise HTTPException(status_code=401, detail="Invalid secret token")
        
        # Get update data
        update_data = await request.json()
        
        # Process update
        update = types.Update(**update_data)
        await bot_instance.dp.feed_update(bot_instance.bot, update)
        
        return {"status": "ok"}
        
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        raise HTTPException(status_code=400, detail=f"Webhook processing failed: {str(e)}")


@app.get("/stats")
async def get_stats():
    """Get bot statistics"""
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    
    try:
        total_users = len(bot_instance.db.users)
        total_queries = sum(user.total_queries for user in bot_instance.db.users.values())
        total_balance = sum(user.balance for user in bot_instance.db.users.values())
        total_services = len(bot_instance.services_by_id)
        
        # Services by category
        services_by_category = {}
        for category, services in bot_instance.services_by_category.items():
            services_by_category[category] = len(services)
        
        # AutoPinger status
        autopinger_status = bot_instance.autopinger.get_status()
        
        return {
            "users": {
                "total": total_users,
                "total_queries": total_queries,
                "total_balance": round(total_balance, 2)
            },
            "services": {
                "total": total_services,
                "by_category": services_by_category
            },
            "autopinger": autopinger_status
        }
        
    except Exception as e:
        logger.error(f"Stats error: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")


# ===== NUEVOS ENDPOINTS PARA GESTIÓN DE CRÉDITOS Y USUARIOS =====

@app.post("/admin/user/add_credits")
async def add_credits(request: AddCreditsRequest):
    """Add credits to a user"""
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    
    try:
        # Verify admin key
        if request.admin_key != settings.admin_key:
            raise HTTPException(status_code=401, detail="Invalid admin key")
        
        # Check if user exists
        if request.user_id not in bot_instance.db.users:
            raise HTTPException(status_code=404, detail="User not found")
        
        user = bot_instance.db.users[request.user_id]
        old_balance = user.balance
        user.balance += request.credits
        
        # Save to database
        bot_instance.db.save()
        
        # Notify user
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
    """Set exact credit amount for a user"""
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    
    try:
        # Verify admin key
        if request.admin_key != settings.admin_key:
            raise HTTPException(status_code=401, detail="Invalid admin key")
        
        # Check if user exists
        if request.user_id not in bot_instance.db.users:
            raise HTTPException(status_code=404, detail="User not found")
        
        user = bot_instance.db.users[request.user_id]
        old_balance = user.balance
        user.balance = request.credits
        
        # Save to database
        bot_instance.db.save()
        
        # Notify user
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
    """Manually register a new user"""
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    
    try:
        # Verify admin key
        if request.admin_key != settings.admin_key:
            raise HTTPException(status_code=401, detail="Invalid admin key")
        
        # Check if user already exists
        if request.user_id in bot_instance.db.users:
            raise HTTPException(status_code=400, detail="User already exists")
        
        # Create new user (asumiendo que tienes una clase User)
        from datetime import datetime
        from app.models.user import User  # Ajusta la importación según tu estructura
        
        new_user = User(
            user_id=request.user_id,
            username=request.username,
            first_name=request.first_name or "Unknown",
            last_name=request.last_name,
            join_date=datetime.now(),
            balance=request.initial_credits
        )
        
        # Add to database
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
async def get_user_info(user_id: int, admin_key: str):
    """Get detailed information about a specific user"""
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    
    try:
        # Verify admin key
        if admin_key != settings.admin_key:
            raise HTTPException(status_code=401, detail="Invalid admin key")
        
        # Check if user exists
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
    """Delete a user from the database"""
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    
    try:
        # Verify admin key
        if admin_key != settings.admin_key:
            raise HTTPException(status_code=401, detail="Invalid admin key")
        
        # Check if user exists
        if user_id not in bot_instance.db.users:
            raise HTTPException(status_code=404, detail="User not found")
        
        user = bot_instance.db.users[user_id]
        user_info = {
            "user_id": user.user_id,
            "username": user.username,
            "balance": user.balance,
            "total_queries": user.total_queries
        }
        
        # Delete user
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
async def broadcast_message(request: Request):
    """Admin endpoint to broadcast messages"""
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    
    try:
        data = await request.json()
        message = data.get("message", "").strip()
        admin_key = data.get("admin_key", "")
        
        # Simple admin key check
        if not admin_key or admin_key != settings.admin_key:
            raise HTTPException(status_code=401, detail="Invalid admin key")
        
        if not message:
            raise HTTPException(status_code=400, detail="Message is required")
        
        # Broadcast to all users
        success_count = 0
        failed_count = 0
        
        for user_id in bot_instance.db.users.keys():
            try:
                await bot_instance.bot.send_message(user_id, f"📢 <b>Mensaje del administrador:</b>\n\n{message}", parse_mode="HTML")
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
async def get_users(limit: int = 50, offset: int = 0, admin_key: str = None):
    """Admin endpoint to get users list"""
    if not bot_instance:
        raise HTTPException(status_code=503, detail="Bot not initialized")
    
    try:
        # Verify admin key
        if not admin_key or admin_key != settings.admin_key:
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


def run():
    """Entry point for running the application"""
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