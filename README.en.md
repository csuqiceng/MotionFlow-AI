# MotionFlow AI - Robot Arm AI Platform

MotionFlow AI is an AI-based robot arm control platform that supports multiple interaction methods (WebUI, CLI, Desktop Application) and provides a complete tool ecosystem to implement robot automation tasks.

## Core Features

### 🤖 Intelligent Robot Control
- **Multi-DOF Control**: Supports precise control of position, flow, library, and processes
- **AI-Driven Execution**: Understands and executes natural language instructions via Large Language Models (LLMs)
- **Safe Execution Mechanism**: Complete execution permit and confirmation mechanisms ensure operational safety
- **Automatic Orchestration**: Supports advanced orchestration features for automatic flow and motion

### 🧠 AI Runtime Architecture
- **Multi-Model Support**: Integrates multiple AI providers including Anthropic, OpenAI, Azure OpenAI, Bedrock, GitHub Copilot, etc.
- **Provider Abstraction Layer**: Unified Provider interface supports model hot-swapping and fallback strategies
- **Thinking & Reasoning Support**: Complete handling of thinking tags and extraction of reasoning content
- **Model Preset System**: Supports preset configurations and dynamic model selection

### 🛠️ Tool System
- **Core Toolset**: File system operations, Shell execution, search tools, etc.
- **Robot-Specific Tools**: Position, Flow, Knowledge Base, Command Library, and other professional tools
- **MCP Integration**: Supports Model Context Protocol server extensions
- **Tool Audit Trail**: Complete tool invocation auditing and operation logging

### 📡 Multiple Interaction Channels
- **WebUI**: Modern web interface
- **CLI**: Command-line interaction
- **Electron Desktop App**: Windows desktop client (MotionFlow AI Windows Desktop Edition)
- **WebSocket Real-time Communication**: Supports streaming responses and real-time events

### ⏰ Automation Capabilities
- **Cron Scheduled Tasks**: Supports crontab-style scheduled execution
- **Local Triggers**: Event-driven automated execution
- **Automation Round Coordination**: Delay and concurrency control
- **Long-term Goal Tasks**: Supports long-cycle goal management and completion confirmation

## System Architecture

```
MotionFlow AI Platform
├── 📦 nanobot-main-1 (Core Python Application)
│   ├── 🤖 agent/          # AI Agent Loop and Context Management
│   ├── 🚌 bus/           # Message Bus and Event System
│   ├── 📡 providers/     # AI Provider Adapters
│   ├── 🛠️ tools/         # Tool Implementations
│   ├── 📅 cron/          # Scheduled Task Service
│   ├── 🎯 session/       # Session Management
│   └── 🔐 security/      # Security Boundaries and Access Control
│
├── 🖥️ desktop (Electron Desktop Application)
│   ├── electron/         # Electron Main Process and Renderer Process
│   └── pyinstaller/      # Python Packaging Configuration
│
├── 📖 docs/              # Architecture Documentation and Design Specifications
│   └── architecture/     # Modular Migration and Architecture Decisions
│
└── 🤖 robot_platform/    # Robot Platform Backend
    ├── adapters/         # File Adapters and Interface Implementations
    └── application/      # Application Services and Business Logic
```

## Quick Start

### Environment Requirements

- **Python**: 3.10 or higher
- **Node.js**: 18+ (for Electron Desktop Application)
- **OS**: Windows 10/11, macOS, or Linux

### Installation

#### Method 1: Using uv (Recommended)

```bash
# Clone repository
git clone https://gitee.com/csucyj/nanobot-robotic-arms.git
cd nanobot-robotic-arms/nanobot-main-1

# Create virtual environment using uv and install
uv venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows
uv pip install -e .
```

#### Method 2: Using pip

```bash
# Clone repository
git clone https://gitee.com/csucyj/nanobot-robotic-arms.git
cd nanobot-robotic-arms/nanobot-main-1

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -e .
```

### Configuration

1. Copy the configuration file template:

```bash
cp config.yaml.example config.yaml
```

2. Edit the configuration file (Optional):

```yaml
# config.yaml
providers:
  anthropic:
    api_key: ${ANTHROPIC_API_KEY}  # Supports environment variable references
    default_model: claude-sonnet-4-20250514

# Or use OpenAI compatible interface
providers:
  openai:
    api_key: ${OPENAI_API_KEY}
    api_base: https://api.openai.com/v1
    default_model: gpt-4o
```

3. Set environment variables:

```bash
export ANTHROPIC_API_KEY="your-api-key"
# Or
export OPENAI_API_KEY="your-api-key"
```

### Running

#### Start WebUI Service

```bash
nanobot run
```

Then access http://localhost:8080 in your browser.

#### Using CLI

```bash
# Interactive mode
nanobot chat

# Single execution
nanobot run "Please move me to Position A"

# Specify session
nanobot run --session "my-session" "Execute Flow B"
```

#### Using SDK

```python
import asyncio
from nanobot import Nanobot

async def main():
    bot = Nanobot.from_config()
    
    # Execute task
    result = await bot.run("Move to standby position")
    print(result.text)
    
    # Streaming response
    async for event in bot.stream("Execute advanced action"):
        print(event)

asyncio.run(main())
```

## Development Guide

### Project Structure

