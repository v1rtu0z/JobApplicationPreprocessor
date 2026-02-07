#!/usr/bin/env python3
"""
Job Application Preprocessor - entry point.
All pipeline logic lives in the pipeline/ package (constants, filtering, collection, bulk_ops, analysis, resumes, validation, runner).
"""

from pipeline.runner import main

if __name__ == "__main__":
    main()
