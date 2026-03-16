from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import MONGO_DB_URL, COLLECTION_NAME


def create_mongo_client() -> AsyncIOMotorClient:
    return AsyncIOMotorClient(MONGO_DB_URL)


def get_mongo_database_name() -> str:
    return COLLECTION_NAME
