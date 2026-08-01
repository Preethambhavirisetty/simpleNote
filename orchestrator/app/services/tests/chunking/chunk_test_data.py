TEST_CASES = [
    {
        "name": "heading_only",
        "text": "# Monthly Review\n\n## Team Updates\n\n### Infrastructure",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["heading_only"],
            "must_contain": [
                "Monthly Review",
                "Team Updates",
                "Infrastructure"
            ]
        }
    },

    {
        "name": "simple_paragraph",
        "text": (
            "The operations team completed a review of all active projects "
            "during the quarter. Several initiatives focused on infrastructure "
            "modernization, process optimization, and customer satisfaction."
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["content"]
        }
    },

    {
        "name": "address_block",
        "text": (
            "Acme Holdings\n"
            "100 Main Street\n"
            "Suite 450\n"
            "Denver, CO 80202\n"
            "United States"
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["address"],
            "must_not_split": [
                "Acme Holdings",
                "100 Main Street",
                "Denver"
            ]
        }
    },

    {
        "name": "contact_block",
        "text": (
            "John Harper\n\n"
            "Email: john.harper@example.com\n"
            "Phone: (217) 555-0142\n"
            "Website: https://johnharper.dev"
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["contact"]
        }
    },

    {
        "name": "faq_block",
        "text": (
            "Q: What was the biggest challenge this year?\n\n"
            "A: Supply chain disruptions.\n\n"
            "Q: What was the biggest success?\n\n"
            "A: Expansion into new markets."
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["faq"]
        }
    },

    {
        "name": "transcript_block",
        "text": (
            "Speaker A:\n"
            "Good morning everyone.\n\n"
            "Speaker B:\n"
            "Let's review the roadmap.\n\n"
            "Speaker A:\n"
            "We should prioritize customer retention."
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["transcript"]
        }
    },

    {
        "name": "table_block",
        "text": (
            "| Quarter | Revenue | Profit |\n"
            "|----------|----------|----------|\n"
            "| Q1 | 12.5M | 4.3M |\n"
            "| Q2 | 13.1M | 4.5M |\n"
            "| Q3 | 15.2M | 6.2M |"
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["table"]
        }
    },

    {
        "name": "code_block",
        "text": (
            "```python\n"
            "def calculate_growth(current, previous):\n"
            "    return ((current - previous) / previous) * 100\n"
            "```"
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["code"]
        }
    },

    {
        "name": "json_block",
        "text": (
            "{\n"
            "  \"environment\": \"production\",\n"
            "  \"region\": \"us-east-1\",\n"
            "  \"replicas\": 12\n"
            "}"
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["json"]
        }
    },

    {
        "name": "glossary_block",
        "text": (
            "ARR: Annual Recurring Revenue\n\n"
            "EBITDA: Earnings Before Interest, Taxes, "
            "Depreciation, and Amortization\n\n"
            "ROI: Return On Investment"
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["glossary"]
        }
    },

    {
        "name": "quote_block",
        "text": (
            "\"Success usually comes to those who are too busy "
            "to be looking for it.\"\n\n"
            "\"The secret of getting ahead is getting started.\""
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["quote"]
        }
    },

    {
        "name": "footer_block",
        "text": (
            "Page 12 of 48\n\n"
            "CONFIDENTIAL - INTERNAL USE ONLY\n\n"
            "Generated on January 15, 2026"
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["content"]
        }
    },

    {
        "name": "header_block",
        "text": (
            "ACME CORPORATION\n\n"
            "FY2025 OPERATIONS REPORT\n\n"
            "Page 1"
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["content"]
        }
    },

    {
        "name": "ocr_noise",
        "text": (
            "The customer experi-\n"
            "ence improved signif-\n"
            "icantly after imple-\n"
            "mentation of the new system."
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["content"]
        }
    },

    {
        "name": "boilerplate",
        "text": (
            "CONFIDENTIAL\n"
            "CONFIDENTIAL\n"
            "CONFIDENTIAL\n"
            "CONFIDENTIAL\n"
            "CONFIDENTIAL"
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["content"]
        }
    },

    {
        "name": "mixed_numbering",
        "text": (
            "1. Item One\n\n"
            "1.1 Sub Item\n\n"
            "A. Alternative Format\n\n"
            "(i) Roman Format"
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["structured_list"]
        }
    },

    {
        "name": "cross_references",
        "text": (
            "For details on revenue growth, see Section 4.2.\n\n"
            "For definitions, refer to the Glossary.\n\n"
            "For configuration settings, see Appendix B."
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["content"]
        }
    },

    {
        "name": "empty_section",
        "text": "## Future Plans",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["heading_only"]
        }
    },

    {
        "name": "divider_lines",
        "text": (
            "------------------------\n"
            "------------------------\n"
            "------------------------"
        ),
        "expected": {
            "chunk_count": 0,
            "chunk_types": []
        }
    },

    {
        "name": "long_content_chunking",
        "text": " ".join(
            ["The organization continued expanding operations."] * 500
        ),
        "expected": {
            "chunk_count_min": 2,
            "chunk_types": ["content"]
        }
    },

    {
        "name": "mixed_document",
        "text": (
            "# Monthly Report\n\n"
            "## Executive Summary\n"
            "Revenue increased by 18%.\n\n"
            "| Quarter | Revenue |\n"
            "|----------|----------|\n"
            "| Q1 | 12M |\n\n"
            "Speaker A:\n"
            "Let's review results.\n\n"
            "ARR: Annual Recurring Revenue"
        ),
        "expected": {
            "chunk_count": 4,
            "chunk_types": [
                "content",
                "table",
                "transcript",
                "glossary"
            ]
        }
    },
    {
        "name": "heading_only_1",
        "text": "# Project Alpha\n\n## Sprint Planning\n\n### Backend\n\n#### Authentication",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["heading_only"],
            "must_contain": [
                "Project Alpha",
                "Sprint Planning",
                "Backend",
                "Authentication"
            ]
        }
    },

    {
        "name": "heading_only_2",
        "text": "# Research Notes\n\n## Experiments\n\n### Trial A\n\n### Trial B\n\n## Results",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["heading_only"],
            "must_contain": [
                "Research Notes",
                "Experiments",
                "Trial A",
                "Trial B",
                "Results"
            ]
        }
    },

    {
        "name": "heading_only_3",
        "text": "# Empty\n\n## Empty\n\n### Empty\n\n#### Empty",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["heading_only"],
            "must_contain": ["Empty"]
        }
    },

    {
        "name": "table_1",
        "text": "| Product | Revenue | Cost |\n|----------|----------|----------|\n| A | 10000 | 6000 |\n| B | 12000 | 7000 |\n| C | 14000 | 8500 |",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["table"],
            "must_contain": ["Product", "Revenue", "Cost"]
        }
    },

    {
        "name": "table_2",
        "text": "| Name | Department | Status |\n|------|------|------|\n| John | Engineering | Active |\n| Sarah | Operations | Active |\n| Mike | Finance | Leave |",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["table"],
            "must_contain": ["Engineering", "Operations", "Finance"]
        }
    },

    {
        "name": "table_3_mixed",
        "text": "| Quarter | Revenue |\n|----------|----------|\n| Q1 | 10M |\n| Q2 | 12M |\n\nNote: Revenue excludes taxes.\n\n| Region | Growth |\n|----------|----------|\n| East | 12% |\n| West | 8% |",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["table"],
            "must_contain": ["Quarter", "Revenue", "Region", "Growth"]
        }
    },

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
            "must_contain": ["SELECT"]
        }
    },

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
        "name": "address_1",
        "text": "Acme Holdings\n100 Main Street\nDenver, CO 80202\nUSA",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["address"],
            "must_contain": ["Acme Holdings", "Denver"]
        }
    },

    {
        "name": "address_2",
        "text": "742 Evergreen Terrace\nSpringfield, IL 62704\nUnited States",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["address"],
            "must_contain": ["Springfield"]
        }
    },

    {
        "name": "address_3",
        "text": "Building C\nInnovation Park\nAustin, TX 78701",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["address"],
            "must_contain": ["Austin"]
        }
    },

    {
        "name": "contact_1",
        "text": "John Harper\n\nEmail: john@example.com\nPhone: (217) 555-0142",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["contact"],
            "must_contain": ["john@example.com"]
        }
    },

    {
        "name": "contact_2",
        "text": "Support Team\n\nsupport@acme.com\n\nhttps://acme.com/support",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["contact"],
            "must_contain": ["support@acme.com"]
        }
    },

    {
        "name": "contact_3",
        "text": "Sales Contact\n\nsales@example.com\n\n+1-800-555-1234",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["contact"],
            "must_contain": ["sales@example.com"]
        }
    },

    {
        "name": "faq_1",
        "text": "Q: How do I reset my password?\n\nA: Use the password reset page.",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["faq"],
            "must_contain": ["password"]
        }
    },

    {
        "name": "faq_2",
        "text": "Q: Is remote work allowed?\n\nA: Yes.\n\nQ: How many days?\n\nA: Three days per week.",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["faq"],
            "must_contain": ["remote work"]
        }
    },

    {
        "name": "faq_3",
        "text": "Frequently Asked Questions\n\nQ: Where is the office?\n\nA: Austin, Texas.",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["faq"],
            "must_contain": ["Austin"]
        }
    },

    {
        "name": "transcript_1",
        "text": "John:\nLet's begin.\n\nSarah:\nI reviewed the proposal.\n\nJohn:\nGreat.",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["transcript"],
            "must_contain": ["John", "Sarah"]
        }
    },

    {
        "name": "transcript_2",
        "text": "Moderator:\nWelcome everyone.\n\nSpeaker:\nThank you.\n\nModerator:\nNext question.",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["transcript"],
            "must_contain": ["Moderator"]
        }
    },

    {
        "name": "transcript_3",
        "text": "Agent:\nHow may I help?\n\nCustomer:\nI need assistance.\n\nAgent:\nCertainly.",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["transcript"],
            "must_contain": ["Customer"]
        }
    },

    {
        "name": "glossary_1",
        "text": "ARR: Annual Recurring Revenue\n\nROI: Return On Investment",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["glossary"],
            "must_contain": ["ARR", "ROI"]
        }
    },

    {
        "name": "glossary_2",
        "text": "API: Application Programming Interface\n\nSDK: Software Development Kit",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["glossary"],
            "must_contain": ["API", "SDK"]
        }
    },

    {
        "name": "glossary_3",
        "text": "SLA: Service Level Agreement\n\nKPI: Key Performance Indicator\n\nOKR: Objectives and Key Results",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["glossary"],
            "must_contain": ["SLA", "KPI", "OKR"]
        }
    },

    {
        "name": "quote_1",
        "text": "\"The best way to predict the future is to create it.\"",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["quote"],
            "must_contain": ["future"]
        }
    },

    {
        "name": "quote_2",
        "text": "\"Success is not final.\"\n\n\"Failure is not fatal.\"",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["quote"],
            "must_contain": ["Success", "Failure"]
        }
    },

    {
        "name": "quote_3_markdown",
        "text": "> Simplicity is the ultimate sophistication.",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["quote"],
            "must_contain": ["Simplicity"]
        }
    },

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
            "must_contain": ["Install software"]
        }
    },

    {
        "name": "list_plus",
        "text": "+ Backend\n+ Frontend\n+ Database",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["list"],
            "must_contain": ["Backend"]
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
        "text": "1. Project\n\n1.1 Backend\n\n1.2 Frontend",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["structured_list"],
            "must_contain": ["Backend", "Frontend"]
        }
    },

    {
        "name": "structured_list_alpha",
        "text": "A. Planning\n\nB. Execution\n\nC. Review",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["structured_list"],
            "must_contain": ["Planning", "Execution"]
        }
    },

    {
        "name": "inline_quote_content",
        "text": (
            "The launch review concluded that the team should \"ship it\" "
            "after the final accessibility check passes."
        ),
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["content"],
            "must_contain": ["ship it"]
        }
    },

    {
        "name": "multiline_markdown_quote",
        "text": "> First principle: make it useful.\n> Second principle: keep it clear.",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["quote"],
            "must_contain": ["First principle", "Second principle"]
        }
    },

    {
        "name": "multiline_wrapped_quote",
        "text": "\"A system should explain itself.\nThe implementation should stay flexible.\"",
        "expected": {
            "chunk_count": 1,
            "chunk_types": ["quote"],
            "must_contain": ["explain itself", "stay flexible"]
        }
    }

]
