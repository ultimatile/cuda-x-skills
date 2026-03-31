# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "requests",
#     "beautifulsoup4",
#     "sphobjinv",
# ]
# ///

"""Validate registry entries for endpoint liveness, parseability, and search viability."""

import argparse
import json
import sys
import tomllib

import requests
import sphobjinv as soi
from bs4 import BeautifulSoup

DEFAULT_REGISTRY_PATH = "registry.toml"
REQUEST_TIMEOUT = 15


def load_registry(path):
    with open(path, "rb") as f:
        return tomllib.load(f)


def check_url(url, timeout=REQUEST_TIMEOUT):
    """Check URL liveness and return status details."""
    try:
        resp = requests.get(url, timeout=timeout, allow_redirects=True)
        redirected = resp.url != url
        return {
            "url": url,
            "status": resp.status_code,
            "ok": resp.status_code == 200,
            "redirected_to": resp.url if redirected else None,
            "content_type": resp.headers.get("Content-Type", ""),
        }
    except Exception as e:
        return {
            "url": url,
            "status": None,
            "ok": False,
            "redirected_to": None,
            "content_type": "",
            "error": str(e),
        }


def audit_sphinx(lib):
    """Audit a sphinx library entry."""
    results = {"checks": [], "ok": True}
    inv_urls = lib.get("inventory_urls", [])

    if not inv_urls:
        results["checks"].append({"check": "inventory_urls", "ok": False, "detail": "no inventory_urls defined"})
        results["ok"] = False
        return results

    # Check inventory URL liveness and parseability
    inv_found = False
    for url in inv_urls:
        url_check = check_url(url)
        if url_check["ok"]:
            inv_found = True
            results["checks"].append({"check": f"inventory_url", "ok": True, "detail": url})

            # Parse inventory and count domains
            try:
                inv = soi.Inventory(url=url)
                domains = {}
                for obj in inv.objects:
                    domains[obj.domain] = domains.get(obj.domain, 0) + 1
                total = len(inv.objects)
                results["checks"].append({
                    "check": "inventory_parse",
                    "ok": total > 0,
                    "detail": f"{total} objects, domains: {domains}",
                })
                if total == 0:
                    results["ok"] = False
            except Exception as e:
                results["checks"].append({"check": "inventory_parse", "ok": False, "detail": str(e)})
                results["ok"] = False
            break
        else:
            results["checks"].append({
                "check": "inventory_url",
                "ok": False,
                "detail": f"{url} -> {url_check.get('status') or url_check.get('error')}",
            })

    # Fallback: try deriving objects.inv from base_urls
    if not inv_found:
        for base_url in lib.get("base_urls", []):
            fallback = base_url.rstrip("/") + "/objects.inv"
            url_check = check_url(fallback)
            if url_check["ok"]:
                inv_found = True
                results["checks"].append({"check": "inventory_url (base_url fallback)", "ok": True, "detail": fallback})
                try:
                    inv = soi.Inventory(url=fallback)
                    domains = {}
                    for obj in inv.objects:
                        domains[obj.domain] = domains.get(obj.domain, 0) + 1
                    total = len(inv.objects)
                    results["checks"].append({
                        "check": "inventory_parse",
                        "ok": total > 0,
                        "detail": f"{total} objects, domains: {domains}",
                    })
                    if total == 0:
                        results["ok"] = False
                except Exception as e:
                    results["checks"].append({"check": "inventory_parse", "ok": False, "detail": str(e)})
                    results["ok"] = False
                break

    if not inv_found:
        results["ok"] = False

    return results


def audit_doxygen(lib):
    """Audit a doxygen library entry."""
    results = {"checks": [], "ok": True}
    index_url = lib.get("index_url", "")

    if not index_url:
        results["checks"].append({"check": "index_url", "ok": False, "detail": "no index_url defined"})
        results["ok"] = False
        return results

    url_check = check_url(index_url)
    results["checks"].append({
        "check": "index_url",
        "ok": url_check["ok"],
        "detail": f"{index_url} -> {url_check['status']}",
    })
    if not url_check["ok"]:
        results["ok"] = False
        return results

    # Check for group__ links
    try:
        resp = requests.get(index_url, timeout=REQUEST_TIMEOUT)
        soup = BeautifulSoup(resp.content, "html.parser")
        group_links = [a for a in soup.find_all("a", href=True) if "group__" in a["href"]]
        results["checks"].append({
            "check": "group_links",
            "ok": len(group_links) > 0,
            "detail": f"{len(group_links)} group__ links found",
        })
        if len(group_links) == 0:
            results["ok"] = False
    except Exception as e:
        results["checks"].append({"check": "group_links", "ok": False, "detail": str(e)})
        results["ok"] = False

    return results


