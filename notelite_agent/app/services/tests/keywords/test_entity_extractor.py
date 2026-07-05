from app.services.ingestion.processors.keywords.entity_extractor import extract_entities


def test_spacy_entity_extraction_uses_strict_allowlist(monkeypatch):
    class Entity:
        def __init__(self, text, label):
            self.text = text
            self.label_ = label

    class Nlp:
        max_length = 1000

        def pipe(self, texts):
            for _text in texts:
                yield type("Doc", (), {
                    "ents": [
                        Entity("Sofia Andersen", "PERSON"),
                        Entity("Daniel Kahneman's", "PERSON"),
                        Entity("Qdrant", "PRODUCT"),
                        Entity("Data Center", "FAC"),
                        Entity("Outage", "EVENT"),
                    ]
                })()

    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.entity_extractor.get_spacy_nlp",
        lambda: Nlp(),
    )

    assert extract_entities("Sofia used Qdrant at the Data Center during the Outage.") == [
        "Sofia Andersen",
        "Daniel Kahneman",
        "Qdrant",
    ]
