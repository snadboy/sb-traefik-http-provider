# VSCode Remote Debugging Setup

## Quick Start

1. **Start container in debug mode:**
   ```bash
   docker-compose run --rm --service-ports traefik-provider debug
   ```

2. **In VSCode:**
   - Open this project folder
   - Go to Run and Debug (Ctrl+Shift+D)
   - Select "Python: Remote Attach (Docker)"
   - Click Start Debugging (F5)

3. **Set breakpoints** in your Python code and test!

## How It Works

- **Debug Port:** 5678 (exposed from container)
- **Source Mapping:** Local files are mounted to `/app` in container
- **Live Editing:** Changes to source files are immediately reflected
- **Debugpy:** Python debug server waits for VSCode to attach

## Available Container Modes

- `debug` - Start with debugpy server waiting for VSCode
- `dev` - Direct Python execution with debug logging
- `shell` - Open bash shell for inspection
- Default - Production mode with Gunicorn

## Tips

- Container will wait for debugger to attach before starting
- You can edit code while debugging (live reload)
- Use `docker-compose logs traefik-provider` to see container output
- Set breakpoints in key functions like `build_traefik_config` for inspection