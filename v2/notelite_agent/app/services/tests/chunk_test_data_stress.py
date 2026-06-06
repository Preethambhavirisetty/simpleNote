TEST_CASES = [

# -------------------------
# HEADINGS
# -------------------------

{
    "name": "heading_only_no_content",
    "text": "# Project Alpha\n\n## Sprint Planning\n\n### Backend\n\n#### Authentication",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["heading_only"],
        "must_contain": ["Project Alpha", "Sprint Planning", "Backend", "Authentication"]
    }
},
{
    "name": "heading_with_single_line_content",
    "text": "# Project Alpha\n\nLogin flow completed.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["Project Alpha", "Login flow completed"]
    }
},
{
    "name": "heading_followed_by_empty_then_content",
    "text": "# Project Alpha\n\n## Empty Section\n\n## Real Section\n\nActual content here.",
    "expected": {
        "chunk_count": 2,
        "chunk_types": ["heading_only", "content"],
        "must_contain": ["Empty Section", "Actual content here"]
    }
},
{
    "name": "deeply_nested_headings_h1_to_h4_with_content",
    "text": "# Company Report\n\n## Q3 Summary\n\n### Revenue\n\n#### Cloud\n\nCloud revenue reached 12M.\n\n#### On-Premise\n\nOn-premise revenue declined 4%.",
    "expected": {
        "chunk_count": 2,
        "chunk_types": ["content"],
        "must_contain": ["Cloud revenue", "On-premise revenue"]
    }
},
{
    "name": "heading_only_multiple_empty_siblings",
    "text": "# Research Notes\n\n## Experiments\n\n### Trial A\n\n### Trial B\n\n### Trial C\n\n## Results",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["heading_only"],
        "must_contain": ["Trial A", "Trial B", "Trial C", "Results"]
    }
},

# -------------------------
# TABLES
# -------------------------

{
    "name": "table_basic",
    "text": "| Product | Revenue | Cost |\n|----------|----------|----------|\n| A | 10000 | 6000 |\n| B | 12000 | 7000 |\n| C | 14000 | 8500 |",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["table"],
        "must_contain": ["Product", "Revenue", "Cost"]
    }
},
{
    "name": "table_without_markdown_separator",
    "text": "Name | Department | Status\nJohn | Engineering | Active\nSarah | Operations | Active\nMike | Finance | Leave",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["table"],
        "must_contain": ["Engineering", "Operations", "Finance"]
    }
},
{
    "name": "table_with_prose_intro",
    "text": "Here is the quarterly performance summary.\n\n| Quarter | Revenue |\n|----------|----------|\n| Q1 | 10M |\n| Q2 | 12M |",
    "expected": {
        "chunk_count": 2,
        "chunk_types": ["content", "table"],
        "must_contain": ["quarterly performance", "Q1", "Q2"]
    }
},
{
    "name": "table_with_prose_after",
    "text": "| Quarter | Revenue |\n|----------|----------|\n| Q1 | 10M |\n| Q2 | 12M |\n\nNote: Revenue excludes taxes.",
    "expected": {
        "chunk_count": 2,
        "chunk_types": ["table", "content"],
        "must_contain": ["Q1", "excludes taxes"]
    }
},
{
    "name": "two_tables_separated_by_prose",
    "text": "| Quarter | Revenue |\n|----------|----------|\n| Q1 | 10M |\n| Q2 | 12M |\n\nNote: Revenue excludes taxes.\n\n| Region | Growth |\n|----------|----------|\n| East | 12% |\n| West | 8% |",
    "expected": {
        "chunk_count": 3,
        "chunk_types": ["table", "content", "table"],
        "must_contain": ["Quarter", "Region", "excludes taxes"]
    }
},
{
    "name": "large_table_30_rows",
    "text": "| ID | Name | Department | Status | Start Date |\n|---|---|---|---|---|\n| 1 | Alice | Engineering | Active | 2020-01-15 |\n| 2 | Bob | Marketing | Active | 2019-03-22 |\n| 3 | Carol | Finance | Leave | 2021-07-01 |\n| 4 | David | Engineering | Active | 2018-11-10 |\n| 5 | Eve | Operations | Active | 2022-05-14 |\n| 6 | Frank | Engineering | Inactive | 2017-09-30 |\n| 7 | Grace | Marketing | Active | 2023-01-02 |\n| 8 | Hank | Finance | Active | 2020-06-18 |\n| 9 | Iris | HR | Active | 2021-03-25 |\n| 10 | Jack | Engineering | Active | 2019-12-05 |\n| 11 | Karen | Operations | Leave | 2022-08-17 |\n| 12 | Leo | Finance | Active | 2018-04-09 |\n| 13 | Mia | Marketing | Active | 2023-07-21 |\n| 14 | Ned | Engineering | Active | 2020-10-13 |\n| 15 | Olivia | HR | Inactive | 2016-02-28 |\n| 16 | Paul | Operations | Active | 2021-11-03 |\n| 17 | Quinn | Marketing | Active | 2022-04-16 |\n| 18 | Rose | Finance | Active | 2019-08-24 |\n| 19 | Sam | Engineering | Active | 2023-02-07 |\n| 20 | Tina | HR | Active | 2020-05-29 |\n| 21 | Uma | Operations | Active | 2018-07-14 |\n| 22 | Victor | Engineering | Leave | 2021-09-06 |\n| 23 | Wendy | Marketing | Active | 2022-12-19 |\n| 24 | Xander | Finance | Active | 2017-03-11 |\n| 25 | Yara | HR | Active | 2023-06-30 |\n| 26 | Zane | Operations | Inactive | 2015-10-22 |\n| 27 | Amy | Engineering | Active | 2020-02-14 |\n| 28 | Brian | Marketing | Active | 2019-07-08 |\n| 29 | Clara | Finance | Active | 2022-01-27 |\n| 30 | Derek | Engineering | Active | 2021-04-19 |",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["table"],
        "must_contain": ["Engineering", "Marketing", "Finance", "Operations"]
    }
},

