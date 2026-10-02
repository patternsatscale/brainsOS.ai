"""brainsOS Unified Terminal CLI Entrypoint."""

import argparse
import sys

from brainsos_terminal.chat import main as chat_main
from brainsos_terminal.models import main as models_main
from brainsos_terminal.status import main as status_main
from brainsos_terminal.urls import main as urls_main


def main():
    parser = argparse.ArgumentParser(
        prog="brainsos",
        description="brainsOS: System Terminal CLI & Operational Gateway Suite",
    )
    subparsers = parser.add_subparsers(dest="command", help="Operational commands")

    subparsers.add_parser("urls", help="Display platform service directory and URLs")
    subparsers.add_parser("status", help="Inspect platform internal service health")
    subparsers.add_parser("models", help="List registered LiteLLM models")

    chat_parser = subparsers.add_parser("chat", help="Send chat message to fleet agent")
    chat_parser.add_argument("agent", help="Agent name (e.g. terrastella, marvin, bawtford)")
    chat_parser.add_argument("message", nargs="+", help="Message prompt")

    args = parser.parse_args()

    if args.command == "urls":
        urls_main()
    elif args.command == "status":
        status_main()
    elif args.command == "models":
        models_main()
    elif args.command == "chat":
        # Pass remaining arguments to chat_main
        sys.argv = ["brainsos-chat", args.agent] + args.message
        chat_main()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
