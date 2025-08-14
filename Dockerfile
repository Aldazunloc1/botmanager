# Base Python slim
FROM python:3.11-slim

# Evitar buffers y bytecode
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Instalar dependencias del sistema y npm para pm2
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    npm \
    && rm -rf /var/lib/apt/lists/*

# Instalar Poetry y pm2
RUN  npm install -g pm2

# Establecer directorio de trabajo
WORKDIR /app

# Copiar solo el contenido de tu carpeta app/ al contenedor
COPY app/ /app/



# Crear usuario no-root
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Comando para ejecutar el bot con pm2-runtime
CMD ["pm2-runtime", "main.py", "--interpreter=python3"]
