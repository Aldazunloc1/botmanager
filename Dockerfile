FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Instalar dependencias del sistema y npm para pm2
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Instalar Poetry y pm2
RUN pip install poetry && npm install -g pm2

# Directorio de trabajo
WORKDIR /app


# Copiar código
COPY . /app/

# Crear usuario no-root
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Ejecutar el bot con pm2-runtime
CMD ["pm2-runtime", "main.py", "--interpreter=python3"]
