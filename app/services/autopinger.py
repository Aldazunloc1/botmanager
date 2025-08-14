import asyncio
import aiohttp
from typing import Optional
import logging

logger = logging.getLogger(__name__)
# Agregar este método a la clase AutoPinger en app/services/autopinger.py

def get_status(self):
    """Get AutoPinger status information"""
    return {
        "enabled": getattr(self, 'enabled', False),
        "url": getattr(self, 'url', None),
        "interval": getattr(self, 'interval', None),
        "last_ping": getattr(self, 'last_ping', None),
        "ping_count": getattr(self, 'ping_count', 0),
        "is_running": getattr(self, 'is_running', False),
        "error_count": getattr(self, 'error_count', 0),
        "last_error": getattr(self, 'last_error', None)
    }
class AutoPinger:
    def __init__(self, config, bot):
        """Initialize AutoPinger with config and bot instance"""
        self.config = config
        self.bot = bot
        self.enabled = config.autopinger_enabled
        self.interval = config.autopinger_interval
        self.url = config.autopinger_url
        self.task: Optional[asyncio.Task] = None
        logger.info(f"AutoPinger initialized - Enabled: {self.enabled}")
    
    async def start(self):
        """Start the autopinger service"""
        if self.enabled and self.url:
            self.task = asyncio.create_task(self._ping_loop())
            logger.info(f"AutoPinger started with interval {self.interval} seconds for URL: {self.url}")
        else:
            logger.info("AutoPinger disabled or no URL configured")
    
    async def stop(self):
        """Stop the autopinger service"""
        if self.task and not self.task.done():
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass
            logger.info("AutoPinger stopped")
    
    async def _ping_loop(self):
        """Main ping loop"""
        while True:
            try:
                await self._ping()
                await asyncio.sleep(self.interval)
            except asyncio.CancelledError:
                logger.info("AutoPinger loop cancelled")
                break
            except Exception as e:
                logger.error(f"AutoPinger loop error: {e}")
                await asyncio.sleep(self.interval)
    
    async def _ping(self):
        """Send ping request"""
        if not self.url:
            return
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(self.url, timeout=10) as response:
                    if response.status == 200:
                        logger.debug(f"Ping successful: {response.status}")
                    else:
                        logger.warning(f"Ping returned status: {response.status}")
        except asyncio.TimeoutError:
            logger.warning(f"Ping timeout for URL: {self.url}")
        except Exception as e:
            logger.warning(f"Ping failed for URL {self.url}: {e}")