# ==============================================================================
# brainsOS: System Terminal Makefile
# Default recipes accessible from anywhere inside the Operator IDE
# ==============================================================================

.PHONY: all help urls status models chat

all: help

help:
	@echo "\033[1;36mbrainsOS System Terminal\033[0m"
	@echo ""
	@echo "Available commands:"
	@echo "  \033[1;32mmake urls\033[0m     - Show service URLs, public domains, and credentials"
	@echo "  \033[1;32mmake status\033[0m   - Check platform service health and connectivity"
	@echo "  \033[1;32mmake models\033[0m   - List all available LLM models registered in LiteLLM"
	@echo "  \033[1;32mmake chat\033[0m     - Start interactive AI chat in the terminal"
	@echo ""

urls:
	@/usr/local/bin/brainsos-urls

status:
	@/usr/local/bin/brainsos-status

models:
	@python3 -c "import urllib.request, json, os; \
	req = urllib.request.Request('http://litellm:4000/v1/models', headers={'Authorization': 'Bearer ' + os.environ.get('OPENAI_API_KEY', '')}); \
	res = json.loads(urllib.request.urlopen(req).read().decode('utf-8')); \
	print('\033[1;36mRegistered LiteLLM Models:\033[0m'); \
	[print('  • ' + m['id'] + (' (' + m.get('mode', 'chat') + ')' if 'mode' in m else '')) for m in res.get('data', [])]" 2>/dev/null || curl -s -H "Authorization: Bearer $${OPENAI_API_KEY}" http://litellm:4000/v1/models

chat:
	@/usr/local/bin/brainsos-chat
