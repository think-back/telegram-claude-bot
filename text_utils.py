"""文本切分：尽量按段落 / 行边界切，避免把代码块或长句拦腰截断。"""


def split_chunks(text: str, max_len: int) -> list[str]:
    """
    把 text 切成 ≤ max_len 的块。
    优先按 "\n\n" 切，再按 "\n"，再按 " "，最后硬切。
    """
    if not text:
        return []
    if len(text) <= max_len:
        return [text]

    chunks: list[str] = []
    remaining = text
    while len(remaining) > max_len:
        window = remaining[:max_len]
        cut = window.rfind("\n\n")
        if cut <= 0:
            cut = window.rfind("\n")
        if cut <= 0:
            cut = window.rfind(" ")
        if cut <= 0:
            cut = max_len
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip("\n ")
    if remaining:
        chunks.append(remaining)
    return chunks