# -------------------------
# CODE BLOCKS
# -------------------------

{
    "name": "code_python",
    "text": "```python\ndef calculate_total(items):\n    return sum(items)\n```",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["code"],
        "must_contain": ["calculate_total"]
    }
},
{
    "name": "code_javascript",
    "text": "```javascript\nconst user = {\n  id: 1,\n  name: 'John'\n}\n```",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["code"],
        "must_contain": ["const user"]
    }
},
{
    "name": "code_sql",
    "text": "```sql\nSELECT *\nFROM customers\nWHERE active = true;\n```",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["code"],
        "must_contain": ["SELECT", "customers"]
    }
},
{
    "name": "code_bash_multiline",
    "text": "```bash\npython -m venv venv\nsource venv/bin/activate\npip install -r requirements.txt\nalembic upgrade head\nuvicorn app.main:app --reload --port 8000\n```",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["code"],
        "must_contain": ["venv", "alembic", "uvicorn"]
    }
},
{
    "name": "code_with_prose_intro",
    "text": "Run the following script to initialize the environment.\n\n```python\ndef setup():\n    print('initializing')\n```",
    "expected": {
        "chunk_count": 2,
        "chunk_types": ["content", "code"],
        "must_contain": ["initialize the environment", "setup"]
    }
},
{
    "name": "unfenced_code_command_sequence",
    "text": "To deploy the application run the following commands.\n\npython -m venv venv\nsource venv/bin/activate\npip install -r requirements.txt\nuvicorn app.main:app --port 8000",
    "expected": {
        "chunk_count": 2,
        "chunk_types": ["content", "code"],
        "must_contain": ["deploy the application", "uvicorn"]
    }
},
{
    "name": "inline_code_in_prose",
    "text": "Run `npm run dev` to start the application. The API key is stored in `config.ts`.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["npm run dev", "config.ts"]
    }
},
{
    "name": "multiple_code_blocks_different_languages",
    "text": "Python example:\n\n```python\ndef hello():\n    print('hello')\n```\n\nSQL example:\n\n```sql\nSELECT * FROM users;\n```",
    "expected": {
        "chunk_count": 4,
        "chunk_types": ["content", "code", "content", "code"],
        "must_contain": ["hello", "SELECT"]
    }
},

