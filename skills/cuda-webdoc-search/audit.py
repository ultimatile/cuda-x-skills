"""Validate registry entries for endpoint liveness and search viability."""

import json
import sys
from typing import Annotated, Optional

import requests
import sphobjinv as soi
import typer
from bs4 import BeautifulSoup

import registry

REQUEST_TIMEOUT = 15


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


def _try_inventory(url, results, label="inventory_url"):
    """Try fetching and parsing a single inventory URL.

    Returns True if the URL is reachable AND parseable with >0 objects.
    Failed attempts are recorded in results but do not stop the search.
    """
    url_check = check_url(url)
    if not url_check["ok"]:
        results["checks"].append(
            {
                "check": label,
                "ok": False,
                "detail": f"{url} -> {url_check.get('status') or url_check.get('error')}",
            }
        )
        return False

    detail = url
    if url_check.get("redirected_to"):
        detail += f" (redirected to {url_check['redirected_to']})"
    results["checks"].append({"check": label, "ok": True, "detail": detail})
    try:
        inv = soi.Inventory(url=url)  # type: ignore[call-arg]  # sphobjinv lacks type stubs
        domains = {}
        for obj in inv.objects:
            domains[obj.domain] = domains.get(obj.domain, 0) + 1
        total = len(inv.objects)
        results["checks"].append(
            {
                "check": "inventory_parse",
                "ok": total > 0,
                "detail": f"{total} objects, domains: {domains}",
            }
        )
        return total > 0
    except Exception as e:
        results["checks"].append(
            {"check": "inventory_parse", "ok": False, "detail": str(e)}
        )
        return False


def audit_sphinx(lib):
    """Audit a sphinx library entry."""
    results = {"checks": [], "ok": True}

    candidates = list(lib.get("inventory_urls", []))
    for base_url in lib.get("base_urls", []):
        fallback = base_url.rstrip("/") + "/objects.inv"
        if fallback not in candidates:
            candidates.append(fallback)

    if not candidates:
        results["checks"].append(
            {
                "check": "inventory_urls",
                "ok": False,
                "detail": "no inventory_urls or base_urls defined",
            }
        )
        results["ok"] = False
        return results

    inv_found = False
    for url in candidates:
        if _try_inventory(url, results):
            inv_found = True
            break

    if not inv_found:
        results["ok"] = False

    return results


def audit_doxygen(lib):
    """Audit a doxygen library entry."""
    results = {"checks": [], "ok": True}
    index_url = lib.get("index_url", "")

    if not index_url:
        results["checks"].append(
            {"check": "index_url", "ok": False, "detail": "no index_url defined"}
        )
        results["ok"] = False
        return results

    try:
        resp = requests.get(index_url, timeout=REQUEST_TIMEOUT)
    except Exception as e:
        results["checks"].append(
            {"check": "index_url", "ok": False, "detail": f"{index_url} -> {e}"}
        )
        results["ok"] = False
        return results

    ok = resp.status_code == 200
    detail = f"{index_url} -> {resp.status_code}"
    if resp.url != index_url:
        detail += f" (redirected to {resp.url})"
    results["checks"].append(
        {
            "check": "index_url",
            "ok": ok,
            "detail": detail,
        }
    )
    if not ok:
        results["ok"] = False
        return results

    try:
        soup = BeautifulSoup(resp.content, "html.parser")
        group_links = [
            a for a in soup.find_all("a", href=True) if "group__" in a["href"]
        ]
        results["checks"].append(
            {
                "check": "group_links",
                "ok": len(group_links) > 0,
                "detail": f"{len(group_links)} group__ links found",
            }
        )
        if len(group_links) == 0:
            results["ok"] = False
    except Exception as e:
        results["checks"].append(
            {"check": "group_links", "ok": False, "detail": str(e)}
        )
        results["ok"] = False

    return results


