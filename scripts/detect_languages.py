from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RULES = {
    "python": ["requirements.txt", "pyproject.toml", "setup.py"],
    "node": ["package.json"],
    "go": ["go.mod"],
    "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "rust": ["Cargo.toml"],
}

def detect(path: Path):
    found = []
    for language, markers in RULES.items():
        if any((path / marker).exists() for marker in markers):
            found.append(language)
    return found

for child in sorted(ROOT.iterdir()):
    if child.is_dir() and child.name not in {".git", ".github", "benchmark", "scripts"}:
        languages = detect(child)
        if languages:
            print(f"{child.name}: {', '.join(languages)}")