# -------------------------
# JSON
# -------------------------

{
    "name": "json_simple",
    "text": "{\n  \"environment\": \"prod\",\n  \"region\": \"us-east-1\"\n}",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["json"],
        "must_contain": ["environment", "region"]
    }
},
{
    "name": "json_nested",
    "text": "{\n  \"user\": {\n    \"name\": \"John\",\n    \"roles\": [\"admin\", \"editor\"]\n  }\n}",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["json"],
        "must_contain": ["user", "roles"]
    }
},
{
    "name": "json_array",
    "text": "[\n  {\n    \"id\": 1,\n    \"name\": \"Sarah\"\n  }\n]",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["json"],
        "must_contain": ["Sarah"]
    }
},
{
    "name": "json_with_prose_context",
    "text": "The deployment configuration is shown below.\n\n```json\n{\n  \"environment\": \"production\",\n  \"replicas\": 3\n}\n```",
    "expected": {
        "chunk_count": 2,
        "chunk_types": ["content", "json"],
        "must_contain": ["deployment configuration", "replicas"]
    }
},

# -------------------------
# FAQ
# -------------------------

{
    "name": "faq_single_pair",
    "text": "Q: How do I reset my password?\n\nA: Use the password reset page.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["faq"],
        "must_contain": ["password"]
    }
},
{
    "name": "faq_multiple_pairs",
    "text": "Q: Is remote work allowed?\n\nA: Yes.\n\nQ: How many days?\n\nA: Three days per week.\n\nQ: Is MFA required?\n\nA: Yes, for all employees.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["faq"],
        "must_contain": ["remote work", "MFA"]
    }
},
{
    "name": "faq_with_header",
    "text": "Frequently Asked Questions\n\nQ: Where is the office?\n\nA: Austin, Texas.\n\nQ: What are office hours?\n\nA: 9 AM to 6 PM local time.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["faq"],
        "must_contain": ["Austin", "office hours"]
    }
},
{
    "name": "faq_with_long_answers",
    "text": "Q: What is the data retention policy?\n\nA: All customer data is retained for a minimum of seven years from the date of collection unless the customer requests deletion under applicable data protection regulations. Retention is governed by the Data Governance Policy document.\n\nQ: How do I request data deletion?\n\nA: Submit a request through the Privacy Portal at privacy.example.com. Requests are processed within 30 days.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["faq"],
        "must_contain": ["retention policy", "Privacy Portal"]
    }
},

# -------------------------
# TRANSCRIPTS
# -------------------------

{
    "name": "transcript_basic",
    "text": "John:\nLet's begin.\n\nSarah:\nI reviewed the proposal.\n\nJohn:\nGreat.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["transcript"],
        "must_contain": ["John", "Sarah"]
    }
},
{
    "name": "transcript_timestamped",
    "text": "[09:02] Alice:\nGood morning everyone.\n\n[09:04] Bob:\nLet's review the agenda.\n\n[09:06] Alice:\nFirst item is the budget update.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["transcript"],
        "must_contain": ["Alice", "Bob", "budget update"]
    }
},
{
    "name": "transcript_chat_paste",
    "text": "John\n10:32 AM\n\nCan we deploy today?\n\nSarah\n10:35 AM\n\nLet's wait for QA signoff.\n\nJohn\n10:37 AM\n\nAgreed.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["transcript"],
        "must_contain": ["10:32 AM", "QA signoff"]
    }
},
{
    "name": "transcript_with_embedded_code",
    "text": "Engineer:\nThe fix is straightforward.\n\nReviewer:\nCan you show the change?\n\nEngineer:\nSure. `return value if value > 0 else 0`\n\nReviewer:\nLooks good.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["transcript"],
        "must_contain": ["Engineer", "Reviewer", "return value"]
    }
},
{
    "name": "transcript_support_with_sql",
    "text": "Support:\nRun this query to check connections.\n\nCustomer:\nOkay.\n\nSupport:\n```sql\nSELECT state, count(*) FROM pg_stat_activity GROUP BY state;\n```\n\nCustomer:\nI see 187 idle connections.",
    "expected": {
        "chunk_count": 2,
        "chunk_types": ["transcript", "code"],
        "must_contain": ["pg_stat_activity", "idle connections"]
    }
},

