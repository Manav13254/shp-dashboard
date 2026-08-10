FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

# Copy codebase
COPY . .

# Expose port
EXPOSE 5000

# Environment variables
ENV PORT=5000
ENV PYTHONUNBUFFERED=1

# Command to run the server
CMD ["gunicorn", "run:app", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "120", "--preload"]
