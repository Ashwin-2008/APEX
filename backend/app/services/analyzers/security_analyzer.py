"""Advanced Security Intelligence Engine: deterministic vulnerability detection and taint-sink analysis."""
from __future__ import annotations

import ast
import re
import time
from pathlib import Path
from typing import Any

from app.services.analyzers.base import AnalyzerOutput, AnalyzerStatus, FindingItem
from backend.ml.mistiq_apr.ingestion import redact_secrets

SECRET_PATTERNS = [
    (re.compile(r"""(?i)(?:aws_secret_access_key|aws_access_key_id)\s*[:=]\s*['"]([A-Za-z0-9/+=]{16,40})['"]"""), "AWS Credentials", "SEC-AWS-CRED"),
    (re.compile(r"""(?i)(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{36}"""), "GitHub Personal Access Token", "SEC-GH-TOKEN"),
    (re.compile(r"""(?i)gsk_[a-zA-Z0-9]{48,60}"""), "Groq API Key", "SEC-GROQ-KEY"),
    (re.compile(r"""(?i)xox[baprs]-[0-9a-zA-Z]{10,48}"""), "Slack API Token", "SEC-SLACK-TOKEN"),
    (re.compile(r"""(?i)(?:api[_-]?key|client[_-]?secret|auth[_-]?token|password)\s*[:=]\s*['"]([^'"]{8,100})['"]"""), "Hardcoded Secret / API Token", "SEC-GENERIC-SECRET"),
    (re.compile(r"""-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"""), "Exposed Private Key", "SEC-PRIVATE-KEY"),
]

SQLI_PATTERNS = [
    (re.compile(r"""(?i)(?:execute|raw|cursor\.execute)\s*\(\s*f['"][^'"]*(?:SELECT|INSERT|UPDATE|DELETE|DROP)\s+[^'"]*\{[^}]+\}"""), "Unparameterized SQL string formatting in execute call", "SEC-SQLI-FSTRING"),
    (re.compile(r"""(?i)(?:execute|raw|cursor\.execute)\s*\(\s*['"][^'"]*(?:SELECT|INSERT|UPDATE|DELETE|DROP)[^'"]*['"]\s*%\s*(?:\([^\)]+\)|[a-zA-Z0-9_]+)"""), "SQL query formatting with % operator", "SEC-SQLI-PERCENT"),
    (re.compile(r"""(?i)(?:execute|raw)\s*\(\s*['"][^'"]*(?:SELECT|INSERT|UPDATE|DELETE|DROP)[^'"]*['"]\s*\+"""), "SQL query concatenated with string operator (+)", "SEC-SQLI-CONCAT"),
]

COMMAND_INJECTION_PATTERNS = [
    (re.compile(r"""(?i)subprocess\.(?:Popen|call|run|check_output|check_call)\s*\([^)]*shell\s*=\s*True"""), "Command execution with shell=True", "SEC-CMD-SHELL"),
    (re.compile(r"""(?i)os\.system\s*\([^)]*"""), "Direct call to os.system without command sanitization", "SEC-CMD-SYSTEM"),
    (re.compile(r"""(?i)os\.popen\s*\([^)]*"""), "Direct call to os.popen", "SEC-CMD-POPEN"),
    (re.compile(r"""\beval\s*\([^)]+"""), "Arbitrary code execution via eval()", "SEC-CODE-EVAL"),
    (re.compile(r"""\bexec\s*\([^)]+"""), "Arbitrary code execution via exec()", "SEC-CODE-EXEC"),
]

XSS_PATTERNS = [
    (re.compile(r"""dangerouslySetInnerHTML\s*=\s*\{\s*\{\s*__html:\s*[^}]+\s*\}\s*\}"""), "React dangerouslySetInnerHTML allows raw HTML injection (XSS risk)", "SEC-XSS-REACT"),
    (re.compile(r"""\binnerHTML\s*=\s*[^;]+"""), "Unsafe innerHTML assignment with dynamic expression", "SEC-XSS-INNERHTML"),
    (re.compile(r"""document\.write\s*\([^)]+"""), "Unsafe document.write call", "SEC-XSS-DOCWRITE"),
]

