FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN pip install poetry

# Set work directory
WORKDIR /app

# Copy poetry files
COPY pyproject.toml poetry.lock* /app/

# Configure poetry
RUN poetry config virtualenvs.create false

<<<<<<< HEAD
# Instalar dependencias (excepto torch, si da problemas)
RUN grep -v "torch" requirements.txt 
# Instalar torch CPU (opcional)
RUN pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
=======
# Install dependencies
RUN poetry install --no-dev

# Copy application
COPY . /app/
>>>>>>> 0fb9278 (commit)

# Create non-root user
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Expose port
EXPOSE 8000

RUN poetry install --only=main
# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run application
CMD ["python", "-m", "app.main"]