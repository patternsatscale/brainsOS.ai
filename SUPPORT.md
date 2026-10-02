# Getting Support for brainsOS

We are glad you are using and exploring **brainsOS** ([brainsOS.ai](https://brainsos.ai))!

Because brainsOS is an active open-source project under rapid alpha development, here is how and where to get assistance, ask architectural questions, or report bugs.

---

## 1. Documentation & Architecture

Before asking questions or filing issues, please review our official documentation and specifications:
- **brainsOS Website & Overview**: [brainsOS.ai](https://brainsos.ai)
- **Architecture & System Specification**: [README.md](README.md)
- **COHUMAIN ACSG Controls Catalog**: [docs/cohumain/CONTROLS.md](docs/cohumain/CONTROLS.md)
- **Operator & Agent Discipline**: [AGENTS.md](AGENTS.md)
- **Patterns at Scale Initiative**: [patternsatscale.com](https://patternsatscale.com)

---

## 2. Asking Questions & Community Discussion

For general questions, design ideas, hardware inquiries (e.g. running on ASUS Ascent GX10 vs. Apple Silicon vs. Linux rigs), or discussions around thermodynamic AI compute:
- **GitHub Discussions**: Use the [brainsOS Discussions tab](https://github.com/patternsatscale/brainsOS/discussions) to ask questions, share edge setups, and connect with the community.
- **Email Contact**: For non-public community inquiries, contact `community@patternsatscale.com`.

---

## 3. Reporting Bugs & Issues

If you encounter unexpected behavior, configuration failures, or container errors:
1. Search [existing GitHub Issues](https://github.com/patternsatscale/brainsOS/issues) to see if the bug has already been reported.
2. If it is new, submit a report using our [Bug Report Template](.github/ISSUE_TEMPLATE/bug_report.md).
3. Include your host operating system (DGX OS, Ubuntu, macOS), hardware specs, Docker version, and relevant logs from repository scripts (`./scripts/control/start-control-plane.sh status` or `docker compose logs`).

---

## 4. Reporting Security Vulnerabilities

Please **do not** open public issues for security vulnerabilities, authentication bypasses, or secret leaks. Review our [Security Policy](SECURITY.md) and report privately to **`security@patternsatscale.com`** or submit a private GitHub Security Advisory.
