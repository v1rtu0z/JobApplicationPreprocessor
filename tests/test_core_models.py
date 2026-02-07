"""Unit tests for Job and Company domain models."""

import pytest

from core.models import Job, Company
from utils.schema import SHEET_HEADER


class TestCompany:
    def test_create_minimal(self):
        c = Company(name="Acme")
        assert c.name == "Acme"
        assert c.url == ""
        assert c.overview == ""

    def test_create_full(self):
        c = Company(name="Acme", url="https://acme.com", overview="We do stuff.")
        assert c.name == "Acme"
        assert c.url == "https://acme.com"
        assert c.overview == "We do stuff."

    def test_with_overview(self):
        c = Company(name="A", url="u")
        c2 = c.with_overview("New overview")
        assert c2.overview == "New overview"
        assert c2.name == c.name
        assert c.overview == ""

    def test_equality(self):
        assert Company("A") == Company("A")
        assert Company("A") != Company("B")
        assert Company("A", "u1") != Company("A", "u2")


class TestJob:
    def test_from_empty_row(self):
        job = Job.from_row(None)
        assert job.job_title == ""
        assert job.company_name == ""
        assert job.job_url == ""
        assert job.job_key_str() == " @ "

    def test_from_row(self):
        row = {
            "Company Name": "Acme",
            "Job Title": "Engineer",
            "Job URL": "https://linkedin.com/jobs/1",
            "Location": "Remote",
            "Job Description": "Code stuff.",
        }
        job = Job.from_row(row)
        assert job.company_name == "Acme"
        assert job.job_title == "Engineer"
        assert job.job_url == "https://linkedin.com/jobs/1"
        assert job.location == "Remote"
        assert job.job_description == "Code stuff."
        assert job.job_key_str() == "Engineer @ Acme"
        assert job.natural_key() == ("https://linkedin.com/jobs/1", "Acme")

    def test_to_row_has_all_columns(self):
        row = {"Company Name": "A", "Job Title": "T", "Job URL": "U"}
        job = Job.from_row(row)
        out = job.to_row()
        for col in SHEET_HEADER:
            assert col in out
        assert out["Company Name"] == "A"
        assert out["Job Title"] == "T"
        assert out["Job URL"] == "U"

    def test_copy_with_updates(self):
        job = Job.from_row({"Company Name": "A", "Job Title": "T", "Job URL": "U"})
        job2 = job.copy_with_updates({"Fit score": "Good fit", "Fit score enum": "4"})
        assert job2.get("Fit score") == "Good fit"
        assert job2.get("Fit score enum") == "4"
        assert job2.company_name == job.company_name

    def test_company_property(self):
        job = Job.from_row({
            "Company Name": "Acme",
            "Job Title": "Dev",
            "Job URL": "u",
            "Company URL": "https://acme.com",
            "Company overview": "Overview text",
        })
        c = job.company
        assert c.name == "Acme"
        assert c.url == "https://acme.com"
        assert c.overview == "Overview text"
