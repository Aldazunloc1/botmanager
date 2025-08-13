from fastapi import FastAPI
from app.core.config import settings
from app.services.imeicheck import check_imei
from app.schemas.imei import IMEICheckRequest
from app.utils.imei_validator import is_valid_imei

app = FastAPI(title="IMEI Check API", version="1.0.0")


@app.post("/api/check-imei")
async def api_check_imei(request: IMEICheckRequest):
    if not is_valid_imei(request.imei):
        return {"error": "IMEI inválido"}

    result = await check_imei(request.imei, request.serviceId)
    return result


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
