from .models import Finding, LinkData, PageData, ScanMeta
from .rules import ALL_RULES


def analyze(pages: list[PageData], links: list[LinkData], meta: ScanMeta) -> list[Finding]:
    findings: list[Finding] = []
    for rule in ALL_RULES:
        findings.extend(rule(pages, links, meta))
    return findings
