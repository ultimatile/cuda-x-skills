"""Tests for registry_audit.py — audit dispatch and validation logic."""

import pytest

from registry_audit import audit_library, print_table


# -- audit_library dispatch --------------------------------------------------

class TestAuditLibrary:
    def test_unsupported_doc_type(self):
        lib = {"name": "testlib", "doc_type": "unknown_type"}
        result = audit_library(lib)
        assert result["ok"] is False
        assert result["name"] == "testlib"
        assert result["doc_type"] == "unknown_type"
        assert any("unsupported" in c["detail"] for c in result["checks"])

    def test_missing_name(self):
        lib = {"doc_type": "unknown_type"}
        result = audit_library(lib)
        assert result["name"] == "unknown"

    def test_missing_doc_type(self):
        lib = {"name": "testlib"}
        result = audit_library(lib)
        assert result["doc_type"] == "unknown"
        assert result["ok"] is False


# -- audit_* input validation (no network) -----------------------------------

class TestAuditInputValidation:
    def test_sphinx_no_urls(self):
        """sphinx with no inventory_urls or base_urls should fail."""
        from registry_audit import audit_sphinx
        lib = {}
        result = audit_sphinx(lib)
        assert result["ok"] is False
        assert any("no inventory_urls" in c["detail"] for c in result["checks"])

    def test_doxygen_no_index_url(self):
        """doxygen with no index_url should fail."""
        from registry_audit import audit_doxygen
        lib = {}
        result = audit_doxygen(lib)
        assert result["ok"] is False
        assert any("no index_url" in c["detail"] for c in result["checks"])

    def test_pdf_no_doc_url(self):
        """pdf with no doc_url should fail."""
        from registry_audit import audit_pdf
        lib = {}
        result = audit_pdf(lib)
        assert result["ok"] is False
        assert any("no doc_url" in c["detail"] for c in result["checks"])

    def test_sphinx_noinv_no_index_url(self):
        """sphinx_noinv with no index_url should fail."""
        from registry_audit import audit_sphinx_noinv
        lib = {}
        result = audit_sphinx_noinv(lib)
        assert result["ok"] is False
        assert any("no index_url" in c["detail"] for c in result["checks"])


# -- print_table formatting --------------------------------------------------

class TestPrintTable:
    def test_ok_result(self, capsys):
        results = [{
            "name": "cublas",
            "doc_type": "sphinx",
            "ok": True,
            "checks": [
                {"check": "inventory_url", "ok": True, "detail": "https://example.com/objects.inv"},
            ],
        }]
        print_table(results)
        captured = capsys.readouterr()
        assert "cublas" in captured.err
        assert "OK" in captured.err

    def test_fail_result(self, capsys):
        results = [{
            "name": "badlib",
            "doc_type": "sphinx",
            "ok": False,
            "checks": [
                {"check": "inventory_url", "ok": False, "detail": "404 not found"},
            ],
        }]
        print_table(results)
        captured = capsys.readouterr()
        assert "badlib" in captured.err
        assert "FAIL" in captured.err
        assert "404" in captured.err

    def test_truncates_long_detail(self, capsys):
        results = [{
            "name": "lib",
            "doc_type": "sphinx",
            "ok": True,
            "checks": [
                {"check": "x", "ok": True, "detail": "a" * 100},
            ],
        }]
        print_table(results)
        captured = capsys.readouterr()
        assert "..." in captured.err
