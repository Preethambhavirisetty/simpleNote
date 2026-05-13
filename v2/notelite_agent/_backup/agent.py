"""
Fundamental Ideas:
no RAG + no LLM
no RAG + LLM: keyword count
RAG + LLM


I'LL COME BACK TO IT SOOOOON

skills
request structure: query
thinking process:
    - identify intents of the query: what does the user want? : get notes which contains challenges, summarize the results
    - sort the intents: which task to execute first
    - execute each task sync or async: decide which to execute async vs sync
    - gather results and repeat until it answers user's query
response structure:
    {"context": "gathered results so far", "is_answer": bool, "action": "list or one action from predefined list", "skills": "skill from a predefined list"}
"""


from pipeline.llm import llm_call
from core.config import LLM_API_BASE


skills = []

_MISTRAL_TIMEOUT = 120.0
_MISTRAL_MODEL = "mistral-7b"


class Agent():
    def __init__(self):
        pass

    def execute(self, query: str):
        payload = {
            "model": _MISTRAL_MODEL,
            "messages": [
                {"role": "system", "content": (
                    "you are an note agent, who knows what user is asking about and then decides which skill to choose and what action to perform",
                    "once you have an answer make is_answer to true, "
                )},
                {"role": "user", "content": query},
            ],
            "max_tokens": 80,
            "temperature": 0.1,
        }
        llm_call(
            payload,
            base_url=LLM_API_BASE,
            timeout=_MISTRAL_TIMEOUT,
            params={"purpose": "summarization"}
        )


def get_agent():
    return Agent()

def think_and_answer(query: str):
    agent = get_agent()
    while agent:
        resp = agent.execute(query)
        if resp.is_answer:
            break
        query = resp.query
    return resp.answer

if __name__ == "__main__":
    query = "get me the notes where I described all the challenges at my work, if there are multiple then summarize them all"
    answer = think_and_answer(query)
