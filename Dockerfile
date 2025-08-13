# Usa Python 3.12 slim como base
FROM python:3.12-slim

# Crear carpeta de trabajo
WORKDIR /app

# Copiar requirements
COPY requirements.txt .

# Actualizar pip
RUN pip install --upgrade pip

# Instalar dependencias (excepto torch, si da problemas)
RUN grep -v "torch" requirements.txt 
# Instalar torch CPU (opcional)
RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu

# Copiar todo el proyecto
COPY . .

# Exponer el puerto del bot
EXPOSE 8000

# Comando por defecto al iniciar el contenedor
CMD ["python", "main.py"]
