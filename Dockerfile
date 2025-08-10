# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container at /app
COPY requirements.txt .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application's code into the container
COPY ./app /app/app
COPY client_secret.json /app/client_secret.json

# Create a directory for token caching
RUN mkdir -p /app/app/token_cache

# Command to run the application
CMD ["python", "-m", "app.main"]