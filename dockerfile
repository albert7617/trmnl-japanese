# Use the official Python 3.10 image as a base
FROM python:3.10-slim

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV APP_HOME=/app
ENV DATA_DIR=/app/data

# Set the working directory in the container
WORKDIR $APP_HOME

# Create the data directory that will be mounted
RUN mkdir -p $DATA_DIR

# Install system dependencies (if needed)
# RUN apt-get update && \
#     apt-get install -y --no-install-recommends ca-certificates && \
#     rm -rf /var/lib/apt/lists/*

ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt

# Copy requirements file first to leverage Docker cache
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy only Python files and the www folder
COPY *.py $APP_HOME/
COPY www $APP_HOME/www/

# Set volume and permissions
VOLUME $DATA_DIR

EXPOSE 80

# Run main.py when the container starts
# CMD ["bash"]
CMD ["python", "main.py"]