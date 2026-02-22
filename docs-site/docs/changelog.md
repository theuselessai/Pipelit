# Changelog

All notable changes to Pipelit will be documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-02-23

### Added

- Deep Agent node type (`deep_agent`) -- advanced agent with built-in task planning (todos), filesystem tools, and inline subagent delegation via the `deepagents` library
- Agent middleware architecture -- shared `PipelitAgentMiddleware` for tool status WebSocket events and streaming across agent types
- LangGraph v1 migration -- `create_react_agent` replaced with `create_agent`
- Real-time chat streaming -- intermediate agent LLM responses streamed to the chat panel during execution
- Dynamic Anthropic model fetching from API
- Auto-generated node IDs (`{type}_{hex}`) and node rename support on the canvas
- Documentation site with MkDocs Material
- Full component reference for all 42+ node types
- API reference documentation
- Architecture documentation with Mermaid diagrams
- Getting started guide and tutorials
- Deployment guides for Docker, production, and reverse proxy setups

---

*For the full commit history, see the [GitHub repository](https://github.com/theuselessai/Pipelit/commits/master).*
