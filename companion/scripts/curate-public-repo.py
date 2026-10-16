"""Build the public monorepo from this working tree, by allowlist.

    python3 scripts/curate-public-repo.py /path/to/krita-creative-agent

Layout: plugin/ (Krita plugin), companion/ (Node companion), mcp-server/ (FastMCP
server), openspec/ (specs and change history). Study output, backups, proof images,
one-off painting scripts and TypeSafe-era evidence are never copied. Existing files in
the destination that this script owns are replaced; .git is left untouched.
"""
import re
import shutil
import sys
from pathlib import Path

WORK = Path(__file__).resolve().parents[2]          # the krita/ checkout
COMPANION = WORK / 'krita-creative-agent'
BRIDGE = WORK / 'krita-mcp'

COMPANION_SCRIPTS = [
    'activate_in_krita.py', 'benchmark-run.mjs', 'build-mac-installer.py', 'build-release.py', 'check-live-pixels.py',
    'compare-stage-one.py', 'evaluate-recipe.mjs', 'evaluate-routing.mjs', 'evaluate-visual-checks.py',
    'export-diagnostics.mjs', 'install-release.mjs', 'install.py', 'langfuse-annotation.mjs', 'langfuse-credentials.mjs',
    'langfuse-smoke.mjs', 'live-acceptance.mjs', 'live-krita-flow.mjs', 'live-reject-check.mjs', 'live-switch-check.mjs',
    'mac-installer.swift', 'reload_panel_in_krita.py', 'setup-local.mjs', 'verify-model-route.mjs',
    'accept-native-tools-live.py', 'test-native-adapters-live.py', 'test-smart-patch-live.py', 'curate-public-repo.py', 'live-asset-test.mjs', 'run-unit-tests.mjs',
    'calibrate-luna-artifacts.mjs', 'evaluate-layer-need.mjs', 'project-dir.mjs', 'luna-artifact-labels.json',
]
COPY = [
    (BRIDGE / 'krita-plugin/kritamcp', 'plugin/kritamcp'),
    (BRIDGE / 'krita-plugin/kritamcp.desktop', 'plugin/kritamcp.desktop'),
    (COMPANION / 'src', 'companion/src'),
    (COMPANION / 'skills', 'companion/skills'),
    (COMPANION / 'tests', 'companion/tests'),
    (COMPANION / 'package.json', 'companion/package.json'),
    (COMPANION / 'package-lock.json', 'companion/package-lock.json'),
    (COMPANION / 'mcp_server.py', 'companion/mcp_server.py'),
    (COMPANION / 'diagnostics_client.py', 'companion/diagnostics_client.py'),
    (COMPANION / 'docs/benchmarks', 'docs/benchmarks'),
    (COMPANION / 'docs/MAC_INSTALLER.md', 'docs/mac-installer.md'),
    (COMPANION / 'docs/RELEASE.md', 'docs/release.md'),
    (BRIDGE / 'server.py', 'mcp-server/server.py'),
    (BRIDGE / 'requirements.txt', 'mcp-server/requirements.txt'),
    (BRIDGE / 'tests', 'mcp-server/tests'),
    (WORK / 'openspec', 'openspec'),
] + [(COMPANION / 'scripts' / name, 'companion/scripts/' + name) for name in COMPANION_SCRIPTS]

IGNORE = shutil.ignore_patterns('__pycache__', '*.pyc', '.DS_Store', '.pytest_cache', 'output', 'node_modules')
# The plugin moves from krita-mcp/krita-plugin/ to plugin/; machine paths become relative.
REWRITES = [
    ('plugin/kritamcp', 'plugin/kritamcp'),
    ("root.parent / 'plugin'", "root.parent / 'plugin'"),
    # mcp-server/: the companion's diagnostics client now lives in ../companion.
    ("Path(__file__).resolve().parent.parent / 'companion'", "Path(__file__).resolve().parent.parent / 'companion'"),
]
# mcp-server/tests load the plugin from a sibling folder that is now ../plugin.
BRIDGE_TEST_REWRITES = [("'krita-plugin/kritamcp", "'../plugin/kritamcp"), ("'krita-plugin'/'kritamcp'", "'..'/'plugin'/'kritamcp'")]
TEXT = {'.example', '.gitignore', '.py', '.mjs', '.js', '.json', '.md', '.swift', '.yaml', '.yml', '.toml', '.txt', '.desktop', '.sh'}
FORBIDDEN = [re.compile(p) for p in (r'/Users/[A-Za-z]', r'sk-lf-[A-Za-z0-9-]{8,}', r'pk-lf-[A-Za-z0-9-]{8,}',
                                      r'sk-or-v1-[A-Za-z0-9]{8,}', r'yakub\.rabiutheen@')]


def main(destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for source, target in COPY:
        path = destination / target
        if path.is_dir(): shutil.rmtree(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir(): shutil.copytree(source, path, ignore=IGNORE)
        else: shutil.copy2(source, path)
    # Public-only files (README, LICENSE, CI, docs) are maintained in public-repo/ and copied over the root.
    public = COMPANION / 'public-repo'
    for file in public.rglob('*'):
        if file.is_file() and '.DS_Store' not in file.name:
            target = destination / file.relative_to(public)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)
    problems = []
    for file in destination.rglob('*'):
        if {'.git', 'node_modules', 'output'} & set(file.parts) or not file.is_file() or file.suffix not in TEXT: continue
        text = file.read_text(encoding='utf-8', errors='ignore')
        rewritten = text
        for old, new in REWRITES: rewritten = rewritten.replace(old, new)
        if file.relative_to(destination).parts[:2] == ('mcp-server', 'tests'):
            for old, new in BRIDGE_TEST_REWRITES: rewritten = rewritten.replace(old, new)
        if rewritten != text: file.write_text(rewritten, encoding='utf-8')
        for pattern in FORBIDDEN:
            for match in pattern.finditer(rewritten):
                line = rewritten.count('\n', 0, match.start()) + 1
                problems.append(f'{file.relative_to(destination)}:{line}: {pattern.pattern}')
    if problems:
        print('Private data found; fix these before publishing:')
        print('\n'.join(problems[:200]))
        sys.exit(1)
    print(f'Curated {destination} with no private paths or keys.')


if __name__ == '__main__':
    if len(sys.argv) != 2: sys.exit(__doc__)
    main(Path(sys.argv[1]).expanduser().resolve())
