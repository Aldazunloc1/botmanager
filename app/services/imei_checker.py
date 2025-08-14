import asyncio
import logging
from typing import Dict, Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class APIError(Exception):
    pass


class IMEIChecker:
    def __init__(self, config: Settings):
        self.config = config
        self.session = None

    async def __aenter__(self):
        self.session = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.request_timeout),
            limits=httpx.Limits(max_keepalive_connections=5, max_connections=10)
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.aclose()

    async def check_imei(self, imei: str, service_id: int) -> Dict[str, Any]:
        """Check IMEI using external API"""
        params = {
            "key": self.config.imei_api_key,
            "service": service_id,
            "imei": imei
        }

        last_error = None
        for attempt in range(self.config.max_retries):
            try:
                response = await self.session.get(self.config.imei_api_url, params=params)
                
                if response.status_code == 200:
                    return response.json()
                elif response.status_code == 429:
                    # Rate limited, wait and retry
                    await asyncio.sleep(2 ** attempt)
                    continue
                else:
                    response.raise_for_status()
                    
            except httpx.TimeoutException:
                last_error = f"Timeout en intento {attempt + 1}"
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)
                    
            except httpx.RequestError as e:
                last_error = f"Error de conexión: {str(e)}"
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(2 ** attempt)

        raise APIError(f"Error después de {self.config.max_retries} intentos. {last_error}")