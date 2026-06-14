from fastapi import APIRouter
from vector_store import VectorStore
from schema import IntentSchema, QuerySchema

router = APIRouter(prefix='/api')

vector_store = VectorStore()

@router.get('/get-intents')
def get_intents():
    intents = vector_store.list_intents()
    return [
        {
            "id": intent['id'],
            "intent": intent['intent'],
            "description": intent["description"][:100],
            "keywords": intent["keywords"],
            "parent_intent": intent["parent_intent"],
            "type": intent["type"],
        }
        for intent in intents
    ]


@router.post('/add-intent')
def add_intent(new_intent: IntentSchema):
    intent_id = vector_store.add_intent(new_intent)
    return {"message": "Added Successfully", "id": intent_id}


@router.delete('/remove-intent/{intent_id}')
def remove_intent(intent_id: str):
    vector_store.remove_intent(intent_id)
    return {"message": "Removed Successfully", "id": intent_id}

@router.post('/classify-intent')
def classify_intent(request: QuerySchema):
    result = vector_store.get_intent(
        query=request.query,
        score_threshold=request.score_threshold or 0.45,
    )
    if not result:
        return {"intent": None, "message": "No confident match found"}
    return result
