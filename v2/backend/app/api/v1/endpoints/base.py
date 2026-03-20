from fastapi import APIRouter

router = APIRouter(tags=['base'])


@router.get('/health')
def health_check():
    return {"STATUS": "OK"}
