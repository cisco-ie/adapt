"""
Fault Summarization agent package.

This agent analyzes network fault alerts and provides structured summaries.
"""
from .agent import run, FaultSummary, agent, FaultSummaryDependencies

__all__ = ['run', 'FaultSummary', 'agent', 'FaultSummaryDependencies']