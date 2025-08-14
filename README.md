# IMEI Bot Manager

Bot de Telegram para consultas IMEI con FastAPI y Poetry.

## 🚀 Características

- **FastAPI**: API web moderna y rápida
- **aiogram 3**: Framework moderno para bots de Telegram
- **Poetry**: Gestión de dependencias y packaging
- **AutoPinger**: Sistema para mantener el bot activo
- **Webhook/Polling**: Soporte para ambos modos
- **Base de datos JSON**: Persistencia simple de usuarios
- **Administración**: Comandos admin para gestión

## 📦 Instalación

### Con Poetry (Recomendado)

```bash
# Clonar repositorio
git clone <tu-repo>
cd botmanager

# Instalar Poetry si no lo tienes
curl -sSL https://install.python-poetry.org | python3 -

# Instalar dependencias
poetry install

# Copiar configuración
cp .env.example .env
# Editar .env con tus valores

# Ejecutar
poetry run python -m app.main
```

### Con Docker

```bash
# Construir y ejecutar
docker-compose up -d

# Solo el bot (sin nginx)
docker-compose up botmanager
```

## ⚙️ Configuración

Edita el archivo `.env`:

```bash
# Configuración obligatoria
BOT_TOKEN=tu_bot_token_aquí
IMEI_CHECKER_API_KEY=tu_api_key_aquí
OWNER_ID=tu_telegram_user_id

# Webhook (opcional)
WEBHOOK_URL=https://tu-dominio.com
WEBHOOK_SECRET=tu_secreto

# AutoPinger
AUTOPINGER_ENABLED=true
AUTOPINGER_INTERVAL=300
```

## 🏃‍♂️ Uso

### Modo Polling (Por defecto)
```bash
poetry run python -m app.main
```

### Modo Webhook
1. Configura `WEBHOOK_URL` en `.env`
2. Ejecuta la aplicación
3. El webhook se configurará automáticamente

### Comandos del Bot

**Usuarios:**
- `/start` - Iniciar bot
- `/help` - Ayuda
- `/account` - Ver cuenta
- `/ping` - Verificar estado

**Admin (solo owner):**
- `/stats` - Estadísticas
- `/addbalance <user_id> <amount>` - Agregar saldo
- `/addservice <id> <title> <price> <category>` - Agregar servicio
- `/removeservice <id>` - Remover servicio
- `/listservices` - Listar servicios
- `/autopinger` - Estado AutoPinger
- `/autopingstart` - Iniciar AutoPinger
- `/autopingstop` - Detener AutoPinger

## 🔗 API Endpoints

- `GET /` - Estado general
- `GET /health` - Health check detallado
- `GET /stats` - Estadísticas públicas
- `POST /webhook` - Endpoint para webhook de Telegram
- `POST /admin/broadcast` - Broadcast (requiere auth)
- `GET /admin/users` - Lista de usuarios (requiere auth)

## 📁 Estructura del Proyecto

```
botmanager/
├── app/
│   ├── bot/
│   │   └── bot_manager.py    # Lógica principal del bot
│   ├── data/
│   │   └── services_data.py  # Datos de servicios IMEI
│   ├── models/
│   │   ├── user.py          # Modelo de usuario
│   │   └── webhook.py       # Modelo webhook
│   ├── services/
│   │   ├── database.py      # Base de datos de usuarios
│   │   ├── imei_checker.py  # Cliente API IMEI
│   │   ├── imei_validator.py # Validador IMEI
│   │   ├── response_formatter.py # Formateador respuestas
│   │   └── autopinger.py    # Servicio AutoPing
│   ├── config.py           # Configuración
│   └── main.py            # Aplicación FastAPI
├── pyproject.toml         # Configuración Poetry
├── Dockerfile
├── docker-compose.yml
└── README.md
```

## 🛠️ Desarrollo

```bash
# Instalar dependencias de desarrollo
poetry install

# Formatear código
poetry run black app/

# Linting
poetry run flake8 app/

# Tests
poetry run pytest
```

## 🐳 Docker

```bash
# Desarrollo
docker-compose up

# Producción con nginx
docker-compose --profile production up -d
```

## 📊 Monitoreo

- **Health Check**: `GET /health`
- **Métricas**: `GET /stats`
- **Logs**: Configuración estándar de Python logging
- **AutoPinger**: Mantiene el bot activo automáticamente

## 🔐 Seguridad

- Webhook con token secreto opcional
- Comandos admin restringidos por owner ID
- Validación de entrada en todos los endpoints
- Rate limiting en cliente HTTP

## 🚀 Deployment

### Heroku
```bash
# Crear app
heroku create tu-bot-app

# Variables de entorno
heroku config:set BOT_TOKEN=tu_token
heroku config:set IMEI_CHECKER_API_KEY=tu_key
heroku config:set WEBHOOK_URL=https://tu-bot-app.herokuapp.com

# Deploy
git push heroku main
```

### Railway
```bash
railway login
railway init
railway add
railway deploy
```

### VPS con nginx
```bash
# Clonar y configurar
git clone <repo> && cd botmanager
cp .env.example .env && nano .env

# Con docker-compose
docker-compose --profile production up -d

# O manual con Poetry + systemd
```

## 📝 Licencia

MIT License