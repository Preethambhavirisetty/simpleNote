import re


HEADING_PATTERN = re.compile(r"\n(?=[A-Z][^.!?\n]{0,60}\n)")
DIVIDER_LINE_PATTERN = re.compile(r"(?m)^[ \t]*[-*_]{3,}[ \t]*$")
SENTINEL_LINE_PATTERN = re.compile(r"(?mi)^[ \t]*\[(?:eof|end)\][ \t]*$")
EMPTY_LIST_ITEM_PATTERN = re.compile(r"(?m)^[ \t]*(?:[*+-]|\d+[.)])[ \t]*$")
NUMBERED_LINE_PATTERN = re.compile(r"^\s*\d+\.\s+(.+)$")
