# Contributing to SB Traefik HTTP Provider

Thank you for your interest in contributing to the SB Traefik HTTP Provider! We welcome contributions from the community.

## How to Contribute

### Reporting Bugs

If you find a bug, please open an issue on GitHub with:
- A clear description of the problem
- Steps to reproduce the issue
- Your environment details (OS, Docker version, etc.)
- Any relevant logs or error messages

### Suggesting Features

We're always looking for ways to improve! Please open an issue with:
- A clear description of the feature
- Use cases and benefits
- Any implementation ideas you might have

### Pull Requests

1. **Fork the repository** and create your branch from `main`
2. **Make your changes**:
   - Write clear, concise commit messages
   - Follow the existing code style
   - Add tests for new functionality
   - Update documentation as needed

3. **Test your changes**:
   ```bash
   # Run the provider locally
   docker-compose up --build sb-traefik-http-provider

   # Test the API
   curl http://localhost:8081/api/traefik/config
   ```

4. **Submit a pull request**:
   - Provide a clear description of your changes
   - Reference any related issues
   - Include screenshots if applicable

## Development Setup

### Prerequisites

- Docker and Docker Compose
- Python 3.11+ (for local development)
- Git

### Local Development

1. Clone the repository:
   ```bash
   git clone https://github.com/snadboy/sb-traefik-http-provider.git
   cd sb-traefik-http-provider
   ```

2. Set up configuration:
   ```bash
   cp config/ssh-hosts.example.yaml config/ssh-hosts.yaml
   cp config/provider-config.example.yaml config/provider-config.yaml
   cp .env.example .env
   # Edit files with your settings
   ```

3. Install Python dependencies (for local development):
   ```bash
   pip install -r requirements.txt
   ```

4. Run locally:
   ```bash
   python app/main.py
   ```

### Docker Development

Build and run with Docker Compose:
```bash
docker-compose up --build
```

Debug with VSCode:
```bash
docker-compose run --rm --service-ports sb-traefik-http-provider debug
```

## Code Style

- Follow PEP 8 for Python code
- Use meaningful variable and function names
- Add type hints where appropriate
- Document complex logic with comments
- Keep functions small and focused

## Testing

Before submitting a PR, ensure:
- All existing tests pass
- New features have test coverage
- The Docker image builds successfully
- The provider works with Traefik v3.x

## Documentation

- Update the README for user-facing changes
- Add docstrings to new functions and classes
- Include examples for new features
- Update configuration examples if needed

## Label Format

When adding new label features, follow the existing pattern:
```yaml
snadboy.revp.{PORT}.{SETTING}={VALUE}
```

## Questions?

Feel free to open an issue for any questions about contributing. We're here to help!

## License

By contributing to this project, you agree that your contributions will be licensed under the MIT License.