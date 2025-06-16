from __future__ import annotations as _annotations

import json
from pydantic_ai import Agent, RunContext

from .agent_prompts import ACTION_ANALYZER_SYSTEM_PROMPT
from ..models import (
    ActionAnalysisReport, 
    ActionExecutorOutput, 
    TroubleshootingStep, 
    FaultSummary,
    ActionAnalyzerDependencies
)
    
# The core agent definition
action_analyzer = Agent(
    model='openai:o4-mini',  # or use your preferred model
    output_type=ActionAnalysisReport,
    system_prompt=ACTION_ANALYZER_SYSTEM_PROMPT,
    name='action_analyzer',
    retries=1,
    deps_type=ActionAnalyzerDependencies,
    instrument=True,
)

@action_analyzer.system_prompt
def add_golden_rules(ctx: RunContext[ActionAnalyzerDependencies]) -> str:
    """Add any configured golden rules to the system prompt."""
    if "golden_rules" in ctx.deps.settings and ctx.deps.settings["golden_rules"]:
        # Format golden rules as numbered list
        golden_rules_text = "\n".join([f"{i+1}. {rule}" for i, rule in enumerate(ctx.deps.settings["golden_rules"])])
        return f"**GOLDEN RULES**\nThe following rules must always be followed during execution:\n{golden_rules_text}"
    return "No golden rules defined."

async def run(deps: ActionAnalyzerDependencies) -> RunContext:
    """
    Run the action_analyzer agent to analyze the output of a network device command.
    
    Args:
        deps: The dependencies containing executor output, action plan, fault summary, current step, settings and logger
        
    Returns:
        An ActionAnalysisReport containing structured analysis of the command output
    """
    # Initialize settings if None in dependencies
    if deps.settings is None:
        deps.settings = {"debug_mode": False, "simulation_mode": True}
      # Log debug information if debug mode is enabled
    if deps.settings.get("debug_mode", False) and deps.logger:
        deps.logger.info("Action Analyzer Agent", extra={
            "user_input": "Analyzing command output..."
        })
    
    # Extract command output from executor_output
    command_output_context = deps.execution_result.command_outputs
    
    # Manually extract fault_summary fields to avoid datetime serialization issues
    fault_summary_dict = {
        "title": deps.fault_summary.title,
        "summary": deps.fault_summary.summary,
        "hostname": deps.fault_summary.hostname,
        "timestamp": deps.fault_summary.timestamp.isoformat() if deps.fault_summary.timestamp else None,
        "severity": deps.fault_summary.severity,
        "metadata": deps.fault_summary.metadata
    }
    
    # Format the input according to the template
    fault_summary_context = f"fault_summary:\n{json.dumps(fault_summary_dict)}\n\n"
    device_facts_context = f"device_facts:\n{json.dumps(deps.device_facts)}\n\n"
    
    # Add context from the current step being analyzed
    current_step_context = f"current_step:\n{json.dumps(deps.current_step.model_dump())}\n\n"
    errors_context = f"errors:\n{json.dumps(deps.execution_result.errors)}\n\n"
    action_plan_history_context = f"action_plan_history:\n{json.dumps([step.model_dump() for step in deps.action_plan_history])}\n\n"
    action_plan_remaining_context = f"action_plan_remaining:\n{json.dumps([step.model_dump() for step in deps.action_plan_remaining])}\n\n"
    
    # Construct the user input with all relevant context
    user_input = (
        f"command_output: {command_output_context}\n"
        f"errors: {errors_context}\n"
        f"current_step: {current_step_context}\n"
        f"current_step_index: {deps.current_step_index}\n"
        f"max_steps: {deps.settings['max_steps']}\n"
        f"fault_summary: {fault_summary_context}\n"
        f"device_facts: {device_facts_context}\n"
        f"action_plan_history: {action_plan_history_context}\n"
        f"action_plan_remaining: {action_plan_remaining_context}\n"
        f"adaptive_mode: {deps.settings['adaptive_mode']}\n"
        f"custom_instructions: {deps.settings.get('custom_instructions', '')}\n"
    )
    
    if deps.settings.get("debug_mode", False) and deps.logger:
        deps.logger.info("Action Analyzer input", extra={
            "user_input": user_input
        })

    # Run the agent with the formatted input
    return await action_analyzer.run(user_input, deps=deps)
