import pytest

from app.services.ingestion.processors.chunking.chunk_processor import ChunkProcessor
from app.services.tests.chunk_test_data_stress import TEST_CASES


def _case_id(case: dict) -> str:
    return case["name"]


def _chunk_text(chunks) -> str:
    return "\n\n".join(chunk.content for chunk in chunks)


@pytest.mark.parametrize("case", TEST_CASES, ids=_case_id)
def test_chunk_test_data_expectations(case):
    chunks = ChunkProcessor().process(case["text"])
    expected = case["expected"]

    if "chunk_count" in expected:
        assert len(chunks) == expected["chunk_count"]
    if "chunk_count_min" in expected:
        assert len(chunks) >= expected["chunk_count_min"]

    chunk_types = [chunk.chunk_type for chunk in chunks]
    for chunk_type in expected.get("chunk_types", []):
        assert chunk_type in chunk_types

    text = _chunk_text(chunks)
    for fragment in expected.get("must_contain", []):
        assert fragment in text

    for fragment in expected.get("must_not_split", []):
        containing_chunks = [chunk for chunk in chunks if fragment in chunk.content]
        assert len(containing_chunks) == 1


@pytest.mark.parametrize(
    "case",
    [
        case
        for case in TEST_CASES
        if case["expected"].get("chunk_count") == 1
        and case["expected"].get("must_not_split")
    ],
    ids=_case_id,
)
def test_declared_atomic_chunks_keep_fragments_together(case):
    chunks = ChunkProcessor().process(case["text"])
    expected_fragments = case["expected"]["must_not_split"]

    assert len(chunks) == 1
    for fragment in expected_fragments:
        assert fragment in chunks[0].content


def test_preserves_nested_heading_context():
    text = """
1. Introduction
This is the introduction.

1.1 Background
Background details.

1.2 Objectives
Objective details.
"""

    chunks = ChunkProcessor().split(text)

    assert any("1.1 Background" in c for c in chunks)
    assert any("1.2 Objectives" in c for c in chunks)
    assert any("1. Introduction" in c for c in chunks)
    assert not any(" > " in c for c in chunks)


def test_never_merge_across_top_level_headings():
    text = """
1. Section A
This text belongs to section A.

2. Section B
This text belongs to section B.
"""

    chunks = ChunkProcessor().split(text)

    assert any("1. Section A" in c for c in chunks)
    assert any("2. Section B" in c for c in chunks)
    assert not any("1. Section A" in c and "2. Section B" in c for c in chunks)


def test_list_items_are_not_parsed_as_headings():
    text = """
DEPLOYMENT GUIDE

1. Installation
Before deployment, complete the following steps:

1. Download package
2. Verify checksum
3. Extract archive
4. Configure environment

1.1 Validation
Validation confirms successful installation.

2. Operations
Operational procedures begin after installation.
"""

    chunks = ChunkProcessor().split(text)

    assert any("1. Installation" in c for c in chunks)
    assert any("1. Download package" in c for c in chunks)
    assert any("4. Configure environment" in c for c in chunks)
    assert any("1.1 Validation" in c for c in chunks)
    assert not any(
        "1. Configure environment" in c and "1.1 Validation" in c
        for c in chunks
    )


def test_preserves_fenced_code_blocks():
    text = """
API DOCUMENTATION

1. Authentication
Use the following example:

```python
import requests
response = requests.post(
    'https://api.example.com/login',
    json={'username':'user','password':'secret'}
)
print(response.json())
```

1.1 Response Handling
Applications should validate status codes and retry transient failures.
"""

    chunks = ChunkProcessor().split(text)

    assert any("```python" in c and "print(response.json())" in c for c in chunks)
    assert not any("1.1 Response Handling" in c and "```python" in c for c in chunks)
    assert any("1.1 Response Handling" in c for c in chunks)


