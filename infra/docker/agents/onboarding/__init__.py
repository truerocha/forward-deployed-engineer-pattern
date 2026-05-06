# Repo Onboarding Agent — Phase 0: Codebase Reasoning Brain
#
# Sequential pipeline that scans a repository, extracts structure using
# Magika + tree-sitter, infers patterns via Claude Haiku, persists a SQLite
# catalog, and generates project-specific FDE steering for human approval.

__version__ = "0.1.0"
