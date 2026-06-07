import json
import re
import os
from pathlib import Path
from typing import List
from uuid import uuid4

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
    VectorParams,
)
from sentence_transformers import SentenceTransformer

from schema import IntentSchema


class VectorStore:
    def __init__(self):
        self.collection_name = "intents"
        self.model_name = os.getenv("MODEL_NAME", "BAAI/bge-small-en-v1.5")
        self.model = SentenceTransformer(self.model_name)
        self.enable_reranker = os.getenv("ENABLE_RERANKER", "false").lower() == "true"
        self.reranker = self._build_reranker()
        self.client = self._build_qdrant_client()
        self._setup_collection()
        self._seed_initial_intents()
        self.policy_rules = {
            "payflex_inspira_hsa": [
                r"\bpay[\s-]?flex\b",
                r"\binspira\b",
                r"\bhsa\b",
                r"\b(debit|benefits?)\s+card\b",
                r"\b(activate|replacement|replace|order|lost|declined)\b",
            ],
            "coverage_dates": [
                r"\bcoverage\b",
                r"\beffective\b",
                r"\bactive\b",
                r"\bstart\b",
                r"\bend\b",
                r"\brenewal\b",
                r"\beligibility\b",
                r"\bperiod\b",
            ],
            "health_care_procedures_services": [
                r"\bmammogram\b",
                r"\bflu shot\b",
                r"\binfluenza vaccine\b",
                r"\beye exam\b",
                r"\bvision\b",
                r"\bwellness visit\b",
                r"\bphysical exam\b",
                r"\breferral\b",
                r"\bspecialist\b",
                r"\bpreventive\b",
                r"\bmri\b",
            ],
            "faq": [
                r"\bdeductible\b",
                r"\bcoinsurance\b",
                r"\bcopay\b",
                r"\bout[-\s]of[-\s]pocket\b",
                r"\bpremium\b",
                r"\bmember id\b",
                r"\bclaim\b",
                r"\beob\b",
            ],
            "self_harm_english": [
                r"\bkill myself\b",
                r"\bwish i (was dead|hadn't been born)\b",
                r"\bend it all\b",
                r"\bsuicid",
                r"\bharm myself\b",
                r"\bmental health emergency\b",
                r"\bhopeless\b",
                r"\btrapped\b",
                r"\btired of life\b",
            ],
            "cancer_care_support_program": [
                r"\bcancer care support program\b",
                r"\bcancer care\b",
            ],
        }

    def _build_reranker(self):
        if not self.enable_reranker:
            return None
        from sentence_transformers import CrossEncoder

        model_name = os.getenv(
            "RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
        )
        return CrossEncoder(model_name)

    def _build_qdrant_client(self):
        qdrant_url = os.getenv("QDRANT_URL")
        if qdrant_url:
            return QdrantClient(url=qdrant_url)

        default_path = Path(__file__).resolve().parent / "qdrant_data"
        qdrant_path = Path(os.getenv("QDRANT_PATH", str(default_path)))
        qdrant_path.mkdir(parents=True, exist_ok=True)
        return QdrantClient(path=str(qdrant_path))

    def _setup_collection(self):
        vector_size = self.model.get_embedding_dimension()
        collections = self.client.get_collections().collections
        exists = any(c.name == self.collection_name for c in collections)
        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
            )

    def _seed_initial_intents(self):
        existing_count = self.client.count(collection_name=self.collection_name).count
        if existing_count > 0:
            return

        intents_path = Path(__file__).resolve().parent / "intent.json"
        with intents_path.open("r", encoding="utf-8") as handle:
            raw_intents = json.load(handle)

        payloads = []
        for intent_name, intent_data in raw_intents.items():
            description = intent_data.get("description", "").strip()
            intent_keywords = intent_data.get("keywords", [])
            if description:
                payloads.append(
                    IntentSchema(
                        intent=intent_name,
                        description=description,
                        keywords=intent_keywords,
                        type="intent",
                    )
                )

            services = intent_data.get("services", {})
            for service_name, service_data in services.items():
                service_description = service_data.get("description", "").strip()
                if service_description:
                    payloads.append(
                        IntentSchema(
                            intent=service_name,
                            description=service_description,
                            keywords=service_data.get("keywords", []),
                            parent_intent=intent_name,
                            type="service",
                        )
                    )

        if payloads:
            self.add_intents(payloads)

    def _encode(self, text: str):
        return self.model.encode(text, normalize_embeddings=True).tolist()

    def _compose_embedding_text(self, payload: IntentSchema):
        parts = [payload.intent.strip(), payload.description.strip()]
        if payload.keywords:
            parts.extend([kw.strip() for kw in payload.keywords if kw and kw.strip()])
        return " | ".join([part for part in parts if part])

    def _search_one(self, query: str, score_threshold: float, query_filter: Filter):
        # qdrant-client 1.14+ uses query_points; legacy .search() was removed from QdrantClient.
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=self._encode(query),
            limit=1,
            score_threshold=score_threshold,
            query_filter=query_filter,
            with_payload=True,
        )
        search_result = response.points if response else []
        if not search_result:
            return None

        top = search_result[0]
        return self._to_result(top)

    def _to_result(self, point):
        return {
            "id": str(point.id),
            "score": point.score,
            "intent": point.payload.get("intent"),
            "description": point.payload.get("description"),
            "keywords": point.payload.get("keywords", []),
            "parent_intent": point.payload.get("parent_intent"),
            "type": point.payload.get("type"),
        }

    def _search_many(
        self,
        query: str,
        query_filter: Filter,
        limit: int = 6,
        score_threshold: float | None = None,
    ):
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=self._encode(query),
            limit=limit,
            score_threshold=score_threshold,
            query_filter=query_filter,
            with_payload=True,
        )
        points = response.points if response else []
        return [self._to_result(point) for point in points]

    def _policy_boost(self, intent_name: str, query: str):
        patterns = self.policy_rules.get(intent_name, [])
        if not patterns:
            return 0.0
        text = query.lower()
        matches = sum(1 for pattern in patterns if re.search(pattern, text))
        boost = min(matches * 0.08, 0.28)
        if intent_name == "self_harm_english" and matches == 0:
            # Prevent false positives when user just asks for an agent.
            boost -= 0.16
        if intent_name == "cancer_care_support_program" and not re.search(
            r"\bcancer\b", text
        ):
            boost -= 0.2
        if intent_name == "faq" and re.search(
            r"\b(pay[\s-]?flex|inspira|hsa|mammogram|flu shot|eye exam|wellness|physical therapy|referral|specialist|mri)\b",
            text,
        ):
            boost -= 0.14
        return boost

    def _clean_internal_keys(self, item: dict):
        return {k: v for k, v in item.items() if not k.startswith("_")}

    def _force_intent_by_policy(self, query: str):
        text = query.lower()
        if re.search(
            r"\b(kill myself|end it all|suicid|harm myself|mental health emergency|behavioral health support|wish i was dead|wish i hadn't been born|hopeless|trapped|tired of life|i'm in crisis|unsafe)\b",
            text,
        ):
            return "self_harm_english"
        if re.search(r"\b(pay[\s-]?flex|inspira|hsa)\b", text) and re.search(
            r"\b(card|activate|replace|replacement|order|declined|debit)\b", text
        ):
            return "payflex_inspira_hsa"
        if re.search(r"\bcancer care support program\b", text):
            return "cancer_care_support_program"
        if re.search(
            r"\b(mammogram|breast imaging|flu shot|influenza vaccine|eye exam|vision screening|wellness visit|physical exam|physical therapy|referral|specialist|mri)\b",
            text,
        ):
            return "health_care_procedures_services"
        return None

    def _select_top_level_intent(self, query: str, score_threshold: float):
        candidates = self._search_many(
            query=query,
            query_filter=Filter(
                must=[FieldCondition(key="type", match=MatchValue(value="intent"))]
            ),
            limit=8,
            score_threshold=max(0.2, score_threshold - 0.2),
        )
        if not candidates:
            return None

        for candidate in candidates:
            candidate["_policy_boost"] = self._policy_boost(candidate["intent"], query)
            candidate["_combined_score"] = candidate["score"] + candidate["_policy_boost"]

        if self.reranker:
            top_candidates = sorted(
                candidates, key=lambda item: item["_combined_score"], reverse=True
            )[:4]
            pairs = [
                [query, self._compose_embedding_text(IntentSchema(**{
                    "intent": item["intent"],
                    "description": item["description"] or "",
                    "keywords": item.get("keywords", []),
                    "parent_intent": item.get("parent_intent"),
                    "type": item.get("type"),
                }))]
                for item in top_candidates
            ]
            rerank_scores = self.reranker.predict(pairs)
            for item, rerank_score in zip(top_candidates, rerank_scores):
                item["_combined_score"] += float(rerank_score) * 0.1

        best = max(candidates, key=lambda item: item["_combined_score"])
        if best["_combined_score"] < score_threshold:
            return None
        return self._clean_internal_keys(best)

    def get_intent(self, query: str, score_threshold: float = 0.45):
        normalized = query.strip().lower()
        if normalized in {"yes", "1", "medical"}:
            return None

        forced_intent = self._force_intent_by_policy(query)
        if forced_intent:
            forced_match = self._search_one(
                query=query,
                score_threshold=0.0,
                query_filter=Filter(
                    must=[
                        FieldCondition(key="type", match=MatchValue(value="intent")),
                        FieldCondition(key="intent", match=MatchValue(value=forced_intent)),
                    ]
                ),
            )
            if forced_match:
                top_level_match = forced_match
            else:
                top_level_match = {
                    "id": None,
                    "score": 1.0,
                    "intent": forced_intent,
                    "description": "",
                    "keywords": [],
                    "parent_intent": None,
                    "type": "intent",
                }
        else:
            top_level_match = self._select_top_level_intent(
                query=query,
                score_threshold=score_threshold,
            )

        if not top_level_match:
            return None

        service_match = self._search_one(
            query=query,
            score_threshold=score_threshold,
            query_filter=Filter(
                must=[
                    FieldCondition(key="type", match=MatchValue(value="service")),
                    FieldCondition(
                        key="parent_intent",
                        match=MatchValue(value=top_level_match["intent"]),
                    ),
                ]
            ),
        )
        if service_match:
            parent = service_match.get("parent_intent") or top_level_match["intent"]
            return {
                "id": service_match["id"],
                "score": service_match["score"],
                "intent": parent,
                "nested_intent": service_match["intent"],
                "description": service_match["description"],
                "parent_intent": None,
                "type": service_match.get("type"),
                "funnel_parent_intent": top_level_match["intent"],
            }

        return top_level_match

    def add_intent(self, payload: IntentSchema):
        intent_type = payload.type or ("service" if payload.parent_intent else "intent")
        point_id = str(uuid4())
        point = PointStruct(
            id=point_id,
            vector=self._encode(self._compose_embedding_text(payload)),
            payload={
                "intent": payload.intent,
                "description": payload.description,
                "keywords": payload.keywords or [],
                "parent_intent": payload.parent_intent,
                "type": intent_type,
            },
        )
        self.client.upsert(collection_name=self.collection_name, points=[point])
        return point_id

    def add_intents(self, payloads: List[IntentSchema]):
        points = []
        for payload in payloads:
            intent_type = payload.type or ("service" if payload.parent_intent else "intent")
            points.append(
                PointStruct(
                    id=str(uuid4()),
                    vector=self._encode(self._compose_embedding_text(payload)),
                    payload={
                        "intent": payload.intent,
                        "description": payload.description,
                        "keywords": payload.keywords or [],
                        "parent_intent": payload.parent_intent,
                        "type": intent_type,
                    },
                )
            )
        self.client.upsert(collection_name=self.collection_name, points=points)

    def list_intents(self, limit: int = 200):
        records, _ = self.client.scroll(
            collection_name=self.collection_name,
            with_payload=True,
            limit=limit,
        )
        return [
            {
                "id": str(record.id),
                "intent": record.payload.get("intent"),
                "description": record.payload.get("description"),
                "keywords": record.payload.get("keywords", []),
                "parent_intent": record.payload.get("parent_intent"),
                "type": record.payload.get("type"),
            }
            for record in records
        ]

    def remove_intent(self, intent_id: str):
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=PointIdsList(points=[intent_id]),
        )