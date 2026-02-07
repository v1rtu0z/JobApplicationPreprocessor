"""
Core domain layer: models, data sources, repository, and services.
Keeps the app data-source agnostic (Apify, LinkedIn, other boards) and testable.
"""

from .models import Job, Company
from .sources import DataSource, ApifyDataSource, LinkedInDataSource
from .repository import JobRepository
from .services import JobAnalysisService, ResumeGenerationService

__all__ = [
    "Job",
    "Company",
    "DataSource",
    "ApifyDataSource",
    "LinkedInDataSource",
    "JobRepository",
    "JobAnalysisService",
    "ResumeGenerationService",
]