def audit_pdf(lib):
    """Audit a pdf library entry."""
    results = {"checks": [], "ok": True}
    doc_url = lib.get("doc_url", "")

    if not doc_url:
        results["checks"].append({"check": "doc_url", "ok": False, "detail": "no doc_url defined"})
        results["ok"] = False
        return results

    # HEAD request to avoid downloading the full PDF
    try:
        resp = requests.head(doc_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        ok = resp.status_code == 200
        results["checks"].append({
            "check": "doc_url",
            "ok": ok,
            "detail": f"{doc_url} -> {resp.status_code}, Content-Type: {resp.headers.get('Content-Type', 'unknown')}",
        })
        if not ok:
            results["ok"] = False
    except Exception as e:
        results["checks"].append({"check": "doc_url", "ok": False, "detail": str(e)})
        results["ok"] = False

    return results


def audit_sphinx_noinv(lib):
    """Audit a sphinx_noinv library entry."""
    results = {"checks": [], "ok": True}
    index_url = lib.get("index_url", "")

    if not index_url:
        results["checks"].append({"check": "index_url", "ok": False, "detail": "no index_url defined"})
        results["ok"] = False
        return results

    url_check = check_url(index_url)
    results["checks"].append({
        "check": "index_url",
        "ok": url_check["ok"],
        "detail": f"{index_url} -> {url_check['status']}",
    })
    if not url_check["ok"]:
        results["ok"] = False

    return results


AUDITORS = {
    "sphinx": audit_sphinx,
    "doxygen": audit_doxygen,
    "pdf": audit_pdf,
    "sphinx_noinv": audit_sphinx_noinv,
}


def audit_library(lib):
    """Run appropriate audit for a library entry."""
    name = lib.get("name", "unknown")
    doc_type = lib.get("doc_type", "unknown")

    auditor = AUDITORS.get(doc_type)
    if not auditor:
        return {
            "name": name,
            "doc_type": doc_type,
            "ok": False,
            "checks": [{"check": "doc_type", "ok": False, "detail": f"unsupported doc_type: {doc_type}"}],
        }

    result = auditor(lib)
    result["name"] = name
    result["doc_type"] = doc_type
    return result


def print_table(results):
    """Print a human-readable summary table to stderr."""
    print(f"\n{'Name':<16} {'Type':<14} {'Status':<6} Details", file=sys.stderr)
    print("-" * 72, file=sys.stderr)
    for r in results:
        status = "OK" if r["ok"] else "FAIL"
        # Show first failing check as detail, or first check summary
        detail = ""
        for c in r["checks"]:
            if not c["ok"]:
                detail = f"{c['check']}: {c['detail']}"
                break
        if not detail and r["checks"]:
            detail = r["checks"][-1].get("detail", "")
        # Truncate long details
        if len(detail) > 60:
            detail = detail[:57] + "..."
        print(f"{r['name']:<16} {r['doc_type']:<14} {status:<6} {detail}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Audit registry entries for endpoint health.")
    parser.add_argument("--registry", default=DEFAULT_REGISTRY_PATH, help="Registry TOML path")
    parser.add_argument("--source", help="Audit only this source")
    parser.add_argument("--json", action="store_true", help="Output JSON only (no table)")
    args = parser.parse_args()

    registry = load_registry(args.registry)
    libraries = registry.get("library", [])

    if args.source:
        libraries = [lib for lib in libraries if lib.get("name") == args.source]
        if not libraries:
            print(f"Error: source '{args.source}' not found in registry", file=sys.stderr)
            sys.exit(1)

    results = []
    for lib in libraries:
        result = audit_library(lib)
        results.append(result)

    if not args.json:
        print_table(results)

    # JSON summary to stdout
    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "results": results,
    }
    print(json.dumps(summary, indent=2))

    # Exit code: 1 if any failures
    if summary["failed"] > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
