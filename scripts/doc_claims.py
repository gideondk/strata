"""Path + symbol claim extraction shared by bootstrap-scan and
plan_correlate. Extensions sorted longest-first; URL hostnames filtered."""
from __future__ import annotations

import re

# Extensions we recognise as "code" for path claim extraction.
# When a doc references `path/to/file.<ext>`, we cross-check that path
# against `git ls-files` or `git log`.
CODE_EXTS = (
    "py", "cs", "ts", "tsx", "js", "jsx", "mjs", "cjs",
    "go", "rs", "java", "kt", "kts", "rb", "php", "sql",
    "swift", "m", "h", "c", "cpp", "cc", "hpp",
    "yaml", "yml", "json", "toml", "ini",
    "sh", "bash", "zsh", "fish",
    "md", "rst", "txt",
    "html", "css", "scss",
    "lua", "ex", "exs", "erl", "hrl", "scala", "clj", "cljs",
    "dart", "vue", "svelte",
    "tf", "hcl",
    "proto", "graphql",
)
# Longest first so `md` wins over `m`, `json` over `js`, etc.
_SORTED_EXTS = sorted(CODE_EXTS, key=lambda e: (-len(e), e))

_PATH_RE = re.compile(
    r"`?([A-Za-z0-9_./-]+\.(?:" + "|".join(_SORTED_EXTS) + r"))"
    r"(?![A-Za-z0-9])`?"
)
_SYMBOL_RE = re.compile(r"`([A-Za-z_][A-Za-z0-9_.]{2,})`")

# Domain suffixes that mean the candidate is almost certainly a URL host
# (e.g. `chriskiehl.com`, `getakka.net/...`), not a file path.
_URL_DOMAIN_HINTS = {
    "com", "net", "org", "io", "ai", "app", "dev", "co",
    "uk", "us", "de", "fr", "nl", "eu", "tv", "me", "gov",
}


def looks_like_url(candidate: str) -> bool:
    """Heuristic — strip URL-shaped matches before they hit the verifier."""
    low = candidate.lower()
    if "://" in low or "@" in low or low.startswith("www."):
        return True
    first = low.split("/", 1)[0]
    if "." in first:
        last_dot = first.rsplit(".", 1)[-1]
        if last_dot in _URL_DOMAIN_HINTS:
            return True
    return False


def extract_path_claims(text: str) -> list[str]:
    """Pull path-like tokens (foo/bar.py, ./scripts/x.sh) from doc text.

    URL-shaped matches are filtered so verification doesn't get polluted
    by hostname.tld false positives.
    """
    out = set()
    for m in _PATH_RE.finditer(text):
        path = m.group(1).lstrip("./")
        if looks_like_url(path):
            continue
        out.add(path)
    return sorted(out)


def extract_symbol_claims(text: str) -> list[str]:
    """Pull backtick-quoted identifiers that look like code symbols.

    Filters: must contain an uppercase char OR underscore OR dot — drops
    common-word backticks like `the` / `null` / `true`.
    """
    out = set()
    for m in _SYMBOL_RE.finditer(text):
        s = m.group(1)
        if any(c.isupper() for c in s) or "_" in s or "." in s:
            out.add(s)
    return sorted(out)
