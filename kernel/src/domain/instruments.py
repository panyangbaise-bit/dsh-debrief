"""Resolve CN namespaces without guessing across overlapping security codes."""


def resolve_cn_symbol(value: str) -> tuple[str, str]:
    """Explicit prefixes disambiguate stock, OTC fund, ETF and index symbols.

    Bare 000/001/002/003 codes overlap stocks, funds and indices. Never fall
    through to another asset class when a provider fails.
    """
    value = value.strip().lower()
    if ":" in value:
        kind, code = value.split(":", 1)
        if kind not in {"stock", "fund", "etf", "index"}:
            raise ValueError("CN prefix must be stock:, fund:, etf: or index:")
    else:
        code = value
        if code.startswith(("000", "001", "002", "003", "399")):
            raise ValueError(
                f"Ambiguous CN symbol {code}; specify index:{code}, stock:{code} "
                f"or fund:{code}. 科创50请用 index:000688。"
            )
        if code.startswith(("51", "56", "58", "15", "16")):
            kind = "etf"
        elif code.startswith("0"):
            kind = "fund"
        elif code.startswith(("60", "68", "30", "4", "8", "92")):
            kind = "stock"
        else:
            raise ValueError(f"Unknown CN asset type for {code}; use an explicit prefix")
    if not code.isdigit() or len(code) != 6:
        raise ValueError("CN symbols must contain a six-digit code")
    return kind, code


def qualify_cn_symbol(symbol: str, asset_class: str) -> str:
    """Catalog symbol to hand back to the picker for one (code, class) pair.

    A bare code is kept when `resolve_cn_symbol` already infers the same class
    (`600519` → stock, `020357` → fund, `510300` → etf). Ambiguous codes get the
    explicit `class:` prefix the resolver understands, so `000001` can be
    offered twice — 平安银行 as `stock:000001`, 华夏成长混合 as `fund:000001` —
    and the write path stores something that resolves back unambiguously.
    """
    code = (symbol or "").strip()
    kind = (asset_class or "").strip().lower()
    if not code or kind not in {"stock", "fund", "etf"}:
        return code
    try:
        inferred, _ = resolve_cn_symbol(code)
    except ValueError:
        return f"{kind}:{code}"
    return code if inferred == kind else f"{kind}:{code}"


def inferred_cn_class(symbol: str) -> str | None:
    """The class a bare CN code implies, or None when it is ambiguous."""
    try:
        kind, _ = resolve_cn_symbol(symbol)
    except ValueError:
        return None
    return kind