# -------------------------
# CONTACT AND ADDRESS
# -------------------------

{
    "name": "contact_with_email_phone_url",
    "text": "John Harper\n\nEmail: john@example.com\nPhone: (217) 555-0142\nhttps://johnharper.dev",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["contact"],
        "must_contain": ["john@example.com", "555-0142"]
    }
},
{
    "name": "contact_email_only",
    "text": "Support Team\n\nsupport@acme.com\n\nhttps://acme.com/support",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["contact"],
        "must_contain": ["support@acme.com"]
    }
},
{
    "name": "address_basic",
    "text": "Acme Holdings\n100 Main Street\nDenver, CO 80202\nUSA",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["address"],
        "must_contain": ["Acme Holdings", "Denver"]
    }
},
{
    "name": "address_international",
    "text": "TechCorp Europe GmbH\nHauptstraße 42\n10117 Berlin\nGermany",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["address"],
        "must_contain": ["Berlin", "Germany"]
    }
},
{
    "name": "multiple_addresses_same_chunk",
    "text": "Corporate Headquarters\n500 Innovation Parkway\nAustin, TX 78701\nUnited States\n\nRegional Office\n200 Harbor Avenue\nSeattle, WA 98101\nUnited States",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["address"],
        "must_contain": ["Austin", "Seattle"]
    }
},
{
    "name": "contact_and_address_together",
    "text": "James Okonkwo\nChief Information Security Officer\n\nEmail: j.okonkwo@company.com\nPhone: +1 (408) 555-0192\n\n350 Technology Drive, Suite 800\nSan Jose, CA 95110\nUnited States",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["contact"],
        "must_contain": ["j.okonkwo@company.com", "San Jose"]
    }
},

# -------------------------
# GLOSSARY
# -------------------------

{
    "name": "glossary_acronyms",
    "text": "ARR: Annual Recurring Revenue\n\nROI: Return On Investment\n\nSLA: Service Level Agreement",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["glossary"],
        "must_contain": ["ARR", "ROI", "SLA"]
    }
},
{
    "name": "glossary_long_definitions",
    "text": "ACID: Atomicity, Consistency, Isolation, Durability. The four properties that guarantee database transactions are processed reliably.\n\nHNSW: Hierarchical Navigable Small World. A graph-based algorithm for approximate nearest neighbor search used in vector databases.\n\nMVCC: Multi-Version Concurrency Control. A database concurrency method that maintains multiple versions of data to allow reads and writes to proceed without blocking each other.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["glossary"],
        "must_contain": ["ACID", "HNSW", "MVCC"]
    }
},
{
    "name": "glossary_with_ambiguous_terms",
    "text": "ARR: Annual Recurring Revenue — used in financial reporting contexts.\n\nARR: Amazon Resource Record — used in DNS and infrastructure contexts.\n\nDLQ: Dead Letter Queue — Kafka messages that could not be processed.\n\nDLQ: Data Lake Query — deprecated term, do not use.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["glossary"],
        "must_contain": ["Annual Recurring Revenue", "Amazon Resource Record", "Dead Letter Queue"]
    }
},

# -------------------------
# QUOTES
# -------------------------

