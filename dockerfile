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
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        fontconfig \
        gcc \
        pkg-config \
        libcairo2-dev \
        libgirepository1.0-dev \
    && rm -rf /var/lib/apt/lists/*  # Clean up to reduce image size

# Create fonts directory
RUN mkdir -p /usr/share/fonts/truetype/custom

# Copy your font files (replace with your font files)
COPY ./www/NotoSansJP-VariableFont_wght.ttf /usr/share/fonts/truetype/custom/

# Update font cache
RUN fc-cache -f -v

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