from __future__ import annotations as _annotations
import os
from dotenv import load_dotenv
from typing import Optional
from pydantic_ai import Agent, RunContext

from .agent_prompts import FAULT_SUMMARY_SYSTEM_PROMPT
from ..models import FaultSummary, FaultSummaryDependencies

# Load environment variables from .env file
load_dotenv()

# Initialize the Fault Summary agent with structured output
agent = Agent(
    model='openai:gpt-4.1-mini',
    system_prompt=FAULT_SUMMARY_SYSTEM_PROMPT,
    output_type=FaultSummary,
    deps_type=FaultSummaryDependencies,
    retries=2,
    instrument=True,
)

# Define a dynamic system prompt that incorporates the golden rules
@agent.system_prompt
def add_golden_rules(ctx: RunContext[FaultSummaryDependencies]) -> str:
    """Add any configured golden rules to the system prompt."""
    if "golden_rules" in ctx.deps.settings and ctx.deps.settings["golden_rules"]:
        # Format golden rules as numbered list
        golden_rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(ctx.deps.settings["golden_rules"])])
        return f"**GOLDEN RULES**\nThe following rules must always be followed during execution:\n{golden_rules_text}"
    return "No golden rules defined."

async def run(user_input: str, deps: Optional[FaultSummaryDependencies] = None):
    """
    Run the fault summary agent with the given user input.
    
    Args:
        user_input: The user input describing the network fault alert
        deps: Dependencies for the agent, including settings, logger, and latest_user_message
        
    Returns:
        The agent's response object containing the structured NetworkFaultSummary
    """
    # Initialize dependencies if None
    if deps is None:
        deps = FaultSummaryDependencies()
      # Log debug information if debug mode is enabled
    if deps.settings.get("debug_mode", False) and deps.logger:
        deps.logger.info("Fault Summary Agent User Prompt", extra={
            "user_input": user_input
        })
        
    return await agent.run(user_input, deps=deps)