FROM mcr.microsoft.com/playwright/python:v1.49.1-noble
RUN pip install --break-system-packages --no-cache-dir playwright==1.49.1
