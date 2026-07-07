# Usar una imagen oficial de Python slim como base
FROM python:3.12-slim

# Configurar variables de entorno para optimizar Python en Docker
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Establecer el directorio de trabajo en el contenedor
WORKDIR /app

# Crear directorio para los archivos SQLite (bases de datos)
RUN mkdir -p /app/data

# Copiar primero el archivo de requerimientos para aprovechar la caché de Docker
COPY requirements.txt .

# Instalar dependencias
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código del servicio
COPY app.py .

# Exponer el puerto del servicio FastAPI
EXPOSE 8000

# Verificación de salud del contenedor vía el endpoint /api/health
HEALTHCHECK --interval=10s --timeout=5s --retries=10 --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health')" || exit 1

# Comando para ejecutar la aplicación
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
