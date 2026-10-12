#!/usr/bin/env python3
"""Fail when a built static site contains a broken local link or anchor."""

from __future__ import annotations

import argparse
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit

CANONICAL_HOSTS = {"clamui.com", "www.clamui.com"}
IGNORED_SCHEMES = {"data", "javascript", "mailto", "tel"}


class PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: set[str] = set()
        self.links: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        for anchor in (attributes.get("id"), attributes.get("name")):
            if anchor:
                self.anchors.add(anchor)
        for attribute in ("href", "src"):
            if value := attributes.get(attribute):
                self.links.append(value)
        if srcset := attributes.get("srcset"):
            self.links.extend(
                candidate.strip().split(maxsplit=1)[0]
                for candidate in srcset.split(",")
                if candidate.strip()
            )


def public_path(site: Path, page: Path) -> str:
    relative = page.relative_to(site).as_posix()
    if relative == "index.html":
        return "/"
    if relative.endswith("/index.html"):
        return f"/{relative.removesuffix('index.html')}"
    return f"/{relative}"


def target_path(site: Path, target_url: str) -> Path | None:
    path = unquote(urlsplit(target_url).path).lstrip("/")
    if not path:
        return site / "index.html"

    direct = site / path
    clean_path = path.rstrip("/")
    candidates = [direct]
    if clean_path:
        candidates.append(site / f"{clean_path}.html")
    candidates.append(site / clean_path / "index.html")

    return next((candidate for candidate in candidates if candidate.is_file()), None)


def is_local(url: str) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme.lower() in IGNORED_SCHEMES:
        return False
    if parsed.scheme in {"http", "https"} or parsed.netloc:
        return parsed.netloc.lower().split(":", 1)[0] in CANONICAL_HOSTS
    return not parsed.scheme


def check_site(site: Path) -> list[str]:
    pages: dict[Path, PageParser] = {}
    public_urls: dict[Path, str] = {}
    for page in site.rglob("*.html"):
        parser = PageParser()
        parser.feed(page.read_text(encoding="utf-8"))
        parser.close()
        pages[page] = parser
        public_urls[page] = public_path(site, page)

    errors: list[str] = []
    for page, parser in pages.items():
        base_url = f"https://clamui.com{public_urls[page]}"
        for link in parser.links:
            if not is_local(link):
                continue
            target_url = urljoin(base_url, link)
            target = target_path(site, target_url)
            reference = f"{page.relative_to(site)} -> {link}"
            if target is None:
                errors.append(f"{reference}: missing local target")
                continue

            fragment = unquote(urlsplit(target_url).fragment)
            target_parser = pages.get(target)
            if fragment and target_parser and fragment not in target_parser.anchors:
                errors.append(f"{reference}: missing anchor #{fragment}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path, help="built site directory")
    args = parser.parse_args()
    site = args.site.resolve()
    if not site.is_dir():
        parser.error(f"not a directory: {site}")

    errors = check_site(site)
    if not errors:
        print(f"Validated local links and anchors in {site}")
        return 0

    print("Broken built-site references:")
    print("\n".join(f"- {error}" for error in sorted(set(errors))))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