```
nanobot-main-1/
├── nanobot/
│   ├── agent/           # Agent Core Logic
│   ├── bus/             # Message Bus
│   ├── providers/       # AI Providers
│   ├── tools/           # Tool Implementations
│   ├── cron/            # Scheduled Tasks
│   ├── session/         # Session Management
│   ├── security/        # Security Module
│   └── sdk/             # SDK Interfaces
├── desktop/             # Electron Desktop Application
├── docs/                # Documentation
├── robot_platform/      # Robot Platform
└── tests/               # Tests
```

### Running Tests

```bash
# Run all tests
pytest tests/

# Run specific module tests
pytest tests/agent/
pytest tests/providers/

# Run type checking
pytest tests/ --typeguard-mode=strict
```

### Code Style

The project uses ruff for code linting and formatting:

```bash
# Check code
ruff check .

# Auto-fix
ruff check --fix .
```

### Contributing Code

1. Fork the project
2. Create feature branch: `git checkout -b feature/your-feature`
3. Commit changes: `git commit -m 'Add some feature'`
4. Push to branch: `git push origin feature/your-feature`
5. Create Pull Request

## Tool System

### Built-in Tools

| Tool | Function | Category |
|------|------|------|
| read_file | Read file | Core |
| write_file | Write file | Core |
| edit_file | Edit file | Core |
| list_dir | List directory | Core |
| find_files | Find files | Core |
| grep | Search content | Core |
| exec | Execute Shell command | Core |
| exec_session | Interactive execution session | Core |
| robot_position | Robot position control | Robot |
| robot_flow | Robot flow control | Robot |
| robot_knowledge | Knowledge base query | Robot |
| robot_library | Command library management | Robot |
| cron | Scheduled task management | Automation |
| long_task | Long-term goal task | Automation |
| spawn | Trigger sub-task | Automation |
| web_search | Web search | External |
| web_fetch | Fetch webpage content | External |
| image_generation | Image generation | External |
| cli_apps | CLI app integration | Integration |
| message | Cross-channel message | Messaging |

### Custom Tools

```python
from nanobot.tools import Tool, tool_parameters

@tool_parameters({
    "name": StringSchema("Parameter Name", description="Description"),
    "required": ["name"]
})
class MyTool(Tool):
    @property
    def name(self) -> str:
        return "my_tool"
    
    @property
    def description(self) -> str:
        return "My custom tool"
    
    async def execute(self, name: str) -> str:
        return f"Hello, {name}!"
```

## Security Features

### Runtime Security Boundaries

- **Workspace Isolation**: Tools can only access the specified workspace by default
- **SSRF Protection**: Prevents Server-Side Request Forgery attacks
- **File Access Control**: Fine-grained file system permission control
- **Shell Sandbox**: Optional bwrap sandbox support

### Robot Execution Safety

```yaml
security:
  # Execution Permit Configuration
  execution_permit:
    required: true
    # Dangerous Command Confirmation
    dangerous_commands:
      - "emergency_stop"
      - "power_off"
```

### Sensitive Information Protection

- API keys do not enter code repositories
- Supports environment variable configuration
- Configuration file permission control
- Audit log sanitization

## Advanced Configuration

### Multi-Model Configuration

```yaml
model_presets:
  default:
    provider: anthropic
    model: claude-sonnet-4-20250514
    temperature: 0.7
  
  code_assistant:
    provider: anthropic
    model: claude-3-5-sonnet-20241022
    temperature: 0.3
  
  creative:
    provider: openai
    model: gpt-4o
    temperature: 0.9
```

### Session Configuration

```yaml
session:
  # Session TTL (minutes)
  ttl_minutes: 60
  # Auto-compaction threshold
  auto_compact:
    enabled: true
    threshold: 0.5
```

### Tool Whitelist

```yaml
tools:
  # Enabled core tools
  enabled:
    - "read_file"
    - "write_file"
    - "exec"
    # ...
  
  # Disabled dangerous tools
  disabled:
    - "sudo"
    - "rm"
```

## Troubleshooting

### Common Issues

**1. Model Connection Failed**
```bash
# Check API key configuration
echo $ANTHROPIC_API_KEY

# Test connection
nanobot doctor
```

**2. Tool Execution Failed**
```bash
# View detailed logs
nanobot run -vv "Execute command"

# Check workspace permissions
nanobot doctor --workspace
```

**3. Desktop Application Startup Issues**
```bash
# Windows: View logs
type %APPDATA%\nanobot\logs\error.log

# Check Python environment
where python
python --version
```

### Log Locations

- **Linux/macOS**: `~/.config/nanobot/logs/`
- **Windows**: `%APPDATA%\nanobot\logs\`

## Related Resources

- **Documentation**: [docs/README.md](docs/README.md)
- **Architecture Documentation**: [docs/architecture/](docs/architecture/)
- **Issue Feedback**: [GitHub Issues](https://github.com/csucyj/nanobot-robotic-arms/issues)
- **Changelog**: [CHANGELOG.md](CHANGELOG.md)

## License

This project is licensed under the MIT License, see the [LICENSE](LICENSE) file for details.

## Acknowledgments

Thank you to all developers who have contributed to this project!

---

**Tip**: For detailed technical architecture and design decisions, please refer to the documentation under the [docs/architecture/](docs/architecture/) directory.