def test_numbered_list_items_do_not_update_heading_context():
    text = """
CHECKLIST

1. Overview
This is the overview.

2. Tasks
Follow these steps:

1. Download package
2. Verify checksum
3. Configure environment

2.1 Validation
Validation confirms successful installation.
"""

    chunks = ChunkProcessor().split(text)

    assert any("2. Tasks" in c for c in chunks)
    assert any("1. Download package" in c for c in chunks)
    assert any("2.1 Validation" in c for c in chunks)
    assert not any("1. Download package" in c and "2.1 Validation" in c for c in chunks)


def test_deep_heading_subsections_remain_separate():
    text = """
SYSTEM ARCHITECTURE

1. Platform
Overview of the platform.

1.1 Services
Description of services.

1.1.1 Authentication
Authentication validates user identity.

1.1.1.1 Token Validation
Token validation checks expiration and signature.

1.1.1.2 Session Management
Session management maintains authenticated state.

1.1.2 Authorization
Authorization controls resource access.

1.2 Storage
Storage handles persistence.

2. Deployment
Deployment covers release procedures.
"""

    chunks = ChunkProcessor().split(text)

    assert any("1.1.1.2 Session Management" in c for c in chunks)
    assert any("1.1.2 Authorization" in c for c in chunks)
    assert any("1.2 Storage" in c for c in chunks)
    assert all(
        not ("1.1.1.2 Session Management" in c and "1.1.2 Authorization" in c)
        for c in chunks
    )


def test_table_headings_do_not_merge_into_following_section():
    text = """
PRODUCT PERFORMANCE REPORT

1. Revenue Summary
The following table contains quarterly performance metrics.

| Quarter | Revenue | Growth | Customers |
|---------|----------|---------|-----------|
| Q1 2024 | $100000 | 5% | 1200 |
| Q2 2024 | $125000 | 25% | 1450 |
| Q3 2024 | $150000 | 20% | 1680 |
| Q4 2024 | $180000 | 20% | 1950 |
| Q1 2025 | $210000 | 17% | 2300 |
| Q2 2025 | $250000 | 19% | 2700 |

2. Analysis
Revenue growth remained consistent throughout the reporting period. Customer acquisition accelerated significantly after Q3 2024.
"""

    chunks = ChunkProcessor().split(text)

    assert any("2. Analysis" in c for c in chunks)
    assert not any(
        "1. Revenue Summary" in c and "2. Analysis" in c
        for c in chunks
    )


def test_fenced_code_with_blank_lines_stays_atomic():
    text = """
API DOCUMENTATION

1. Example
Use this example:

```python
class ChunkProcessor:
    def embed(self):
        return embeddings

    def split(self, document):
        return []
```

1.1 After Code
This section should not be part of the code block chunk.
"""

    chunks = ChunkProcessor().split(text)

    code_chunks = [chunk for chunk in chunks if "```python" in chunk or "def split" in chunk]
    assert len(code_chunks) == 1
    assert "```python" in code_chunks[0]
    assert "def split(self, document):" in code_chunks[0]
    assert code_chunks[0].count("```") == 2
    assert "1.1 After Code" not in code_chunks[0]


def test_heading_and_immediate_body_stay_together():
    text = """
1. Executive Summary
Overview text.

1.2 Objectives
The primary goals are retrieval accuracy, scalability, and maintainability.
"""

    chunks = ChunkProcessor().split(text)

    assert any(
        "1.2 Objectives" in chunk
        and "The primary goals are retrieval accuracy" in chunk
        for chunk in chunks
    )
    assert not any(chunk.strip().endswith("1.2 Objectives") for chunk in chunks)


def test_deep_architecture_hierarchy_does_not_collapse_into_one_chunk():
    text = """
2. Platform Architecture
Platform overview.

2.1 Ingestion
Ingestion receives source files.

2.1.1 Validation
Validation checks file integrity.

2.1.1.1 File Checks
File checks verify supported formats.

2.1.1.2 Security Checks
Security checks scan for unsafe content.

2.1.2 Extraction
Extraction converts documents into text.

2.2 Chunking
Chunking creates retrieval-friendly segments.

2.2.1 Hybrid Chunking
Hybrid chunking combines headings and semantic windows.

2.2.2 Embedding
Embedding converts chunks into vectors.
"""

    chunks = ChunkProcessor().split(text)

    file_format_chunks = [chunk for chunk in chunks if "supported formats" in chunk]
    hybrid_chunks = [chunk for chunk in chunks if "Hybrid chunking combines" in chunk]
    assert file_format_chunks
    assert hybrid_chunks
    assert not any("supported formats" in chunk and "Hybrid chunking combines" in chunk for chunk in chunks)


