# Changelog

All notable changes to the ADAPT project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] - 2025-06-13

### Added
- Initial release of ADAPT system
- Multi-agent workflow powered by LangGraph
- Agents: Fault Summarizer, Action Planner, Action Executor, Action Analyzer, Summary Reporter
- Support for simulation, test, and production modes
- Streamlit-based user interface
- Network device inventory management
- Command execution with approval system
- Comprehensive reporting of troubleshooting results
- Direct URL access to results and logs

### Known Issues
- Simulation Mode does not provide consistent results as if interfacing with a real network device - they are random results each time
- General UI bugginess in Streamlit app when clicking buttons too quickly
- Step count in revised action plan shows the wrong number for first step
- Extra logging code is present that has no functional impact on the logging behavior of the app and needs to be cleaned up
- Logfire warning messages are generated when a Logfire API key is not set, but this does not affect functionality
- After human intervention for human-in-the-loop, log file may reset and start logging only after the human-in-the-loop step
- When parsing device facts in the Initialize Dependencies node, additional interfaces show up in the interfaces list that aren't actually real interfaces (parsing issue)

### Planned for Future Releases
- Integration of Retrieval Augmented Generation (RAG) agent for dynamic integration of fault-specific knowledge articles
- Introduce "Reflection Agent" for feedback on agent results to validate and improve troubleshooting steps and analysis
- Separation of responsibilities: have Action Analyzer agent push action re-planning requests to Action Planner instead of executing them directly
- Add "RCA Mode" for read-only analysis of past troubleshooting sessions with no ability for impactful changes
- Provide the ability to automatically convert a recent live execution into a test scenario for future simulations
- Update Simulation Mode to provide more consistent output across show commands as if interfacing with a single network device
- Update Simulation Mode to allow for customer simulation instructions so that device can simulate the presence of a particular issue
- Improved error handling for execution failures
- Explore integration with AGNTCY and use of MCP for greater modularity and reusability
- Create Action Executor tools for Splunk query actions to evaluate broader network environment health and state data