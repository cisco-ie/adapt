"""
Action Executor Agent for network device CLI command execution.

This agent executes CLI commands on network devices using SSH or simulation.
"""

from .agent import run, ActionExecutorDeps, action_executor

__all__ = ['run', 'ActionExecutorDeps', 'action_executor']