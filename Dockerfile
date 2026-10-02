FROM python:3.12-slim

RUN useradd -m -u 1000 user
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=user . .
USER user

# Hugging Face Spaces écoute sur le port 7860 (la variable PORT active le mode « en ligne »)
ENV PORT=7860
EXPOSE 7860
CMD ["python", "web.py"]
