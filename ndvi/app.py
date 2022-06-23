#!/usr/bin/env python3
from fastapi import FastAPI
from .api import router


app = FastAPI(version="0.1.0", description="FastAPI REST service")
app.include_router(router)