CORS_DEBUG_PATTERNS = [
    (re.compile(r"""(?i)allow_origins\s*=\s*\[\s*['"]\*['"]\s*\]\s*,\s*allow_credentials\s*=\s*True"""), "Insecure CORS: wildcard origin ('*') with allow_credentials=True", "SEC-CORS-WILDCARD-CREDS"),
    (re.compile(r"""(?i)DEBUG\s*=\s*True"""), "Production debug mode enabled (DEBUG = True)", "SEC-CONFIG-DEBUG-TRUE"),
]


def _check_source_to_sink_taint(file_path: str, content: str) -> list[FindingItem]:
    """Inspect Python AST for source-to-sink taint flows (untrusted request input to dangerous sinks)."""
    findings: list[FindingItem] = []
    if not file_path.endswith(".py"):
        return findings

    try:
        tree = ast.parse(content, filename=file_path)
    except SyntaxError:
        return findings

    lines = content.splitlines()

    class TaintVisitor(ast.NodeVisitor):
        def __init__(self):
            self.tainted_vars: set[str] = set()

        def visit_FunctionDef(self, node: ast.FunctionDef):
            # Check if this looks like a route / controller receiving request parameters
            is_endpoint = False
            for decorator in node.decorator_list:
                dec_repr = ast.unparse(decorator) if hasattr(ast, "unparse") else ""
                if any(kw in dec_repr for kw in [".get", ".post", ".put", ".delete", ".route"]):
                    is_endpoint = True
                    break

            if is_endpoint:
                for arg in node.args.args:
                    if arg.arg not in {"self", "cls", "request", "db", "session"}:
                        self.tainted_vars.add(arg.arg)

            self.generic_visit(node)

        def visit_Assign(self, node: ast.Assign):
            # Track variable propagation: var = tainted_var
            try:
                rhs = ast.unparse(node.value) if hasattr(ast, "unparse") else ""
                if any(t_var in rhs for t_var in self.tainted_vars):
                    for target in node.targets:
                        if isinstance(target, ast.Name):
                            self.tainted_vars.add(target.id)
            except Exception:
                pass
            self.generic_visit(node)

        def visit_Call(self, node: ast.Call):
            func_name = ""
            try:
                func_name = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
            except Exception:
                pass

            dangerous_sinks = {
                "os.system": ("Command Injection", "critical", "SEC-TAINT-SYSTEM"),
                "subprocess.run": ("Command Execution", "high", "SEC-TAINT-SUBPROCESS"),
                "eval": ("Dynamic Code Execution", "critical", "SEC-TAINT-EVAL"),
                "open": ("Path Traversal", "medium", "SEC-TAINT-OPEN"),
            }

            for sink, (risk_label, severity, rule_id) in dangerous_sinks.items():
                if sink in func_name:
                    # check if any argument uses a tainted variable
                    call_args_str = " ".join(ast.unparse(a) for a in node.args if hasattr(ast, "unparse"))
                    for tainted in self.tainted_vars:
                        if tainted in call_args_str:
                            start_line = getattr(node, "lineno", 1)
                            end_line = getattr(node, "end_lineno", start_line)
                            evidence_line = lines[start_line - 1].strip() if 0 < start_line <= len(lines) else ""
                            evidence_redacted, _ = redact_secrets(evidence_line)

                            data_flow = [
                                {"stage": "SOURCE", "description": f"Untrusted endpoint input parameter '{tainted}'"},
                                {"stage": "TRANSFORM", "description": f"Variable propagated into expression '{call_args_str[:80]}'"},
                                {"stage": "SINK", "description": f"Dangerous function call '{func_name}' at line {start_line}"},
                            ]

                            findings.append(
                                FindingItem(
                                    category="security",
                                    severity=severity,
                                    confidence=0.88,
                                    evidence=f"Data-flow taint: untrusted input '{tainted}' flows directly into sensitive sink '{func_name}' at line {start_line}.",
                                    analyzer_source="taint_analyzer",
                                    rule_id=rule_id,
                                    file=file_path,
                                    line=start_line,
                                    end_line=end_line,
                                    title=f"Source-to-Sink {risk_label} in {file_path}:{start_line}",
                                    remediation=f"Sanitize or validate '{tainted}' before passing it to '{func_name}', or use parameterized APIs.",
                                    data_flow=data_flow,
                                )
                            )
            self.generic_visit(node)

    visitor = TaintVisitor()
    visitor.visit(tree)
    return findings


