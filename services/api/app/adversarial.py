"""Deterministic adversarial-instruction scanner for uploaded source text.

Uploaded documents are data. The generation projection never sends raw chunk text to
the model, and prompts mark supplied content as untrusted, so these phrases cannot act
as instructions. This scanner makes such content visible for human review (SRS 1.6
xlix, Step 43). Flags are recomputed from chunk text on every read, never stored in
the traceability locator, and never alter or remove source text.
"""

import re
import unicodedata

# Each pattern targets text addressed to an AI/system, not ordinary policy wording
# (for example "act as the escalation point" or "do not reveal your password").
_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (code, re.compile(pattern, re.IGNORECASE)) for code, pattern in (
        ("INSTRUCTION_OVERRIDE",
         r"\b(ignore|disregard|forget|override|bypass)\s+(all\s+|any\s+|the\s+|your\s+)?"
         r"(previous|prior|above|earlier|preceding|system|original)\s+(instructions?|rules|prompts?|directions)\b"),
        ("ROLE_MANIPULATION",
         r"\b(you are now|act as|pretend (to be|you are))\s+(an?\s+|the\s+)?(ai|assistant|chatbot|language model|"
         r"system|admin(istrator)?|developer|unrestricted|jailbroken)\b|\b(developer mode|jailbreak|"
         r"new system (prompt|instructions?)|updated system (prompt|instructions?))\b"),
        ("FAKE_AUTHORITY",
         r"\b(system|admin(istrator)?|root)\s+(override|directive|command)\b|\b(message|instruction|directive)s?"
         r"\s+from\s+(the\s+)?(system|ai\s+admin(istrator)?|model\s+admin(istrator)?)\b"),
        ("APPROVAL_MANIPULATION",
         r"\b(approve|verify|pass|certify)\s+(this|every|all)\s+(employees?|plans?|users?|candidates?)\b"
         r"(?![^.]{0,40}\b(only|after|once|when|if)\b)"
         r"|\bmark\s+(it|this|them|everything|all)\s+as\s+verified\b"
         r"|\b(set|change)\s+(the\s+)?(verification\s+)?status\s+to\s+verified\b"
         r"|\bskip\s+(all\s+|the\s+)?(validation|verification)\b"),
        ("OUTPUT_MANIPULATION",
         r"\b(respond|reply|answer)\s+only\s+with\b|\b(print|output)\s+the\s+following\b"),
        ("SECRET_EXFILTRATION",
         r"\b(reveal|print|show|disclose|repeat|leak|output)\s+(your|the)\s+(system\s+prompt|"
         r"(hidden|internal|initial|original)\s+(instructions|prompt))\b"),
    ))
# Zero-width and bidi-override characters can hide instructions from human reviewers.
_HIDDEN_CHARACTERS = frozenset(map(chr, (0x200B, 0x200C, 0x200D, 0x2060, 0xFEFF, 0x202D, 0x202E)))


def scan_text(text: str) -> tuple[str, ...]:
    """Return the sorted adversarial codes found in text (empty tuple when clean)."""
    visible = "".join(char for char in unicodedata.normalize("NFKC", text) if char not in _HIDDEN_CHARACTERS)
    codes = {code for code, pattern in _PATTERNS if pattern.search(visible)}
    if any(char in _HIDDEN_CHARACTERS for char in text):
        codes.add("HIDDEN_CHARACTERS")
    return tuple(sorted(codes))


def flag_chunks(chunks: list[dict]) -> list[dict]:
    """Per-chunk flags for chunks that match; content itself is never returned here."""
    flags = []
    for chunk in chunks:
        codes = scan_text(chunk.get("content") or "")
        if codes:
            flags.append({"sequence": chunk.get("sequence"), "codes": list(codes)})
    return flags