def _with_small_chunk_budget(size: int):
    from app.services.ingestion.processors.chunking import token_budget, window_chunker

    previous_token_budget_size = token_budget.MAX_CHUNK_SIZE
    previous_window_size = window_chunker.MAX_CHUNK_SIZE
    token_budget.MAX_CHUNK_SIZE = size
    window_chunker.MAX_CHUNK_SIZE = size
    return token_budget, window_chunker, previous_token_budget_size, previous_window_size


def _restore_chunk_budget(state):
    token_budget, window_chunker, previous_token_budget_size, previous_window_size = state
    token_budget.MAX_CHUNK_SIZE = previous_token_budget_size
    window_chunker.MAX_CHUNK_SIZE = previous_window_size


def test_large_tables_split_only_between_rows():
    state = _with_small_chunk_budget(80)
    try:
        text = """
## Cloud Provider Service Comparison Matrix
| Category | Service | AWS | Azure | GCP | Notes |
|----------|---------|-----|-------|-----|-------|
| Compute | Virtual Machines | EC2 | Azure VMs | Compute Engine | All support spot/preemptible instances |
| Networking | Load Balancer | ALB / NLB | Azure Load Balancer | Cloud Load Balancing | Layer 4 and Layer 7 options |
| Networking | API Gateway | API Gateway | APIM | Apigee / Cloud Endpoints | Apigee is most full-featured |
| DevOps | Infrastructure as Code | CloudFormation / CDK | Bicep / ARM | Deployment Manager | Most teams prefer Terraform |
"""

        chunks = ChunkProcessor().split(text)

        assert any("ALB / NLB" in chunk for chunk in chunks)
        assert not any(chunk.strip().startswith("B |") for chunk in chunks)
        assert not any("ALB / NL\nB" in chunk for chunk in chunks)
    finally:
        _restore_chunk_budget(state)


def test_long_paragraph_splits_without_visible_sentence_overlap():
    state = _with_small_chunk_budget(45)
    try:
        repeated_sentence = "The ACID guarantees shaped database design for decades."
        text = f"""
## Database History
Early systems focused on correctness under concurrent access. {repeated_sentence} Two phase locking provided a practical serializability protocol. Multi version concurrency control allowed readers and writers to proceed independently. Distributed SQL systems later combined horizontal scale with stronger transactional guarantees.
"""

        chunks = ChunkProcessor().split(text)
        matching_chunks = [chunk for chunk in chunks if repeated_sentence in chunk]

        assert len(chunks) > 1
        assert len(matching_chunks) == 1
    finally:
        _restore_chunk_budget(state)


def test_heading_only_stub_sections_are_not_indexed():
    text = """
## 1. Distributed Systems
Useful distributed systems content.
### 1.1 What Is a Distributed System?
More useful content.
#### 1.2.3 Partition Tolerance
### 1.3 The CAP Theorem
## 2. Networking Fundamentals
## 3. Consensus Algorithms
## 4. Relational Databases
### 4.1 ACID Transactions
ACID transactions have atomicity, consistency, isolation, and durability.
"""

    chunks = ChunkProcessor().split(text)

    assert any("ACID transactions have" in chunk for chunk in chunks)
    assert not any(
        "1.3 The CAP Theorem" in chunk
        and "ACID transactions have" not in chunk
        for chunk in chunks
    )