def run_security_analysis(root_dir: str | Path, file_paths: list[Path] | None = None) -> AnalyzerOutput:
    """Run comprehensive deterministic security rules and taint analysis."""
    start_time = time.perf_counter()
    root = Path(root_dir).resolve()
    findings: list[FindingItem] = []
    files_analyzed = 0
    files_skipped = 0

    target_files = file_paths or [
        p for p in root.rglob("*")
        if p.is_file() and not any(part in {".git", "node_modules", "venv", ".venv", "__pycache__", "dist", "build"} for part in p.parts)
    ]

    for file_path in target_files:
        if file_path.stat().st_size > 2_000_000:
            files_skipped += 1
            continue

        rel_path = str(file_path.relative_to(root)).replace("\\", "/")
        is_example_file = ".example" in rel_path.lower() or "test" in rel_path.lower()

        try:
            content = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            files_skipped += 1
            continue

        files_analyzed += 1
        lines = content.splitlines()

        # 1. Hardcoded Secret Detection
        if not is_example_file:
            for pattern, label, rule_id in SECRET_PATTERNS:
                for match in pattern.finditer(content):
                    line_no = content[:match.start()].count("\n") + 1
                    raw_line = lines[line_no - 1] if 0 < line_no <= len(lines) else ""
                    redacted_line, _ = redact_secrets(raw_line)
                    findings.append(
                        FindingItem(
                            category="security",
                            severity="critical",
                            confidence=0.95,
                            evidence=f"Detected {label} pattern at line {line_no}: {redacted_line.strip()[:120]}",
                            analyzer_source="secret_analyzer",
                            rule_id=rule_id,
                            file=rel_path,
                            line=line_no,
                            title=f"Hardcoded Secret in {rel_path}:{line_no}",
                            remediation="Extract credentials into environment variables or a secure secret manager and rotate exposed keys immediately.",
                        )
                    )

        # 2. SQL Injection Patterns
        for pattern, label, rule_id in SQLI_PATTERNS:
            for match in pattern.finditer(content):
                line_no = content[:match.start()].count("\n") + 1
                line_text = lines[line_no - 1].strip() if 0 < line_no <= len(lines) else ""
                redacted, _ = redact_secrets(line_text)
                findings.append(
                    FindingItem(
                        category="security",
                        severity="critical",
                        confidence=0.92,
                        evidence=f"{label} at line {line_no}: {redacted[:120]}",
                        analyzer_source="sqli_analyzer",
                        rule_id=rule_id,
                        file=rel_path,
                        line=line_no,
                        title=f"SQL Injection Risk in {rel_path}:{line_no}",
                        remediation="Use parameterized queries (e.g. cursor.execute(query, params) or ORM models) rather than string formatting.",
                    )
                )

        # 3. Command Injection & Arbitrary Code Execution
        for pattern, label, rule_id in COMMAND_INJECTION_PATTERNS:
            for match in pattern.finditer(content):
                line_no = content[:match.start()].count("\n") + 1
                line_text = lines[line_no - 1].strip() if 0 < line_no <= len(lines) else ""
                findings.append(
                    FindingItem(
                        category="security",
                        severity="high",
                        confidence=0.90,
                        evidence=f"{label} at line {line_no}: {line_text[:120]}",
                        analyzer_source="command_injection_analyzer",
                        rule_id=rule_id,
                        file=rel_path,
                        line=line_no,
                        title=f"Command Injection Risk in {rel_path}:{line_no}",
                        remediation="Avoid shell=True and pass command arguments as a list, or use subprocess.run with validated parameters.",
                    )
                )

        # 4. Cross-Site Scripting (XSS)
        for pattern, label, rule_id in XSS_PATTERNS:
            for match in pattern.finditer(content):
                line_no = content[:match.start()].count("\n") + 1
                line_text = lines[line_no - 1].strip() if 0 < line_no <= len(lines) else ""
                findings.append(
                    FindingItem(
                        category="security",
                        severity="high",
                        confidence=0.88,
                        evidence=f"{label} at line {line_no}: {line_text[:120]}",
                        analyzer_source="xss_analyzer",
                        rule_id=rule_id,
                        file=rel_path,
                        line=line_no,
                        title=f"Cross-Site Scripting Risk in {rel_path}:{line_no}",
                        remediation="Sanitize raw HTML with DOMPurify or use standard JSX/TSX text bindings to prevent unescaped script execution.",
                    )
                )

        # 5. Insecure CORS and Debug Mode
        for pattern, label, rule_id in CORS_DEBUG_PATTERNS:
            for match in pattern.finditer(content):
                line_no = content[:match.start()].count("\n") + 1
                findings.append(
                    FindingItem(
                        category="configuration",
                        severity="medium",
                        confidence=0.85,
                        evidence=f"{label} detected at line {line_no}.",
                        analyzer_source="cors_config_analyzer",
                        rule_id=rule_id,
                        file=rel_path,
                        line=line_no,
                        title=f"{label} in {rel_path}",
                        remediation="Restrict allowed origins to trusted domains and disable debug mode in production configurations.",
                    )
                )

        # 6. Source-to-Sink Taint Flows (Intra-file)
        taint_findings = _check_source_to_sink_taint(rel_path, content)
        findings.extend(taint_findings)

    # 7. Repository-Wide Interprocedural Taint Flow Analysis
    interproc_count = 0
    try:
        from app.services.analyzers.repository_graph import RepositorySymbolIndex
        from app.services.analyzers.taint_engine import InterproceduralTaintAnalyzer
        symbol_index = RepositorySymbolIndex(root)
        interproc_analyzer = InterproceduralTaintAnalyzer(symbol_index)
        interproc_findings = interproc_analyzer.analyze()

        # Deduplicate findings favoring richer interprocedural traces
        seen_locs = {(f.file, f.line, f.rule_id) for f in findings}
        for ip_f in interproc_findings:
            loc_key = (ip_f.file, ip_f.line, ip_f.rule_id)
            if loc_key not in seen_locs:
                findings.append(ip_f)
                seen_locs.add(loc_key)
                interproc_count += 1
            else:
                # Replace less detailed single-file finding with full interprocedural trace
                for i, existing in enumerate(findings):
                    if (existing.file, existing.line, existing.rule_id) == loc_key and not existing.data_flow:
                        findings[i] = ip_f
                        break
    except Exception:
        # Bounded resilience: errors in interprocedural pass do not terminate overall security scan
        pass

    duration = (time.perf_counter() - start_time) * 1000
    return AnalyzerOutput(
        analyzer_name="security_analyzer",
        status=AnalyzerStatus.COMPLETE,
        findings=findings,
        metrics={
            "rules_evaluated": len(SECRET_PATTERNS) + len(SQLI_PATTERNS) + len(COMMAND_INJECTION_PATTERNS) + len(XSS_PATTERNS) + 2,
            "interprocedural_flows_detected": interproc_count,
        },
        duration_ms=duration,
        files_analyzed=files_analyzed,
        files_skipped=files_skipped,
    )

