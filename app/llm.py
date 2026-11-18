import requests
from .config import (OPENROUTER_API_KEY, OPENROUTER_MODEL,
                     OPENROUTER_SITE_URL, OPENROUTER_APP_NAME)

def answer_with_openrouter(question, history, docs):
    if not OPENROUTER_API_KEY:
        return None
    context = "\n\n".join(
        f"[{i+1}] Source: {d['source']} | Title: {d['title']} | URL: {d['url']}\n{d['content'][:2600]}"
        for i, d in enumerate(docs)
    )
    messages = [{
        "role": "system",
        "content": (
            "You are a careful property research assistant for DarGlobal and Wasalt. "
            "Answer ONLY from the supplied source excerpts. Do not invent prices, availability, "
            "amenities, project details, or legal/financial advice. If evidence is insufficient, "
            "say so and suggest what data is needed. Distinguish the two sources. "
            "Cite factual claims inline as [1], [2], matching the supplied excerpts. "
            "Never imply listings are current unless the source explicitly establishes that."
            "\n\nSOURCE EXCERPTS:\n" + (context or "No matching source excerpts were retrieved.")
        )
    }]
    for item in (history or [])[-6:]:
        if item.get("role") in ("user", "assistant") and item.get("content"):
            messages.append({"role": item["role"], "content": str(item["content"])[:2000]})
    messages.append({"role": "user", "content": question})
    response = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": OPENROUTER_SITE_URL,
            "X-Title": OPENROUTER_APP_NAME
        },
        json={"model": OPENROUTER_MODEL, "messages": messages, "temperature": 0.2},
        timeout=45
    )
    response.raise_for_status()
    data = response.json()
    return data["choices"][0]["message"]["content"]

def grounded_fallback(question, docs):
    if not docs:
        return ("I couldn't find matching information in the currently indexed sources. "
                "The Wasalt dataset may not have been imported yet, or the requested detail "
                "may not appear in the indexed DarGlobal pages.")
    snippets = []
    for i, d in enumerate(docs[:4], 1):
        text = d["content"][:650].strip()
        snippets.append(f"**{d['title']}** ({d['source']})\n{text}… [{i}]")
    return ("I found these relevant source excerpts. Add an OpenRouter API key to enable "
            "AI-generated synthesis; until then, this is a retrieval-only response.\n\n" +
            "\n\n".join(snippets))
