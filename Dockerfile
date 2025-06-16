FROM python:3.12-slim

WORKDIR /app

# Copy requirements first for better cache utilization
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application code
COPY . .

# Create necessary directories
RUN mkdir -p workbench

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Expose ports - 8501 for Streamlit and 8001 for when the Alert Queue service is started
EXPOSE 8501
EXPOSE 8001

# Command to run the Streamlit application
CMD ["streamlit", "run", "streamlit_app.py", "--server.port=8501", "--server.address=0.0.0.0"]
