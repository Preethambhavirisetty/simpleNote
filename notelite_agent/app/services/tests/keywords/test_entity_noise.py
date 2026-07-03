from app.services.ingestion.processors.keywords.entity_extractor import extract_entities


def test_spacy_entity_extraction_filters_table_ocr_and_generic_noise(monkeypatch):
    class Entity:
        def __init__(self, text, label="ORG"):
            self.text = text
            self.label_ = label

    class Nlp:
        max_length = 1000

        def pipe(self, texts):
            for _text in texts:
                yield type("Doc", (), {
                    "ents": [
                        Entity("Variable QDRANT_PORT"),
                        Entity("Resolution Retry"),
                        Entity("ge st io n"),
                        Entity("GPU"),
                        Entity("Qdrant", "PRODUCT"),
                    ]
                })()

    monkeypatch.setattr(
        "app.services.ingestion.processors.keywords.entity_extractor.get_spacy_nlp",
        lambda: Nlp(),
    )

    assert extract_entities("normalized table and OCR text") == ["Qdrant"]