def audit_pdf(lib):
    """Audit a pdf library entry."""
    results = {"checks": [], "ok": True}
    doc_url = lib.get("doc_url", "")

    if not doc_url:
        results["checks"].append(
            {"check": "doc_url", "ok": False, "detail": "no doc_url defined"}
        )
        results["ok"] = False
        return results

    try:
        resp = requests.head(doc_url, timeout=REQUEST_TIMEOUT, allow_redirects=True)
        content_type = resp.headers.get("Content-Type", "")
        ok = resp.status_code == 200
        if ok and "text/html" in content_type.lower():
            ok = False
            redirect_note = (
                f" (redirected to {resp.url})" if resp.url != doc_url else ""
            )
            results["checks"].append(
                {
                    "check": "doc_url",
                    "ok": False,
                    "detail": f"{doc_url} -> 200 but Content-Type is {content_type} (expected PDF, not HTML){redirect_note}",
                }
            )
        else:
            redirect_note = (
                f" (redirected to {resp.url})" if resp.url != doc_url else ""
            )
            results["checks"].append(
                {
                    "check": "doc_url",
                    "ok": ok,
                    "detail": f"{doc_url} -> {resp.status_code}, Content-Type: {content_type or 'unknown'}{redirect_note}",
                }
            )
        if not ok:
            results["ok"] = False
    except Exception as e:
        results["checks"].append(
            {"check": "doc_url", "ok": False, "detail": f"HEAD {doc_url} failed: {e}"}
        )
        results["ok"] = False

    return results


def audit_sphinx_noinv(lib):
    """Audit a sphinx_noinv library entry."""
    results = {"checks": [], "ok": True}
    index_url = lib.get("index_url", "")

    if not index_url:
        results["checks"].append(
            {"check": "index_url", "ok": False, "detail": "no index_url defined"}
        )
        results["ok"] = False
        return results

    url_check = check_url(index_url)
    detail = f"{index_url} -> {url_check.get('status') or url_check.get('error')}"
    if url_check.get("redirected_to"):
        detail += f" (redirected to {url_check['redirected_to']})"
    results["checks"].append(
        {
            "check": "index_url",
            "ok": url_check["ok"],
            "detail": detail,
        }
    )
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
            "checks": [
                {
                    "check": "doc_type",
                    "ok": False,
                    "detail": f"unsupported doc_type: {doc_type}",
                }
            ],
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
        detail = ""
        if r["ok"]:
            for c in reversed(r["checks"]):
                if c["ok"]:
                    detail = c.get("detail", "")
                    break
        else:
            for c in r["checks"]:
                if not c["ok"]:
                    detail = f"{c['check']}: {c['detail']}"
                    break
        if not detail and r["checks"]:
            detail = r["checks"][-1].get("detail", "")
        if len(detail) > 60:
            detail = detail[:57] + "..."
        print(
            f"{r['name']:<16} {r['doc_type']:<14} {status:<6} {detail}",
            file=sys.stderr,
        )


def audit(
    source: Annotated[
        Optional[str], typer.Option(help="Audit only this source")
    ] = None,
    registry_path: Annotated[
        str,
        typer.Option("--registry", help="Registry TOML path"),
    ] = registry.DEFAULT_REGISTRY_PATH,
    no_table: Annotated[
        bool,
        typer.Option(
            "--no-table",
            help="Suppress the human-readable table (JSON always to stdout)",
        ),
    ] = False,
):
    """Audit registry entries for endpoint health."""
    reg = registry.load_registry(registry_path)
    if isinstance(reg, str):
        print(f"Error: {reg}", file=sys.stderr)
        raise typer.Exit(1)
    libraries = reg.get("library", [])

    if source:
        libraries = [lib for lib in libraries if lib.get("name") == source]
        if not libraries:
            print(f"Error: source '{source}' not found in registry", file=sys.stderr)
            raise typer.Exit(1)

    results = []
    for lib in libraries:
        result = audit_library(lib)
        results.append(result)

    if not no_table:
        print_table(results)

    summary = {
        "total": len(results),
        "passed": sum(1 for r in results if r["ok"]),
        "failed": sum(1 for r in results if not r["ok"]),
        "results": results,
    }
    print(json.dumps(summary, indent=2))

    if summary["failed"] > 0:
        raise typer.Exit(1)
