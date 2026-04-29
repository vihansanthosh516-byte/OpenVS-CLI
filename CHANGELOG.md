# Changelog

## 0.1.0-beta.1

Initial public beta.

### Features
- Multi-model AI CLI with NVIDIA NIM integration
- 8 models: qwen, deepseek, deepseek-flash, glm, gemma, gpt-oss, nemotron, local
- Event-driven architecture with persistent event store
- Job persistence with crash recovery
- Plugin system with schema validation and runtime isolation
- Swarm execution foundation (local workers)
- Deterministic event replay engine
- Distributed network layer (RPC protocol, node registry, task protocol)
- Swarm coordinator with task assignment and failure recovery
- Live observability streaming
- Lifecycle orchestration (9-state lifecycle)
- Terminal UX: boot screen, spinner, model prefix, error formatting
- API key management: `/config set-key <provider> <key>`
- Zero npm dependencies, zero Python dependencies (stdlib only)

### Commands
`/help` `/model` `/models` `/config` `/status` `/jobs` `/events` `/plugin`
`/diagnostics` `/swarm` `/replay` `/coordinator` `/network` `/agents` `/exit`

### Getting Started
```
npm install -g logos-cli@beta
logos
/config set-key nvidia YOUR_KEY
```
