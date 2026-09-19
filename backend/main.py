from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.logging_config import setup_logging

setup_logging()

from app.api import analysis, auth, holdings  # noqa: E402  (must follow setup_logging)

app = FastAPI(title="Portfolio Risk Copilot")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(holdings.router)
app.include_router(analysis.router)


@app.get("/")
def root():
    return {"status": "ok"}