{
    "name": "quote_single",
    "text": "\"The best way to predict the future is to create it.\"",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["quote"],
        "must_contain": ["future"]
    }
},
{
    "name": "quote_multiple",
    "text": "\"Success is not final.\"\n\n\"Failure is not fatal.\"",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["quote"],
        "must_contain": ["Success", "Failure"]
    }
},
{
    "name": "quote_markdown_blockquote",
    "text": "> Simplicity is the ultimate sophistication.\n\n> Perfection is achieved not when there is nothing more to add, but when there is nothing left to take away.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["quote"],
        "must_contain": ["Simplicity", "Perfection"]
    }
},
{
    "name": "quote_with_attribution",
    "text": "\"Premature optimization is the root of all evil.\"\n— Donald Knuth\n\n\"Programs must be written for people to read.\"\n— Harold Abelson",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["quote"],
        "must_contain": ["Donald Knuth", "Harold Abelson"]
    }
},

# -------------------------
# LISTS
# -------------------------

{
    "name": "list_dash",
    "text": "- Apples\n- Bananas\n- Oranges",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["list"],
        "must_contain": ["Apples", "Bananas"]
    }
},
{
    "name": "list_star",
    "text": "* Install software\n* Configure environment\n* Run tests",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["list"],
        "must_contain": ["Install software", "Run tests"]
    }
},
{
    "name": "list_nested_deep",
    "text": "- Corporate\n  - Finance\n    - Budget Planning\n    - Cost Optimization\n  - Operations\n    - Logistics\n    - Procurement\n- Technology\n  - Infrastructure\n  - Security",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["list"],
        "must_contain": ["Budget Planning", "Procurement", "Security"]
    }
},
{
    "name": "list_task_checklist",
    "text": "- [x] Finish API integration\n- [x] Review PR\n- [ ] Deploy to production\n- [ ] Update documentation",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["list"],
        "must_contain": ["Deploy to production", "Update documentation"]
    }
},
{
    "name": "structured_list_numeric",
    "text": "1. Login\n2. Configure\n3. Deploy",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["structured_list"],
        "must_contain": ["Login", "Deploy"]
    }
},
{
    "name": "structured_list_hierarchical",
    "text": "1. Project\n\n1.1 Backend\n\n1.2 Frontend\n\n1.3 Database",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["structured_list"],
        "must_contain": ["Backend", "Frontend", "Database"]
    }
},
{
    "name": "structured_list_alpha",
    "text": "A. Planning\n\nB. Execution\n\nC. Review",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["structured_list"],
        "must_contain": ["Planning", "Execution", "Review"]
    }
},
{
    "name": "mixed_numbering_formats",
    "text": "1. Item One\n2. Item Two\n\n1.1 Sub Item A\n1.2 Sub Item B\n\nA. Alternative Format\nB. Another Alternative\n\n(i) Roman One\n(ii) Roman Two",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["structured_list"],
        "must_contain": ["Sub Item A", "Alternative Format", "Roman One"]
    }
},

# -------------------------
# PDF ARTIFACTS
# -------------------------

{
    "name": "ocr_hyphenation",
    "text": "The customer experi-\nence improved signif-\nicantly after imple-\nmentation of the new system.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["experience", "significantly", "implementation"]
    }
},
{
    "name": "page_break_markers",
    "text": "The system processed all requests successfully.\n\n--- PAGE BREAK ---\n\n© 2024 Company Inc. All rights reserved. Page 47 of 312.\n\nSection 3.4 continued\n\nThe next phase began in January 2024.",
    "expected": {
        "chunk_count": 2,
        "chunk_types": ["content", "footer"],
        "must_contain": ["processed all requests", "next phase"]
    }
},
{
    "name": "running_footer_repeated",
    "text": "The organization completed FY2025 review.\n\nCONFIDENTIAL - INTERNAL USE ONLY\nPage 2 of 8\n\nCustomer satisfaction improved by 17%.\n\nCONFIDENTIAL - INTERNAL USE ONLY\nPage 3 of 8\n\nInfrastructure investments reduced costs.",
    "expected": {
        "chunk_count": 3,
        "chunk_types": ["content", "footer", "content"],
        "must_contain": ["FY2025 review", "satisfaction improved", "Infrastructure investments"]
    }
},
{
    "name": "redacted_block",
    "text": "The contract terms are as follows.\n\n[REDACTED — ATTORNEY-CLIENT PRIVILEGED]\n\nPayment is due within 30 days.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["contract terms", "Payment is due"]
    }
},
{
    "name": "out_of_context_footnote",
    "text": "The algorithm proceeds in three phases.\n\nNOTE: The following was extracted from a footnote: \"See also RFC 7519 (JSON Web Tokens) and RFC 6749 (OAuth 2.0).\"",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["three phases", "RFC 7519"]
    }
},

