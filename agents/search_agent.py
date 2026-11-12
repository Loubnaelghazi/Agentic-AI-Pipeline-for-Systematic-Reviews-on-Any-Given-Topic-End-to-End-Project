from agents.client import chat_model

llm = chat_model(250, timeout=180)


def generate_search_query(topic: str) -> str:
    prompt = f"""
You are an academic research assistant.

Convert the following research topic into a concise
academic search query suitable for OpenAlex.

Topic: {topic}

Rules:
- Keep the most important keywords.
- Include relevant technical terminology.
- Do not explain anything.
- Return only the search query.
"""

    response = llm.invoke(prompt)

    return response.content.strip()
