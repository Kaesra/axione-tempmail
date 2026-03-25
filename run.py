from app.config import settings

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.web_host, port=settings.web_port, reload=False)