# -------------------------
# REPEATED CONTENT
# -------------------------

{
    "name": "repeated_boilerplate_lines",
    "text": "CONFIDENTIAL\nCONFIDENTIAL\nCONFIDENTIAL\nCONFIDENTIAL\nCONFIDENTIAL",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["footer"],
        "must_contain": ["CONFIDENTIAL"]
    }
},
{
    "name": "repeated_sentences_in_paragraph",
    "text": "Revenue increased significantly during the year.\nProfit margins improved due to operational efficiencies.\nRevenue increased significantly during the year.\nCustomer retention reached record levels.\nProfit margins improved due to operational efficiencies.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["Revenue", "Profit margins", "Customer retention"]
    }
},
{
    "name": "near_duplicate_sections",
    "text": "## Standard Terms — Version A\nBy using this software you agree to be bound by these terms. This software is provided as is without warranty of any kind.\n\n## Standard Terms — Version B\nBy using this software you agree to be bound by these terms. This software is provided as is without warranty of any kind.",
    "expected": {
        "chunk_count": 2,
        "chunk_types": ["content"],
        "must_contain": ["Version A", "Version B"]
    }
},

# -------------------------
# VERY SHORT SECTIONS
# -------------------------

{
    "name": "single_word_chunk",
    "text": "Deprecated.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["Deprecated"]
    }
},
{
    "name": "tbd_placeholder",
    "text": "TBD",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["TBD"]
    }
},
{
    "name": "reserved_placeholder",
    "text": "[Reserved for future use]",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["Reserved"]
    }
},

# -------------------------
# VERY LONG PARAGRAPHS
# -------------------------

{
    "name": "long_paragraph_single_topic",
    "text": "PostgreSQL connection pooling must be configured correctly in production environments. The pool_recycle parameter should be set to 3600 seconds to avoid stale connections. The pool_pre_ping parameter should be enabled so that SQLAlchemy verifies a connection is alive before handing it to application code. The pool_size parameter should be tuned based on the number of application workers and the expected query duration. For short fast queries a higher pool size is acceptable. For long running queries a smaller pool size prevents connection exhaustion. The max_overflow parameter controls how many additional connections can be opened beyond pool_size when demand spikes. Setting max_overflow too high can cause the database to exceed its max_connections limit and begin rejecting connections entirely. A good baseline is pool_size equal to the number of CPU cores times two, max_overflow equal to pool_size, and pool_recycle set to 3600.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["pool_recycle", "pool_pre_ping", "max_overflow"]
    }
},
{
    "name": "long_paragraph_multiple_topics",
    "text": "The platform uses Apache Kafka for event streaming and Apache Airflow for batch orchestration. Kafka topics are partitioned across six broker nodes distributed across three availability zones. Airflow runs on Amazon EKS using the Kubernetes Executor which creates isolated pods for each task. The data lake is organized in a medallion architecture with Bronze, Silver, and Gold layers stored on Amazon S3 using Apache Iceberg as the table format. Iceberg provides ACID transactions, schema evolution, and time travel on data lake storage. The compute layer uses Apache Spark on Amazon EMR with ephemeral clusters provisioned per job. Snowflake serves as the primary analytical query engine for the Gold layer. Data quality is enforced using Great Expectations with validation suites that block downstream tasks on failure. MLflow manages the machine learning lifecycle including experiment tracking and model registry. Qdrant provides vector similarity search for semantic search workloads. All infrastructure is defined in Terraform and deployed via GitHub Actions.",
    "expected": {
        "chunk_count": 3,
        "chunk_types": ["content"],
        "must_contain": ["Apache Kafka", "Apache Iceberg", "Snowflake", "Qdrant"]
    }
},
{
    "name": "long_paragraph_with_repeated_sentences",
    "text": "The organization continued to expand across multiple markets while simultaneously investing in employee development, operational efficiency, and customer satisfaction initiatives. Supply chain optimization and regional partnerships drove significant cost reductions. The organization continued to expand across multiple markets while simultaneously investing in employee development, operational efficiency, and customer satisfaction initiatives. Supply chain optimization and regional partnerships drove significant cost reductions.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["expand across multiple markets", "Supply chain optimization"]
    }
},

