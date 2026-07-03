from __future__ import annotations


def get_leaf_name(path: str) -> str:
    normalized = path.replace("\\", "/").rstrip("/")
    return normalized.rsplit("/", 1)[-1] if "/" in normalized else normalized


def generate_titles(
    title: str | None,
    path: str,
    windows: int | list[str] | None,
) -> list[str]:
    if isinstance(windows, list):
        return list(windows)

    base = title or get_leaf_name(path)
    count = windows if isinstance(windows, int) and windows > 1 else 1

    titles: list[str] = [base]
    for i in range(2, count + 1):
        titles.append(f"{base}-{i}")
    return titles
