from __future__ import annotations as _annotations
import os
from dotenv import load_dotenv
from pydantic_ai import Agent, RunContext
from typing import Optional

from .agent_prompts import HELLO_WORLD_SYSTEM_PROMPT
from ..models import HelloWorldDependencies

# Load environment variables from .env file
load_dotenv()

# Initialize the Hello World agent
agent = Agent(
    model='openai:gpt-4.1-mini',
    system_prompt=HELLO_WORLD_SYSTEM_PROMPT,
    deps_type=HelloWorldDependencies,
    instrument=True,
)

# Define a dynamic system prompt that incorporates the golden rules
@agent.system_prompt
def add_golden_rules(ctx: RunContext[HelloWorldDependencies]) -> str:
    """Add any configured golden rules to the system prompt."""
    if "golden_rules" in ctx.deps.settings and ctx.deps.settings["golden_rules"]:
        # Format golden rules as numbered list
        golden_rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(ctx.deps.settings["golden_rules"])])
        return f"GOLDEN RULES: The following rules must always be followed during execution:\n{golden_rules_text}"
    return "No golden rules defined."

async def run(user_input: str, deps: Optional[HelloWorldDependencies] = None):
    """
    Run the hello world agent with the given user input.
    
    Args:
        deps: Dependencies for the agent
        
    Returns:
        The agent's response object
    """
    # Initialize dependencies if None
    if deps is None:
        deps = HelloWorldDependencies()
    
    # Log debug information if debug mode is enabled
    if deps.settings.get("debug_mode", False) and deps.logger:
        deps.logger.info("Hello World Agent User Prompt", extra={
            "user_input": user_input
        })
        
    return await agent.run(user_input, deps=deps)