# -------------------------
# MIXED CONTENT
# -------------------------

{
    "name": "mixed_prose_table_code",
    "text": "# Sprint Review\n\nRevenue increased 12% this quarter.\n\n## Performance\n\n| Team | Status |\n|--------|--------|\n| Backend | Done |\n| Frontend | In Progress |\n\n## Deployment Script\n\n```bash\ndocker compose up --build\n```\n\nOwner: John. Next review: Friday.",
    "expected": {
        "chunk_count": 4,
        "chunk_types": ["content", "table", "code", "content"],
        "must_contain": ["Revenue increased", "Frontend", "docker compose", "Next review"]
    }
},
{
    "name": "meeting_notes_with_action_items",
    "text": "Meeting Notes\n\nDate: January 10, 2026\n\nAttendees: John, Sarah, Mike\n\nDiscussion:\n- Login issue identified in production\n- Deployment timeline reviewed\n\nDecisions:\n- Release scheduled for Friday\n\nAction Items:\n- John: Fix authentication bug by Thursday\n- Sarah: Complete QA testing by Wednesday\n- Mike: Update deployment runbook",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["Attendees", "Action Items", "authentication bug"]
    }
},
{
    "name": "daily_note_all_types",
    "text": "# Daily Notes\n\nCompleted the onboarding workflow implementation today.\n\nTasks:\n- Finish testing\n- Deploy staging build\n\nMeeting Notes:\nJohn suggested improving the login experience.\nSarah agreed and will review the mockups.\n\nCode run today:\n`npm run test`\n\nTomorrow:\n- Start payment integration\n- Review security audit findings",
    "expected": {
        "chunk_count": 3,
        "chunk_types": ["content", "list", "transcript"],
        "must_contain": ["onboarding workflow", "payment integration", "Sarah agreed"]
    }
},

# -------------------------
# EDGE CASES
# -------------------------