def test_contact_address_blocks_stay_atomic():
    text = """
# Contact Information
**European Office:**
TechCorp Europe GmbH
Hauptstraße 42
10117 Berlin
Germany
Phone: +49 30 555 01000
EU Data Protection: dpo@techcorp-eu.example.com

**Asia-Pacific Office:**
TechCorp Asia Pacific Pte. Ltd.
1 Raffles Place, #28-00 One Raffles Place
Singapore 048616
Phone: +65 6555 0100
"""

    chunks = ChunkProcessor().split(text)
    berlin_chunks = [chunk for chunk in chunks if "10117 Berlin" in chunk]
    singapore_chunks = [chunk for chunk in chunks if "Singapore 048616" in chunk]

    assert len(berlin_chunks) == 1
    assert "TechCorp Europe GmbH" in berlin_chunks[0]
    assert "Phone: +49 30 555 01000" in berlin_chunks[0]
    assert len(singapore_chunks) == 1
    assert "TechCorp Asia Pacific" in singapore_chunks[0]


def test_plain_us_contact_address_block_stays_atomic():
    text = """
## Contact Information
Acme Holdings
100 Main Street
Suite 450
Denver, CO 80202
Phone: +1 303 555 0100
Email: hello@example.com

## Quotes
Quoted material belongs in a separate section.
"""

    chunks = ChunkProcessor().split(text)
    address_chunks = [chunk for chunk in chunks if "100 Main Street" in chunk]

    assert len(address_chunks) == 1
    assert "Acme Holdings" in address_chunks[0]
    assert "Suite 450" in address_chunks[0]
    assert "hello@example.com" in address_chunks[0]
    assert "## Quotes" not in address_chunks[0]


def test_structural_boundary_sections_do_not_merge():
    text = """
## Address
100 Main Street
Denver, CO 80202

## Quotes
Quote one.

## Appendix
Appendix material.

## Glossary
Term definitions.

## Footer
Footer text.
"""

    chunks = ChunkProcessor().split(text)

    assert not any("## Quotes" in chunk and "## Appendix" in chunk for chunk in chunks)
    assert not any("## Appendix" in chunk and "## Glossary" in chunk for chunk in chunks)


def test_ocr_hyphenation_repaired_before_chunking():
    text = """
## Notes
The implementation improved experi-
ence across the document.
"""

    chunks = ChunkProcessor().split(text)
    joined = "\n\n".join(chunks)

    assert "experience" in joined
    assert "experi-" not in joined
    assert "\nence" not in joined


def test_divider_lines_force_boundaries_without_becoming_chunks():
    text = "Before the divider.\n\n------------------------\n\nAfter the divider."

    chunks = ChunkProcessor().process(text)

    assert [chunk.content for chunk in chunks] == ["Before the divider.", "After the divider."]
    assert all("---" not in chunk.content for chunk in chunks)


def test_divider_only_document_produces_no_chunks():
    chunks = ChunkProcessor().process("---\n________\n********")

    assert chunks == []


def test_headed_document_is_not_short_circuited_by_contact_signal():
    text = "# Review\n\n## Summary\n\nWork completed.\n\n## Contact\n\nEmail: team@example.com\n\n## Final\n\nDone."

    chunks = ChunkProcessor().process(text)

    assert len(chunks) == 3
    assert [chunk.metadata.get("h2") for chunk in chunks] == ["Summary", "Contact", "Final"]
    assert [chunk.chunk_type for chunk in chunks] == ["content", "contact", "content"]


def test_headed_document_splits_inline_footer_bands_and_preamble():
    text = "Cover Page\nPage 1 of 2\n\n# Report\n\n## First\n\nFirst body.\n\nCONFIDENTIAL - INTERNAL USE ONLY\nPage 2 of 2\n\n## Second\n\nSecond body."

    chunks = ChunkProcessor().process(text)

    assert chunks[0].content == "Cover Page"
    assert any(chunk.chunk_type == "footer" for chunk in chunks)
    assert any(chunk.metadata.get("h2") == "First" and "First body" in chunk.content for chunk in chunks)
    assert any(chunk.metadata.get("h2") == "Second" and "Second body" in chunk.content for chunk in chunks)
    assert not any("First body" in chunk.content and "Second body" in chunk.content for chunk in chunks)
