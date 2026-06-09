"""API v1 路由注册"""

from fastapi import APIRouter

from src.platform_api.api.v1.systems import router as systems_router
from src.platform_api.api.v1.documents import router as documents_router
from src.platform_api.api.v1.documents import systems_doc_router
from src.platform_api.api.v1.batches import router as batches_router
from src.platform_api.api.v1.testcases import router as testcases_router
from src.platform_api.api.v1.exports import router as exports_router
from src.platform_api.api.v1.callbacks import router as callbacks_router

v1_router = APIRouter(prefix="/api/v1")

v1_router.include_router(systems_router)
v1_router.include_router(systems_doc_router)  # /systems/:id/documents, /systems/:id/documents/batch
v1_router.include_router(documents_router)
v1_router.include_router(batches_router)
v1_router.include_router(testcases_router)
v1_router.include_router(exports_router)
v1_router.include_router(callbacks_router)