{
    "name": "only_urls",
    "text": "https://data-access.internal.company.com\nhttps://docs.internal.company.com/data-platform\nhttps://airflow.internal.company.com\nhttps://github.com/company-org/data-platform",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["data-access", "airflow", "github"]
    }
},
{
    "name": "only_identifiers",
    "text": "INC-2024-1847\nSEC-2024-0847\nCHG-2024-1923\nDATA-2024-0934",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["INC-2024-1847", "CHG-2024-1923"]
    }
},
{
    "name": "sentence_with_15_plus_entities",
    "text": "The platform integrates with Apache Kafka, Apache Spark, Apache Airflow, Apache Iceberg, Amazon S3, Amazon EMR, Amazon EKS, Amazon RDS, HashiCorp Vault, Snowflake, Great Expectations, dbt, MLflow, Feast, Qdrant, Datadog, PagerDuty, Terraform, and GitHub Actions.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["Apache Kafka", "Snowflake", "Qdrant", "GitHub Actions"]
    }
},
{
    "name": "all_caps_dense",
    "text": "ALL PLATFORM ENGINEERS MUST COMPLETE THE ANNUAL SECURITY TRAINING BY DECEMBER 31 2024. FAILURE TO COMPLETE TRAINING WILL RESULT IN ACCESS SUSPENSION. CONTACT HR@COMPANY.COM FOR ACCOMMODATIONS.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["SECURITY TRAINING", "ACCESS SUSPENSION"]
    }
},
{
    "name": "extremely_long_single_sentence",
    "text": "The Enterprise Data Platform architecture as designed and implemented by the Data Engineering team led by Arjun Mehta in collaboration with the Platform Engineering team led by Sofia Andersen and the ML Engineering team led by Priya Nair, operating under the overall technical direction of the Chief Technology Officer and subject to the security requirements defined by Chief Information Security Officer James Okonkwo and the compliance requirements arising from SOC 2 Type II certification, GDPR compliance obligations in Germany, France, and the Netherlands, CCPA obligations in California, and the data localization requirements applicable to operations in Japan, South Korea, and India, represents a comprehensive solution to the challenge of providing real-time and batch data processing capabilities at scale while maintaining the security, compliance, and operational standards required by enterprise customers including Siemens AG, Volkswagen Group, and Tata Consultancy Services.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["Arjun Mehta", "SOC 2", "Siemens AG", "Tata Consultancy Services"]
    }
},
{
    "name": "negation_heavy",
    "text": "The platform does NOT support real-time writes to the Gold layer. Do NOT modify Kafka broker configurations directly. The system does NOT guarantee exactly-once delivery on the Bronze layer. Do NOT use the PlatformAdminRole in day-to-day operations. Cross-region replication does NOT apply to Bronze layer data by default.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["does NOT support", "does NOT guarantee", "NOT apply"]
    }
},
{
    "name": "cross_references",
    "text": "See Section 3.1 for Kafka configuration details.\nRefer to Appendix A for environment variable reference.\nAs described in ADR-2023-041, the migration from Hadoop to Apache Spark was completed in Q4 2023.\nFor incident response, see Runbook RB-INFRA-007.\nFor cost estimates, refer to Section 13.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["ADR-2023-041", "Runbook RB-INFRA-007"]
    }
},
{
    "name": "section_only_table_no_prose",
    "text": "## SLA Metrics\n\n| Metric | Target | Status |\n|--------|--------|--------|\n| Availability | 99.9% | Green |\n| Latency P95 | 200ms | Green |\n| Error Rate | 0.1% | Green |",
    "expected": {
        "chunk_count": 2,
        "chunk_types": ["heading_only", "table"],
        "must_contain": ["SLA Metrics", "Availability", "Latency P95"]
    }
},
{
    "name": "section_only_code_no_prose",
    "text": "## Deployment Command\n\n```bash\ndocker compose up --build -d\n```",
    "expected": {
        "chunk_count": 2,
        "chunk_types": ["heading_only", "code"],
        "must_contain": ["Deployment Command", "docker compose"]
    }
},
{
    "name": "ambiguous_acronym_same_document",
    "text": "ARR for Q3 2024 reached $1.64 billion, representing 29.6% year-over-year growth. The infrastructure team also updated the ARR DNS records for the us-east-1 region as part of the failover configuration.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["ARR", "DNS records", "failover"]
    }
},
{
    "name": "multilingual_snippet",
    "text": "The German interface uses the following labels:\n\nDatenbankverbindung — Database connection\nDatenqualität — Data quality\nEchtzeitverarbeitung — Real-time processing\n\nThe Japanese interface uses:\n\nデータレイク — Data lake\nストリーミング — Streaming",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["Datenbankverbindung", "データレイク"]
    }
},
{
    "name": "financial_data_dense",
    "text": "Revenue for Q3 2024 reached $847.3 million, a 22.4% increase from $692.2 million in Q3 2023. Gross margin expanded to 68.3% from 65.1%. Operating expenses totaled $412.6 million. Net income was $163.7 million or $1.24 per diluted share. Adjusted EBITDA was $241.9 million representing a 28.6% margin. Cash and equivalents totaled $2.14 billion.",
    "expected": {
        "chunk_count": 1,
        "chunk_types": ["content"],
        "must_contain": ["$847.3 million", "EBITDA", "$2.14 billion"]
    }
}

]